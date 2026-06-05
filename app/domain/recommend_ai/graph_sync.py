"""
RDS(PostgreSQL) + pgvector → Neo4j Knowledge Graph 동기화.

노드: Policy, Card, Insurance, Category, Organization, Tag
관계: IN_CATEGORY, HOSTED_BY, TAGGED_WITH, CONFLICTS_WITH, SIMILAR_TO(pgvector 기반)
"""
import json
import logging
from typing import Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.client.neo4j_client import neo4j_client
from app.core.config.database import SessionLocal
from app.core.config.settings import settings
from app.core.config.vector_database import VectorSessionLocal
from app.domain.recommend.entity import CardProduct, InsuranceProduct, PolicyProduct

logger = logging.getLogger(__name__)

SIMILAR_TOP_K_DEFAULT = 3


def _parse_tags(tags_raw: Optional[str]) -> list[str]:
    if not tags_raw:
        return []
    try:
        parsed = json.loads(tags_raw)
        if isinstance(parsed, list):
            return [str(t).strip() for t in parsed if str(t).strip()]
    except Exception:
        pass
    return [t.strip() for t in tags_raw.split(",") if t.strip()]


def _parse_conflict_ids(raw: Optional[str]) -> list[str]:
    if not raw:
        return []
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, list):
            return [str(x) for x in parsed if x]
    except Exception:
        pass
    return []


def _run_write(query: str, **params) -> None:
    if not neo4j_client._is_ready():  # noqa: SLF001 — sync 전용
        raise RuntimeError("Neo4j가 비활성화되어 있습니다. .env의 NEO4J_URI를 확인하세요.")

    assert neo4j_client._driver is not None  # noqa: SLF001

    def _tx(tx):
        tx.run(query, **params)

    with neo4j_client._driver.session(database=settings.NEO4J_DATABASE) as session:  # noqa: SLF001
        session.execute_write(_tx)


def _ensure_constraints() -> None:
    statements = [
        "CREATE CONSTRAINT policy_key IF NOT EXISTS FOR (n:Policy) REQUIRE n.key IS UNIQUE",
        "CREATE CONSTRAINT card_key IF NOT EXISTS FOR (n:Card) REQUIRE n.key IS UNIQUE",
        "CREATE CONSTRAINT insurance_key IF NOT EXISTS FOR (n:Insurance) REQUIRE n.key IS UNIQUE",
        "CREATE CONSTRAINT category_name IF NOT EXISTS FOR (n:Category) REQUIRE n.name IS UNIQUE",
        "CREATE CONSTRAINT org_name IF NOT EXISTS FOR (n:Organization) REQUIRE n.name IS UNIQUE",
        "CREATE CONSTRAINT tag_name IF NOT EXISTS FOR (n:Tag) REQUIRE n.name IS UNIQUE",
    ]
    for stmt in statements:
        _run_write(stmt)


def _clear_graph() -> None:
    _run_write("MATCH (n) DETACH DELETE n")


def _sync_policy(policy: PolicyProduct) -> None:
    _run_write(
        """
        MERGE (p:Policy {key: $key})
        SET p.name = $name,
            p.org = $org,
            p.category = $category,
            p.core_benefit = $core_benefit,
            p.age_min = $age_min,
            p.age_max = $age_max,
            p.income_condition = $income_condition,
            p.deadline = $deadline
        """,
        key=policy.key,
        name=policy.policy_name or "",
        org=policy.org or "",
        category=policy.category or "",
        core_benefit=policy.core_benefit or "",
        age_min=policy.age_min,
        age_max=policy.age_max,
        income_condition=policy.income_condition or "",
        deadline=policy.deadline or "",
    )

    if policy.category:
        _run_write(
            """
            MATCH (p:Policy {key: $key})
            MERGE (c:Category {name: $category})
            MERGE (p)-[:IN_CATEGORY]->(c)
            """,
            key=policy.key,
            category=policy.category,
        )

    if policy.org:
        _run_write(
            """
            MATCH (p:Policy {key: $key})
            MERGE (o:Organization {name: $org})
            MERGE (p)-[:HOSTED_BY]->(o)
            """,
            key=policy.key,
            org=policy.org,
        )

    for tag in _parse_tags(policy.tags):
        _run_write(
            """
            MATCH (p:Policy {key: $key})
            MERGE (t:Tag {name: $tag})
            MERGE (p)-[:TAGGED_WITH]->(t)
            """,
            key=policy.key,
            tag=tag,
        )

    for other_key in _parse_conflict_ids(policy.conflict_policy_ids):
        _run_write(
            """
            MATCH (a:Policy {key: $key})
            MERGE (b:Policy {key: $other})
            MERGE (a)-[:CONFLICTS_WITH]->(b)
            """,
            key=policy.key,
            other=other_key,
        )


# 카드/보험 혜택 키워드 → Category 매핑
BENEFIT_CATEGORY_MAP = {
    # 카드 혜택 키워드
    "외식": "생활지원", "식비": "생활지원", "배달": "생활지원",
    "카페": "문화/여가", "커피": "문화/여가",
    "교통": "생활지원", "대중교통": "생활지원", "주유": "생활지원",
    "쇼핑": "생활지원", "백화점": "생활지원",
    "여행": "문화/여가", "해외": "문화/여가", "항공": "문화/여가",
    "적립": "금융", "포인트": "금융", "캐시백": "금융",
    "저축": "금융", "연금": "금융", "자산": "금융",
    "영화": "문화/여가", "공연": "문화/여가", "OTT": "문화/여가",
    "통신": "생활지원", "편의점": "생활지원",
    # 보험 혜택 키워드
    "실손": "건강", "의료": "건강", "입원": "건강", "수술": "건강",
    "암": "건강", "건강": "건강", "치과": "건강", "치아": "건강",
    "자동차": "생활지원", "운전자": "생활지원",
    "종신": "금융", "사망": "금융",
    "펫": "생활지원", "반려": "생활지원",
}

BENEFIT_TAG_MAP = {
    "외식": "외식할인", "카페": "카페할인", "교통": "교통할인",
    "주유": "주유할인", "쇼핑": "쇼핑할인", "여행": "여행혜택",
    "적립": "포인트적립", "캐시백": "캐시백", "통신": "통신할인",
    "실손": "실손보험", "의료": "의료보장", "암": "암보험",
    "자동차": "자동차보험", "운전자": "운전자보험",
    "연금": "연금보험", "저축": "저축보험",
}

def _extract_categories_from_benefit(top_benefit: str, benefits: str) -> list[str]:
    """혜택 텍스트에서 카테고리 추출."""
    combined = f"{top_benefit} {benefits or ''}"
    categories = set()
    for keyword, category in BENEFIT_CATEGORY_MAP.items():
        if keyword in combined:
            categories.add(category)
    return list(categories)

def _extract_tags_from_benefit(top_benefit: str, benefits: str) -> list[str]:
    """혜택 텍스트에서 태그 추출."""
    combined = f"{top_benefit} {benefits or ''}"
    tags = set()
    for keyword, tag in BENEFIT_TAG_MAP.items():
        if keyword in combined:
            tags.add(tag)
    return list(tags)


def _sync_card(card: CardProduct) -> None:
    _run_write(
        """
        MERGE (c:Card {key: $key})
        SET c.company = $company,
            c.name = $name,
            c.top_benefit = $top_benefit
        """,
        key=card.key,
        company=card.company or "",
        name=card.card_name or "",
        top_benefit=card.top_benefit or "",
    )

    # 카테고리 연결
    for category in _extract_categories_from_benefit(card.top_benefit or "", card.benefits or ""):
        _run_write(
            """
            MATCH (c:Card {key: $key})
            MERGE (cat:Category {name: $category})
            MERGE (c)-[:IN_CATEGORY]->(cat)
            """,
            key=card.key,
            category=category,
        )

    # 태그 연결
    for tag in _extract_tags_from_benefit(card.top_benefit or "", card.benefits or ""):
        _run_write(
            """
            MATCH (c:Card {key: $key})
            MERGE (t:Tag {name: $tag})
            MERGE (c)-[:TAGGED_WITH]->(t)
            """,
            key=card.key,
            tag=tag,
        )


def _sync_insurance(ins: InsuranceProduct) -> None:
    _run_write(
        """
        MERGE (i:Insurance {key: $key})
        SET i.insurer = $insurer,
            i.name = $name,
            i.top_benefit = $top_benefit
        """,
        key=ins.key,
        insurer=ins.insurer or "",
        name=ins.insurance_name or "",
        top_benefit=ins.top_benefit or "",
    )

    # 카테고리 연결
    for category in _extract_categories_from_benefit(ins.top_benefit or "", ins.benefits or ""):
        _run_write(
            """
            MATCH (i:Insurance {key: $key})
            MERGE (cat:Category {name: $category})
            MERGE (i)-[:IN_CATEGORY]->(cat)
            """,
            key=ins.key,
            category=category,
        )

    # 태그 연결
    for tag in _extract_tags_from_benefit(ins.top_benefit or "", ins.benefits or ""):
        _run_write(
            """
            MATCH (i:Insurance {key: $key})
            MERGE (t:Tag {name: $tag})
            MERGE (i)-[:TAGGED_WITH]->(t)
            """,
            key=ins.key,
            tag=tag,
        )


def _sync_similar_edges(product_type: str, top_k: int) -> int:
    """pgvector cosine distance로 동일 타입 상품 간 SIMILAR_TO 관계 생성."""
    vdb: Session = VectorSessionLocal()
    created = 0
    label = {"policy": "Policy", "card": "Card", "insurance": "Insurance"}[product_type]

    try:
        rows = vdb.execute(
            text("SELECT product_id, embedding::text FROM product_embedding WHERE product_type = :ptype"),
            {"ptype": product_type},
        ).fetchall()

        for product_id, emb_text in rows:
            if not emb_text:
                continue

            similar = vdb.execute(
                text("""
                    SELECT product_id,
                           1 - (embedding <=> CAST(:emb AS vector)) AS score
                    FROM product_embedding
                    WHERE product_type = :ptype
                      AND product_id <> :pid
                    ORDER BY embedding <=> CAST(:emb AS vector)
                    LIMIT :limit
                """),
                {"emb": emb_text, "ptype": product_type, "pid": product_id, "limit": top_k},
            ).fetchall()

            for other_id, score in similar:
                if score is None or score <= 0:
                    continue
                _run_write(
                    f"""
                    MATCH (a:{label} {{key: $a}})
                    MATCH (b:{label} {{key: $b}})
                    MERGE (a)-[r:SIMILAR_TO]->(b)
                    SET r.score = $score
                    """,
                    a=product_id,
                    b=other_id,
                    score=float(score),
                )
                created += 1
    finally:
        vdb.close()

    return created


def sync_knowledge_graph(
    *,
    clear: bool = False,
    include_similar: bool = True,
    similar_top_k: int = SIMILAR_TOP_K_DEFAULT,
) -> dict:
    """
    RDS 상품 + (선택) pgvector 유사도 → Neo4j Knowledge Graph 적재.
    """
    if not neo4j_client._is_ready():  # noqa: SLF001
        raise RuntimeError("Neo4j 연결 불가 — NEO4J_URI/USERNAME/PASSWORD 확인")

    db: Session = SessionLocal()
    stats = {
        "policies": 0,
        "cards": 0,
        "insurances": 0,
        "similar_edges": 0,
        "cleared": clear,
    }

    try:
        _ensure_constraints()
        if clear:
            _clear_graph()
            logger.info("[GraphSync] 기존 그래프 삭제 완료")

        policies = db.query(PolicyProduct).all()
        for p in policies:
            _sync_policy(p)
        stats["policies"] = len(policies)

        cards = db.query(CardProduct).all()
        for c in cards:
            _sync_card(c)
        stats["cards"] = len(cards)

        insurances = db.query(InsuranceProduct).all()
        for i in insurances:
            _sync_insurance(i)
        stats["insurances"] = len(insurances)

        if include_similar:
            stats["similar_edges"] = (
                _sync_similar_edges("policy", similar_top_k)
                + _sync_similar_edges("card", similar_top_k)
                + _sync_similar_edges("insurance", similar_top_k)
            )

        logger.info(f"[GraphSync] 완료 - {stats}")
        return stats
    finally:
        db.close()


def get_graph_stats() -> dict:
    """Neo4j 노드/관계 수 요약."""
    if not neo4j_client._is_ready():  # noqa: SLF001
        return {"enabled": False}

    assert neo4j_client._driver is not None  # noqa: SLF001

    with neo4j_client._driver.session(database=settings.NEO4J_DATABASE) as session:  # noqa: SLF001
        nodes = session.run(
            """
            MATCH (n)
            RETURN labels(n)[0] AS label, count(*) AS cnt
            ORDER BY cnt DESC
            """
        ).data()
        rels = session.run(
            """
            MATCH ()-[r]->()
            RETURN type(r) AS type, count(*) AS cnt
            ORDER BY cnt DESC
            """
        ).data()

    return {"enabled": True, "nodes": nodes, "relationships": rels}

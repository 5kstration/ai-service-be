import logging
from typing import Any, Iterable, Optional

from neo4j import GraphDatabase

from app.core.config.settings import settings

logger = logging.getLogger(__name__)


class Neo4jClient:
    """
    Graph RAG용 Neo4j read-only 클라이언트.

    - 설정이 없으면(NEO4J_ENABLED=False) 항상 빈 결과를 반환해 기존 파이프라인을 깨지 않음
    - 스키마에 강하게 의존하지 않도록, 정책(Policy) 노드에서 주변 관계를 넓게 수집하는 방식
    """

    def __init__(self) -> None:
        # NEO4J_ENABLED=true면 명시적으로 사용, 아니면 URI가 있으면 자동 활성화(로컬/운영 .env 호환)
        self._enabled = bool(settings.NEO4J_ENABLED) or bool(settings.NEO4J_URI)
        self._driver = None
        if self._enabled:
            user = settings.NEO4J_USER or getattr(settings, "NEO4J_USERNAME", "") or ""
            self._driver = GraphDatabase.driver(
                settings.NEO4J_URI,
                auth=(user, settings.NEO4J_PASSWORD),
            )

    def close(self) -> None:
        if self._driver is not None:
            self._driver.close()

    def _is_ready(self) -> bool:
        return self._enabled and self._driver is not None

    def fetch_triples(
        self,
        keys: Iterable[str],
        *,
        label_hint: Optional[str] = None,
        hops: Optional[int] = None,
        max_triples: Optional[int] = None,
    ) -> list[dict[str, Any]]:
        """
        입력 key들에 대해, 해당 노드 주변의 (subject, predicate, object) 트리플을 수집.
        - label_hint가 있으면 (가능하면) 해당 라벨로 시작 노드를 제한
        - 실제 스키마가 달라도 최대한 일부는 동작하도록 "느슨한" 쿼리로 구성
        """
        keys = [k for k in keys if k]
        if not keys or not self._is_ready():
            return []

        # hops는 쿼리 안정성을 위해 상한을 둠
        hops_val = hops if hops is not None else int(settings.NEO4J_POLICY_HOPS)
        max_val = max_triples if max_triples is not None else int(settings.NEO4J_POLICY_MAX_TRIPLES)
        hops_val = max(1, min(int(hops_val), 3))
        max_val = max(10, min(int(max_val), 200))

        # label_hint가 있으면 우선 시도, 실패 시(라벨 미존재 등)도 soft-fail로 처리
        label_match = f":{label_hint}" if label_hint else ""

        cypher = f"""
        MATCH (start_node{label_match})
        WHERE start_node.key IN $keys
        CALL {{
          WITH start_node
          MATCH path = (start_node)-[r*1..{hops_val}]-(n)
          WITH relationships(path) AS rels
          UNWIND rels AS rel
          WITH DISTINCT rel
          RETURN
            coalesce(startNode(rel).key, startNode(rel).id, startNode(rel).name, labels(startNode(rel))[0]) AS s,
            type(rel) AS p,
            coalesce(endNode(rel).key, endNode(rel).id, endNode(rel).name, labels(endNode(rel))[0]) AS o,
            labels(startNode(rel)) AS s_labels,
            labels(endNode(rel)) AS o_labels
          LIMIT $max_triples
        }}
        RETURN s, p, o, s_labels, o_labels
        """

        try:
            assert self._driver is not None
            with self._driver.session(database=settings.NEO4J_DATABASE) as session:
                rows = session.run(cypher, keys=keys, max_triples=max_val)
                return [
                    {
                        "s": r["s"],
                        "p": r["p"],
                        "o": r["o"],
                        "s_labels": r["s_labels"],
                        "o_labels": r["o_labels"],
                    }
                    for r in rows
                ]
        except Exception as e:
            # 그래프가 없어도 서비스가 깨지지 않게 "soft fail"
            logger.warning(f"[Neo4jClient] fetch_triples 실패 - error={e}")
            return []

    def fetch_policy_triples(self, policy_keys: Iterable[str]) -> list[dict[str, Any]]:
        return self.fetch_triples(policy_keys, label_hint="Policy")

    def fetch_candidates_by_categories(self, categories: list[str], limit: int = 10) -> dict[str, list[str]]:
        """
        카테고리(유저의 주요 지출 분야) 기반으로 Neo4j에서 후보 상품 키들을 검색.
        - Policy: IN_CATEGORY 관계 사용
        - Card/Insurance: top_benefit 속성에 키워드 포함 여부 확인
        """
        if not categories or not self._is_ready():
            return {"cards": [], "insurances": [], "policies": []}

        cypher_policy = """
        MATCH (p:Policy)-[:IN_CATEGORY]->(c:Category)
        WHERE c.name IN $categories
        RETURN DISTINCT p.key AS key
        LIMIT $limit
        """

        cypher_card = """
        MATCH (n:Card)
        WHERE any(kw IN $categories WHERE n.top_benefit CONTAINS kw)
        RETURN DISTINCT n.key AS key
        LIMIT $limit
        """

        cypher_insurance = """
        MATCH (n:Insurance)
        WHERE any(kw IN $categories WHERE n.top_benefit CONTAINS kw)
        RETURN DISTINCT n.key AS key
        LIMIT $limit
        """

        try:
            assert self._driver is not None
            with self._driver.session(database=settings.NEO4J_DATABASE) as session:
                policies = [r["key"] for r in session.run(cypher_policy, categories=categories, limit=limit)]
                cards = [r["key"] for r in session.run(cypher_card, categories=categories, limit=limit)]
                insurances = [r["key"] for r in session.run(cypher_insurance, categories=categories, limit=limit)]
                
                return {
                    "policies": policies,
                    "cards": cards,
                    "insurances": insurances
                }
        except Exception as e:
            logger.warning(f"[Neo4jClient] fetch_candidates_by_categories 실패 - error={e}")
            return {"cards": [], "insurances": [], "policies": []}

    def fetch_candidates_by_cf(self, categories: list[str], limit: int = 10) -> dict[str, list[str]]:
        """
        Collaborative Filtering (협업 필터링) 검색
        현재 유저가 선호하는 카테고리를 똑같이 좋아하는 다른 유저들이 가장 많이 가입한 상품 추천.
        """
        if not categories or not self._is_ready():
            return {"cards": [], "insurances": [], "policies": []}

        # User -> Product 공통 쿼리 포맷
        def build_cf_query(product_label: str) -> str:
            return f"""
            MATCH (u:User)-[:SUBSCRIBED_TO]->(p:{product_label})
            WHERE u.favorite_category IN $categories
            RETURN p.key AS key, count(u) AS popularity
            ORDER BY popularity DESC
            LIMIT $limit
            """

        try:
            assert self._driver is not None
            with self._driver.session(database=settings.NEO4J_DATABASE) as session:
                policies = [r["key"] for r in session.run(build_cf_query("Policy"), categories=categories, limit=limit)]
                cards = [r["key"] for r in session.run(build_cf_query("Card"), categories=categories, limit=limit)]
                insurances = [r["key"] for r in session.run(build_cf_query("Insurance"), categories=categories, limit=limit)]
                
                return {
                    "policies": policies,
                    "cards": cards,
                    "insurances": insurances
                }
        except Exception as e:
            logger.warning(f"[Neo4jClient] fetch_candidates_by_cf 실패 - error={e}")
            return {"cards": [], "insurances": [], "policies": []}

neo4j_client = Neo4jClient()

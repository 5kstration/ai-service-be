# app/domain/recommend_ai/nodes.py
import json
import logging
import sys
from datetime import date
import re as _re

from sqlalchemy.orm import Session
from sqlalchemy import text

from app.domain.recommend_ai.state import RecommendState
from app.domain.recommend.entity import (
    CardProduct, InsuranceProduct, PolicyProduct,
    RecommendCard, RecommendInsurance, RecommendPolicy,
)
from app.domain.profile.entity import UserProfile
from app.core.client.bedrock_client import bedrock_client
from app.core.client.neo4j_client import neo4j_client
from app.core.config.database import SessionLocal
from app.core.config.vector_database import VectorSessionLocal
from app.core.utils.tsid import TSID

logger = logging.getLogger(__name__)

MAX_RECOMMEND = 5
VECTOR_CANDIDATES = 30  # 벡터 검색 후보 수
RERANK_TOP_N      = 7   # 리랭커 통과 후 LLM에 넘길 수

_CAT_LIFE    = "생활지원"
_CAT_CULTURE = "문화/여가"
_CAT_FINANCE = "금융"
_CAT_HEALTH  = "건강"
_CAT_HOUSING = "주거"
_CAT_EDU     = "교육/자기계발"
_CAT_JOB     = "취업/창업"

# =============================================
# 1. 프로파일 노드
# =============================================
def profile_node(state: RecommendState) -> dict:
    """user_profile + monthly_summary 조회."""
    user_id = state["user_id"]
    db: Session = SessionLocal()

    try:
        profile = db.query(UserProfile).filter(
            UserProfile.user_id == user_id
        ).first()

        if not profile:
            logger.warning(f"[ProfileNode] 유저 프로필 없음 - user_id={user_id}")
            return {"error": "user_profile not found"}

        # 나이 계산
        age = None
        if profile.birth:
            today = date.today()
            age = today.year - profile.birth.year - (
                (today.month, today.day) < (profile.birth.month, profile.birth.day)
            )

        # 월간 지출 조회
        today = date.today()
        from app.domain.report.entity import MonthlySummary
        summaries = db.query(MonthlySummary).filter(
            MonthlySummary.user_id == user_id,
            MonthlySummary.year   == today.year,
            MonthlySummary.month  == today.month,
        ).all()
        CATEGORY_KO_MAP = {
            "FOOD": "식비", "TRANSPORT": "교통", "SHOPPING": "쇼핑",
            "CAFE": "카페", "HOUSING": "주거", "MEDICAL": "의료",
            "TRAVEL": "여행", "CAR": "자동차", "CULTURE": "문화",
            "EDUCATION": "교육", "BUSINESS": "사업", "INVEST": "투자",
            "GAS": "주유", "TELECOM": "통신", "SPORT": "운동",
            "HOBBY": "여가", "OTHER": "기타",
        }

        monthly_summary = [
            {
                "category": CATEGORY_KO_MAP.get(s.category.upper(), s.category),
                "amount": s.amount or 0
            }
            for s in summaries
        ]


        logger.info(f"[ProfileNode] 완료 - user_id={user_id}, age={age}")
        return {
            "user_age":        age,
            "user_sex":        profile.sex,
            "user_income":     profile.monthly_income,
            "monthly_summary": monthly_summary,
        }
    finally:
        db.close()


# =============================================
# 2. 임베딩 노드
# =============================================

def embed_node(state: RecommendState) -> dict:
    if state.get("error"):
        return {}

    BENEFIT_KEYWORD_MAP = {
        "식비":   "외식할인 음식점할인 배달할인 식비절약 카페할인",
        "교통":   "대중교통할인 교통비지원 버스지하철 교통비절약",
        "쇼핑":   "쇼핑할인 쇼핑캐시백 온라인쇼핑 포인트적립",
        "카페":   "카페할인 커피할인 음료할인 카페적립",
        "주거":   "월세지원 전세대출 주거지원 주거비절약 임대주택",
        "의료":   "실손보험 의료비지원 건강보험 병원비절약",
        "여행":   "여행자보험 해외결제무료 항공마일리지 여행혜택",
        "자동차": "자동차보험 주유할인 운전자보험 차량비절약",
        "문화":   "문화누리카드 공연할인 문화비지원 여가혜택",
        "교육":   "자기계발지원 내일배움카드 교육비지원 자격증",
        "사업":   "창업지원 사업화자금 소상공인지원 비즈니스",
        "투자":   "연금저축 자산형성 적금혜택 재테크",
        "주유":   "주유할인 기름값절약 주유소혜택 차량비",
        "통신":   "통신비할인 휴대폰요금 통신비절약",
        "운동":   "스포츠강좌 헬스할인 체육시설 건강관리",
        "기타":   "생활비절약 청년지원 금융혜택",
    }

    income = state.get("user_income") or 0
    age    = state.get("user_age") or 0
    sex    = state.get("user_sex") or ""

    if income < 2000000:
        income_hint = "저소득 생활지원 청년지원금"
    elif income < 3500000:
        income_hint = "중소득 청년정책 금융혜택"
    else:
        income_hint = "고소득 자산형성 프리미엄"

    if age < 25:
        age_hint = "대학생 청년 취업준비"
    elif age < 30:
        age_hint = "사회초년생 청년 자립"
    else:
        age_hint = "청년 직장인 자산관리"

    import numpy as np
    summary = state["monthly_summary"]
    total   = sum(s["amount"] for s in summary)

    embeddings = []
    weights    = []

    for s in summary:
        cat      = s["category"]
        amount   = s["amount"]
        ratio    = amount / total if total > 0 else 0.0
        keywords = BENEFIT_KEYWORD_MAP.get(cat, cat)
        text     = f"{keywords} {income_hint} {age_hint} {sex} 청년"

        try:
            emb = bedrock_client.embed(text)
            emb = np.array(emb, dtype=np.float32)
            norm = np.linalg.norm(emb)
            emb = emb / norm if norm > 0 else emb
            embeddings.append(emb)
            weights.append(ratio)
        except Exception as e:
            logger.warning(f"[EmbedNode] 카테고리 임베딩 실패 - cat={cat}, error={e}")

    if not embeddings:
        logger.error(f"[EmbedNode] 임베딩 전체 실패 - user_id={state['user_id']}")
        return {"error": "임베딩 실패"}

    weighted = np.average(embeddings, axis=0, weights=weights)
    norm     = np.linalg.norm(weighted)
    embedding = (weighted / norm if norm > 0 else weighted).tolist()

    logger.info(f"[EmbedNode] 가중 평균 임베딩 완료 - user_id={state['user_id']}, categories={len(embeddings)}개")
    return {"user_embedding": embedding}




# =============================================
# 3. 벡터 검색 노드

 
def vector_search_node(state: RecommendState) -> dict:
    """pgvector cosine similarity → 후보 상품 검색."""
    if state.get("error"):
        return {}

    embedding = state["user_embedding"]
    vdb: Session = VectorSessionLocal()
    db: Session  = SessionLocal()

    try:
        embedding_str = f"[{','.join(map(str, embedding))}]"

        sorted_summary = sorted(state.get("monthly_summary", []), key=lambda x: x.get("amount", 0), reverse=True)

        # ── Neo4j Graph Retrieval ──
        CATEGORY_MAP = {
            "식비":   [_CAT_LIFE, _CAT_FINANCE],
            "교통":   [_CAT_LIFE, "교통지원"],
            "쇼핑":   [_CAT_LIFE, _CAT_FINANCE],
            "카페":   [_CAT_LIFE, _CAT_CULTURE],
            "주거":   [_CAT_HOUSING, "주거지원"],
            "의료":   [_CAT_HEALTH],
            "여행":   [_CAT_CULTURE],
            "자동차": [_CAT_LIFE, _CAT_FINANCE],
            "문화":   [_CAT_CULTURE, "문화지원"],
            "교육":   [_CAT_EDU, "교육지원"],
            "사업":   [_CAT_JOB, "창업지원"],
            "투자":   [_CAT_FINANCE, "자산형성"],
            "주유":   [_CAT_LIFE],
            "통신":   [_CAT_LIFE],
            "운동":   [_CAT_CULTURE, _CAT_HEALTH],
        }

        raw_cats = [s["category"] for s in sorted_summary[:2]]
        mapped = []
        for cat in raw_cats:
            mapped.extend(CATEGORY_MAP.get(cat, [cat]))
        top_categories = list(dict.fromkeys(mapped))

        graph_candidates = neo4j_client.fetch_candidates_by_categories(top_categories, limit=10)
        cf_candidates    = neo4j_client.fetch_candidates_by_cf(top_categories, limit=10)

        # ── Vector Search ──
        def search(product_type: str) -> list:
            result = vdb.execute(text("""
                SELECT product_id
                FROM product_embedding
                WHERE product_type = :ptype
                ORDER BY embedding <=> CAST(:emb AS vector)
                LIMIT :limit
            """), {"ptype": product_type, "emb": embedding_str, "limit": 30})
            return [row[0] for row in result.fetchall()]

        card_ids      = list(set(search("card")      + graph_candidates.get("cards", [])      + cf_candidates.get("cards", [])))
        insurance_ids = list(set(search("insurance") + graph_candidates.get("insurances", []) + cf_candidates.get("insurances", [])))
        policy_ids    = list(set(search("policy")    + graph_candidates.get("policies", [])   + cf_candidates.get("policies", [])))

        cards      = db.query(CardProduct).filter(CardProduct.key.in_(card_ids)).all()
        insurances = db.query(InsuranceProduct).filter(InsuranceProduct.key.in_(insurance_ids)).all()
        policies   = db.query(PolicyProduct).filter(PolicyProduct.key.in_(policy_ids)).all()

        # ── 보험 위험도 점수 기반 필터링 ──
        CATEGORY_INSURANCE_SCORE = {
            "의료":   {"실손": 3, "건강": 3, "입원": 2},
            "운동":   {"상해": 3, "건강": 2},
            "여행":   {"여행": 3, "상해": 2, "해외": 3},
            "자동차": {"운전자": 3, "자동차": 3},
            "주유":   {"운전자": 3, "자동차": 2},
            "교통":   {"상해": 2, "운전자": 1},
            "식비": {"건강": 1, "실손": 1},
            "여가":   {"상해": 2, "여행": 1},
        }

        total_amount = sum(s["amount"] for s in sorted_summary) or 1
        insurance_type_scores: dict = {}
        for s in sorted_summary:
            cat    = s["category"]
            weight = s["amount"] / total_amount
            for ins_kw, base_score in CATEGORY_INSURANCE_SCORE.get(cat, {}).items():
                insurance_type_scores[ins_kw] = (
                    insurance_type_scores.get(ins_kw, 0) + base_score * weight
                )

        insurance_risk_summary = ""
        if insurance_type_scores:
            top_keywords = sorted(
                insurance_type_scores,
                key=lambda k: insurance_type_scores[k],
                reverse=True
            )[:3]

            # 위험도 요약 텍스트 생성 (소비 카테고리 명시)  
            risk_lines = []
            for kw in top_keywords:
                score = round(insurance_type_scores[kw], 2)
                # 이 키워드에 기여한 카테고리 찾기
                related_cats = [
                    f"{s['category']}({s['amount']:,}원)"
                    for s in sorted_summary
                    if kw in CATEGORY_INSURANCE_SCORE.get(s["category"], {})
                ]
                related_text = ", ".join(related_cats) if related_cats else "일반 생활"
                risk_lines.append(f"  - {kw} 관련 보험 (위험도 점수: {score}, 근거 지출: {related_text})")
            insurance_risk_summary = "소비 패턴 기반 보험 위험도 분석:\n" + "\n".join(risk_lines)
            logger.info(f"[VectorSearchNode] 보험 위험도: { {k: round(insurance_type_scores[k], 2) for k in top_keywords} }")

            filtered = [
                i for i in insurances
                if any(kw in (i.insurance_name or "") or kw in (i.top_benefit or "")
                       for kw in top_keywords)
            ]
            if len(filtered) >= 1:
                insurances = filtered
                logger.info(f"[VectorSearchNode] 보험 타입 필터링 - {len(filtered)}개 ({top_keywords})")

        logger.info(
            f"[VectorSearchNode] 완료 - "
            f"cards={len(cards)}, insurances={len(insurances)}, policies={len(policies)}"
        )

        return {
            "card_candidates":        [{"key": c.key, "company": c.company, "card_name": c.card_name, "top_benefit": c.top_benefit, "benefits": c.benefits, "apply_url": c.apply_url, "accent_color": c.accent_color} for c in cards],
            "insurance_candidates":   [{"key": i.key, "insurer": i.insurer, "insurance_name": i.insurance_name, "top_benefit": i.top_benefit, "benefits": i.benefits, "apply_url": i.apply_url, "accent_color": i.accent_color} for i in insurances],
            "policy_candidates":      [{"key": p.key, "policy_name": p.policy_name, "org": p.org, "category": p.category, "category_color": p.category_color, "deadline": p.deadline, "dday": p.dday, "tags": p.tags, "age_min": p.age_min, "age_max": p.age_max, "income_condition": p.income_condition, "conflict_policy_ids": p.conflict_policy_ids} for p in policies],
            "insurance_risk_summary": insurance_risk_summary,
        }
    finally:
        vdb.close()
        db.close()
 
# =============================================
# 3-1. 리랭크 노드
# =============================================
def rerank_node(state: RecommendState) -> dict:
    if state.get("error"):
        return {}
 
    # Ablation: rerank skip
    if state.get("disable_rerank"):
        logger.info("[RerankNode] SKIP (disable_rerank=true) - 상위 7개만 통과")
        return {
            "card_candidates":      state["card_candidates"][:RERANK_TOP_N],
            "insurance_candidates": state["insurance_candidates"][:RERANK_TOP_N],
            "policy_candidates":    state["policy_candidates"][:RERANK_TOP_N],
        }
 
    from app.domain.recommend_ai.reranker import reranker_client
 
    summary_text = ", ".join([
        f"{s['category']} {s['amount']:,}원"
        for s in state["monthly_summary"]
    ])

    card_query = (
        f"나이 {state['user_age']}세 {state['user_sex']}. "
        f"이번 달 지출: {summary_text}. "
        f"지출 카테고리에 맞는 할인 혜택 카드"
    )
    insurance_query = (
        f"나이 {state['user_age']}세 {state['user_sex']}. "
        f"이번 달 지출: {summary_text}. "
        f"소비 패턴 기반 보험 보장"
    )
    policy_query = (
        f"나이 {state['user_age']}세 {state['user_sex']}. "
        f"월 소득 {state['user_income']:,}원. "
        f"나이와 소득 조건에 맞는 청년 지원 정책"
    )
    def rerank_candidates(candidates: list, text_fn, query: str) -> list:
        if not candidates:
            return []
        texts   = [text_fn(c) for c in candidates]
        indices = reranker_client.rerank(query, texts, top_n=RERANK_TOP_N)
        return [candidates[i] for i in indices]

    def card_text(c: dict) -> str:
        return f"{c.get('company','')} {c.get('card_name','')}. {c.get('top_benefit','')}. 혜택: {c.get('benefits','')}"

    def insurance_text(i: dict) -> str:
        return f"{i.get('insurer','')} {i.get('insurance_name','')}. 핵심 혜택: {i.get('top_benefit','')}. 혜택 상세: {i.get('benefits','')}"

    def policy_text(p: dict) -> str:
        return f"{p.get('policy_name','')}. 카테고리: {p.get('category','')}. 태그: {p.get('tags','')}"
    
    reranked_cards      = rerank_candidates(state["card_candidates"],      card_text,      card_query)
    reranked_insurances = rerank_candidates(state["insurance_candidates"],  insurance_text, insurance_query)
    reranked_policies   = rerank_candidates(state["policy_candidates"],     policy_text,    policy_query)
    logger.info(
        f"[RerankNode] 완료 - "
        f"cards: {len(state['card_candidates'])}→{len(reranked_cards)}, "
        f"insurances: {len(state['insurance_candidates'])}→{len(reranked_insurances)}, "
        f"policies: {len(state['policy_candidates'])}→{len(reranked_policies)}"
    )
 
    return {
        "card_candidates":      reranked_cards,
        "insurance_candidates": reranked_insurances,
        "policy_candidates":    reranked_policies,
    }
# =============================================
# 4. 필터 노드 (룰 기반)
# =============================================
_MEDIAN_INCOME_1P = 2_392_013
 
def _income_condition_met(condition: str, monthly_income: int) -> bool:
    if not condition:
        return True
    c = condition.strip()
    if any(x in c for x in ["제한없음", "기준 없음", "없음"]):
        return True
    m = _re.search(r"중위소득\s*(\d+)%\s*이하", c)
    if m:
        return monthly_income <= _MEDIAN_INCOME_1P * int(m.group(1)) / 100
    m = _re.search(r"(?:연소득|총급여|개인소득)\s*([\d,]+)만?원\s*이하", c)
    if m:
        val = int(m.group(1).replace(",", ""))
        if val < 10000: val *= 10000
        return monthly_income <= val / 12
    m = _re.search(r"부부합산\s*([\d,]+)만?원\s*이하", c)
    if m:
        val = int(m.group(1).replace(",", ""))
        if val < 10000: val *= 10000
        return monthly_income <= val / 2 / 12
    return True
 
_REGION_PATTERN = _re.compile(r'[가-힣]+(시|군|구|동|읍|면)\s')

def _is_policy_eligible(policy: dict, user_age: int, user_income: int, skip_income: bool) -> bool:
    age_min = policy.get("age_min")
    age_max = policy.get("age_max")

    if age_min is not None and user_age < age_min:
        return False
    if age_max is not None and user_age > age_max:
        return False

    # 지역 조건 있는 정책 제외
    policy_name = policy.get("policy_name") or ""
    if _REGION_PATTERN.search(policy_name):
        return False

    if not skip_income:
        income_condition = policy.get("income_condition") or ""
        if not _income_condition_met(income_condition, user_income):
            return False
    return True


def filter_node(state: RecommendState) -> dict:
    if state.get("error"):
        return {}

    user_age    = state.get("user_age") or 0
    user_income = state.get("user_income") or 0
    skip_income = state.get("disable_income_filter", False)

    filtered  = [p for p in state["policy_candidates"] if _is_policy_eligible(p, user_age, user_income, skip_income)]
    rejected  = len(state["policy_candidates"]) - len(filtered)

    logger.info(
        f"[FilterNode] 필터 완료 - "
        f"{len(state['policy_candidates'])}개 → {len(filtered)}개 "
        f"(제외 {rejected}개, 소득필터={'OFF' if skip_income else 'ON'})"
    )
    return {"filtered_policies": filtered}
 

# =============================================
# 4-1. Graph 확장 노드 (Neo4j)
# =============================================
def graph_expand_node(state: RecommendState) -> dict:
    if state.get("error"):
        return {}
 
    # Ablation: neo4j skip
    if state.get("disable_neo4j"):
        logger.info("[GraphExpandNode] SKIP (disable_neo4j=true)")
        return {
            "card_graph_triples":      [],
            "insurance_graph_triples": [],
            "policy_graph_triples":    [],
        }
 
    card_keys = [
        c.get("key")
        for c in (state.get("card_candidates") or [])
        if isinstance(c, dict) and c.get("key")
    ]
    insurance_keys = [
        i.get("key")
        for i in (state.get("insurance_candidates") or [])
        if isinstance(i, dict) and i.get("key")
    ]
    policies = state.get("filtered_policies") or []
    policy_keys = [p.get("key") for p in policies if isinstance(p, dict) and p.get("key")]
 
    card_triples      = neo4j_client.fetch_triples(card_keys,      label_hint="Card")
    insurance_triples = neo4j_client.fetch_triples(insurance_keys, label_hint="Insurance")
    policy_triples    = neo4j_client.fetch_triples(policy_keys,    label_hint="Policy")
 
    logger.info(
        "[GraphExpandNode] 완료 - "
        f"cards={len(card_keys)}/{len(card_triples)}triples, "
        f"insurances={len(insurance_keys)}/{len(insurance_triples)}triples, "
        f"policies={len(policy_keys)}/{len(policy_triples)}triples"
    )
 
    return {
        "card_graph_triples":      card_triples,
        "insurance_graph_triples": insurance_triples,
        "policy_graph_triples":    policy_triples,
    }


# =============================================
# 5. Conflict 노드
# =============================================
def conflict_node(state: RecommendState) -> dict:
    """정책 간 중복 불가 정보 추출."""
    if state.get("error"):
        return {}

    conflict_info = {}
    for policy in state["filtered_policies"]:
        raw = policy.get("conflict_policy_ids")
        if isinstance(raw, list):
            conflict_ids = raw
        else:
            conflict_ids = json.loads(raw or "[]")
        if conflict_ids:
            conflict_info[policy["key"]] = conflict_ids

    logger.info(f"[ConflictNode] conflict 감지 - {len(conflict_info)}개 정책 충돌 있음")
    return {"conflict_info": conflict_info}


# =============================================
# 6. LLM 추천 노드
# =============================================

def llm_recommend_node(state: RecommendState) -> dict:
    """Bedrock Claude → 최종 추천 5개 + 추천 사유 생성."""
    if state.get("error"):
        return {}

    db: Session = SessionLocal()
    try:
        conflict_text = "없음"
        if state["conflict_info"]:
            # key → 정책명 매핑 만들기
            policy_name_map = {
                p["key"]: p["policy_name"]
                for p in state["filtered_policies"]
            }
            # policy_candidates도 포함 (filtered_policies에 없을 수 있음)
            for p in state["policy_candidates"]:
                if p["key"] not in policy_name_map:
                    policy_name_map[p["key"]] = p["policy_name"]

            lines = []
            for pid, cids in state["conflict_info"].items():
                pname  = policy_name_map.get(pid, pid)
                cnames = [policy_name_map.get(cid, cid) for cid in cids]
                lines.append(f"- {pname}은 {', '.join(cnames)}와 중복 신청 불가")
            conflict_text = "\n".join(lines)

        # 소비 패턴 텍스트 (TOP 3 강조)
        sorted_summary = sorted(
            state["monthly_summary"],
            key=lambda x: x["amount"],
            reverse=True
        )
        top3 = sorted_summary[:3]
        total = sum(s["amount"] for s in state["monthly_summary"])

        summary_lines = []
        for s in sorted_summary:
            ratio = int(s["amount"] / total * 100) if total > 0 else 0
            summary_lines.append(f"  - {s['category']}: {s['amount']:,}원 ({ratio}%)")
        summary_text = "\n".join(summary_lines)

        top3_text = ", ".join([f"{s['category']}({s['amount']:,}원)" for s in top3])

        def triples_to_lines(triples: list) -> str:
            lines = []
            for t in (triples or [])[:200]:
                s = str(t.get("s", ""))
                p = str(t.get("p", ""))
                o = str(t.get("o", ""))
                if s and p and o:
                    lines.append(f"- ({s}) -[{p}]-> ({o})")
            return "\n".join(lines) if lines else "없음"

        card_graph_context = triples_to_lines(state.get("card_graph_triples") or [])
        insurance_graph_context = triples_to_lines(state.get("insurance_graph_triples") or [])
        policy_graph_context = triples_to_lines(state.get("policy_graph_triples") or [])

        prompt = f"""당신은 청년 금융 전문가입니다. 아래 유저 정보와 소비 패턴을 꼼꼼히 분석하여 가장 적합한 금융 상품을 추천해주세요.

## 유저 프로필
- 나이: {state['user_age']}세 / 성별: {state['user_sex']}
- 월 소득: {state['user_income']:,}원
- 이번 달 총 지출: {total:,}원 (소득 대비 {int(total/state['user_income']*100) if state['user_income'] else 0}%)

## 이번 달 소비 패턴
{summary_text}

## TOP 3 지출 카테고리
{top3_text}

## 후보 카드 목록
{json.dumps(state['card_candidates'], ensure_ascii=False, indent=2)}

## 후보 보험 목록
{json.dumps(state['insurance_candidates'], ensure_ascii=False, indent=2)}

## 후보 정책 목록
{json.dumps(state['filtered_policies'], ensure_ascii=False, indent=2)}

## 카드 지식그래프 근거 (Neo4j, 선택)
{card_graph_context}

## 보험 지식그래프 근거 (Neo4j, 선택)
{insurance_graph_context}

## 정책 지식그래프 근거 (Neo4j, 선택)
{policy_graph_context}

## 정책 중복 불가 정보
{conflict_text}
## [절대 금지 사항][필수]
- 후보 목록에 없는 수치(할인율, 지원금액, 적립율)를 절대 임의로 작성하지 말 것
- top_benefit, benefits, core_benefit에 명시된 내용만 사용할 것
- 수치가 불확실하면 "~혜택이 있어요"로만 표현할 것
- 보험 추천 시 유저 소비 패턴에 없는 카테고리(예를 들어서 여행 지출 없으면 여행보험) 추천 금지
## 추천 규칙
1. 카드/보험/정책 각각 반드시 최소 1개, 최대 {MAX_RECOMMEND}개 선택
2. 추천 사유 작성 규칙:
   - 반드시 유저의 실제 소비 데이터(금액, 카테고리)를 언급할 것
   - 후보 목록의 top_benefit, benefits 필드에 있는 내용만 사용할 것
   - 확인되지 않은 수치(할인율, 지원금액)를 임의로 만들지 말 것 → 상품 정보에 없으면 "~혜택이 있어요"로만 표현
   - 2~3문장으로 작성
   - "~할 것 같습니다" 금지 → "~할 수 있어요", "~에 딱 맞아요" 사용
## 보험 추천 근거 (소비 패턴 기반 위험도 분석)
{state.get('insurance_risk_summary') or '분석 없음'}

3. 보험 추천 규칙:
   - 위험도 분석 결과를 반드시 참고하여 추천할 것
   - 위험도 점수가 높은 보험 타입을 우선 추천
   - 추천 사유에 반드시 "근거 지출" 카테고리와 금액을 언급할 것
     예: "이번 달 여행을 1,000,000원을 지출하셨는데, 여행 중 사고에 대비한 상해보험을 추천드려요"
   - 근거 지출이 없는 보험 타입 추천 금지
   - 분석 결과에 없는 보험 타입(여행 지출 없으면 여행보험 등) 추천 금지
4. 정책은 나이/소득 조건에 맞는 것 중 가장 혜택이 큰 것 우선
   - 후보 정책 목록이 비어있지 않으면 반드시 1개 이상 추천할 것
   - 조건이 애매하면 유저에게 유리하게 해석하여 추천
5. 중복 불가 정책이 있으면 추천 사유 마지막에 "단, [정책명]과는 중복 신청이 안 돼요. 둘 중 하나만 선택하세요!" 형태로 정책명으로 명시
6. [필수 체크] 최종 출력 전 반드시 확인:
   - cards 배열이 비어있지 않은가?
   - insurances 배열이 비어있지 않은가?
   - policies 배열이 비어있지 않은가?
   - 위 세 가지 중 하나라도 비어있으면 후보 목록에서 반드시 추가할 것
   ## [Few-shot 예시] 이런 스타일로 작성하세요
### 카드 추천 사유 예시
- "이번 달 카페에서 {top3[0]['amount']:,}원을 쓰셨네요! 이 카드는 스타벅스·이디야 등 카페에서 10% 할인돼서 매달 약 {int(top3[0]['amount']*0.1):,}원 아낄 수 있어요. 커피값 걱정 없이 즐기세요 ☕"
- "교통비로 매달 꽤 쓰고 계시네요. 이 카드는 대중교통 이용 시 20% 할인 혜택이 있어서 한 달에 최대 15,000원까지 절약 가능해요. 출퇴근길이 가벼워질 거예요!"
- "쇼핑을 즐기시는군요! 이 카드는 온라인 쇼핑몰에서 5% 캐시백을 제공해서 이번 달 지출 기준으로 약 {int(top3[0]['amount']*0.05):,}원이 돌아와요. 쇼핑할수록 이득이에요 🛍️"

### 보험 추천 사유 예시 (반드시 소비 데이터 기반으로 작성)
- "이번 달 의료비로 {top3[0]['amount']:,}원을 지출하셨네요. 병원을 자주 방문하시는 것 같아 통원/입원비를 실손으로 보장받을 수 있는 건강보험을 추천드려요. 매달 나가는 의료비 부담이 확 줄어들 거예요!"
- "운동 관련 지출이 꾸준히 있으시네요. 스포츠 활동 중 발생할 수 있는 상해 위험에 대비해 상해보험 하나 챙겨두시는 게 좋아요. 보험료 부담 없이 실질적인 보호를 받을 수 있어요."
- "해외 결제나 여행 관련 지출이 확인됐어요. 여행 중 발생할 수 있는 의료비, 수하물 분실, 항공 지연 등을 폭넓게 보장받을 수 있는 여행자보험을 추천드려요 ✈️"
- "교통비 지출이 매달 꾸준히 나가고 있네요. 대중교통·출퇴근 중 발생하는 사고에 대비한 상해보험은 보험료 대비 실질 보장이 높아요."

### 정책 추천 사유 예시  
- "나이와 소득 조건이 딱 맞는 청년 지원 정책이에요! 매달 최대 XX만원을 지원받을 수 있어서 생활비 부담을 크게 줄일 수 있어요. 신청 마감이 얼마 안 남았으니 서둘러보세요!"
- "취업 준비 중이시라면 이 정책을 확인해보세요. 교육비와 취업 활동비를 지원해줘서 자기계발에 집중할 수 있어요. 조건이 맞으면 바로 신청하는 걸 추천해요 💪"

## [중요] 응답 프로세스 (Chain of Thought)
최종 JSON 응답 전에 반드시 `<thinking>` 태그로 추론 과정 작성:
- 유저 소비 TOP 3 카테고리 분석
- 각 상품이 왜 적합한지 top_benefit 기반으로 판단
- 수치는 반드시 상품 정보에서만 인용
- 정책은 나이/소득 조건 충족 여부 명시적으로 확인

[출력 예시]
<thinking>
- 유저는 식비 지출이 가장 높음. A카드는 음식점 10% 할인이 있으므로 식비 절감에 적합.
- 나이가 25세이고 대중교통 이용이 잦을 수 있으므로 B정책(청년 교통비 지원) 적합. 단 C정책과 중복 불가.
- 보험은 실손보험과 여행보험 2종류로 다양하게 추천.
</thinking>
```json
{{
  "cards": [
    {{"key": "01HXPRODCARD00000001", "reason": "이번 달 식비 200,000원을 지출하셨네요! 이 카드는 음식점에서 10% 할인돼서 매달 약 20,000원 절약할 수 있어요."}}
  ],
  "insurances": [
    {{"key": "01HXPRODINS00000001", "reason": "25세 청년에게 꼭 필요한 실손보험이에요. 입원/통원 의료비의 80%를 보장받을 수 있어요."}}
  ],
  "policies": [
    {{"key": "01HXPRODPOL000000021", "reason": "나이와 소득 조건이 딱 맞는 청년 지원 정책이에요. 매달 최대 30만원을 지원받을 수 있어요."}}
  ]
}}
```"""

        response_text = bedrock_client.recommend(prompt)

        # JSON 파싱
        clean = response_text.strip()

        # <answer> 태그 우선 추출
        if "<answer>" in clean:
            clean = clean.split("<answer>")[1].split("</answer>")[0].strip()

        # 마크다운 코드블럭 제거
        if "```" in clean:
            parts = clean.split("```")
            for part in parts:
                part = part.strip()
                if part.startswith("json"):
                    part = part[4:].strip()
                try:
                    result = json.loads(part)
                    break
                except Exception:
                    continue
            else:
                result = json.loads(clean)
        else:
            result = json.loads(clean.strip())

        logger.info(
            f"[LLMNode] 추천 완료 - "
            f"cards={len(result.get('cards', []))}, "
            f"insurances={len(result.get('insurances', []))}, "
            f"policies={len(result.get('policies', []))}"
        )
        return {
            "recommended_cards":      result.get("cards", []),
            "recommended_insurances": result.get("insurances", []),
            "recommended_policies":   result.get("policies", []),
        }
    except Exception as e:
        logger.error(f"[LLMNode] 추천 실패 - error={e}")
        return {"error": str(e)}
    finally:
        db.close()

# =============================================
# 7. 저장 노드
# =============================================
def save_node(state: RecommendState) -> dict:
    """recommend_* 테이블에 저장."""
    user_id = state["user_id"]
    db: Session = SessionLocal()

    try:
        # 기존 추천 삭제 (재추천 시 덮어쓰기)
        db.query(RecommendCard).filter(RecommendCard.user_id == user_id).delete()
        db.query(RecommendInsurance).filter(RecommendInsurance.user_id == user_id).delete()
        db.query(RecommendPolicy).filter(RecommendPolicy.user_id == user_id).delete()

        # 검증용 allowlist 생성
        valid_card_keys = {c.get("key") for c in state.get("card_candidates", []) if c.get("key")}
        valid_ins_keys = {i.get("key") for i in state.get("insurance_candidates", []) if i.get("key")}
        valid_pol_keys = {p.get("key") for p in state.get("filtered_policies", []) if p.get("key")}

        # 카드 저장
        for item in state.get("recommended_cards", []):
            product_id = item.get("product_id") or item.get("key")
            if not product_id or product_id not in valid_card_keys: 
                continue
            db.add(RecommendCard(
                key             = TSID.create(),
                user_id         = user_id,
                card_product_id = product_id,
                ai_reason       = item.get("reason", ""),
            ))

        # 보험 저장
        for item in state.get("recommended_insurances", []):
            product_id = item.get("product_id") or item.get("key")
            if not product_id or product_id not in valid_ins_keys: 
                continue
            db.add(RecommendInsurance(
                key                  = TSID.create(),
                user_id              = user_id,
                insurance_product_id = product_id,
                ai_reason            = item.get("reason", ""),
            ))

        # 정책 저장
        for item in state.get("recommended_policies", []):
            product_id = item.get("product_id") or item.get("key")
            if not product_id or product_id not in valid_pol_keys: 
                continue
            db.add(RecommendPolicy(
                key               = TSID.create(),
                user_id           = user_id,
                policy_product_id = product_id,
                ai_reason         = item.get("reason", ""),
            ))

        db.commit()
        logger.info(f"[SaveNode] 저장 완료 - user_id={user_id}")
        return {}

    except Exception as e:
        db.rollback()
        logger.error(f"[SaveNode] 저장 실패 - error={e}")
        return {"error": str(e)}
    finally:
        db.close()
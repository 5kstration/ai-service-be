# app/domain/recommend_ai/nodes.py
import json
import logging
import sys
from datetime import date

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

        monthly_summary = [
            {"category": s.category, "amount": s.amount or 0}
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
 
        # 1. Neo4j Graph Retrieval (Top 2 카테고리 기반 10개씩)

        # 수정
        sorted_summary = sorted(state.get("monthly_summary", []), key=lambda x: x.get("amount", 0), reverse=True)

        CATEGORY_MAP = {
            "식비":   ["생활지원", "금융"],
            "교통":   ["생활지원", "교통지원"],
            "쇼핑":   ["생활지원", "금융"],
            "카페":   ["생활지원", "문화/여가"],
            "주거":   ["주거", "주거지원"],
            "의료":   ["건강"],
            "여행":   ["문화/여가"],
            "자동차": ["생활지원", "금융"],
            "문화":   ["문화/여가", "문화지원"],
            "교육":   ["교육/자기계발", "교육지원"],
            "사업":   ["취업/창업", "창업지원"],
            "투자":   ["금융", "자산형성"],
            "주유":   ["생활지원"],
            "통신":   ["생활지원"],
            "운동":   ["문화/여가", "건강"],
        }

        raw_cats   = [s["category"] for s in sorted_summary[:2]]
        mapped     = []
        for cat in raw_cats:
            mapped.extend(CATEGORY_MAP.get(cat, [cat]))
        top_categories = list(dict.fromkeys(mapped))  # 순서 유지하면서 중복 제거

        graph_candidates = neo4j_client.fetch_candidates_by_categories(top_categories, limit=10)
        cf_candidates    = neo4j_client.fetch_candidates_by_cf(top_categories, limit=10)




        # 3. Vector Search (임베딩 유사도 기반 30개씩)
        def search(product_type: str) -> list[str]:
            result = vdb.execute(text("""
                SELECT product_id
                FROM product_embedding
                WHERE product_type = :ptype
                ORDER BY embedding <=> CAST(:emb AS vector)
                LIMIT :limit
            """), {
                "ptype": product_type,
                "emb":   embedding_str,
                "limit": 30, # 기존처럼 벡터 검색 30개 유지 (Recall 손실 방지)
            })
            return [row[0] for row in result.fetchall()]
 
        # 세 가지 결과를 중복 제거하여 합침 (최대 50개)
        card_ids      = list(set(search("card") + graph_candidates.get("cards", []) + cf_candidates.get("cards", [])))
        insurance_ids = list(set(search("insurance") + graph_candidates.get("insurances", []) + cf_candidates.get("insurances", [])))
        policy_ids    = list(set(search("policy") + graph_candidates.get("policies", []) + cf_candidates.get("policies", [])))
 
        cards      = db.query(CardProduct).filter(CardProduct.key.in_(card_ids)).all()
        insurances = db.query(InsuranceProduct).filter(InsuranceProduct.key.in_(insurance_ids)).all()
        policies   = db.query(PolicyProduct).filter(PolicyProduct.key.in_(policy_ids)).all()
 
        logger.info(
            f"[VectorSearchNode] 완료 - "
            f"cards={len(cards)}, insurances={len(insurances)}, policies={len(policies)}"
        )
        return {
            "card_candidates":      [{"key": c.key, "company": c.company, "card_name": c.card_name, "top_benefit": c.top_benefit, "benefits": c.benefits, "apply_url": c.apply_url, "accent_color": c.accent_color} for c in cards],
            "insurance_candidates": [{"key": i.key, "insurer": i.insurer, "insurance_name": i.insurance_name, "top_benefit": i.top_benefit, "benefits": i.benefits, "apply_url": i.apply_url, "accent_color": i.accent_color} for i in insurances],
            "policy_candidates":    [{"key": p.key, "policy_name": p.policy_name, "org": p.org, "category": p.category, "category_color": p.category_color, "deadline": p.deadline, "dday": p.dday, "tags": p.tags, "age_min": p.age_min, "age_max": p.age_max, "income_condition": p.income_condition, "conflict_policy_ids": p.conflict_policy_ids} for p in policies],
        }
    finally:
        vdb.close()
        db.close()
 
 
# =============================================
# 3-1. 리랭크 노드
# =============================================
def rerank_node(state: RecommendState) -> dict:
    """
    벡터 검색 후보를 Cohere Rerank로 재정렬.
    20개 → 7개로 압축해서 LLM 입력 토큰 절감.
 
    실패 시: 원본 순서 그대로 top_n개 통과 (서비스 중단 없음)
    """
    if state.get("error"):
        return {}
 
    from app.domain.recommend_ai.reranker import reranker_client
    from app.domain.recommend_ai.embed_service import _card_to_text, _insurance_to_text, _policy_to_text
 
    # 유저 쿼리 텍스트 (임베딩 때 만든 것과 동일)
    summary_text = ", ".join([
        f"{s['category']} {s['amount']:,}원"
        for s in state["monthly_summary"]
    ])
    query = (
        f"나이 {state['user_age']}세 {state['user_sex']}. "
        f"월급 {state['user_income']:,}원. "
        f"이번 달 지출: {summary_text}"
    )
 
    def rerank_candidates(candidates: list, text_fn) -> list:
        """후보 리스트를 리랭킹해서 상위 RERANK_TOP_N개만 반환."""
        if not candidates:
            return []
        texts   = [text_fn(c) for c in candidates]
        indices = reranker_client.rerank(query, texts, top_n=RERANK_TOP_N)
        return [candidates[i] for i in indices]
 
    # 카드 텍스트 변환 함수 (dict → str)
    def card_text(c: dict) -> str:
        return f"{c.get('company','')} {c.get('card_name','')}. {c.get('top_benefit','')}. 혜택: {c.get('benefits','')}"
 
    def insurance_text(i: dict) -> str:
        return f"{i.get('insurer','')} {i.get('insurance_name','')}. 핵심 혜택: {i.get('top_benefit','')}. 혜택 상세: {i.get('benefits','')}"
 
    def policy_text(p: dict) -> str:
        return f"{p.get('policy_name','')}. 카테고리: {p.get('category','')}. 태그: {p.get('tags','')}"
 
    reranked_cards      = rerank_candidates(state["card_candidates"],      card_text)
    reranked_insurances = rerank_candidates(state["insurance_candidates"],  insurance_text)
    reranked_policies   = rerank_candidates(state["policy_candidates"],     policy_text)
 
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
import re as _re

# 2025년 1인가구 기준 중위소득 (월)
_MEDIAN_INCOME_1P = 2_392_013

def _income_condition_met(condition: str, monthly_income: int) -> bool:
    """소득 조건 텍스트 파싱 → 충족 여부 반환."""
    if not condition:
        return True
    c = condition.strip()

    if any(x in c for x in ["제한없음", "기준 없음", "없음"]):
        return True

    # 중위소득 % 기반
    m = _re.search(r"중위소득\s*(\d+)%\s*이하", c)
    if m:
        pct   = int(m.group(1))
        limit = _MEDIAN_INCOME_1P * pct / 100
        return monthly_income <= limit

    # 연소득/총급여 기반 → 월 환산
    m = _re.search(r"(?:연소득|총급여|개인소득)\s*([\d,]+)만?원\s*이하", c)
    if m:
        val = int(m.group(1).replace(",", ""))
        if val < 10000:
            val *= 10000
        return monthly_income <= val / 12

    # 부부합산 → 절반으로
    m = _re.search(r"부부합산\s*([\d,]+)만?원\s*이하", c)
    if m:
        val = int(m.group(1).replace(",", ""))
        if val < 10000:
            val *= 10000
        return monthly_income <= val / 2 / 12

    # 소득분위, 예술활동 등 파싱 어려운 건 통과
    return True


def filter_node(state: RecommendState) -> dict:
    """나이/소득 조건으로 정책 필터링."""
    if state.get("error"):
        return {}

    user_age    = state.get("user_age") or 0
    user_income = state.get("user_income") or 0

    filtered = []
    rejected = 0
    for policy in state["policy_candidates"]:
        age_min = policy.get("age_min")
        age_max = policy.get("age_max")

        # 나이 조건
        if age_min is not None and user_age < age_min:
            rejected += 1
            continue
        if age_max is not None and user_age > age_max:
            rejected += 1
            continue

        # 소득 조건
        income_condition = policy.get("income_condition") or ""
        if not _income_condition_met(income_condition, user_income):
            rejected += 1
            continue

        filtered.append(policy)

    logger.info(
        f"[FilterNode] 필터 완료 - "
        f"{len(state['policy_candidates'])}개 → {len(filtered)}개 "
        f"(나이/소득 조건 미충족 {rejected}개 제외)"
    )
    return {"filtered_policies": filtered}
# =============================================
# 4-1. Graph 확장 노드 (Neo4j)
# =============================================
def graph_expand_node(state: RecommendState) -> dict:
    """
    필터링된 정책 후보를 Neo4j 그래프로 확장해서 LLM 근거 컨텍스트를 강화.
    Neo4j 설정이 없으면 빈 결과를 반환하고 파이프라인은 계속 진행.
    """
    if state.get("error"):
        return {}

    # 카드/보험 후보(리랭크 이후)를 그래프로 확장
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

    # 정책은 필터링된 후보를 기준으로 확장
    policies = state.get("filtered_policies") or []
    policy_keys = [p.get("key") for p in policies if isinstance(p, dict) and p.get("key")]

    card_triples = neo4j_client.fetch_triples(card_keys, label_hint="Card")
    insurance_triples = neo4j_client.fetch_triples(insurance_keys, label_hint="Insurance")
    policy_triples = neo4j_client.fetch_triples(policy_keys, label_hint="Policy")

    logger.info(
        "[GraphExpandNode] 완료 - "
        f"cards={len(card_keys)}/{len(card_triples)}triples, "
        f"insurances={len(insurance_keys)}/{len(insurance_triples)}triples, "
        f"policies={len(policy_keys)}/{len(policy_triples)}triples"
    )

    return {
        "card_graph_triples": card_triples,
        "insurance_graph_triples": insurance_triples,
        "policy_graph_triples": policy_triples,
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

## 추천 규칙
1. 카드/보험/정책 각각 최대 {MAX_RECOMMEND}개 선택
2. 추천 사유 작성 규칙:
   - 반드시 유저의 실제 소비 데이터(금액, 카테고리)를 언급할 것
   - 지식그래프(Neo4j) 근거가 있는 상품을 추천할 경우, 이를 활용하여 상품이 유저의 소비 카테고리와 어떻게 연결되는지 자연스럽게 설명할 것 (단, 그래프 근거가 없더라도 유저에게 가장 적합한 상품이라면 우선적으로 추천할 것)
   - 예시: "이번 달 식비 {top3[0]['amount']:,}원을 지출했는데, 이 카드로 매달 약 XX원 절약 가능해요"
   - 친근하고 응원하는 톤으로 작성 (딱딱한 설명 금지)
   - 1~2문장으로 간결하게
   - "~할 것 같습니다" 표현 절대 금지 → "~할 수 있어요", "~에 딱 맞아요" 등 사용
3. 보험은 유저 나이와 성별, 소비 패턴에서 유추한 라이프스타일 기반으로 추천
4. 정책은 나이/소득 조건에 맞는 것 중 가장 혜택이 큰 것 우선
5. 중복 불가 정책이 있으면 추천 사유 마지막에 "단, [정책명]과는 중복 신청이 안 돼요. 둘 중 하나만 선택하세요!" 형태로 정책명으로 명시

## [중요] 응답 프로세스 (Chain of Thought)
최종 JSON 응답을 생성하기 전에, 반드시 `<thinking>` 태그를 사용하여 유저의 소비 패턴을 분석하고 각 상품이 왜 적합한지 짧게 추론하는 과정을 먼저 작성하세요.
그 다음, 완벽한 JSON 형식으로 최종 결과를 출력하세요. 마크다운 코드블럭(```json ... ```) 안에 작성해야 합니다.

[출력 예시]
<thinking>
- 유저는 식비 지출이 가장 높음. A카드는 음식점 10% 할인이 있으므로 식비 절감에 적합.
- 나이가 25세이고 대중교통 이용이 잦을 수 있으므로 B정책(청년 교통비 지원) 적합. 단 C정책과 중복 불가.
</thinking>
```json
{{
  "cards": [
    {{"key": "01HXPRODCARD00000001", "reason": "이번 달 식비에 가장 많은 금액을 쓰셨네요!"}}
  ],
  "insurances": [],
  "policies": [
    {{"key": "01HXPRODPOL000000021", "reason": "매일 출퇴근하시는 25세 청년에게 딱 맞는 교통비 지원 정책이에요."}}
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
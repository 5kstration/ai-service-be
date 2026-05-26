# app/domain/recommend_ai/nodes.py
import json
import logging
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
from app.core.config.database import SessionLocal
from app.core.config.vector_database import VectorSessionLocal
from app.core.utils.tsid import TSID

logger = logging.getLogger(__name__)

MAX_RECOMMEND = 5
VECTOR_CANDIDATES = 20  # 벡터 검색 후보 수


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
    """소비 패턴 텍스트 → Bedrock Titan 임베딩."""
    if state.get("error"):
        return {}

    # 소비 패턴 텍스트 조합
    summary_text = ", ".join([
        f"{s['category']} {s['amount']:,}원"
        for s in state["monthly_summary"]
    ])
    text = (
        f"나이 {state['user_age']}세 {state['user_sex']}. "
        f"월급 {state['user_income']:,}원. "
        f"이번 달 지출: {summary_text}"
    )

    try:
        embedding = bedrock_client.embed(text)
        logger.info(f"[EmbedNode] 임베딩 생성 완료 - user_id={state['user_id']}")
        return {"user_embedding": embedding}
    except Exception as e:
        logger.error(f"[EmbedNode] 임베딩 실패 - error={e}")
        return {"error": str(e)}


# =============================================
# 3. 벡터 검색 노드
# =============================================
def vector_search_node(state: RecommendState) -> dict:
    """pgvector cosine similarity → 후보 상품 검색."""
    if state.get("error"):
        return {}

    embedding = state["user_embedding"]
    vdb: Session = VectorSessionLocal()
    db: Session  = SessionLocal()

    try:
        embedding_str = f"[{','.join(map(str, embedding))}]"

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
                "limit": VECTOR_CANDIDATES,
            })
            return [row[0] for row in result.fetchall()]

        card_ids      = search("card")
        insurance_ids = search("insurance")
        policy_ids    = search("policy")

        # product_id로 실제 상품 조회
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
# 4. 필터 노드 (룰 기반)
# =============================================
def filter_node(state: RecommendState) -> dict:
    """나이/소득 조건으로 정책 필터링."""
    if state.get("error"):
        return {}

    user_age    = state.get("user_age") or 0
    user_income = state.get("user_income") or 0

    filtered = []
    for policy in state["policy_candidates"]:
        age_min = policy.get("age_min")
        age_max = policy.get("age_max")

        # 나이 조건 체크
        if age_min and age_max:
            if not (age_min <= user_age <= age_max):
                continue

        filtered.append(policy)

    logger.info(f"[FilterNode] 필터 완료 - {len(state['policy_candidates'])}개 → {len(filtered)}개")
    return {"filtered_policies": filtered}


# =============================================
# 5. Conflict 노드
# =============================================
def conflict_node(state: RecommendState) -> dict:
    """정책 간 중복 불가 정보 추출."""
    if state.get("error"):
        return {}

    conflict_info = {}
    for policy in state["filtered_policies"]:
        conflict_ids = json.loads(policy.get("conflict_policy_ids") or "[]")
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
        # conflict 텍스트 생성
        conflict_text = ""
        if state["conflict_info"]:
            lines = []
            for pid, cids in state["conflict_info"].items():
                lines.append(f"- {pid}는 {', '.join(cids)}와 중복 신청 불가")
            conflict_text = "\n".join(lines)

        summary_text = ", ".join([
            f"{s['category']} {s['amount']:,}원"
            for s in state["monthly_summary"]
        ])

        prompt = f"""
당신은 청년 금융 전문가입니다. 아래 유저 정보와 후보 상품을 보고 각각 최대 {MAX_RECOMMEND}개를 추천해주세요.

[유저 정보]
- 나이: {state['user_age']}세
- 성별: {state['user_sex']}
- 월급: {state['user_income']:,}원
- 이번 달 지출: {summary_text}

[후보 카드 목록]
{json.dumps(state['card_candidates'], ensure_ascii=False, indent=2)}

[후보 보험 목록]
{json.dumps(state['insurance_candidates'], ensure_ascii=False, indent=2)}

[후보 정책 목록]
{json.dumps(state['filtered_policies'], ensure_ascii=False, indent=2)}

[정책 중복 불가 정보]
{conflict_text if conflict_text else "없음"}

규칙:
1. 카드/보험/정책 각각 최대 {MAX_RECOMMEND}개 선택
2. 추천 사유는 유저의 소비 패턴과 연결해서 한 문장으로
3. 중복 불가 정책은 추천 사유에 "이 정책은 [정책명]과 중복 신청이 불가합니다" 명시
4. 중복 가능 정책은 "이 정책은 [정책명]과 함께 신청 가능합니다" 명시
5. 금융소비자보호법을 회피하기 위해 상품 설명을 그대로 쓰지 말고, 유저 정보와 연결해서 재구성 및 토스나 카카오 뱅크 처럼 돌려서 표현

아래 JSON 형식으로만 응답하세요:
{{
  "cards": [{{"product_id": "...", "reason": "..."}}],
  "insurances": [{{"product_id": "...", "reason": "..."}}],
  "policies": [{{"product_id": "...", "reason": "..."}}]
}}
"""
        response_text = bedrock_client.recommend(prompt)

        # JSON 파싱
        clean = response_text.strip()
        if "```" in clean:
            clean = clean.split("```")[1]
            if clean.startswith("json"):
                clean = clean[4:]
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

        # 카드 저장
        for item in state.get("recommended_cards", []):
            db.add(RecommendCard(
                key             = TSID.create(),
                user_id         = user_id,
                card_product_id = item["product_id"],
                ai_reason       = item["reason"],
            ))

        # 보험 저장
        for item in state.get("recommended_insurances", []):
            db.add(RecommendInsurance(
                key                  = TSID.create(),
                user_id              = user_id,
                insurance_product_id = item["product_id"],
                ai_reason            = item["reason"],
            ))

        # 정책 저장
        for item in state.get("recommended_policies", []):
            db.add(RecommendPolicy(
                key               = TSID.create(),
                user_id           = user_id,
                policy_product_id = item["product_id"],
                ai_reason         = item["reason"],
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
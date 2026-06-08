# app/domain/recommend_ai/embed_service.py
import re
import json
import logging
import time
from sqlalchemy.orm import Session

from app.domain.recommend.entity import CardProduct, InsuranceProduct, PolicyProduct
from app.domain.recommend_ai.entity import ProductEmbedding
from app.core.client.bedrock_client import bedrock_client
from app.core.config.database import SessionLocal
from app.core.config.vector_database import VectorSessionLocal
from app.core.utils.tsid import TSID

logger = logging.getLogger(__name__)


# =============================================
# 불용어 (금융 도메인 최소화)
# =============================================
STOPWORDS = set([
    "입니다", "있습니다", "합니다", "됩니다", "드립니다",
    "받습니다", "습니다", "습니까", "니다", "하여",
    "이것", "그것", "저것", "이런", "그런", "저런",
    "그리고", "그래서", "하지만", "또한", "및",
    "을", "를", "이", "가", "은", "는", "의", "에", "로", "으로",
])

SYNONYM_MAP = {
    "식비":   "식비 외식 음식 밥 식당 배달 음식점",
    "교통":   "교통 버스 지하철 대중교통 출퇴근 교통비",
    "주거":   "주거 월세 전세 임대 주택 집 주거비",
    "의료":   "의료 병원 건강 치료 진료 약국 의료비",
    "여행":   "여행 해외 항공 관광 숙박 해외여행",
    "자동차": "자동차 차량 주유 운전 카 자동차보험",
    "문화":   "문화 공연 영화 예술 도서 문화생활",
    "교육":   "교육 학습 자격증 훈련 취업 공부",
    "쇼핑":   "쇼핑 구매 백화점 온라인몰 쇼핑몰",
    "카페":   "카페 커피 음료 카페라떼 스타벅스",
    "사업":   "창업 사업 비즈니스 스타트업 소상공인",
    "투자":   "투자 자산 저축 연금 적금 재테크",
    "주유":   "주유 기름 연료 주유소 리터",
    "통신":   "통신 휴대폰 인터넷 통신비 요금",
    "운동":   "운동 스포츠 헬스 체육 피트니스",
}

def expand_synonyms(text: str) -> str:
    for keyword, synonyms in SYNONYM_MAP.items():
        if keyword in text:
            text = text.replace(keyword, synonyms)
    return text

def normalize_numbers(text: str) -> str:
    text = re.sub(r"\d+,\d+원", "금액", text)
    text = re.sub(r"\d+만원", "금액", text)
    text = re.sub(r"\d+천원", "금액", text)
    text = re.sub(r"리터당\s*\d+원", "주유할인", text)
    text = re.sub(r"\d+%\s*할인", "할인혜택", text)
    text = re.sub(r"\d+%\s*캐시백", "캐시백혜택", text)
    text = re.sub(r"\d+%\s*적립", "적립혜택", text)
    text = re.sub(r"월\s*\d+[만천]?원", "월정액지원", text)
    text = re.sub(r"연\s*\d+[만천]?원", "연간지원", text)
    text = re.sub(r"\d+세", "청년", text)
    return text

def clean_text(text: str) -> str:
    text = text.replace(".", " ")
    words = text.split()
    words = [w for w in words if w not in STOPWORDS]
    text  = " ".join(words)
    text  = re.sub(r"\s+", " ", text)
    return text.strip()

def process_text(text: str) -> str:
    text = expand_synonyms(text)
    text = normalize_numbers(text)
    text = clean_text(text)
    return text


# =============================================
# 헬퍼
# =============================================
def _parse_benefits_text(raw: str) -> str:
    try:
        items = json.loads(raw or "[]")
        if isinstance(items, list):
            parts = []
            for b in items:
                label = b.get("label", "")
                value = b.get("value", "")
                if label or value:
                    parts.append(f"{label} {value}")
            return " ".join(parts)
    except Exception:
        pass
    return raw or ""

def _parse_tags_text(raw: str) -> str:
    try:
        items = json.loads(raw or "[]")
        if isinstance(items, list):
            return " ".join(str(t) for t in items)
    except Exception:
        pass
    return raw or ""


# =============================================
# 임베딩 텍스트 생성
# =============================================
def _card_to_text(card: CardProduct) -> str:
    benefits_text = _parse_benefits_text(card.benefits or "")
    raw = (
        f"{card.top_benefit} "
        f"혜택 {benefits_text} "
        f"{card.company} {card.card_name}"
    )
    return process_text(raw)

def _insurance_to_text(ins: InsuranceProduct) -> str:
    benefit       = ins.top_benefit or ""
    name          = ins.insurance_name or ""
    benefits_text = _parse_benefits_text(ins.benefits or "")
    type_hint     = ""

    if any(k in name or k in benefit for k in ["실손", "의료비", "입원", "통원"]):
        type_hint = "의료비 실손 보장 병원비"
    elif any(k in name or k in benefit for k in ["암", "종양", "항암"]):
        type_hint = "암 진단 집중 보장 건강"
    elif any(k in name or k in benefit for k in ["운전자", "자동차", "교통사고", "벌금"]):
        type_hint = "자동차 운전자 차량 출퇴근 운전"
    elif any(k in name or k in benefit for k in ["여행", "해외", "항공"]):
        type_hint = "여행 해외여행 사고 보장"
    elif any(k in name or k in benefit for k in ["연금", "저축", "노후"]):
        type_hint = "노후 연금 장기 자산 형성"
    elif any(k in name or k in benefit for k in ["펫", "반려", "동물"]):
        type_hint = "반려동물 펫 의료비"
    elif any(k in name or k in benefit for k in ["치아", "임플란트", "치과"]):
        type_hint = "치과 치아 임플란트 치료비"
    elif any(k in name or k in benefit for k in ["종신", "사망", "생명"]):
        type_hint = "사망 종신 가족 부양"
    elif any(k in name or k in benefit for k in ["어린이", "태아", "자녀"]):
        type_hint = "자녀 어린이 태아 성장기"

    raw = (
        f"{type_hint} "
        f"{ins.top_benefit} "
        f"혜택상세 {benefits_text} "
        f"{ins.insurer} {ins.insurance_name}"
    )
    return process_text(raw)

def _policy_to_text(policy: PolicyProduct) -> str:
    tags_text = _parse_tags_text(policy.tags or "")
    raw = (
        f"{policy.core_benefit} "
        f"카테고리 {policy.category} "
        f"태그 {tags_text} "
        f"{policy.policy_name} "
        f"주관기관 {policy.org} "
        f"지원대상 {policy.age_min}세 {policy.age_max}세 "
        f"소득조건 {policy.income_condition or ''}"
    )
    return process_text(raw)


# =============================================
# 전체 상품 임베딩 생성 (개별 commit)
# =============================================
def embed_all_products():
    db:  Session = SessionLocal()
    vdb: Session = VectorSessionLocal()
    saved = 0
    failed = 0

    try:
        # 기존 임베딩 삭제
        vdb.query(ProductEmbedding).delete()
        vdb.commit()
        logger.info("[EmbedService] 기존 임베딩 삭제 완료")

        # 카드 임베딩
        cards = db.query(CardProduct).all()
        logger.info(f"[EmbedService] 카드 임베딩 시작 - {len(cards)}개")
        for card in cards:
            try:
                text      = _card_to_text(card)
                embedding = bedrock_client.embed(text)
                time.sleep(0.5)
                vdb.add(ProductEmbedding(
                    id           = TSID.create(),
                    product_id   = card.key,
                    product_type = "card",
                    embedding    = embedding,
                    content      = text,
                ))
                vdb.commit()  # 개별 commit
                saved += 1
                if saved % 10 == 0:
                    logger.info(f"[EmbedService] 진행 중 - saved={saved}")
            except Exception as e:
                vdb.rollback()
                failed += 1
                logger.error(f"[EmbedService] 카드 임베딩 실패 - key={card.key}, error={e}")

        # 보험 임베딩
        insurances = db.query(InsuranceProduct).all()
        logger.info(f"[EmbedService] 보험 임베딩 시작 - {len(insurances)}개")
        for ins in insurances:
            try:
                text      = _insurance_to_text(ins)
                embedding = bedrock_client.embed(text)
                time.sleep(0.5)
                vdb.add(ProductEmbedding(
                    id           = TSID.create(),
                    product_id   = ins.key,
                    product_type = "insurance",
                    embedding    = embedding,
                    content      = text,
                ))
                vdb.commit()  # 개별 commit
                saved += 1
                if saved % 10 == 0:
                    logger.info(f"[EmbedService] 진행 중 - saved={saved}")
            except Exception as e:
                vdb.rollback()
                failed += 1
                logger.error(f"[EmbedService] 보험 임베딩 실패 - key={ins.key}, error={e}")

        # 정책 임베딩
        policies = db.query(PolicyProduct).all()
        logger.info(f"[EmbedService] 정책 임베딩 시작 - {len(policies)}개")
        for policy in policies:
            try:
                text      = _policy_to_text(policy)
                embedding = bedrock_client.embed(text)
                time.sleep(0.5)
                vdb.add(ProductEmbedding(
                    id           = TSID.create(),
                    product_id   = policy.key,
                    product_type = "policy",
                    embedding    = embedding,
                    content      = text,
                ))
                vdb.commit()  # 개별 commit
                saved += 1
                if saved % 50 == 0:
                    logger.info(f"[EmbedService] 진행 중 - saved={saved}")
            except Exception as e:
                vdb.rollback()
                failed += 1
                logger.error(f"[EmbedService] 정책 임베딩 실패 - key={policy.key}, error={e}")

        logger.info(f"[EmbedService] 임베딩 완료 - saved={saved}, failed={failed}")

    except Exception as e:
        vdb.rollback()
        logger.error(f"[EmbedService] 임베딩 저장 실패 - error={e}")
        raise
    finally:
        db.close()
        vdb.close()
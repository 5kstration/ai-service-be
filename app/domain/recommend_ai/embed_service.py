# app/domain/recommend_ai/embed_service.py
import logging
from sqlalchemy.orm import Session

from app.domain.recommend.entity import CardProduct, InsuranceProduct, PolicyProduct
from app.domain.recommend_ai.entity import ProductEmbedding
from app.core.client.bedrock_client import bedrock_client
from app.core.config.database import SessionLocal
from app.core.config.vector_database import VectorSessionLocal
from app.core.utils.tsid import TSID

logger = logging.getLogger(__name__)


def _card_to_text(card: CardProduct) -> str:
    return (
        f"{card.company} {card.card_name}. "
        f"{card.top_benefit}. "
        f"혜택: {card.benefits or ''}"
    )


def _insurance_to_text(ins: InsuranceProduct) -> str:
    return (
        f"{ins.insurer} {ins.insurance_name}. "
        f"핵심 혜택: {ins.top_benefit}. "
        f"혜택 상세: {ins.benefits or ''}"
    )


def _policy_to_text(policy: PolicyProduct) -> str:
    return (
        f"{policy.policy_name}. "
        f"주관기관: {policy.org}. "
        f"카테고리: {policy.category}. "
        f"핵심 혜택: {policy.core_benefit}. "
        f"지원 대상: {policy.age_min}~{policy.age_max}세. "
        f"소득 조건: {policy.income_condition or ''}. "
        f"태그: {policy.tags or ''}"
    )


def embed_all_products():
    """전체 상품 임베딩 생성 및 vector DB 저장."""
    db:  Session = SessionLocal()
    vdb: Session = VectorSessionLocal()

    try:
        # 기존 임베딩 전체 삭제 후 재생성
        vdb.query(ProductEmbedding).delete()

        saved = 0

        # 카드 임베딩
        cards = db.query(CardProduct).all()
        for card in cards:
            text = _card_to_text(card)
            embedding = bedrock_client.embed(text)
            try:
                with vdb.begin_nested():
                    vdb.add(ProductEmbedding(
                        id           = TSID.create(),
                        product_id   = card.key,
                        product_type = "card",
                        embedding    = embedding,
                        content      = text,
                    ))
                    vdb.flush()
                saved += 1
            except Exception as e:
                logger.error(f"[EmbedService] 카드 임베딩 실패 - key={card.key}, error={e}")

        # 보험 임베딩
        insurances = db.query(InsuranceProduct).all()
        for ins in insurances:
            try:
                text      = _insurance_to_text(ins)
                embedding = bedrock_client.embed(text)
                vdb.add(ProductEmbedding(
                    id           = TSID.create(),
                    product_id   = ins.key,
                    product_type = "insurance",
                    embedding    = embedding,
                    content      = text,
                ))
                saved += 1
            except Exception as e:
                logger.error(f"[EmbedService] 보험 임베딩 실패 - key={ins.key}, error={e}")

        # 정책 임베딩
        policies = db.query(PolicyProduct).all()
        for policy in policies:
            try:
                text      = _policy_to_text(policy)
                embedding = bedrock_client.embed(text)
                vdb.add(ProductEmbedding(
                    id           = TSID.create(),
                    product_id   = policy.key,
                    product_type = "policy",
                    embedding    = embedding,
                    content      = text,
                ))
                saved += 1
            except Exception as e:
                logger.error(f"[EmbedService] 정책 임베딩 실패 - key={policy.key}, error={e}")

        vdb.commit()
        logger.info(f"[EmbedService] 임베딩 완료 - total={saved}개")
    except Exception:
        vdb.rollback()
        logger.error(f"[EmbedService] 임베딩 저장 실패")
        raise

    finally:
        db.close()
        vdb.close()
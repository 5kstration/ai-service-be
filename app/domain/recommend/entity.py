# app/domain/recommend/entity.py
from sqlalchemy import Column, String, Integer, Text, DateTime, Boolean, ForeignKey
from sqlalchemy.sql import func
from app.core.config.database import Base


# =============================================
# 상품 원본 테이블 (공통 데이터)
# =============================================

class PolicyProduct(Base):
    """청년 정책 원본 데이터. 공공데이터에서 수집."""
    __tablename__ = "policy_product"

    key                  = Column(String(26),  primary_key=True, nullable=False)
    policy_name          = Column(String(255), nullable=True)
    org                  = Column(String(255), nullable=True)   # 주관기관
    category             = Column(String(100), nullable=True)   # 주거, 금융 등
    category_color       = Column(String(20),  nullable=True)
    deadline             = Column(String(50),  nullable=True)   # "2025.05.31"
    dday                 = Column(Integer,      nullable=True)
    tags                 = Column(Text,         nullable=True)   # JSON 배열
    core_benefit         = Column(String(255), nullable=True)
    description          = Column(Text,         nullable=True)
    age_min              = Column(Integer,      nullable=True)
    age_max              = Column(Integer,      nullable=True)
    income_condition     = Column(String(255), nullable=True)
    employment_condition = Column(String(255), nullable=True)
    education_condition  = Column(String(255), nullable=True)
    application_period   = Column(String(255), nullable=True)
    apply_url            = Column(Text,         nullable=True)
    created_at           = Column(DateTime,     nullable=False, server_default=func.now())
    updated_at           = Column(DateTime,     nullable=False, server_default=func.now(), onupdate=func.now())


class InsuranceProduct(Base):
    """보험 상품 원본 데이터. 금감원 API에서 수집."""
    __tablename__ = "insurance_product"

    key            = Column(String(26),  primary_key=True, nullable=False)
    insurer        = Column(String(255), nullable=True)   # 보험사
    insurance_name = Column(String(255), nullable=True)
    top_benefit    = Column(String(255), nullable=True)
    benefits       = Column(Text,        nullable=True)   # JSON [{label, value}]
    apply_url      = Column(Text,        nullable=True)
    accent_color   = Column(String(20),  nullable=True)
    created_at     = Column(DateTime,    nullable=False, server_default=func.now())
    updated_at     = Column(DateTime,    nullable=False, server_default=func.now(), onupdate=func.now())


class CardProduct(Base):
    """카드 상품 원본 데이터."""
    __tablename__ = "card_product"

    key          = Column(String(26),  primary_key=True, nullable=False)
    company      = Column(String(255), nullable=True)   # 카드사
    card_name    = Column(String(255), nullable=True)
    top_benefit  = Column(String(255), nullable=True)
    benefits     = Column(Text,        nullable=True)   # JSON [{label, value}]
    apply_url    = Column(Text,        nullable=True)
    accent_color = Column(String(20),  nullable=True)
    created_at   = Column(DateTime,    nullable=False, server_default=func.now())
    updated_at   = Column(DateTime,    nullable=False, server_default=func.now(), onupdate=func.now())


# =============================================
# 유저별 추천 결과 테이블 (유저마다 다른 데이터)
# =============================================

class RecommendPolicy(Base):
    """유저별 AI 정책 추천 결과."""
    __tablename__ = "recommend_policy"

    key               = Column(String(26), primary_key=True, nullable=False)
    user_id           = Column(String(26), nullable=False)
    policy_product_id = Column(String(26), ForeignKey("policy_product.key"), nullable=False)
    match_score       = Column(Integer,    nullable=True)
    ai_reason         = Column(Text,       nullable=True)  # 유저별 추천 사유
    created_at        = Column(DateTime,   nullable=False, server_default=func.now())


class RecommendInsurance(Base):
    """유저별 AI 보험 추천 결과."""
    __tablename__ = "recommend_insurance"

    key                  = Column(String(26), primary_key=True, nullable=False)
    user_id              = Column(String(26), nullable=False)
    insurance_product_id = Column(String(26), ForeignKey("insurance_product.key"), nullable=False)
    match_score          = Column(Integer,    nullable=True)
    ai_reason            = Column(Text,       nullable=True)
    created_at           = Column(DateTime,   nullable=False, server_default=func.now())


class RecommendCard(Base):
    """유저별 AI 카드 추천 결과."""
    __tablename__ = "recommend_card"

    key             = Column(String(26), primary_key=True, nullable=False)
    user_id         = Column(String(26), nullable=False)
    card_product_id = Column(String(26), ForeignKey("card_product.key"), nullable=False)
    match_score     = Column(Integer,    nullable=True)
    ai_reason       = Column(Text,       nullable=True)
    created_at      = Column(DateTime,   nullable=False, server_default=func.now())


# =============================================
# 북마크
# =============================================

class Bookmark(Base):
    """북마크 (정책/보험/카드 공통)."""
    __tablename__ = "bookmark"

    bookmark_id   = Column(String(26), primary_key=True, nullable=False)
    user_id       = Column(String(26), nullable=False)
    target_type   = Column(String(20), nullable=False)   # Policy, Insurance, card
    target_ref_id = Column(String(26), nullable=False)   # product 테이블의 key
    remind_at     = Column(DateTime,   nullable=True)
    is_reminded   = Column(Boolean,    nullable=True, default=False)
    created_at    = Column(DateTime,   nullable=False, server_default=func.now())
    deleted_at    = Column(DateTime,   nullable=True)
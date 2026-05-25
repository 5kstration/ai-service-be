# app/domain/recommend/entity.py
from sqlalchemy import Column, String, Integer, Text, DateTime, Boolean, ForeignKey
from sqlalchemy.sql import func
from app.core.config.database import Base


class PolicyProduct(Base):
    """청년 정책 원본 데이터."""
    __tablename__ = "policy_product"

    key                  = Column(String(26),  primary_key=True, nullable=False)
    policy_name          = Column(String(255), nullable=True)
    org                  = Column(String(255), nullable=True)
    category             = Column(String(100), nullable=True)
    category_color       = Column(String(20),  nullable=True)
    deadline             = Column(String(50),  nullable=True)
    dday                 = Column(Integer,      nullable=True)
    tags                 = Column(Text,         nullable=True)
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
    external_id = Column(String(255), nullable=True, unique=True)


class InsuranceProduct(Base):
    """보험 상품 원본 데이터."""
    __tablename__ = "insurance_product"

    key            = Column(String(26),  primary_key=True, nullable=False)
    insurer        = Column(String(255), nullable=True)
    insurance_name = Column(String(255), nullable=True)
    top_benefit    = Column(String(255), nullable=True)
    benefits       = Column(Text,        nullable=True)
    apply_url      = Column(Text,        nullable=True)
    accent_color   = Column(String(20),  nullable=True)
    created_at     = Column(DateTime,    nullable=False, server_default=func.now())
    updated_at     = Column(DateTime,    nullable=False, server_default=func.now(), onupdate=func.now())
    external_id = Column(String(255), nullable=True, unique=True)


class CardProduct(Base):
    """카드 상품 원본 데이터."""
    __tablename__ = "card_product"

    key          = Column(String(26),  primary_key=True, nullable=False)
    company      = Column(String(255), nullable=True)
    card_name    = Column(String(255), nullable=True)
    top_benefit  = Column(String(255), nullable=True)
    benefits     = Column(Text,        nullable=True)
    apply_url    = Column(Text,        nullable=True)
    accent_color = Column(String(20),  nullable=True)
    created_at   = Column(DateTime,    nullable=False, server_default=func.now())
    updated_at   = Column(DateTime,    nullable=False, server_default=func.now(), onupdate=func.now())
    external_id = Column(String(255), nullable=True, unique=True)

class RecommendPolicy(Base):
    """유저별 AI 정책 추천 결과."""
    __tablename__ = "recommend_policy"

    key               = Column(String(26), primary_key=True, nullable=False)
    user_id           = Column(String(26), nullable=False)
    policy_product_id = Column(String(26), ForeignKey("policy_product.key"), nullable=False)
    ai_reason         = Column(Text,       nullable=True)
    created_at        = Column(DateTime,   nullable=False, server_default=func.now())


class RecommendInsurance(Base):
    """유저별 AI 보험 추천 결과."""
    __tablename__ = "recommend_insurance"

    key                  = Column(String(26), primary_key=True, nullable=False)
    user_id              = Column(String(26), nullable=False)
    insurance_product_id = Column(String(26), ForeignKey("insurance_product.key"), nullable=False)
    ai_reason            = Column(Text,       nullable=True)
    created_at           = Column(DateTime,   nullable=False, server_default=func.now())


class RecommendCard(Base):
    """유저별 AI 카드 추천 결과."""
    __tablename__ = "recommend_card"

    key             = Column(String(26), primary_key=True, nullable=False)
    user_id         = Column(String(26), nullable=False)
    card_product_id = Column(String(26), ForeignKey("card_product.key"), nullable=False)
    ai_reason       = Column(Text,       nullable=True)
    created_at      = Column(DateTime,   nullable=False, server_default=func.now())


class Bookmark(Base):
    """북마크 (정책/보험/카드 공통)."""
    __tablename__ = "bookmark"

    bookmark_id   = Column(String(26), primary_key=True, nullable=False)
    user_id       = Column(String(26), nullable=False)
    target_type   = Column(String(20), nullable=False)
    target_ref_id = Column(String(26), nullable=False)
    remind_at     = Column(DateTime,   nullable=True)
    is_reminded   = Column(Boolean,    nullable=True, default=False)
    created_at    = Column(DateTime,   nullable=False, server_default=func.now())
    deleted_at    = Column(DateTime,   nullable=True)
# app/domain/recommend/entity.py
from sqlalchemy import Column, String, Text, DateTime, Boolean, ForeignKey
from sqlalchemy.sql import func
from app.core.config.database import Base
from app.core.utils.tsid import TSID


class RecommendCard(Base):
    __tablename__ = "recommend_card"

    rec_card_id     = Column(String(26),  primary_key=True, default=TSID.create, nullable=False)
    user_id         = Column(String(26),  nullable=False)
    card_company    = Column(String(255))
    card_name       = Column(String(255))
    core_benefit    = Column(Text)
    benefit_details = Column(Text)
    ai_reason       = Column(Text)
    card_url        = Column(Text)
    category        = Column(String(50))
    created_at      = Column(DateTime,    nullable=False, server_default=func.now())
    insight_id      = Column(String(26),  ForeignKey("ai_insight.insight_id"), nullable=False)


class RecommendInsurance(Base):
    __tablename__ = "recommend_insurance"

    rec_ins_id       = Column(String(26),  primary_key=True, default=TSID.create, nullable=False)
    user_id          = Column(String(26),  nullable=False)
    insurance_corp   = Column(String(255))
    insurance_name   = Column(String(255))
    core_benefit     = Column(String(255))
    coverage_details = Column(Text        )
    benefit_details  = Column(Text        )
    ai_reason        = Column(Text        )
    insurance_url    = Column(Text        )
    category         = Column(String(50),  )
    created_at       = Column(DateTime,    nullable=False, server_default=func.now())
    insight_id       = Column(String(26),  ForeignKey("ai_insight.insight_id"), nullable=False)


class RecommendPolicy(Base):
    __tablename__ = "recommend_policy"

    rec_pol_id    = Column(String(26),  primary_key=True, default=TSID.create, nullable=False)
    user_id       = Column(String(26),  nullable=False)
    policy_org    = Column(String(255))
    policy_name   = Column(String(255))
    core_benefit  = Column(String(255))
    policy_detail = Column(Text)
    ai_reason     = Column(Text)
    policy_url    = Column(Text)
    category      = Column(String(50)  )
    created_at    = Column(DateTime,    nullable=False, server_default=func.now())
    insight_id    = Column(String(26),  ForeignKey("ai_insight.insight_id"), nullable=False)


class Bookmark(Base):
    __tablename__ = "bookmark"

    bookmark_id   = Column(String(26), primary_key=True, default=TSID.create, nullable=False)
    user_id       = Column(String(26), nullable=False)
    target_type   = Column(String(20), nullable=False)
    target_ref_id = Column(String(26), nullable=False)
    remind_at     = Column(DateTime)
    is_reminded   = Column(Boolean,    nullable=False, default=False)
    created_at    = Column(DateTime,   nullable=False, server_default=func.now())
    deleted_at    = Column(DateTime)
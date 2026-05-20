# app/domain/insight/entity.py
import enum
from sqlalchemy import Column, String, Integer, BigInteger, Text, DateTime, Enum
from sqlalchemy.sql import func
from app.core.config.database import Base
from app.core.utils.tsid import TSID


class InsightType(str, enum.Enum):
    MONTHLY_ANALYSIS    = "월별 분석"
    GOAL_SUGGESTION     = "목표 제안"
    CARD_RECOMMEND      = "카드 추천"
    INSURANCE_RECOMMEND = "보험 추천"
    POLICY_RECOMMEND    = "청년 정책 추천"


class AiInsight(Base):
    __tablename__ = "ai_insight"

    insight_id       = Column(String(26),  primary_key=True, default=TSID.create, nullable=False)
    user_id          = Column(String(26),  nullable=False)
    year             = Column(Integer,     )
    month            = Column(Integer,     )
    insight_type     = Column(Enum(InsightType, name="insight_type_enum"), nullable=False)
    insight_title    = Column(String(255) )
    description      = Column(Text        )
    target_id        = Column(String(26)  )
    total_expense    = Column(BigInteger  )
    goal_expense     = Column(BigInteger  )
    achievement_rate = Column(Integer     )
    remain_budge     = Column(Integer     )
    remain_days      = Column(Integer     )
    daily_budge      = Column(Integer     )
    saving_tip       = Column(String(255) )
    icon_type        = Column(String(50)  )
    accent_color     = Column(String(10)  )
    created_at       = Column(DateTime,    nullable=False, server_default=func.now())
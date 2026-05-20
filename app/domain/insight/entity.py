# app/domain/insight/entity.py
from sqlalchemy import Column, String, Text, DateTime, Enum
from sqlalchemy.sql import func
from app.core.config.database import Base
from app.core.utils.tsid import TSID


class AiInsight(Base):

    __tablename__ = "ai_insight"

    insight_id    = Column(String(26), primary_key=True, default=TSID.create)
    user_id       = Column(String(26), nullable=False)
    insight_type  = Column(
        Enum(
            "월별 분석",
            "목표 제안",
            "카드 추천",
            "보험 추천",
            "청년 정책 추천",
            name="insight_type_enum"
        ),
        nullable=False
    )
    title         = Column(String(255))                    # API title (예: "카페 지출 줄었어요")
    description   = Column(Text)                           # API description (인사이트 본문)
    icon_type     = Column(String(50))                     # API iconType (TrendingDown, TrendingUp, Users 등)
    accent_color  = Column(String(10))                     # API accentColor (예: "#3182F6")
    goal_id       = Column(String(26))                     # 목표 id 참조
    created_at    = Column(DateTime, server_default=func.now())
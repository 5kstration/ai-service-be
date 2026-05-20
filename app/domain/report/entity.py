from sqlalchemy import Column, String, Integer, Text, DateTime
from sqlalchemy.sql import func

from app.core.config.database import Base
from app.core.utils.tsid import TSID



class AiReport(Base):
    __tablename__ = "ai_report"

    report_id        = Column(String(26), primary_key=True, default=TSID.create)
    user_id          = Column(String(26), nullable=False)
    year             = Column(Integer, nullable=False)
    month            = Column(Integer, nullable=False)
    summary_message  = Column(Text)
    total_expense    = Column(Integer)
    target_expense   = Column(Integer)
    achievement_rate = Column(Integer)
    insight_id       = Column(String(26))
    created_at       = Column(DateTime, server_default=func.now())
    updated_at       = Column(DateTime, server_default=func.now(), onupdate=func.now())
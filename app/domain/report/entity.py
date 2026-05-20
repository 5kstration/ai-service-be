# app/domain/report/entity.py
from sqlalchemy import Column, String, Integer, Text, DateTime, Date, Numeric
from sqlalchemy.sql import func
from app.core.config.database import Base
from app.core.utils.tsid import TSID


class AiReport(Base):
    __tablename__ = "ai_report"

    report_id        = Column(String(26), primary_key=True, default=TSID.create, nullable=False)
    user_id          = Column(String(26), nullable=False)
    year             = Column(Integer,    nullable=False)
    month            = Column(Integer,    nullable=False)
    summary_message  = Column(Text)
    total_expense    = Column(Integer)
    target_expense   = Column(Integer)
    achievement_rate = Column(Integer)
    remain_budge     = Column(Integer,    nullable=True)   # 목표 - 총 지출 = 남은 예산
    remain_days      = Column(Integer,    nullable=True)   # 이번 달 남은 날짜
    daily_budge      = Column(Integer,    nullable=True)   # 남은 예산 / 남은 날짜
    saving_tip       = Column(String(255),nullable=True)   # LLM이 생성한 절약 팁

    insight_id       = Column(String(26))
    created_at       = Column(DateTime,   nullable=False, server_default=func.now())
    updated_at       = Column(DateTime,   nullable=False, server_default=func.now(), onupdate=func.now())


class MonthlySummary(Base):
    __tablename__ = "monthly_summary"

    summary_id = Column(String(26),     primary_key=True, default=TSID.create, nullable=False)
    user_id    = Column(String(26),     nullable=False)
    year       = Column(Integer,        nullable=False)
    month      = Column(Integer,        nullable=False)
    category   = Column(String(100))
    amount     = Column(Integer)
    ratio      = Column(Numeric(5, 2))
    created_at = Column(DateTime,       nullable=False, server_default=func.now())


class WeeklyExpense(Base):
    __tablename__ = "weekly_expense"

    weekly_id  = Column(String(26), primary_key=True, default=TSID.create, nullable=False)
    user_id    = Column(String(26), nullable=False)
    year       = Column(Integer,    nullable=False)
    month      = Column(Integer,    nullable=False)
    week       = Column(Integer,    nullable=False)
    amount     = Column(Integer,  default=0)
    start_date = Column(Date)
    end_date   = Column(Date)
    created_at = Column(DateTime,   nullable=False, server_default=func.now())


class Goal(Base):
    __tablename__ = "goal"

    goal_id       = Column(String(26),  primary_key=True, default=TSID.create, nullable=False)
    user_id       = Column(String(26),  nullable=False)
    goal_month    = Column(Date)
    total_expense = Column(Integer)
    goal_expense  = Column(Integer)
    description   = Column(String(255))
    created_at    = Column(DateTime,    nullable=False, server_default=func.now())
    updated_at    = Column(DateTime,    nullable=False, server_default=func.now(), onupdate=func.now())
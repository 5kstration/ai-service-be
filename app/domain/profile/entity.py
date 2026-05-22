# app/domain/profile/entity.py
from sqlalchemy import Column, String, Integer, Date, DateTime
from sqlalchemy.sql import func
from app.core.config.database import Base
from app.core.utils.tsid import TSID

# auth-service 온보딩 데이터 복사본
class UserProfile(Base):
    __tablename__ = "user_profile"

    user_id        = Column(String(26),  primary_key=True, nullable=False)
    birth          = Column(Date,        nullable=True)
    sex            = Column(String(10),  nullable=True)   # "남자", "여자"
    monthly_income = Column(Integer,  nullable=True)
    created_at     = Column(DateTime,    nullable=False, server_default=func.now())
    updated_at     = Column(DateTime,    nullable=False, server_default=func.now(), onupdate=func.now())
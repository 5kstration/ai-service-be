# app/domain/report/repository.py
import logging
from datetime import date
from typing import Optional

from sqlalchemy.orm import Session
from sqlalchemy.exc import SQLAlchemyError

from app.domain.report.entity import AiReport, WeeklyExpense, Goal
from app.core.error.exception import BusinessException
from app.core.error.error_code import ErrorCode

logger = logging.getLogger(__name__)


class ReportRepository:
    def __init__(self, db: Session):
        self.db = db
        
        
        
        
    # 오늘 날짜(year/month/day) 기준 리포트 단건 조회.
    # Redis 캐시 미스 시 호출.
    def find_today(self, user_id: str) -> Optional[AiReport]:
        today = date.today()
        try:
            return (
                self.db.query(AiReport)
                .filter(
                    AiReport.user_id == user_id,
                    AiReport.year    == today.year,
                    AiReport.month   == today.month,
                    AiReport.day     == today.day,
                )
                .first()
            )
        except SQLAlchemyError as e:
            logger.error(f"[ReportRepository] 오늘 리포트 조회 실패 - user_id={user_id}, error={e}")
            raise BusinessException(ErrorCode.DB_ERROR)
  
  
  
  
  
    # 이번 달 리포트 단건 조회. LLM 프롬프트 구성 시 이번 달 리포트 데이터로 활용.
    def find_goal_current_month(self, user_id: str) -> Optional[Goal]:
        today = date.today()
        try:
            return (
                self.db.query(Goal)
                .filter(
                    Goal.user_id    == user_id,
                    Goal.goal_month == date(today.year, today.month, 1),
                )
                .first()
            )
        except SQLAlchemyError as e:
            logger.error(f"[ReportRepository] 목표 조회 실패 - user_id={user_id}, error={e}")
            raise BusinessException(ErrorCode.DB_ERROR)

   
   
   
   
   # 이번 달 주차별 지출 목록 조회. LLM 프롬프트 구성 시 주간 지출 데이터로 활용.
    def find_weekly_expenses_current_month(self, user_id: str) -> list[WeeklyExpense]:
        today = date.today()
        try:
            return (
                self.db.query(WeeklyExpense)
                .filter(
                    WeeklyExpense.user_id == user_id,
                    WeeklyExpense.year    == today.year,
                    WeeklyExpense.month   == today.month,
                )
                .order_by(WeeklyExpense.week.asc())
                .all()
            )
        except SQLAlchemyError as e:
            logger.error(f"[ReportRepository] 주간 지출 조회 실패 - user_id={user_id}, error={e}")
            raise BusinessException(ErrorCode.DB_ERROR)






    # 리포트 저장.
    def save(self, report: AiReport) -> AiReport:
        try:
            self.db.merge(report)
            self.db.commit()
            self.db.refresh(report)
            return report
        except SQLAlchemyError as e:
            self.db.rollback()
            logger.error(f"[ReportRepository] 리포트 저장 실패 - user_id={report.user_id}, error={e}")
            raise BusinessException(ErrorCode.DB_ERROR)
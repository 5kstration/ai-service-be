# app/domain/report/repository.py
import logging
from datetime import date
from typing import Optional

from sqlalchemy.orm import Session
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy import func, text
from app.domain.profile.entity import UserProfile
from datetime import date
from app.domain.report.entity import AiReport, WeeklyExpense, Goal
from app.core.error.exception import BusinessException
from app.core.error.error_code import ErrorCode

logger = logging.getLogger(__name__)


class ReportRepository:
    def __init__(self, db: Session):
        self.db = db

# =============================================
#  또래 그룹 카테고리별 평균 지출 집계
# =============================================

    def find_peer_avg_by_category(self, user_id: str, age_range: int = 3) -> list[dict]:
        """
        또래 그룹 카테고리별 평균 지출 집계.
 
        또래 기준:
        - user_profile 테이블에서 나이 ±age_range(3) 이내 유저
        - 본인 제외
        - 이번 달 monthly_summary 데이터 있는 유저만
 
        개인정보 보호:
        - 그룹 인원 5명 미만이면 빈 리스트 반환 (개인 특정 방지)
        """

 
        today = date.today()
 
        try:
            # 1. 본인 나이 조회
            my_profile = (
                self.db.query(UserProfile)
                .filter(UserProfile.user_id == user_id)
                .first()
            ) # 내정보 조회 실패는 예외 처리보다 빈 결과로 대응 (또래 비교 자체가 불가능하므로)
            if not my_profile or not my_profile.birth:
                logger.warning(f"[ReportRepository] 온보딩 정보 없음 - user_id={user_id}")
                return []

            # 내 나이 계산
            my_age = today.year - my_profile.birth.year
 
            # 2. 또래 유저 ID 목록 조회 (나이 ±3, 본인 제외)
            peer_ids = (
                self.db.query(UserProfile.user_id)
                .filter(
                    UserProfile.user_id != user_id,
                    func.extract("year", func.now()) - func.extract("year", UserProfile.birth)
                    >= my_age - age_range,
                    func.extract("year", func.now()) - func.extract("year", UserProfile.birth)
                    <= my_age + age_range,
                )
                .all()
            )
            peer_id_list = [p.user_id for p in peer_ids]
 
            # 3. 개인 특정 방지 (5명 미만이면 빈 리스트)
            if len(peer_id_list) < 5:
                logger.warning(f"[ReportRepository] 또래 그룹 인원 부족 - count={len(peer_id_list)}")
                return []
 
            # 4. 또래 카테고리별 평균 집계
            results = (
                self.db.query(
                    MonthlySummary.category,
                    func.avg(MonthlySummary.amount).label("avg_amount"),
                    func.count(MonthlySummary.user_id).label("peer_count"),
                )
                .filter(
                    MonthlySummary.user_id.in_(peer_id_list),
                    MonthlySummary.year  == today.year,
                    MonthlySummary.month == today.month,
                )
                .group_by(MonthlySummary.category)
                .all()
            )
 
            return [
                {
                    "category":    r.category,
                    "avg_amount":  int(r.avg_amount),
                    "peer_count":  r.peer_count,
                }
                for r in results
            ]
 
        except SQLAlchemyError as e:
            logger.error(f"[ReportRepository] 또래 집계 실패 - user_id={user_id}, error={e}")
            raise BusinessException(ErrorCode.DB_ERROR)





# =============================================
# 리포트 조회/저장 관련 DB 처리
# =============================================

    def find_today(self, user_id: str) -> Optional[AiReport]:
        # 오늘 날짜(year/month/day) 기준 리포트 단건 조회.
        # Redis 캐시 미스 시 호출.
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

    def find_goal_current_month(self, user_id: str) -> Optional[Goal]:
        # 이번 달 목표 단건 조회.
        # LLM 프롬프트 구성 시 target_expense 계산에 활용.
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

    def find_weekly_expenses_current_month(self, user_id: str) -> list[WeeklyExpense]:
        # 이번 달 주차별 지출 목록 조회.
        # LLM 프롬프트 구성 시 주간 지출 데이터로 활용.
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

    def save(self, report: AiReport) -> AiReport:
        # 리포트 신규 저장.
        # 저장 실패 시 rollback 후 DB_ERROR 발생.
        try:
            self.db.add(report)
            self.db.commit()
            self.db.refresh(report)
            return report
        except SQLAlchemyError as e:
            self.db.rollback()
            logger.error(f"[ReportRepository] 리포트 저장 실패 - user_id={report.user_id}, error={e}")
            raise BusinessException(ErrorCode.DB_ERROR)
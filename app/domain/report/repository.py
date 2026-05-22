# app/domain/report/repository.py
import logging
from datetime import date
from typing import Optional

from sqlalchemy.orm import Session
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy import func

from app.domain.profile.entity import UserProfile
from app.domain.report.entity import AiReport, WeeklyExpense, Goal, MonthlySummary
from app.core.error.exception import BusinessException
from app.core.error.error_code import ErrorCode

logger = logging.getLogger(__name__)

PEER_MIN_COUNT = 5  # 개인 특정 방지 최소 또래 인원


class ReportRepository:
    def __init__(self, db: Session):
        self.db = db

    # =============================================
    # 리포트
    # =============================================

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
            self.db.rollback()
            logger.error(f"[ReportRepository] 오늘 리포트 조회 실패 - error={e}")
            raise BusinessException(ErrorCode.DB_ERROR)

    def save(self, report: AiReport) -> AiReport:
        try:
            self.db.add(report)
            self.db.commit()
            self.db.refresh(report)
            return report
        except SQLAlchemyError as e:
            self.db.rollback()
            logger.error(f"[ReportRepository] 리포트 저장 실패 - error={e}")
            raise BusinessException(ErrorCode.DB_ERROR)

    # =============================================
    # 목표
    # =============================================

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
            self.db.rollback()
            logger.error(f"[ReportRepository] 목표 조회 실패 - error={e}")
            raise BusinessException(ErrorCode.DB_ERROR)

    # =============================================
    # 주간 지출
    # =============================================

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
            self.db.rollback()
            logger.error(f"[ReportRepository] 주간 지출 조회 실패 - error={e}")
            raise BusinessException(ErrorCode.DB_ERROR)

    # =============================================
    # 카테고리별 월간 집계
    # =============================================

    def find_monthly_summary_current_month(self, user_id: str) -> list[MonthlySummary]:
        today = date.today()
        try:
            return (
                self.db.query(MonthlySummary)
                .filter(
                    MonthlySummary.user_id == user_id,
                    MonthlySummary.year    == today.year,
                    MonthlySummary.month   == today.month,
                )
                .order_by(MonthlySummary.amount.desc())
                .all()
            )
        except SQLAlchemyError as e:
            self.db.rollback()
            logger.error(f"[ReportRepository] 카테고리 집계 조회 실패 - error={e}")
            raise BusinessException(ErrorCode.DB_ERROR)

    # =============================================
    # 또래 비교
    # =============================================

    def find_peer_avg_by_category(self, user_id: str, age_range: int = 3) -> list[dict]:
        """
        또래 그룹 카테고리별 평균 지출 집계.

        익명화 기준:
        - user_profile 나이 ±3 이내 유저 중 본인 제외
        - 이번 달 monthly_summary 데이터가 실제로 있는 유저 기준 5명 이상
        - 카테고리별 peer_count도 5명 미만이면 해당 카테고리 제외
        """
        today = date.today()

        try:
            # 1. 본인 프로필 조회
            my_profile = (
                self.db.query(UserProfile)
                .filter(UserProfile.user_id == user_id)
                .first()
            )
            if not my_profile or not my_profile.birth:
                logger.warning(f"[ReportRepository] 온보딩 정보 없음")
                return []

            # 2. 내 나이 계산
            my_age = today.year - my_profile.birth.year

            # 3. 또래 유저 ID 목록 조회 (나이 ±3, 본인 제외)
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

            if not peer_id_list:
                logger.warning(f"[ReportRepository] 또래 후보 없음")
                return []

            # 4. 카테고리별 집계 (peer_count 포함)
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

            # 5. 실제 monthly_summary 있는 또래 수 확인
            # (모든 카테고리 중 가장 많은 peer_count 기준)
            if not results:
                logger.warning(f"[ReportRepository] 또래 집계 데이터 없음")
                return []

            max_peer_count = max(r.peer_count for r in results)
            if max_peer_count < PEER_MIN_COUNT:
                logger.warning(
                    f"[ReportRepository] 또래 그룹 인원 부족 - "
                    f"max_peer_count={max_peer_count}, 기준={PEER_MIN_COUNT}"
                )
                return []

            # 6. 카테고리별 peer_count도 5명 미만이면 해당 카테고리 제외
            return [
                {
                    "category":   r.category,
                    "avg_amount": int(r.avg_amount),
                    "peer_count": r.peer_count,
                }
                for r in results
                if r.peer_count >= PEER_MIN_COUNT
            ]

        except SQLAlchemyError as e:
            self.db.rollback()
            logger.error(f"[ReportRepository] 또래 집계 실패 - error={e}")
            raise BusinessException(ErrorCode.DB_ERROR)
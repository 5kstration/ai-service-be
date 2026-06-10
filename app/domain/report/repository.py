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
    # 목표 (Goal)
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

    def save_goal(self, goal: Goal) -> Goal:
        """이번 달 목표 저장. 이미 존재하면 GOAL_ALREADY_EXISTS 예외."""
        try:
            existing = self.find_goal_current_month(goal.user_id)
            if existing:
                raise BusinessException(ErrorCode.GOAL_ALREADY_EXISTS)

            self.db.add(goal)
            self.db.commit()
            self.db.refresh(goal)
            logger.info(f"[ReportRepository] 목표 저장 완료 - user_id={goal.user_id}, goal_expense={goal.goal_expense}")
            return goal
        except BusinessException:
            raise
        except SQLAlchemyError as e:
            self.db.rollback()
            logger.error(f"[ReportRepository] 목표 저장 실패 - error={e}")
            raise BusinessException(ErrorCode.DB_ERROR)

    # =============================================
    # 유저 프로필 (UserProfile)
    # =============================================

    def find_profile(self, user_id: str) -> Optional[UserProfile]:
        """유저 프로필 조회."""
        try:
            return (
                self.db.query(UserProfile)
                .filter(UserProfile.user_id == user_id)
                .first()
            )
        except SQLAlchemyError as e:
            self.db.rollback()
            logger.error(f"[ReportRepository] 유저 프로필 조회 실패 - error={e}")
            raise BusinessException(ErrorCode.DB_ERROR)

    def patch_profile(
        self,
        user_id: str,
        monthly_income: Optional[int],
        birth,
        sex: Optional[str],
    ) -> UserProfile:
        """
        유저 프로필 부분 업데이트 (patch).
        None으로 들어온 필드는 기존 값을 유지.
        프로필 row가 없으면 신규 생성 (consumer.py의 handle_onboarding_event와 동일).
        """
        try:
            existing = self.find_profile(user_id)
            if existing:
                # None이 아닌 필드만 덮어씀
                if monthly_income is not None:
                    existing.monthly_income = monthly_income
                if birth is not None:
                    existing.birth = birth
                if sex is not None:
                    existing.sex = sex
                self.db.commit()
                self.db.refresh(existing)
                logger.info(
                    f"[ReportRepository] 유저 프로필 부분 업데이트 완료 - user_id={user_id}, "
                    f"updated_fields={{'monthly_income': {monthly_income is not None}, "
                    f"'birth': {birth is not None}, 'sex': {sex is not None}}}"
                )
                return existing
            else:
                profile = UserProfile(
                    user_id        = user_id,
                    monthly_income = monthly_income,
                    birth          = birth,
                    sex            = sex,
                )
                self.db.add(profile)
                self.db.commit()
                self.db.refresh(profile)
                logger.info(f"[ReportRepository] 유저 프로필 신규 저장 완료 - user_id={user_id}")
                return profile
        except BusinessException:
            raise
        except SQLAlchemyError as e:
            self.db.rollback()
            logger.error(f"[ReportRepository] 유저 프로필 저장 실패 - error={e}")
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
    # 월간 요약 (MonthlySummary)
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
            logger.error(f"[ReportRepository] 월간 요약 조회 실패 - error={e}")
            raise BusinessException(ErrorCode.DB_ERROR)
    # =============================================
    # 또래 비교
    # =============================================

    def find_peer_avg_by_category(self, user_id: str) -> list[dict]:
        """
        나이 ±3세 또래 그룹의 카테고리별 평균 지출.
        PEER_MIN_COUNT 미만이면 개인 특정 방지를 위해 빈 리스트 반환.
        """
        try:
            today   = date.today()
            profile = self.find_profile(user_id)
            if not profile or not profile.birth:
                return []

            my_age   = today.year - profile.birth.year
            year_min = today.year - (my_age + 3)
            year_max = today.year - (my_age - 3)

            peer_ids = (
                self.db.query(UserProfile.user_id)
                .filter(
                    UserProfile.user_id != user_id,
                    UserProfile.birth   != None,
                    func.extract("year", UserProfile.birth).between(year_min, year_max),
                )
                .all()
            )

            if len(peer_ids) < PEER_MIN_COUNT:
                logger.info(f"[ReportRepository] 또래 부족 - count={len(peer_ids)}, min={PEER_MIN_COUNT}")
                return []

            peer_user_ids = [p.user_id for p in peer_ids]

            rows = (
                self.db.query(
                    MonthlySummary.category,
                    func.avg(MonthlySummary.amount).label("avg_amount"),
                )
                .filter(
                    MonthlySummary.user_id.in_(peer_user_ids),
                    MonthlySummary.year  == today.year,
                    MonthlySummary.month == today.month,
                )
                .group_by(MonthlySummary.category)
                .all()
            )

            return [{"category": r.category, "avg_amount": int(r.avg_amount or 0)} for r in rows]

        except SQLAlchemyError as e:
            self.db.rollback()
            logger.error(f"[ReportRepository] 또래 비교 조회 실패 - error={e}")
            raise BusinessException(ErrorCode.DB_ERROR)
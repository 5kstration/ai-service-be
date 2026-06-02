# app/domain/report/service.py
import json
import logging
import calendar
import time
from datetime import date, datetime
from typing import Optional

from sqlalchemy.orm import Session

from app.domain.report.repository import ReportRepository
from app.domain.report.schema import (
    ReportResponse,
    PeersComparisonResponse,
    PeerCategoryItem,
    ReportEntryStatusResponse,
    ProfileSetupRequest,
    ProfileSetupResponse,
    GoalSetupRequest,
    GoalSetupResponse,
)
from app.domain.report.entity import AiReport, Goal
from app.core.config.redis import get_redis_client
from app.core.config.sqs import publish_profile_update
from app.core.error.exception import BusinessException
from app.core.error.error_code import ErrorCode
from app.core.utils.tsid import TSID
from app.core.client.llm_client import llm_client

logger = logging.getLogger(__name__)

REPORT_CACHE_TTL    = 86400  # 리포트 캐시 TTL: 1일
GENERATING_LOCK_TTL = 60     # LLM 생성 중 분산 락 TTL: 60초
LLM_MAX_RETRY       = 2      # LLM 호출 최대 재시도 횟수
LLM_RETRY_DELAY     = 1.5    # LLM 재시도 간격 (초)
LOCK_WAIT_SECONDS   = 3      # 락 대기 후 DB 재조회까지 대기 시간 (초)


def _cache_key(user_id: str) -> str:
    today = date.today()
    return f"report:{user_id}:{today.year}:{today.month}:{today.day}"


def _lock_key(user_id: str) -> str:
    today = date.today()
    return f"report:lock:{user_id}:{today.year}:{today.month}:{today.day}"


class ReportService:
    def __init__(self, db: Session):
        self.repo = ReportRepository(db)

    # =============================================
    # AI 리포트 탭 진입 상태 체크
    # =============================================

    def check_entry_status(self, user_id: str) -> ReportEntryStatusResponse:
        """
        AI 리포트 탭 진입 시 클라이언트가 가장 먼저 호출하는 API.

        체크 순서:
        1. user_profile 존재 여부 (monthly_income 필수)
        2. 이번 달 goal 존재 여부

        반환 예시:
        - profile_required=True  → 클라이언트: 프로필 입력 화면으로 이동
        - goal_required=True     → 클라이언트: 목표 설정 화면으로 이동
        - is_ready=True          → 클라이언트: 리포트 조회 API 호출
        """
        profile = self.repo.find_profile(user_id)

        # monthly_income이 없으면 프로필 입력 필요
        profile_required = (
            profile is None
            or profile.monthly_income is None
            or profile.monthly_income <= 0
        )

        # 프로필 없으면 goal 체크 의미 없음
        if profile_required:
            logger.info(f"[ReportService] 프로필 미설정 - user_id={user_id}")
            return ReportEntryStatusResponse(
                profile_required = True,
                goal_required    = True,   # 어차피 다음 단계
                is_ready         = False,
            )

        goal = self.repo.find_goal_current_month(user_id)
        goal_required = (goal is None)

        is_ready = not goal_required
        logger.info(
            f"[ReportService] 진입 상태 체크 완료 - user_id={user_id}, "
            f"profile_required={profile_required}, goal_required={goal_required}"
        )
        return ReportEntryStatusResponse(
            profile_required = False,
            goal_required    = goal_required,
            is_ready         = is_ready,
        )

    # =============================================
    # 프로필 비어있는 필드 조회
    # =============================================

    def get_profile_missing_fields(self, user_id: str) -> "ProfileMissingFieldsResponse":
        """
        현재 저장된 프로필에서 비어있는 필드만 반환.
        프론트가 이 응답을 보고 어떤 입력 필드를 보여줄지 결정.
        """
        from app.domain.report.schema import ProfileMissingFieldsResponse
        profile = self.repo.find_profile(user_id)

        return ProfileMissingFieldsResponse(
            monthly_income_missing = (profile is None or profile.monthly_income is None or profile.monthly_income <= 0),
            birth_missing          = (profile is None or profile.birth is None),
            sex_missing            = (profile is None or profile.sex is None),
            monthly_income         = profile.monthly_income if profile else None,
            birth                  = profile.birth if profile else None,
            sex                    = profile.sex if profile else None,
        )

    # =============================================
    # 프로필 설정 (온보딩 스킵 유저 대상)
    # =============================================

    def setup_profile(self, user_id: str, req: "ProfileSetupRequest") -> "ProfileSetupResponse":
        """
        보내온 필드만 업데이트. None으로 보낸 필드는 기존 저장값 유지.
        SQS 발행도 이번 요청에서 실제 변경된 필드 + 기존 저장값을 합쳐서 전체 스냅샷 발행.

        예: birth만 보내면 → birth만 업데이트, monthly_income/sex는 기존값 유지.
            SQS에는 {userId, monthlyIncome: 기존값, birth: 새값, sex: 기존값} 으로 발행.
        """
        from app.domain.report.schema import ProfileSetupResponse

        # 요청에서 실제로 값이 들어온 필드만 추적
        updated_fields = []
        if req.monthly_income is not None:
            if req.monthly_income < 0:
                raise BusinessException(ErrorCode.INVALID_REQUEST)
            updated_fields.append("monthly_income")
        if req.birth is not None:
            updated_fields.append("birth")
        if req.sex is not None:
            updated_fields.append("sex")

        if not updated_fields:
            raise BusinessException(ErrorCode.INVALID_REQUEST)

        profile = self.repo.patch_profile(
            user_id        = user_id,
            monthly_income = req.monthly_income,
            birth          = req.birth,
            sex            = req.sex,
        )

        # SQS 발행: AUTH가 받는 형식 그대로 (전체 스냅샷 = 업데이트 후 최종 저장값)
        sqs_payload = {
            "userId":        user_id,
            "monthlyIncome": profile.monthly_income,
            "birth":         profile.birth.isoformat() + "T00:00:00" if profile.birth else None,
            "sex":           profile.sex,
        }
        published = publish_profile_update(sqs_payload)
        if not published:
            logger.warning(
                f"[ReportService] 프로필 SQS 발행 실패 - user_id={user_id}. "
                f"프로필 저장은 완료. AUTH 서비스 데이터 불일치 가능."
            )

        goal = self.repo.find_goal_current_month(user_id)
        goal_required = (goal is None)

        logger.info(
            f"[ReportService] 프로필 설정 완료 - user_id={user_id}, "
            f"updated_fields={updated_fields}, goal_required={goal_required}"
        )
        return ProfileSetupResponse(
            user_id        = user_id,
            monthly_income = profile.monthly_income,
            birth          = profile.birth,
            sex            = profile.sex,
            goal_required  = goal_required,
            updated_fields = updated_fields,
        )

    # =============================================
    # 이번 달 목표 설정
    # =============================================

    def setup_goal(self, user_id: str, req: GoalSetupRequest) -> GoalSetupResponse:
        """
        이번 달 목표 지출액 설정.

        - 이번 달 goal이 이미 있으면 GOAL_ALREADY_EXISTS (409) 반환.
        - goal_expense는 1원 이상이어야 함.
        """
        if req.goal_expense <= 0:
            raise BusinessException(ErrorCode.INVALID_REQUEST)

        today      = date.today()
        goal_month = date(today.year, today.month, 1)

        goal = Goal(
            goal_id       = TSID.create(),
            user_id       = user_id,
            goal_month    = goal_month,
            goal_expense  = req.goal_expense,
            total_expense = 0,
            description   = None,
        )
        saved = self.repo.save_goal(goal)

        logger.info(
            f"[ReportService] 목표 설정 완료 - user_id={user_id}, "
            f"goal_month={goal_month}, goal_expense={req.goal_expense}"
        )
        return GoalSetupResponse(
            goal_id      = saved.goal_id,
            goal_month   = saved.goal_month,
            goal_expense = saved.goal_expense,
        )

    # =============================================
    # 또래비교 리턴
    # =============================================

    def get_peers_comparison(self, user_id: str) -> PeersComparisonResponse:
        """
        카테고리별 나의 지출 vs 또래 평균 비교.

        예외 케이스:
        - 온보딩 정보 없음  → categories 빈 리스트 반환
        - 또래 5명 미만     → categories 빈 리스트 반환
        - 내 데이터 없음    → categories 빈 리스트 반환
        """
        today = date.today()

        peer_avgs    = self.repo.find_peer_avg_by_category(user_id)
        my_summaries = self.repo.find_monthly_summary_current_month(user_id)

        if not peer_avgs or not my_summaries:
            return PeersComparisonResponse(
                year       = today.year,
                month      = today.month,
                categories = [],
            )

        my_map = {s.category: (s.amount or 0) for s in my_summaries}

        categories = []
        for peer in peer_avgs:
            my_amount       = my_map.get(peer["category"], 0)
            peer_avg_amount = peer["avg_amount"]
            diff_amount     = my_amount - peer_avg_amount
            diff_rate       = int(diff_amount / peer_avg_amount * 100) if peer_avg_amount > 0 else 0

            categories.append(PeerCategoryItem(
                category        = peer["category"],
                my_amount       = my_amount,
                peer_avg_amount = peer_avg_amount,
                diff_amount     = diff_amount,
                diff_rate       = diff_rate,
            ))

        saving_categories = [c for c in categories if c.diff_amount < 0]
        best_saving = min(saving_categories, key=lambda x: x.diff_amount) if saving_categories else None

        return PeersComparisonResponse(
            year                 = today.year,
            month                = today.month,
            categories           = categories,
            best_saving_category = best_saving.category if best_saving else None,
            best_saving_amount   = abs(best_saving.diff_amount) if best_saving else None,
        )

    # =============================================
    # AI 리포트 조회/생성 로직
    # =============================================

    def get_or_generate_report(self, user_id: str) -> ReportResponse:
        """
        AI 리포트 메뉴 진입 시 호출.
        Redis → DB → LLM 생성 순으로 처리.

        사전 조건: check_entry_status에서 is_ready=True 확인 후 호출해야 함.
        프로필/목표 미설정 상태로 호출 시 LLM이 빈 데이터로 생성 진행 (클라이언트 책임).
        """
        cache_key = _cache_key(user_id)
        lock_key  = _lock_key(user_id)

        # ── Step 1. Redis 캐시 조회 ──────────────────────────
        cached = self._get_from_cache(cache_key)
        if cached:
            logger.info(f"[ReportService] 캐시 히트 - user_id={user_id}")
            return cached

        # ── Step 2. DB 조회 ──────────────────────────────────
        logger.info(f"[ReportService] 캐시 미스 - DB 조회. user_id={user_id}")
        report = self.repo.find_today(user_id)
        if report:
            logger.info(f"[ReportService] DB 히트 - Redis 재캐싱. report_id={report.report_id}")
            response = self._to_response(report)
            self._set_to_cache(cache_key, response)
            return response

        # ── Step 3. 동시성 락 획득 ───────────────────────────
        lock_acquired = self._acquire_lock(lock_key)
        if not lock_acquired:
            logger.warning(f"[ReportService] 락 획득 실패 - 다른 요청 생성 중. user_id={user_id}")
            time.sleep(LOCK_WAIT_SECONDS)
            report = self.repo.find_today(user_id)
            if report:
                logger.info(f"[ReportService] 락 대기 후 DB 히트 - report_id={report.report_id}")
                response = self._to_response(report)
                self._set_to_cache(cache_key, response)
                return response
            raise BusinessException(ErrorCode.REDIS_LOCK_ACQUIRE_FAILED)

        # ── Step 4. LLM 생성 ─────────────────────────────────
        try:
            logger.info(f"[ReportService] 락 획득 성공 - LLM 생성 시작. user_id={user_id}")
            return self._generate_report(user_id, cache_key)
        finally:
            self._release_lock(lock_key)

    # =============================================
    # LLM 생성 로직
    # =============================================
    def _generate_report(self, user_id: str, cache_key: str) -> ReportResponse:
        today = date.today()

        goal           = self.repo.find_goal_current_month(user_id)
        target_expense = goal.goal_expense if goal else 0
        logger.info(f"[ReportService] 목표 조회 완료 - target_expense={target_expense}")

        weekly_expenses = self.repo.find_weekly_expenses_current_month(user_id)
        total_expense   = sum(w.amount or 0 for w in weekly_expenses)
        logger.info(f"[ReportService] 주간 지출 조회 완료 - total_expense={total_expense}")

        achievement_rate = int((total_expense / target_expense) * 100) if target_expense > 0 else 0
        remain_budge     = max(target_expense - total_expense, 0)
        remain_days      = calendar.monthrange(today.year, today.month)[1] - today.day
        daily_budge      = int(remain_budge / remain_days) if remain_days > 0 else 0

        summary_message, saving_tip = self._call_llm_with_retry(
            user_id          = user_id,
            total_expense    = total_expense,
            target_expense   = target_expense,
            achievement_rate = achievement_rate,
            weekly_expenses  = weekly_expenses,
        )

        report = AiReport(
            report_id        = TSID.create(),
            user_id          = user_id,
            year             = today.year,
            month            = today.month,
            day              = today.day,
            summary_message  = summary_message,
            total_expense    = total_expense,
            target_expense   = target_expense,
            achievement_rate = achievement_rate,
            remain_budge     = remain_budge,
            remain_days      = remain_days,
            daily_budge      = daily_budge,
            saving_tip       = saving_tip,
        )
        saved = self.repo.save(report)
        logger.info(f"[ReportService] 리포트 DB 저장 완료 - report_id={saved.report_id}")

        response = self._to_response(saved)
        self._set_to_cache(cache_key, response)
        return response

    def _call_llm_with_retry(
        self,
        user_id: str,
        total_expense: int,
        target_expense: int,
        achievement_rate: int,
        weekly_expenses: list,
    ) -> tuple[str, str]:
        last_error = None

        for attempt in range(1, LLM_MAX_RETRY + 2):
            try:
                return llm_client.generate_report_message(
                    user_id          = user_id,
                    total_expense    = total_expense,
                    target_expense   = target_expense,
                    achievement_rate = achievement_rate,
                    weekly_expenses  = weekly_expenses,
                )
            except BusinessException as e:
                if e.error_code == ErrorCode.LLM_RESPONSE_PARSE_FAILED:
                    raise
                last_error = e
                if attempt <= LLM_MAX_RETRY:
                    logger.warning(
                        f"[ReportService] LLM 호출 실패 - {attempt}회차 재시도 예정. "
                        f"user_id={user_id}, delay={LLM_RETRY_DELAY}s"
                    )
                    time.sleep(LLM_RETRY_DELAY)

        logger.error(f"[ReportService] LLM 최대 재시도 초과 - user_id={user_id}")
        if last_error:
            raise last_error
        raise BusinessException(ErrorCode.LLM_CALL_FAILED)

    # =============================================
    # 동시성 락 헬퍼
    # =============================================
    def _acquire_lock(self, lock_key: str) -> bool:
        client = get_redis_client()
        if not client:
            return True  # Redis 없으면 락 없이 진행
        try:
            return bool(client.set(lock_key, "1", nx=True, ex=GENERATING_LOCK_TTL))
        except Exception as e:
            logger.warning(f"[ReportService] 락 획득 중 Redis 오류 - key={lock_key}, error={e}")
            return True  # Redis 장애 시 락 없이 진행

    def _release_lock(self, lock_key: str) -> None:
        client = get_redis_client()
        if not client:
            return
        try:
            client.delete(lock_key)
            logger.info(f"[ReportService] 락 해제 - key={lock_key}")
        except Exception as e:
            logger.error(f"[ReportService] 락 해제 실패 (TTL 자동 만료) - key={lock_key}, error={e}")

    # =============================================
    # 캐시 헬퍼
    # =============================================
    def _get_from_cache(self, cache_key: str) -> Optional[ReportResponse]:
        client = get_redis_client()
        if not client:
            return None
        try:
            cached = client.get(cache_key)
            if not cached:
                return None
            return ReportResponse(**json.loads(cached))
        except json.JSONDecodeError as e:
            logger.error(f"[ReportService] 캐시 손상 - key={cache_key}, error={e}")
            try:
                client.delete(cache_key)
            except Exception as e:
                logger.warning(f"[ReportService] 손상 캐시 삭제 실패 - key={cache_key}, error={e}")
            return None
        except Exception as e:
            logger.error(f"[ReportService] Redis 조회 실패 (DB fallback) - key={cache_key}, error={e}")
            return None

    def _set_to_cache(self, cache_key: str, response: ReportResponse) -> None:
        client = get_redis_client()
        if not client:
            logger.warning("[ReportService] Redis 없음 - 캐싱 스킵")
            return
        try:
            client.setex(cache_key, REPORT_CACHE_TTL, response.model_dump_json())
            logger.info(f"[ReportService] 캐시 저장 완료 - key={cache_key}, ttl={REPORT_CACHE_TTL}s")
        except Exception as e:
            logger.error(f"[ReportService] Redis 캐싱 실패 (서비스 정상) - key={cache_key}, error={e}")

    def _to_response(self, report: AiReport) -> ReportResponse:
        return ReportResponse(
            report_id        = report.report_id,
            year             = report.year,
            month            = report.month,
            day              = report.day,
            summary_message  = report.summary_message,
            total_expense    = report.total_expense,
            target_expense   = report.target_expense,
            achievement_rate = report.achievement_rate,
            remain_budge     = report.remain_budge,
            remain_days      = report.remain_days,
            daily_budge      = report.daily_budge,
            saving_tip       = report.saving_tip,
            created_at       = report.created_at,
        )
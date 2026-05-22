# app/domain/report/service.py
import json
import logging
import calendar
import time
from datetime import date
from typing import Optional

from sqlalchemy.orm import Session

from app.domain.report.repository import ReportRepository
from app.domain.report.schema import ReportResponse
from app.domain.report.entity import AiReport
from app.core.config.redis import get_redis_client
from app.core.error.exception import BusinessException
from app.core.error.error_code import ErrorCode
from app.core.utils.tsid import TSID
from app.core.client.llm_client import llm_client
from app.domain.report.schema import ReportResponse, PeersComparisonResponse, PeerCategoryItem
logger = logging.getLogger(__name__)

REPORT_CACHE_TTL    = 86400  # 리포트 캐시 TTL: 1일
GENERATING_LOCK_TTL = 60     # LLM 생성 중 분산 락 TTL: 60초 (비정상 종료 시 자동 해제)
LLM_MAX_RETRY       = 2      # LLM 호출 최대 재시도 횟수
LLM_RETRY_DELAY     = 1.5    # LLM 재시도 간격 (초)
LOCK_WAIT_SECONDS   = 3      # 락 대기 후 DB 재조회까지 대기 시간 (초)


def _cache_key(user_id: str) -> str:
    # 날짜가 바뀌면 자연스럽게 다른 키 → 별도 만료 처리 불필요
    today = date.today()
    return f"report:{user_id}:{today.year}:{today.month}:{today.day}"


def _lock_key(user_id: str) -> str:
    today = date.today()
    return f"report:lock:{user_id}:{today.year}:{today.month}:{today.day}"


class ReportService:
    def __init__(self, db: Session):
        self.repo = ReportRepository(db)



#=============================================
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
 
        # 가장 많이 절약한 카테고리 (diff_amount 음수인 것 중 가장 큰 절약)
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
        """
        cache_key = _cache_key(user_id)
        lock_key  = _lock_key(user_id)

        # ── Step 1. Redis 캐시 조회 ──────────────────────────
        # 히트: 즉시 반환 / 장애: 스킵 후 DB 조회 / 손상: 삭제 후 DB 조회
        cached = self._get_from_cache(cache_key)
        if cached:
            logger.info(f"[ReportService] 캐시 히트 - user_id={user_id}")
            return cached

        # ── Step 2. DB 조회 ──────────────────────────────────
        # 오늘 날짜(year/month/day) 기준 리포트 조회
        logger.info(f"[ReportService] 캐시 미스 - DB 조회. user_id={user_id}")
        report = self.repo.find_today(user_id)
        if report:
            logger.info(f"[ReportService] DB 히트 - Redis 재캐싱. report_id={report.report_id}")
            response = self._to_response(report)
            self._set_to_cache(cache_key, response)
            return response

        # ── Step 3. 동시성 락 획득 ───────────────────────────
        # 같은 사용자의 동시 요청이 LLM을 중복 호출하지 않도록 분산 락 사용
        lock_acquired = self._acquire_lock(lock_key)
        if not lock_acquired:
            # 다른 요청이 생성 중 → 대기 후 DB 재조회
            logger.warning(f"[ReportService] 락 획득 실패 - 다른 요청 생성 중. user_id={user_id}")
            time.sleep(LOCK_WAIT_SECONDS)
            report = self.repo.find_today(user_id)
            if report:
                logger.info(f"[ReportService] 락 대기 후 DB 히트 - report_id={report.report_id}")
                response = self._to_response(report)
                self._set_to_cache(cache_key, response)
                return response
            # 대기 후에도 없으면 409
            raise BusinessException(ErrorCode.REDIS_LOCK_ACQUIRE_FAILED)

        # ── Step 4. LLM 생성 ─────────────────────────────────
        try:
            logger.info(f"[ReportService] 락 획득 성공 - LLM 생성 시작. user_id={user_id}")
            return self._generate_report(user_id, cache_key)
        finally:
            # 성공/실패 무관하게 락 반드시 해제
            self._release_lock(lock_key)


    # =============================================
    # LLM 생성 로직
    # =============================================
    def _generate_report(self, user_id: str, cache_key: str) -> ReportResponse:
        today = date.today()

        # 1. 목표 조회 (없으면 0으로 처리, 생성 중단 안 함)
        goal           = self.repo.find_goal_current_month(user_id)
        target_expense = goal.goal_expense if goal else 0
        logger.info(f"[ReportService] 목표 조회 완료 - target_expense={target_expense}")

        # 2. 주간 지출 조회 (없으면 빈 리스트, 생성 중단 안 함)
        weekly_expenses = self.repo.find_weekly_expenses_current_month(user_id)
        total_expense   = sum(w.amount or 0 for w in weekly_expenses)
        logger.info(f"[ReportService] 주간 지출 조회 완료 - total_expense={total_expense}")

        # 3. 지표 계산
        achievement_rate = int((total_expense / target_expense) * 100) if target_expense > 0 else 0
        remain_budge     = max(target_expense - total_expense, 0)
        remain_days      = calendar.monthrange(today.year, today.month)[1] - today.day
        daily_budge      = int(remain_budge / remain_days) if remain_days > 0 else 0

        # 4. LLM 호출 (재시도 포함)
        summary_message, saving_tip = self._call_llm_with_retry(
            user_id          = user_id,
            total_expense    = total_expense,
            target_expense   = target_expense,
            achievement_rate = achievement_rate,
            weekly_expenses  = weekly_expenses,
        )

        # 5. DB 저장
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

        # 6. Redis 캐싱 (실패해도 응답은 정상 반환)
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
        """
        LLM 호출 재시도 래퍼.
        - 파싱 실패(LLM_RESPONSE_PARSE_FAILED)는 재시도 의미 없으므로 즉시 raise
        - 호출 실패(LLM_CALL_FAILED)는 최대 LLM_MAX_RETRY회 재시도
        """
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
                    raise  # 파싱 실패는 재시도 무의미
                last_error = e
                if attempt <= LLM_MAX_RETRY:
                    logger.warning(
                        f"[ReportService] LLM 호출 실패 - {attempt}회차 재시도 예정. "
                        f"user_id={user_id}, delay={LLM_RETRY_DELAY}s"
                    )
                    time.sleep(LLM_RETRY_DELAY)

        logger.error(f"[ReportService] LLM 최대 재시도 초과 - user_id={user_id}")
        # last_error가 None인 경우 방어 처리
        if last_error:
            raise last_error
        raise BusinessException(ErrorCode.LLM_CALL_FAILED)

    # =============================================
    # 동시성 락 헬퍼
    # =============================================
    def _acquire_lock(self, lock_key: str) -> bool:
        """
        Redis SET NX 분산 락 획득.
        - Redis 없음: 락 없이 진행 (서비스 중단 > 중복 생성)
        - Redis 장애: 락 없이 진행
        - TTL 설정으로 비정상 종료 시 자동 해제 보장
        """
        client = get_redis_client()
        if not client:
            logger.warning("[ReportService] Redis 없음 - 락 없이 진행")
            return True
        try:
            acquired = client.set(lock_key, "1", nx=True, ex=GENERATING_LOCK_TTL)
            if acquired:
                logger.info(f"[ReportService] 락 획득 - key={lock_key}")
            else:
                logger.warning(f"[ReportService] 락 이미 존재 - key={lock_key}")
            return bool(acquired)
        except Exception as e:
            # Redis 장애 시 락 없이 진행 (중복 생성 감수 > 서비스 중단)
            logger.error(f"[ReportService] 락 획득 중 Redis 장애 - 락 없이 진행. key={lock_key}, error={e}")
            return True

    def _release_lock(self, lock_key: str) -> None:
        """
        분산 락 해제.
        finally 블록에서 호출되므로 실패해도 TTL로 자동 만료.
        """
        client = get_redis_client()
        if not client:
            return
        try:
            client.delete(lock_key)
            logger.info(f"[ReportService] 락 해제 - key={lock_key}")
        except Exception as e:
            # 해제 실패해도 TTL(60초)로 자동 만료되므로 서비스 영향 없음
            logger.error(f"[ReportService] 락 해제 실패 (TTL 자동 만료) - key={lock_key}, error={e}")

    # =============================================
    # 캐시 헬퍼
    # =============================================
    def _get_from_cache(self, cache_key: str) -> Optional[ReportResponse]:
        """
        Redis 캐시 조회.
        - Redis 없음: None 반환 → DB 조회로 fallback
        - 연결 실패: None 반환 → DB 조회로 fallback
        - 데이터 손상: 캐시 삭제 후 None 반환 → DB 재조회
        """
        client = get_redis_client()
        if not client:
            return None
        try:
            cached = client.get(cache_key)
            if not cached:
                return None
            return ReportResponse(**json.loads(cached))
        except json.JSONDecodeError as e:
            # 캐시 데이터 손상 → 삭제 후 DB 재조회
            logger.error(f"[ReportService] 캐시 손상 - key={cache_key}, error={e}")
            try:
                client.delete(cache_key)
            except Exception as e:
                logger.warning(f"[ReportService] 손상 캐시 삭제 실패 - key={cache_key}, error={e}")
            return None
        except Exception as e:
            # Redis 연결 실패 등 → DB 조회로 fallback (서비스 중단 없음)
            logger.error(f"[ReportService] Redis 조회 실패 (DB fallback) - key={cache_key}, error={e}")
            return None

    def _set_to_cache(self, cache_key: str, response: ReportResponse) -> None:
        """
        Redis 캐싱.
        실패해도 응답은 정상 반환 (캐싱 실패가 서비스 실패로 전파되지 않음).
        """
        client = get_redis_client()
        if not client:
            logger.warning("[ReportService] Redis 없음 - 캐싱 스킵")
            return
        try:
            client.setex(cache_key, REPORT_CACHE_TTL, response.model_dump_json())
            logger.info(f"[ReportService] 캐시 저장 완료 - key={cache_key}, ttl={REPORT_CACHE_TTL}s")
        except Exception as e:
            # 캐싱 실패해도 응답은 정상 반환
            logger.error(f"[ReportService] Redis 캐싱 실패 (서비스 정상) - key={cache_key}, error={e}")

    def _to_response(self, report: AiReport) -> ReportResponse:
        """AiReport entity → ReportResponse 변환."""
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
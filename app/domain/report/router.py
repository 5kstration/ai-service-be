# app/domain/report/router.py
import logging
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.domain.report.schema import (
    ReportResponse,
    PeersComparisonResponse,
    ReportEntryStatusResponse,
    ProfileMissingFieldsResponse,
    ProfileSetupRequest,
    ProfileSetupResponse,
    GoalSetupRequest,
    GoalSetupResponse,
)
from app.domain.report.service import ReportService
from app.core.config.database import get_db
from app.core.common.response import CommonResponse
from app.core.middleware.auth import get_current_user

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/report", tags=["AI Report"])


# =============================================
# 탭 진입 상태 체크 (가장 먼저 호출)
# =============================================

@router.get(
    "/status",
    response_model=CommonResponse[ReportEntryStatusResponse],
    summary="AI 리포트 탭 진입 상태 체크",
    description="""
    AI 리포트 탭 진입 시 **가장 먼저 호출**하는 API입니다.
    응답 값에 따라 클라이언트가 이동할 화면을 결정합니다.

    **응답 분기**
    | profile_required | goal_required | is_ready | 클라이언트 동작 |
    |---|---|---|---|
    | true | - | false | 프로필 입력 화면으로 이동 |
    | false | true | false | 목표 설정 화면으로 이동 |
    | false | false | true | 리포트 조회 API(`GET /report`) 호출 |
    """,
    responses={
        200: {"description": "상태 조회 성공"},
        401: {"description": "인증 실패"},
    }
)
def get_report_entry_status(
    db: Session = Depends(get_db),
    current_user: str = Depends(get_current_user),
):
    logger.info(f"[ReportRouter] GET /api/ai/report/status - user_id={current_user}")
    service = ReportService(db)
    data = service.check_entry_status(current_user)
    return CommonResponse.of(data)


# =============================================
# 프로필 비어있는 필드 조회
# =============================================

@router.get(
    "/profile",
    response_model=CommonResponse[ProfileMissingFieldsResponse],
    summary="프로필 미입력 필드 조회",
    description="""
    현재 저장된 프로필에서 **비어있는 필드만** 반환합니다.
    프론트가 이 응답을 보고 어떤 입력 칸을 보여줄지 결정합니다.

    **응답 예시 (월소득만 없는 경우)**
    ```json
    {
      "monthly_income_missing": true,
      "birth_missing": false,
      "sex_missing": false,
      "monthly_income": null,
      "birth": "1997-03-15",
      "sex": "남자"
    }
    ```
    """,
    responses={
        200: {"description": "조회 성공"},
        401: {"description": "인증 실패"},
    }
)
def get_profile_missing_fields(
    db: Session = Depends(get_db),
    current_user: str = Depends(get_current_user),
):
    logger.info(f"[ReportRouter] GET /api/ai/report/profile - user_id={current_user}")
    service = ReportService(db)
    data = service.get_profile_missing_fields(current_user)
    return CommonResponse.of(data)


# =============================================
# 프로필 설정 (온보딩 스킵 유저 대상)
# =============================================

from fastapi import APIRouter, Depends, BackgroundTasks

@router.post(
    "/profile",
    response_model=CommonResponse[ProfileSetupResponse],
    summary="프로필 정보 입력",
    description="""
    보내온 필드만 업데이트합니다. **보내지 않은 필드(생략 또는 null)는 기존 저장값을 유지**합니다.

    **사용 시나리오**
    - `GET /report/profile`로 비어있는 필드 확인 후 해당 필드만 전송
    - 예: 생년월일만 없으면 `{"birth": "1997-03-15"}` 만 전송

    **NATS 발행 (AUTH 수신 형식과 동일)**
    변경된 필드 + 기존 저장값을 합친 **전체 스냅샷**으로 발행합니다.
    ```json
    {
      "userId":        "01HXXX...",
      "monthlyIncome": 3000000,
      "birth":         "1997-03-15T00:00:00",
      "sex":           "남자"
    }
    ```
    NATS 발행 실패 시 서비스 중단 없이 로깅만 처리합니다 (DB 저장은 이미 완료).

    **응답의 `updated_fields`**: 이번 요청에서 실제 업데이트된 필드 목록.
    **응답의 `goal_required`**: true면 목표 설정 화면으로 이동.
    """,
    responses={
        200: {"description": "프로필 설정 성공"},
        400: {"description": "잘못된 요청 (monthly_income 음수 등)"},
        401: {"description": "인증 실패"},
        500: {"description": "DB 저장 실패"},
    }
)
def setup_profile(
    req: ProfileSetupRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: str = Depends(get_current_user),
):
    logger.info(f"[ReportRouter] POST /api/ai/report/profile - user_id={current_user}")
    service = ReportService(db)
    data = service.setup_profile(current_user, req, background_tasks)
    return CommonResponse.of(data, message="프로필 정보가 저장되었습니다.")


# =============================================
# 이번 달 목표 설정
# =============================================

@router.post(
    "/goal",
    response_model=CommonResponse[GoalSetupResponse],
    summary="이번 달 목표 지출액 설정",
    description="""
    이번 달 목표 지출액을 설정합니다.

    **제약 조건**
    - 이번 달 목표가 이미 존재하면 `409 GOAL_ALREADY_EXISTS` 반환
    - `goal_expense`는 1원 이상이어야 함

    **목표 설정 완료 후**
    - 클라이언트는 `GET /report` 를 호출하여 AI 리포트 조회
    """,
    responses={
        200: {"description": "목표 설정 성공"},
        400: {"description": "잘못된 요청 (goal_expense 0 이하)"},
        401: {"description": "인증 실패"},
        409: {"description": "이번 달 목표가 이미 존재함"},
        500: {"description": "DB 저장 실패"},
    }
)
def setup_goal(
    req: GoalSetupRequest,
    db: Session = Depends(get_db),
    current_user: str = Depends(get_current_user),
):
    logger.info(f"[ReportRouter] POST /api/ai/report/goal - user_id={current_user}, goal_expense={req.goal_expense}")
    service = ReportService(db)
    data = service.setup_goal(current_user, req)
    return CommonResponse.of(data, message="이번 달 목표가 설정되었습니다.")


# =============================================
# AI 리포트 조회/생성
# =============================================

@router.get(
    "",
    response_model=CommonResponse[ReportResponse],
    summary="AI 리포트 조회",
    description="""
    AI 리포트를 조회합니다. `GET /report/status`에서 `is_ready=true` 확인 후 호출하세요.

    **처리 흐름**
    1. Redis 캐시 조회 (오늘 날짜 기준 키) → 있으면 즉시 반환
    2. DB 조회 (오늘 year/month/day 기준) → 있으면 Redis 재캐싱 후 반환
    3. 없으면 LLM 호출하여 오늘 리포트 생성 → DB 저장 → Redis 캐싱 → 반환

    **예외 케이스**
    - Redis 장애            → 캐시 스킵 후 DB 조회 (서비스 중단 없음)
    - 목표 미설정           → target_expense=0 으로 생성 진행
    - 주간 지출 데이터 없음 → 빈 데이터로 LLM 생성 진행
    - LLM 호출 실패         → 502
    - LLM 응답 파싱 실패    → 500
    """,
    responses={
        200: {"description": "리포트 조회/생성 성공"},
        401: {"description": "인증 실패"},
        502: {"description": "LLM 호출 실패"},
        500: {"description": "서버 오류"},
    }
)
def get_report(
    db: Session = Depends(get_db),
    current_user: str = Depends(get_current_user),
):
    logger.info(f"[ReportRouter] GET /api/ai/report - user_id={current_user}")
    service = ReportService(db)
    data = service.get_or_generate_report(current_user)
    return CommonResponse.of(data)


# =============================================
# 또래 비교 조회
# =============================================

@router.get(
    "/peers-comparison",
    response_model=CommonResponse[PeersComparisonResponse],
    summary="또래 비교 조회",
    description="""
    카테고리별 나의 지출과 또래 평균을 비교합니다.

    **또래 기준**
    - 나이 ±3세 이내
    - 이번 달 지출 데이터 있는 유저
    - 5명 미만이면 빈 리스트 반환 (개인 특정 방지)

    **diff_amount**
    - 양수: 또래보다 초과 지출
    - 음수: 또래보다 절약

    **예외 케이스**
    - 온보딩 정보 없음 → 빈 리스트
    - 또래 5명 미만    → 빈 리스트
    - DB 오류          → 500
    """,
    responses={
        200: {"description": "조회 성공 (또래 부족 시 빈 리스트)"},
        401: {"description": "인증 실패"},
        500: {"description": "서버 오류"},
    }
)
def get_peers_comparison(
    db: Session = Depends(get_db),
    current_user: str = Depends(get_current_user),
):
    logger.info("[ReportRouter] GET /api/ai/report/peers-comparison")
    service = ReportService(db)
    data = service.get_peers_comparison(current_user)
    return CommonResponse.of(data)
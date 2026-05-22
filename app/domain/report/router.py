# app/domain/report/router.py
import logging
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.domain.report.schema import ReportResponse
from app.domain.report.service import ReportService
from app.core.config.database import get_db
from app.core.common.response import CommonResponse
from app.core.middleware.auth import get_current_user
from app.domain.report.schema import ReportResponse, PeersComparisonResponse
logger = logging.getLogger(__name__)

router = APIRouter(prefix="/report", tags=["AI Report"])

# ======================================
# AI 리포트 조회/생성 엔드포인트
# ======================================
@router.get(
    "",
    response_model=CommonResponse[ReportResponse],
    summary="AI 리포트 조회",
    description="""
    AI 리포트 메뉴 진입 시 호출됩니다.
    날짜는 서버에서 오늘 날짜(year/month/day) 기준으로 자동 계산합니다.

    **처리 흐름**
    1. Redis 캐시 조회 (오늘 날짜 기준 키) → 있으면 즉시 반환
    2. DB 조회 (오늘 year/month/day 기준) → 있으면 Redis 재캐싱 후 반환
    3. 없으면 LLM 호출하여 오늘 리포트 생성 → DB 저장 → Redis 캐싱 → 반환

    **예외 케이스**
    - Redis 장애            → 캐시 스킵 후 DB 조회 (서비스 중단 없음)
    - 캐시 데이터 손상      → 캐시 삭제 후 DB 재조회
    - 목표 미설정           → target_expense=0 으로 생성 진행
    - 주간 지출 데이터 없음 → 빈 데이터로 LLM 생성 진행
    - LLM 호출 실패         → 502
    - LLM 응답 파싱 실패    → 500
    - DB 저장 실패          → 500
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


# ======================================
# peers-comoprsion 엔드포인트 
# ======================================


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
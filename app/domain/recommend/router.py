# app/domain/recommend/router.py
import logging
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.domain.recommend.schema import (
    PolicyListResponse, PolicyDetailResponse,
    InsuranceListResponse, CardListResponse,
    BookmarkRequest, BookmarkResponse,
    BookmarkListResponse,
)
from app.domain.recommend.service import RecommendService
from app.core.config.database import get_db
from app.core.common.response import CommonResponse
from app.core.middleware.auth import get_current_user
from fastapi import BackgroundTasks
logger = logging.getLogger(__name__)

router = APIRouter(prefix="", tags=["Recommend"])


# =============================================
# 청년 정책 추천 목록
# =============================================
@router.get(
    "/policies",
    response_model=CommonResponse[PolicyListResponse],
    summary="청년 정책 추천 목록",
)
def get_policies(
    background_tasks: BackgroundTasks,
    page: int = Query(default=0, ge=0, description="페이지 번호"),
    size: int = Query(default=10, ge=1, le=50, description="페이지당 항목 수"),
    db: Session = Depends(get_db),
    current_user: str = Depends(get_current_user),
):
    logger.info("[RecommendRouter] GET /policies")
    service = RecommendService(db)
    data = service.get_policies(current_user, page, size)

    last_recommended_at = service.repo.find_last_recommended_at(current_user)
    if last_recommended_at:
        update_count = service.repo.count_summary_updates_since(current_user, last_recommended_at)
        if update_count >= 5:
            background_tasks.add_task(_run_pipeline, current_user)
    else:
        background_tasks.add_task(_run_pipeline, current_user)

    return CommonResponse.of(data)



# =============================================
# 청년 정책 상세
# =============================================
@router.get(
    "/policies/{policy_id}",
    response_model=CommonResponse[PolicyDetailResponse],
    summary="청년 정책 상세 조회",
    responses={
        404: {"description": "정책을 찾을 수 없음"},
    }
)
def get_policy_detail(
    policy_id: str,
    db: Session = Depends(get_db),
    current_user: str = Depends(get_current_user),
):
    logger.info(f"[RecommendRouter] GET /policies/{policy_id}")
    service = RecommendService(db)
    data = service.get_policy_detail(current_user, policy_id)
    return CommonResponse.of(data)


# =============================================
# 보험 추천 목록
# =============================================
@router.get(
    "/insurances",
    response_model=CommonResponse[InsuranceListResponse],
    summary="보험 추천 목록",
)
def get_insurances(
    db: Session = Depends(get_db),
    current_user: str = Depends(get_current_user),
):
    logger.info("[RecommendRouter] GET /insurances")
    service = RecommendService(db)
    data = service.get_insurances(current_user)
    return CommonResponse.of(data)


# =============================================
# 카드 추천 목록
# =============================================
@router.get(
    "/cards",
    response_model=CommonResponse[CardListResponse],
    summary="카드 추천 목록",
)
def get_cards(
    db: Session = Depends(get_db),
    current_user: str = Depends(get_current_user),
):
    logger.info("[RecommendRouter] GET /cards")
    service = RecommendService(db)
    data = service.get_cards(current_user)
    return CommonResponse.of(data)


# =============================================
# 북마크 설정/해제
# =============================================
@router.patch(
    "/bookmark/patch",
    response_model=CommonResponse[BookmarkResponse],
    summary="북마크 설정/해제",
    description="""
    북마크 토글.
    - 이미 북마크된 경우 → 해제
    - 아닌 경우 → 설정

    **category**: policy, insurance, card
    """,
)
def toggle_bookmark(
    request: BookmarkRequest,
    db: Session = Depends(get_db),
    current_user: str = Depends(get_current_user),
):
    logger.info("[RecommendRouter] PATCH /bookmark/patch")
    service = RecommendService(db)
    data = service.toggle_bookmark(current_user, request)
    return CommonResponse.of(data)


# =============================================
# 북마크한 혜택 목록
# =============================================

@router.get(
    "/bookmarks",
    response_model=CommonResponse[BookmarkListResponse],
    summary="북마크한 혜택 목록",
    description="북마크한 정책/보험/카드를 모두 반환합니다.",
)
def get_bookmarks(
    db: Session = Depends(get_db),
    current_user: str = Depends(get_current_user),
):
    logger.info("[RecommendRouter] GET /bookmarks")
    service = RecommendService(db)
    data = service.get_bookmarks(current_user)  # get_bookmarked_policies → get_bookmarks
    return CommonResponse.of(data)



async def _run_pipeline(user_id: str):
    try:
        from app.domain.recommend_ai.graph import run_recommend_pipeline
        await run_recommend_pipeline(user_id)
        logger.info(f"[RecommendRouter] 백그라운드 파이프라인 완료 - user_id={user_id}")
    except Exception as e:
        logger.error(f"[RecommendRouter] 백그라운드 파이프라인 실패 - user_id={user_id}, error={e}")
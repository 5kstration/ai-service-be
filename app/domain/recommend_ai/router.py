# app/domain/recommend_ai/router.py
import logging
from fastapi import APIRouter, Depends, BackgroundTasks
from sqlalchemy.orm import Session

from app.domain.recommend_ai.graph import run_recommend_pipeline
from app.domain.recommend_ai.embed_service import embed_all_products
from app.core.config.database import get_db
from app.core.common.response import CommonResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/internal/recommend", tags=["Recommend AI"])


@router.post(
    "/generate/{user_id}",
    summary="특정 유저 추천 생성 (수동 트리거)",
)
async def generate_recommend(
    user_id: str,
    background_tasks: BackgroundTasks,
):
    """특정 유저 추천 파이프라인 수동 실행."""
    logger.info(f"[RecommendAIRouter] POST /generate/{user_id}")
    background_tasks.add_task(run_recommend_pipeline, user_id)
    return CommonResponse.of({"message": f"추천 생성 요청 완료 - user_id={user_id}"})


@router.post(
    "/embed/products",
    summary="전체 상품 임베딩 생성 (수동 트리거)",
)
async def embed_products(background_tasks: BackgroundTasks):
    """전체 카드/보험/정책 상품 임베딩 생성."""
    logger.info("[RecommendAIRouter] POST /embed/products")
    background_tasks.add_task(embed_all_products)
    return CommonResponse.of({"message": "임베딩 생성 요청 완료"})
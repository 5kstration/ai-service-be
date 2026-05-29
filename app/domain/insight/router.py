# app/domain/insight/router.py
import logging
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.domain.insight.schema import InsightResponse
from app.domain.insight.service import InsightService
from app.core.config.database import get_db
from app.core.common.response import CommonResponse
from app.core.middleware.auth import get_current_user

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/insights")


@router.get(
    "",
    response_model=CommonResponse[InsightResponse],
    summary="AI 인사이트 전체 조회",
)
def get_insights(
    db: Session = Depends(get_db),
    current_user: str = Depends(get_current_user),
):
    logger.info(f"[InsightRouter] GET /api/ai/insights - user_id={current_user}")
    service = InsightService(db)
    data = service.get_insights(current_user)
    return CommonResponse.of(data)
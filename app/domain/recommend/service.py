# app/domain/recommend/service.py
import json
import logging
from typing import Optional
from datetime import datetime

from sqlalchemy.orm import Session

from app.domain.recommend.repository import RecommendRepository
from app.domain.recommend.entity import Bookmark
from app.domain.recommend.schema import (
    PolicyListItem, PolicyListResponse,
    PolicyDetailResponse,
    InsuranceItem, InsuranceListResponse,
    CardItem, CardListResponse,
    BookmarkRequest, BookmarkResponse,
    BookmarkPolicyItem, BookmarkListResponse,
    BenefitItem,
)
from app.core.error.exception import BusinessException
from app.core.error.error_code import ErrorCode
from app.core.utils.tsid import TSID

logger = logging.getLogger(__name__)


def _parse_tags(tags_json: Optional[str]) -> list:
    if not tags_json:
        return []
    try:
        return json.loads(tags_json)
    except Exception:
        return []


def _parse_benefits(benefits_json: Optional[str]) -> list[BenefitItem]:
    if not benefits_json:
        return []
    try:
        items = json.loads(benefits_json)
        return [BenefitItem(label=i["label"], value=i["value"]) for i in items]
    except Exception:
        return []


class RecommendService:
    def __init__(self, db: Session):
        self.repo = RecommendRepository(db)

    # =============================================
    # 청년 정책 추천 목록
    # =============================================

    def get_policies(self, user_id: str, page: int, size: int) -> PolicyListResponse:
        items, total = self.repo.find_policies_by_user(user_id, page, size) # (RecommendPolicy, PolicyProduct) 튜플 리스트. repository에서 JOIN으로 한 번에 조회하도록 수정
        # AI 추천 사유는 상세 조회에서만 반환하므로 여기서는 포함하지 않음. 대신 북마크 여부를 위해 유저의 북마크된 정책 ID 리스트 조회       
        bookmarked_ids = self.repo.find_bookmarked_ids_by_type(user_id, "Policy")

        policies = [
            PolicyListItem(
                policy_id      = product.key,
                title          = product.policy_name or "",
                org            = product.org or "",
                category       = product.category or "",
                category_color = product.category_color or "#3182F6",
                deadline       = product.deadline or "",
                dday           = product.dday or 0,
                tags           = _parse_tags(product.tags),
                is_bookmarked  = product.key in bookmarked_ids,
            )
            for _, product in items  # (RecommendPolicy, PolicyProduct) 튜플
        ]

        return PolicyListResponse(
            policies    = policies,
            total_count = total,
            has_next    = (page + 1) * size < total,
        )

    # =============================================
    # 청년 정책 상세
    # =============================================

    def get_policy_detail(self, user_id: str, policy_id: str) -> PolicyDetailResponse:
        product = self.repo.find_policy_by_id(policy_id) # PolicyProduct 단건 조회. repository에서 JOIN 제거하고 AI 추천 사유는 별도 조회하도록 수정
        if not product: # 해당 ID의 정책이 존재하지 않는 경우
            raise BusinessException(ErrorCode.RECOMMEND_POLICY_NOT_FOUND) # 404 에러로 처리

        # 유저별 AI 추천 사유 조회
        # AI 추천 사유는 RecommendPolicy 테이블에 저장되어 있다고 가정. 유저 ID + 정책 ID로 조회
        recommend = self.repo.find_recommend_policy_by_user_and_product(user_id, policy_id)
        # 북마크 여부 확인을 위해 유저의 북마크된 정책 ID 리스트 조회
        bookmarked_ids = self.repo.find_bookmarked_ids_by_type(user_id, "Policy")

        return PolicyDetailResponse(
            policy_id            = product.key,
            title                = product.policy_name or "",
            org                  = product.org or "",
            category             = product.category or "",
            category_color       = product.category_color or "#3182F6",
            deadline             = product.deadline or "",
            dday                 = product.dday or 0,
            tags                 = _parse_tags(product.tags),
            is_bookmarked        = product.key in bookmarked_ids,
            age_min              = product.age_min,
            age_max              = product.age_max,
            income_condition     = product.income_condition,
            employment_condition = product.employment_condition,
            education_condition  = product.education_condition,
            application_period   = product.application_period,
            description          = product.description,
            apply_url            = product.apply_url,
            ai_recommend_reason  = recommend.ai_reason if recommend else None,
        )


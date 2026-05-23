# app/domain/recommend/service.py
import json
import logging
from typing import Optional

from sqlalchemy.orm import Session

from app.domain.recommend.repository import RecommendRepository
from app.domain.recommend.entity import Bookmark
from app.domain.recommend.schema import (
    PolicyListItem, PolicyListResponse,
    PolicyDetailResponse,
    InsuranceItem, InsuranceListResponse,
    CardItem, CardListResponse,
    BookmarkRequest, BookmarkResponse,
    BookmarkPolicyItem, BookmarkInsuranceItem, BookmarkCardItem,  
    BookmarkListResponse,
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

    def get_policies(self, user_id: str, page: int, size: int) -> PolicyListResponse:
        items, total = self.repo.find_policies_by_user(user_id, page, size)
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
            for _, product in items
        ]

        return PolicyListResponse(
            policies    = policies,
            total_count = total,
            has_next    = (page + 1) * size < total,
        )

    def get_policy_detail(self, user_id: str, policy_id: str) -> PolicyDetailResponse:
        product = self.repo.find_policy_by_id(policy_id)
        if not product:
            raise BusinessException(ErrorCode.RECOMMEND_POLICY_NOT_FOUND)

        recommend = self.repo.find_recommend_policy_by_user_and_product(user_id, policy_id)
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

    def get_insurances(self, user_id: str) -> InsuranceListResponse:
        items = self.repo.find_insurances_by_user(user_id)
        bookmarked_ids = self.repo.find_bookmarked_ids_by_type(user_id, "Insurance")

        insurances = [
            InsuranceItem(
                recommend_id   = product.key,
                insurer        = product.insurer or "",
                insurance_name = product.insurance_name or "",
                top_benefit    = product.top_benefit or "",
                benefits       = _parse_benefits(product.benefits),
                match_reason   = recommend.ai_reason or "",
                accent_color   = product.accent_color or "#8B5CF6",
                apply_url      = product.apply_url,
                is_bookmarked  = product.key in bookmarked_ids,
            )
            for recommend, product in items
        ]

        recommended_at = items[0][0].created_at if items else None

        return InsuranceListResponse(
            recommended_at = recommended_at,
            insurances     = insurances,
        )

    def get_cards(self, user_id: str) -> CardListResponse:
        items = self.repo.find_cards_by_user(user_id)
        bookmarked_ids = self.repo.find_bookmarked_ids_by_type(user_id, "card")

        cards = [
            CardItem(
                recommend_id  = product.key,
                company       = product.company or "",
                card_name     = product.card_name or "",
                top_benefit   = product.top_benefit or "",
                benefits      = _parse_benefits(product.benefits),
                match_reason  = recommend.ai_reason or "",
                accent_color  = product.accent_color or "#3182F6",
                apply_url     = product.apply_url,
                is_bookmarked = product.key in bookmarked_ids,
            )
            for recommend, product in items
        ]

        recommended_at = items[0][0].created_at if items else None

        return CardListResponse(
            recommended_at = recommended_at,
            cards          = cards,
        )

    def toggle_bookmark(self, user_id: str, request: BookmarkRequest) -> BookmarkResponse:
        type_map = {"policy": "Policy", "insurance": "Insurance", "card": "card"}
        target_type = type_map.get(request.category.lower(), request.category)

        existing = self.repo.find_bookmark(user_id, target_type, request.id)

        if existing:
            self.repo.delete_bookmark(existing)
            return BookmarkResponse(
                bookmark_id   = None,
                category      = request.category,
                id            = request.id,
                is_bookmarked = False,
            )
        else:
            bookmark = Bookmark(
                bookmark_id   = TSID.create(),
                user_id       = user_id,
                target_type   = target_type,
                target_ref_id = request.id,
            )
            saved = self.repo.save_bookmark(bookmark)
            return BookmarkResponse(
                bookmark_id   = saved.bookmark_id,
                category      = request.category,
                id            = request.id,
                is_bookmarked = True,
            )


    def get_bookmarks(self, user_id: str) -> BookmarkListResponse:
        """북마크한 정책/보험/카드 전체 목록."""
        policy_items    = self.repo.find_bookmarked_policies(user_id)
        insurance_items = self.repo.find_bookmarked_insurances(user_id)
        card_items      = self.repo.find_bookmarked_cards(user_id)
 
        policies = [
            BookmarkPolicyItem(
                policy_id      = item.key,
                title          = item.policy_name or "",
                org            = item.org or "",
                category       = item.category or "",
                category_color = item.category_color or "#3182F6",
                deadline       = item.deadline or "",
                dday           = item.dday or 0,
                tags           = _parse_tags(item.tags),
                is_bookmarked  = True,
            )
            for item in policy_items
        ]
 
        insurances = [
            BookmarkInsuranceItem(
                recommend_id   = item.key,
                insurer        = item.insurer or "",
                insurance_name = item.insurance_name or "",
                top_benefit    = item.top_benefit or "",
                accent_color   = item.accent_color or "#8B5CF6",
                apply_url      = item.apply_url,
                is_bookmarked  = True,
            )
            for item in insurance_items
        ]
 
        cards = [
            BookmarkCardItem(
                recommend_id  = item.key,
                company       = item.company or "",
                card_name     = item.card_name or "",
                top_benefit   = item.top_benefit or "",
                accent_color  = item.accent_color or "#3182F6",
                apply_url     = item.apply_url,
                is_bookmarked = True,
            )
            for item in card_items
        ]
 
        return BookmarkListResponse(
            policies    = policies,
            insurances  = insurances,
            cards       = cards,
            total_count = len(policies) + len(insurances) + len(cards),
        )
 

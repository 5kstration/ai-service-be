# app/domain/recommend/repository.py
import logging
from typing import Optional

from sqlalchemy.orm import Session
from sqlalchemy.exc import SQLAlchemyError

from app.domain.recommend.entity import (
    RecommendPolicy, RecommendInsurance, RecommendCard,
    PolicyProduct, InsuranceProduct, CardProduct,
    Bookmark,
)
from app.core.error.exception import BusinessException
from app.core.error.error_code import ErrorCode

logger = logging.getLogger(__name__)


class RecommendRepository:
    def __init__(self, db: Session):
        self.db = db

    # =============================================
    # 정책
    # =============================================

    def find_policies_by_user(self, user_id: str, page: int, size: int):
        """유저 추천 정책 + 상품 원본 JOIN."""
        try:
            query = (
                self.db.query(RecommendPolicy, PolicyProduct)
                .join(PolicyProduct, RecommendPolicy.policy_product_id == PolicyProduct.key)
                .filter(RecommendPolicy.user_id == user_id)
                .order_by(PolicyProduct.dday.asc())
            )
            total = query.count()
            items = query.offset(page * size).limit(size).all()
            return items, total
        except SQLAlchemyError as e:
            self.db.rollback()
            logger.error(f"[RecommendRepository] 정책 목록 조회 실패 - error={e}")
            raise BusinessException(ErrorCode.DB_ERROR)

    def find_policy_by_id(self, policy_product_id: str):
        """정책 상품 원본 단건 조회."""
        try:
            return (
                self.db.query(PolicyProduct)
                .filter(PolicyProduct.key == policy_product_id)
                .first()
            )
        except SQLAlchemyError as e:
            self.db.rollback()
            logger.error(f"[RecommendRepository] 정책 상세 조회 실패 - error={e}")
            raise BusinessException(ErrorCode.DB_ERROR)

    def find_recommend_policy_by_user_and_product(self, user_id: str, policy_product_id: str):
        """유저의 특정 정책 추천 결과 조회 (AI 추천 사유 포함)."""
        try:
            return (
                self.db.query(RecommendPolicy)
                .filter(
                    RecommendPolicy.user_id           == user_id,
                    RecommendPolicy.policy_product_id == policy_product_id,
                )
                .first()
            )
        except SQLAlchemyError as e:
            self.db.rollback()
            logger.error(f"[RecommendRepository] 정책 추천 결과 조회 실패 - error={e}")
            raise BusinessException(ErrorCode.DB_ERROR)

    # =============================================
    # 보험
    # =============================================

    def find_insurances_by_user(self, user_id: str):
        """유저 추천 보험 + 상품 원본 JOIN."""
        try:
            return (
                self.db.query(RecommendInsurance, InsuranceProduct)
                .join(InsuranceProduct, RecommendInsurance.insurance_product_id == InsuranceProduct.key)
                .filter(RecommendInsurance.user_id == user_id)
                .order_by(RecommendInsurance.created_at.desc())  
                .all()
            )
        except SQLAlchemyError as e:
            self.db.rollback()
            logger.error(f"[RecommendRepository] 보험 목록 조회 실패 - error={e}")
            raise BusinessException(ErrorCode.DB_ERROR)


    # =============================================
    # 카드
    # =============================================

    def find_cards_by_user(self, user_id: str):
        """유저 추천 카드 + 상품 원본 JOIN."""
        try:
            return (
                self.db.query(RecommendCard, CardProduct)
                .join(CardProduct, RecommendCard.card_product_id == CardProduct.key)
                .filter(RecommendCard.user_id == user_id)
                .order_by(RecommendCard.created_at.desc()) 
                .all()
            )
        except SQLAlchemyError as e:
            self.db.rollback()
            logger.error(f"[RecommendRepository] 카드 목록 조회 실패 - error={e}")
            raise BusinessException(ErrorCode.DB_ERROR)
        
    # =============================================
    # 북마크
    # =============================================

    def find_bookmark(self, user_id: str, target_type: str, target_ref_id: str):
        try:
            return (
                self.db.query(Bookmark)
                .filter(
                    Bookmark.user_id       == user_id,
                    Bookmark.target_type   == target_type,
                    Bookmark.target_ref_id == target_ref_id,
                    Bookmark.deleted_at    == None,
                )
                .first()
            )
        except SQLAlchemyError as e:
            self.db.rollback()
            logger.error(f"[RecommendRepository] 북마크 조회 실패 - error={e}")
            raise BusinessException(ErrorCode.DB_ERROR)

    def find_bookmarked_ids_by_type(self, user_id: str, target_type: str) -> set:
        try:
            results = (
                self.db.query(Bookmark.target_ref_id)
                .filter(
                    Bookmark.user_id     == user_id,
                    Bookmark.target_type == target_type,
                    Bookmark.deleted_at  == None,
                )
                .all()
            )
            return {r.target_ref_id for r in results}
        except SQLAlchemyError as e:
            self.db.rollback()
            logger.error(f"[RecommendRepository] 북마크 ID 목록 조회 실패 - error={e}")
            return set()

    def save_bookmark(self, bookmark: Bookmark) -> Bookmark:
        try:
            self.db.add(bookmark)
            self.db.commit()
            self.db.refresh(bookmark)
            return bookmark
        except SQLAlchemyError as e:
            self.db.rollback()
            logger.error(f"[RecommendRepository] 북마크 저장 실패 - error={e}")
            raise BusinessException(ErrorCode.DB_ERROR)

    def delete_bookmark(self, bookmark: Bookmark) -> None:
        try:
            from datetime import datetime
            bookmark.deleted_at = datetime.now()
            self.db.commit()
        except SQLAlchemyError as e:
            self.db.rollback()
            logger.error(f"[RecommendRepository] 북마크 삭제 실패 - error={e}")
            raise BusinessException(ErrorCode.DB_ERROR)

    def find_bookmarked_policies(self, user_id: str):
        """북마크한 정책 목록 (product 원본 조회)."""
        try:
            bookmarked_ids = self.find_bookmarked_ids_by_type(user_id, "Policy")
            if not bookmarked_ids:
                return []
            return (
                self.db.query(PolicyProduct)
                .filter(PolicyProduct.key.in_(bookmarked_ids))
                .order_by(PolicyProduct.dday.asc())
                .all()
            )
        except SQLAlchemyError as e:
            self.db.rollback()
            logger.error(f"[RecommendRepository] 북마크 정책 목록 조회 실패 - error={e}")
            raise BusinessException(ErrorCode.DB_ERROR)
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
                .join(PolicyProduct, RecommendPolicy.policy_product_id == PolicyProduct.key) # JOIN
                .filter(RecommendPolicy.user_id == user_id) # 유저에 해당하는 추천 결과만
                .order_by(PolicyProduct.dday.asc()) # D-day 기준 오름차순 정렬
            )
            total = query.count() # 페이징을 위한 전체 개수 조회
            items = query.offset(page * size).limit(size).all() # 페이징 적용
            return items, total 
        except SQLAlchemyError as e:
            self.db.rollback() # 트랜잭션 롤백(나머지 에러는 service 레이어에서 처리)
            logger.error(f"[RecommendRepository] 정책 목록 조회 실패 - error={e}")
            raise BusinessException(ErrorCode.DB_ERROR)
 
    def find_policy_by_id(self, policy_product_id: str):
        """정책 상품 원본 단건 조회."""
        try:
            return (
                self.db.query(PolicyProduct)
                .filter(PolicyProduct.key == policy_product_id) # PK로 조회
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
                .order_by(RecommendInsurance.match_score.desc())
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
                .order_by(RecommendCard.match_score.desc())
                .all()
            )
        except SQLAlchemyError as e:
            self.db.rollback()
            logger.error(f"[RecommendRepository] 카드 목록 조회 실패 - error={e}")
            raise BusinessException(ErrorCode.DB_ERROR)
 
 
 
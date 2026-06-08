# # app/domain/sync/router.py
# import logging
# from fastapi import APIRouter, Depends
# from sqlalchemy.orm import Session

# from app.domain.sync.service import SyncService
# from app.core.config.database import get_db
# from app.core.common.response import CommonResponse

# logger = logging.getLogger(__name__)

# router = APIRouter(prefix="/internal/sync", tags=["Sync"])


# @router.post(
#     "/card-products",
#     summary="카드 원본 데이터 수동 적재",
#     description="raw-externals에서 CARD 데이터를 가져와 card_product 테이블에 저장합니다.",
# )
# def sync_card_products(db: Session = Depends(get_db)):
#     logger.info("[SyncRouter] POST /internal/sync/card-products")
#     service = SyncService(db)
#     result = service.sync_card_products()
#     return CommonResponse.of(result)


# @router.post(
#     "/insurance-products",
#     summary="보험 원본 데이터 수동 적재",
#     description="raw-externals에서 INSURANCE 데이터를 가져와 insurance_product 테이블에 저장합니다.",
# )
# def sync_insurance_products(db: Session = Depends(get_db)):
#     logger.info("[SyncRouter] POST /internal/sync/insurance-products")
#     service = SyncService(db)
#     result = service.sync_insurance_products()
#     return CommonResponse.of(result)


# @router.post(
#     "/youth-policies",
#     summary="청년정책 원본 데이터 수동 적재",
#     description="raw-externals에서 POLICY 데이터를 가져와 policy_product 테이블에 저장합니다.",
# )
# def sync_youth_policies(db: Session = Depends(get_db)):
#     logger.info("[SyncRouter] POST /internal/sync/youth-policies")
#     service = SyncService(db)
#     result = service.sync_policy_products()
#     return CommonResponse.of(result)
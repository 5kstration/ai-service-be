# # app/domain/sync/client.py
# import logging
# import httpx
# from typing import Optional
# from app.core.config.settings import settings

# logger = logging.getLogger(__name__)


# class RawExternalClient:
#     """
#     온프레미스 recommend-service의 raw-externals API 호출 클라이언트.
#     """

#     def __init__(self):
#         self.base_url = settings.RAW_EXTERNAL_BASE_URL 

#     def fetch_raw_externals(
#         self,
#         category: str,
#         source_code: Optional[str] = None,
#         page: int = 0,
#         size: int = 100,
#     ) -> dict:
#         """
#         rawExternals 목록 조회.
#         category: CARD, INSURANCE, POLICY
#         """
#         try:
#             payload = {
#                 "category": category,
#                 "status": "SUCCESS",
#                 "page": page,
#                 "size": size,
#             }
#             if source_code:
#                 payload["sourceCode"] = source_code

#             with httpx.Client(timeout=30) as client:
#                 response = client.request(
#                     method  = "GET",
#                     url     = f"{self.base_url}/internal/v1/raw-externals",
#                     json    = payload,
#                     headers = {"Content-Type": "application/json"},
#                 )
#                 response.raise_for_status()
#                 return response.json()

#         except httpx.TimeoutException:
#             logger.error("[RawExternalClient] 요청 타임아웃")
#             raise
#         except httpx.HTTPStatusError as e:
#             logger.error(f"[RawExternalClient] HTTP 오류 - status={e.response.status_code}")
#             raise
#         except Exception as e:
#             logger.error(f"[RawExternalClient] 알 수 없는 오류 - error={e}")
#             raise


# raw_external_client = RawExternalClient()
# app/domain/recommend_ai/reranker.py
import json
import logging
import boto3
from app.core.config.settings import settings

logger = logging.getLogger(__name__)


class RerankerClient:
    """
    Bedrock Cohere Rerank 클라이언트.
    벡터 검색 결과를 더 정밀하게 재정렬.
    """

    def __init__(self):
        self._client = boto3.client(
            "bedrock-runtime",
            region_name           = settings.AWS_REGION,
            aws_access_key_id     = settings.AWS_ACCESS_KEY_ID,
            aws_secret_access_key = settings.AWS_SECRET_ACCESS_KEY,
        )

    def rerank(
        self,
        query:     str,
        documents: list[str],
        top_n:     int = 7,
    ) -> list[int]:
        """
        query: 유저 소비 패턴 텍스트
        documents: 후보 상품 텍스트 목록
        top_n: 상위 몇 개 반환할지
        반환: 재정렬된 원본 인덱스 목록

        예시:
          입력:  [카드A, 카드B, 카드C, 카드D, 카드E]
          반환:  [2, 0, 4, 1, 3]  ← 카드C가 가장 관련성 높음
        """
        if not documents:
            return []

        # documents가 top_n보다 적으면 전체 반환
        if len(documents) <= top_n:
            return list(range(len(documents)))

        try:
            response = self._client.invoke_model(
                modelId     = "cohere.rerank-v3-5:0",
                contentType = "application/json",
                accept      = "application/json",
                body        = json.dumps({
                    "query":     query,
                    "documents": documents,
                    "top_n":     top_n,
                }),
            )
            result = json.loads(response["body"].read())
            return [r["index"] for r in result["results"]]

        except Exception as e:
            logger.warning(f"[Reranker] 리랭킹 실패 - fallback to original order. error={e}")
            # 실패 시 원본 순서 그대로 top_n개 반환 (서비스 중단 없음)
            return list(range(min(top_n, len(documents))))


reranker_client = RerankerClient()
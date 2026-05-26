# app/core/client/bedrock_client.py
import json
import logging
import boto3
from app.core.config.settings import settings

logger = logging.getLogger(__name__)


class BedrockClient:
    def __init__(self):
        self._client = boto3.client(
            "bedrock-runtime",
            region_name           = settings.AWS_REGION,
            aws_access_key_id     = settings.AWS_ACCESS_KEY_ID,
            aws_secret_access_key = settings.AWS_SECRET_ACCESS_KEY,
        )

    # =============================================
    # 임베딩 생성 (Titan Embeddings V2)
    # =============================================
    def embed(self, text: str) -> list[float]:
        """텍스트 → 1024 벡터 반환."""
        try:
            response = self._client.invoke_model(
                modelId     = settings.BEDROCK_EMBED_MODEL,
                contentType = "application/json",
                accept      = "application/json",
                body        = json.dumps({
                    "inputText":  text,

                }),
            )
            result = json.loads(response["body"].read())
            return result["embedding"]
        except Exception as e:
            logger.error(f"[BedrockClient] 임베딩 생성 실패 - error={e}")
            raise

    # =============================================
    # 추천 사유 생성 (Claude Haiku)
    # =============================================
    def recommend(self, prompt: str, max_retries: int = 2) -> str:
        """프롬프트 → 추천 결과 JSON 문자열 반환."""
        
        last_error = None
        
        for attempt in range(max_retries + 1):
            try:
                response = self._client.invoke_model(
                    modelId     = settings.BEDROCK_LLM_MODEL,
                    contentType = "application/json",
                    accept      = "application/json",
                    body        = json.dumps({
                        "anthropic_version": "bedrock-2023-05-31",
                        "max_tokens":        2000,
                        "temperature":       0.3,   # 추천은 일관성 중요 → 낮게
                        "messages": [
                            {"role": "user", "content": prompt}
                        ],
                    }),
                )
                result = json.loads(response["body"].read())
                
                # stop_reason 체크 (max_tokens 초과 시 응답 잘릴 수 있음)
                stop_reason = result.get("stop_reason")
                if stop_reason == "max_tokens":
                    logger.warning(f"[BedrockClient] 응답이 max_tokens에서 잘림 - attempt={attempt}")
                
                text = result["content"][0]["text"]
                
                # 빈 응답 체크
                if not text or not text.strip():
                    raise ValueError("LLM 빈 응답")
                
                return text

            except self._client.exceptions.ThrottlingException as e:
                # 요청 한도 초과 → 재시도
                last_error = e
                if attempt < max_retries:
                    import time
                    wait = 2 ** attempt  # 1초, 2초 exponential backoff
                    logger.warning(f"[BedrockClient] Throttling - {wait}초 후 재시도 ({attempt+1}/{max_retries})")
                    time.sleep(wait)
                
            except self._client.exceptions.ModelNotReadyException as e:
                # 모델 준비 안 됨 → 재시도
                last_error = e
                if attempt < max_retries:
                    import time
                    logger.warning(f"[BedrockClient] 모델 준비 중 - 재시도 ({attempt+1}/{max_retries})")
                    time.sleep(3)

            except Exception as e:
                logger.error(f"[BedrockClient] LLM 호출 실패 - error={e}")
                raise

        logger.error(f"[BedrockClient] 최대 재시도 초과 - error={last_error}")
        raise last_error

bedrock_client = BedrockClient()



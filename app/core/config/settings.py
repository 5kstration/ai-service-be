# app/core/config/settings.py
import os
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # llm
    ANTHROPIC_API_KEY: str = os.getenv("ANTHROPIC_API_KEY", "")
    LLM_MODEL: str = "claude-haiku-4-5-20251001"
    
    GATEWAY_SECRET_TOKEN: str = ""  
    
    # Redis
    REDIS_HOST: str = ""
    REDIS_PORT: int = 6379
    REDIS_PASSWORD: str = ""
    REDIS_SENTINEL_HOST: str = ""        # 비어있으면 직접 연결 (로컬)
    REDIS_SENTINEL_SVC_PORT: int = 26379
    REDIS_SENTINEL_MASTER: str = "mymaster"
    
    # AWS
    AWS_REGION: str            = "ap-northeast-2"
    AWS_ACCESS_KEY_ID: str     = ""
    AWS_SECRET_ACCESS_KEY: str = ""
 
    # SQS
    SQS_QUEUE_URL: str = ""         # 수신 큐 (AUTH → AI)
    SQS_PUBLISH_QUEUE_URL: str = "" # 발행 큐 (AI → AUTH), 프로필 업데이트 이벤트
    SQS_ENDPOINT_URL: str = ""      # 로컬: http://localhost:4566, 운영: 빈값
    SQS_BUDGET_QUEUE_URL: str = "https://sqs.ap-northeast-2.amazonaws.com/525089404962/budget-ai-event"

    #raw
    RAW_EXTERNAL_BASE_URL: str = "http://10.0.2.62:8081"
    # Bedrock (추천 파이프라인용)
    BEDROCK_EMBED_MODEL: str = "amazon.titan-embed-text-v2:0"
    BEDROCK_LLM_MODEL:   str = "anthropic.claude-haiku-4-5-20251001:0"
    
    #vector db
    VECTOR_DB_HOST:     str = ""  
    VECTOR_DB_PORT:     int = 5432
    VECTOR_DB_NAME:     str = ""
    VECTOR_DB_USER:     str = ""
    VECTOR_DB_PASSWORD: str = ""
    
    # Neo4j (Graph RAG)
    # - .env에 NEO4J_URI가 이미 있으면 활성화 없이도 동작하게 만들기 위해, client에서 자동 enable도 지원
    NEO4J_ENABLED: bool = False
    NEO4J_URI: str = ""
    # 호환성: 기존 .env에 NEO4J_USERNAME을 쓰는 경우 지원
    NEO4J_USER: str = ""
    NEO4J_USERNAME: str = ""
    NEO4J_PASSWORD: str = ""
    NEO4J_DATABASE: str = "neo4j"
    # 그래프 확장 깊이/최대 트리플 수 (LLM 토큰 보호용)
    NEO4J_POLICY_HOPS: int = 2
    NEO4J_POLICY_MAX_TRIPLES: int = 60
    
    
    class Config:
        env_file = ".env"
        extra = "ignore"  


settings = Settings()
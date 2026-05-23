# app/core/config/settings.py
import os
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # llm
    ANTHROPIC_API_KEY: str = os.getenv("ANTHROPIC_API_KEY", "")
    LLM_MODEL: str = "claude-haiku-4-5-20251001"
    
    #redis
    REDIS_HOST: str = "localhost"
    REDIS_PORT: int = 6379
    
    # AWS
    AWS_REGION: str            = "ap-northeast-2"
    AWS_ACCESS_KEY_ID: str     = ""
    AWS_SECRET_ACCESS_KEY: str = ""
 
    # SQS
    SQS_QUEUE_URL: str = ""
    SQS_ENDPOINT_URL: str = ""  # 로컬: http://localhost:4566, 운영: 빈값
    
    class Config:
        env_file = ".env"
        extra = "ignore"  


settings = Settings()
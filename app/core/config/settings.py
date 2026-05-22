# app/core/config/settings.py
import os
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    ANTHROPIC_API_KEY: str = os.getenv("ANTHROPIC_API_KEY", "")
    LLM_MODEL: str = "claude-haiku-4-5-20251001"
    REDIS_HOST: str = "localhost"
    REDIS_PORT: int = 6379
    NATS_URL: str = "nats://localhost:4222"
    class Config:
        env_file = ".env"
        extra = "ignore"  # 추가


settings = Settings()
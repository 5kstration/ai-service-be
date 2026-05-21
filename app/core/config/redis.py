# app/core/config/redis.py
import logging
import redis
from typing import Optional
from app.core.config.settings import settings

logger = logging.getLogger(__name__)

# 모듈 레벨 싱글톤 (초기 연결 시도)
# None이면 get_redis_client() 호출 시마다 재연결 시도
_redis_client: Optional[redis.Redis] = None


def _create_redis_client() -> Optional[redis.Redis]:
    """
    Redis Connection Pool 기반 클라이언트 생성.
    실패 시 None 반환 → service 레이어에서 fallback 처리 담당.
    앱 시작을 막지 않음.
    """
    try:
        pool = redis.ConnectionPool(
            host             = settings.REDIS_HOST,
            port             = settings.REDIS_PORT,
            db               = 0,
            decode_responses = True,
            max_connections  = 10,
            socket_timeout         = 3,
            socket_connect_timeout = 3,
        )
        client = redis.Redis(connection_pool=pool)
        client.ping()  # 초기 연결 확인
        logger.info(f"[Redis] 연결 성공 - {settings.REDIS_HOST}:{settings.REDIS_PORT}")
        return client
    except Exception as e:
        logger.warning(
            f"[Redis] 연결 실패로 캐시 비활성화 - "
            f"{settings.REDIS_HOST}:{settings.REDIS_PORT}, error={e}"
        )
        return None


def get_redis_client() -> Optional[redis.Redis]:
    """
    Redis 클라이언트 반환.
    - 초기 연결 실패 시 None이었다가 이후 호출 시점에 재연결 시도
    - Redis 복구 시 다음 get_redis_client() 호출부터 자동 정상화
    - 재연결 실패해도 None 반환으로 service fallback 처리
    """
    global _redis_client
    if _redis_client is None:
        logger.info("[Redis] 재연결 시도 중...")
        _redis_client = _create_redis_client()
    return _redis_client


# 앱 시작 시 초기 연결 시도
_redis_client = _create_redis_client()
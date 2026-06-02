# app/core/config/redis.py
import logging
from typing import Optional
from app.core.config.settings import settings

logger = logging.getLogger(__name__)

_redis_client = None


def _create_redis_client():
    try:
        # Sentinel 주소가 설정된 경우 (운영)
        if settings.REDIS_SENTINEL_HOST:
            from redis.sentinel import Sentinel
            sentinel = Sentinel(
                [(settings.REDIS_SENTINEL_HOST, settings.REDIS_SENTINEL_PORT)],
                password         = settings.REDIS_PASSWORD,
                socket_timeout   = 3,
                decode_responses = True,
            )
            master = sentinel.master_for(
                settings.REDIS_SENTINEL_MASTER,
                password = settings.REDIS_PASSWORD,
            )
            master.ping()
            logger.info(f"[Redis] Sentinel 연결 성공 - {settings.REDIS_SENTINEL_HOST}:{settings.REDIS_SENTINEL_PORT}")
            return master

        # Sentinel 없으면 직접 연결 (로컬)
        else:
            import redis
            pool = redis.ConnectionPool(
                host                   = settings.REDIS_HOST,
                port                   = settings.REDIS_PORT,
                password               = settings.REDIS_PASSWORD or None,
                db                     = 0,
                decode_responses       = True,
                max_connections        = 10,
                socket_timeout         = 3,
                socket_connect_timeout = 3,
            )
            client = redis.Redis(connection_pool=pool)
            client.ping()
            logger.info(f"[Redis] 직접 연결 성공 - {settings.REDIS_HOST}:{settings.REDIS_PORT}")
            return client

    except Exception as e:
        logger.warning(f"[Redis] 연결 실패로 캐시 비활성화 - error={e}")
        return None  # 앱 시작 막지 않음, service에서 fallback 처리


def get_redis_client():
    global _redis_client
    if _redis_client is None:
        _redis_client = _create_redis_client()
    return _redis_client


_redis_client = _create_redis_client()
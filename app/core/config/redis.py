# app/core/config/redis.py
import logging
import redis
from app.core.config.settings import settings
from app.core.error.error_code import ErrorCode
from app.core.error.exception import BusinessException

logger = logging.getLogger(__name__)

_redis_client = None


def _create_redis_client() -> redis.Redis:
    try:
        pool = redis.ConnectionPool(
            host                   = settings.REDIS_HOST,
            port                   = settings.REDIS_PORT,
            password               = settings.REDIS_PASSWORD,
            db                     = 0,
            decode_responses       = True,
            max_connections        = 10,
            socket_timeout         = 3,
            socket_connect_timeout = 3,
        )
        client = redis.Redis(connection_pool=pool)
        client.ping()
        logger.info(f"[Redis] 연결 성공 - {settings.REDIS_HOST}:{settings.REDIS_PORT}")
        return client
    except Exception as e:
        logger.error(f"[Redis] 연결 실패 - {settings.REDIS_HOST}:{settings.REDIS_PORT}, error={e}")
        raise BusinessException(ErrorCode.REDIS_CONNECTION_ERROR)


def get_redis_client() -> redis.Redis:
    global _redis_client
    if _redis_client is None:
        _redis_client = _create_redis_client()  # 실패 시 예외 발생
    return _redis_client


# 앱 시작 시 연결 확인 (실패 시 앱 시작 자체를 막음)
_redis_client = _create_redis_client()
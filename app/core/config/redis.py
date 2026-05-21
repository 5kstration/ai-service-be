# app/core/config/redis.py
import logging
import redis
from typing import Optional
from app.core.config.settings import settings

logger = logging.getLogger(__name__)


def _create_redis_client() -> Optional[redis.Redis]:
    """
    Redis Connection Pool 기반 클라이언트 생성.

    Connection Pool 동작:
    - 미리 연결을 풀로 관리하여 매 요청마다 새 연결 오버헤드 제거
    - 연결이 끊기면 다음 요청 시점에 자동 재연결 시도
    - 백그라운드 재시도는 없음. 재연결 트리거는 다음 API 요청

    실패 시 None 반환 → service 레이어에서 fallback 처리 담당.
    앱 시작을 막지 않음.
    """
    try:
        pool = redis.ConnectionPool(
            host             = settings.REDIS_HOST,
            port             = settings.REDIS_PORT,
            db               = 0,
            decode_responses = True,   # str 반환
            max_connections  = 10,
            socket_timeout         = 3,    # 읽기 타임아웃 3초
            socket_connect_timeout = 3,    # 연결 타임아웃 3초
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


# 싱글톤 인스턴스
# - Redis 장애 시 None
# - service 레이어에서 None 체크 후 fallback 처리
# - Redis 복구 시 다음 요청부터 Pool이 자동 재연결
redis_client = _create_redis_client()
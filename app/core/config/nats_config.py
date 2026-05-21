# app/core/config/nats.py
import logging
import nats
from app.core.config.settings import settings

logger = logging.getLogger(__name__)

_nats_client = None
_js = None


async def get_nats_client():
    """NATS 클라이언트 반환. 없으면 연결 시도."""
    global _nats_client
    if _nats_client is None or not _nats_client.is_connected:
        try:
            _nats_client = await nats.connect(settings.NATS_URL)
            logger.info(f"[NATS] 연결 성공 - {settings.NATS_URL}")
        except Exception as e:
            logger.error(f"[NATS] 연결 실패 - {settings.NATS_URL}, error={e}")
            return None
    return _nats_client


async def get_jetstream():
    """JetStream 컨텍스트 반환."""
    global _js
    client = await get_nats_client()
    if not client:
        return None
    if _js is None:
        _js = client.jetstream()
    return _js


async def start_consumers():
    """
    앱 시작 시 모든 NATS consumer 등록.
    main.py의 startup 이벤트에서 호출.
    """
    from app.domain.profile.consumer import handle_onboarding_event, ONBOARDING_SUBJECT

    js = await get_jetstream()
    if not js:
        logger.warning("[NATS] JetStream 없음 - consumer 등록 스킵")
        return

    try:
        await js.subscribe(
            ONBOARDING_SUBJECT,
            durable   = "ai-service-onboarding-consumer",  # 내구성 consumer
            cb        = handle_onboarding_event,
        )
        logger.info(f"[NATS] consumer 등록 완료 - subject={ONBOARDING_SUBJECT}")
    except Exception as e:
        logger.error(f"[NATS] consumer 등록 실패 - error={e}")
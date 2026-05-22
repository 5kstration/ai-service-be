# app/core/config/nats.py
import logging
import nats
from app.core.config.settings import settings
from app.domain.profile.consumer import handle_onboarding_event, ONBOARDING_SUBJECT

logger = logging.getLogger(__name__)

_nats_client = None
_js = None


async def get_nats_client():
    global _nats_client, _js
    if _nats_client is None or not _nats_client.is_connected:
        try:
            _nats_client = await nats.connect(
                settings.NATS_URL,
                connect_timeout=3,
            )
            _js = None
            logger.warning(f"[NATS] 연결 성공 - {settings.NATS_URL}")  
        except Exception as e:
            logger.warning(f"[NATS] 연결 실패 - consumer 비활성화. error={e}")
            return None
    return _nats_client


async def get_jetstream():
    global _js
    client = await get_nats_client()
    if not client:
        return None
    if _js is None:
        _js = client.jetstream()
    return _js


async def start_consumers():

    js = await get_jetstream()
    logger.warning(f"[NATS] js 획득: {js}") 
    if not js:
        logger.warning("[NATS] JetStream 없음 - consumer 등록 스킵")
        return

    try:
        await js.subscribe(
            ONBOARDING_SUBJECT,
            durable = "ai-service-onboarding-consumer",
            cb      = handle_onboarding_event,
            manual_ack=True,
        )
        logger.warning(f"[NATS] consumer 등록 완료 - subject={ONBOARDING_SUBJECT}")
    except Exception as e:
        logger.warning(f"[NATS] consumer 등록 실패 - error={e}")
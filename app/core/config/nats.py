import asyncio
import json
import logging
from nats.aio.client import Client as NatsClient
from nats.js.errors import NotFoundError
from nats.js.api import StreamConfig, RetentionPolicy, StorageType
from app.core.config.settings import settings
from app.domain.profile.consumer import handle_onboarding_event
from app.domain.budget.consumer import handle_budget_event

logger = logging.getLogger(__name__)

_nats_client = None
_js = None
_consumer_tasks = []

async def get_nats_client():
    global _nats_client, _js
    if _nats_client is None:
        try:
            nc = NatsClient()
            nats_url = settings.NATS_URL if hasattr(settings, 'NATS_URL') and settings.NATS_URL else "nats://nats-leaf:4222"
            await nc.connect(nats_url)
            _nats_client = nc
            _js = nc.jetstream()
            logger.info(f"[NATS] 클라이언트 연결 완료 - url={nats_url}")
        except Exception as e:
            logger.error(f"[NATS] 클라이언트 연결 실패 - error={e}")
            return None, None
    return _nats_client, _js

async def _ensure_stream(js, stream_name: str, subjects: list):
    try:
        await js.stream_info(stream_name)
        logger.info(f"[NATS] 스트림 '{stream_name}' 이미 존재함.")
    except NotFoundError:
        logger.info(f"[NATS] 스트림 '{stream_name}' 생성 중...")
        await js.add_stream(name=stream_name, subjects=subjects, storage=StorageType.FILE)

async def start_consumers():
    nc, js = await get_nats_client()
    if not js:
        logger.warning("[NATS] JetStream 클라이언트 없음 - consumer 등록 스킵")
        return

    # Onboarding Consumer
    try:
        stream_name = "onboarding-events"
        subject = "onboarding.event.>"
        await _ensure_stream(js, stream_name, [subject])
        logger.info(f"[NATS] onboarding consumer 시작 - stream={stream_name}, subject={subject}")
        
        async def onboarding_cb(msg):
            try:
                body = msg.data.decode()
                await handle_onboarding_event(body)
                await msg.ack()
            except Exception as e:
                logger.error(f"[NATS] Onboarding 메시지 처리 실패 - error={e}")
                await msg.nak()

        sub1 = await js.subscribe(subject, queue="ai-service-onboarding-queue", stream=stream_name, durable="ai-service-onboarding-consumer", cb=onboarding_cb)
        _consumer_tasks.append(sub1)
    except Exception as e:
        logger.error(f"[NATS] Onboarding consumer 시작 실패 - error={e}")

    # Budget Consumer
    try:
        stream_name = "budget-log-events"
        subject = "budget.log.event"
        await _ensure_stream(js, stream_name, [subject])
        logger.info(f"[NATS] budget consumer 시작 - stream={stream_name}, subject={subject}")
        
        async def budget_cb(msg):
            try:
                body = msg.data.decode()
                await handle_budget_event(body)
                await msg.ack()
            except Exception as e:
                logger.error(f"[NATS] Budget 메시지 처리 실패 - error={e}")
                await msg.nak()

        sub2 = await js.subscribe(subject, queue="ai-service-budget-queue", stream=stream_name, durable="ai-service-budget-consumer", cb=budget_cb)
        _consumer_tasks.append(sub2)
    except Exception as e:
        logger.error(f"[NATS] Budget consumer 시작 실패 - error={e}")

# =============================================
# NATS 메시지 발행 (AI → AUTH)
# =============================================
async def publish_profile_update(payload: dict) -> bool:
    """
    AI 서비스에서 AUTH 서비스로 프로필 업데이트 이벤트 발행.
    AUTH에서 받는 onboarding 이벤트와 동일한 포맷으로 발행.
    """
    nc, js = await get_nats_client()
    if not js:
        logger.warning("[NATS] 클라이언트 없음 - 프로필 업데이트 발행 스킵")
        return False

    stream_name = "ai-events"
    subject = "ai.event.profile.update"
    
    try:
        await _ensure_stream(js, stream_name, ["ai.event.>"])
        
        body = json.dumps(payload, ensure_ascii=False).encode('utf-8')
        await js.publish(subject, body)
        logger.info(f"[NATS] 프로필 업데이트 발행 완료 - userId={payload.get('userId')}")
        return True
    except Exception as e:
        logger.error(f"[NATS] 프로필 업데이트 발행 실패 - userId={payload.get('userId')}, error={e}")
        return False

# app/core/config/sqs.py
import asyncio
import json
import logging
import boto3
from botocore.exceptions import ClientError
from app.core.config.settings import settings
from app.domain.profile.consumer import handle_onboarding_event, handle_budget_event

logger = logging.getLogger(__name__)

_sqs_client = None
_consumer_task = None


def get_sqs_client():
    global _sqs_client
    if _sqs_client is None:
        try:
            kwargs = {
                    "region_name": settings.AWS_REGION,
                }
            if settings.AWS_ACCESS_KEY_ID and settings.AWS_SECRET_ACCESS_KEY:
                kwargs["aws_access_key_id"] = settings.AWS_ACCESS_KEY_ID
                kwargs["aws_secret_access_key"] = settings.AWS_SECRET_ACCESS_KEY

            # 로컬 환경에서만 endpoint_url 추가
            if settings.SQS_ENDPOINT_URL:
                kwargs["endpoint_url"] = settings.SQS_ENDPOINT_URL

            _sqs_client = boto3.client("sqs", **kwargs)
            logger.info(f"[SQS] 클라이언트 생성 완료 - region={settings.AWS_REGION}")
        except Exception as e:
            logger.error(f"[SQS] 클라이언트 생성 실패 - error={e}")
            return None
    return _sqs_client




# 실제 사용 시 get_sqs_client 함수에서 boto3 클라이언트 생성 로직을 활성화해야 합니다.
# def get_sqs_client():
#     """SQS 클라이언트 싱글톤 반환."""
#     global _sqs_client
#     if _sqs_client is None:
#         try:
#             _sqs_client = boto3.client(
#                 "sqs",
#                 region_name          = settings.AWS_REGION,
#                 aws_access_key_id    = settings.AWS_ACCESS_KEY_ID,
#                 aws_secret_access_key= settings.AWS_SECRET_ACCESS_KEY,
#             )
#             logger.info(f"[SQS] 클라이언트 생성 완료 - region={settings.AWS_REGION}")
#         except Exception as e:
#             logger.error(f"[SQS] 클라이언트 생성 실패 - error={e}")
#             return None
#     return _sqs_client


async def start_consumers():
    sqs = get_sqs_client()
    global _consumer_task
    if not sqs:
        logger.warning("[SQS] 클라이언트 없음 - consumer 등록 스킵")
        return

    tasks = []

    if settings.SQS_QUEUE_URL:
        logger.info(f"[SQS] onboarding consumer 시작 - queue={settings.SQS_QUEUE_URL}")
        tasks.append(asyncio.create_task(_poll_messages(sqs, settings.SQS_QUEUE_URL, "onboarding")))

    if settings.SQS_BUDGET_QUEUE_URL:
        logger.info(f"[SQS] budget consumer 시작 - queue={settings.SQS_BUDGET_QUEUE_URL}")
        tasks.append(asyncio.create_task(_poll_messages(sqs, settings.SQS_BUDGET_QUEUE_URL, "budget")))

    if tasks:
        _consumer_task = tasks
        
async def _poll_messages(sqs, queue_url: str, consumer_type: str):

    handler = handle_budget_event if consumer_type == "budget" else handle_onboarding_event
    
    while True:
        try:
            response = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: sqs.receive_message(
                    QueueUrl            = queue_url,
                    MaxNumberOfMessages = 10,
                    WaitTimeSeconds     = 20,
                    VisibilityTimeout   = 60,
                )
            )
            messages = response.get("Messages", [])
            if not messages:
                continue

            for message in messages:
                await _process_message(sqs, message, handler, queue_url)

        except ClientError as e:
            logger.error(f"[SQS] 메시지 수신 실패 - queue={queue_url}, error={e}")
            await asyncio.sleep(5)
        except Exception as e:
            logger.error(f"[SQS] 알 수 없는 오류 - queue={queue_url}, error={e}")
            await asyncio.sleep(5)
            

async def _process_message(sqs, message: dict, handler, queue_url: str):
    receipt_handle = message["ReceiptHandle"]
    body = message.get("Body", "")
    try:
        await handler(body)
        await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: sqs.delete_message(
                QueueUrl      = queue_url,
                ReceiptHandle = receipt_handle,
            )
        )
        logger.info("[SQS] 메시지 처리 및 삭제 완료")
    except Exception as e:
        logger.error(f"[SQS] 메시지 처리 실패 - 재시도 예정. error={e}")
        


# =============================================
# SQS 메시지 발행 (AI → AUTH)
# =============================================
def publish_profile_update(payload: dict) -> bool:
    """
    AI 서비스에서 AUTH 서비스로 프로필 업데이트 이벤트 발행.
    AUTH에서 받는 onboarding 이벤트와 동일한 포맷으로 발행.

    payload 형식 (AUTH가 수신하는 포맷과 동일):
    {
        "userId":        "01HXXX...",
        "monthlyIncome": 3000000,
        "birth":         "1997-03-15T00:00:00",   # ISO 형식, 없으면 null
        "sex":           "남자"                    # 없으면 null
    }

    Returns:
        True: 발행 성공
        False: 발행 실패 (서비스 중단 없이 로깅만)
    """
    sqs = get_sqs_client()
    if not sqs:
        logger.warning("[SQS] 클라이언트 없음 - 프로필 업데이트 발행 스킵")
        return False

    queue_url = settings.SQS_PUBLISH_QUEUE_URL
    if not queue_url:
        logger.warning("[SQS] SQS_PUBLISH_QUEUE_URL 미설정 - 프로필 업데이트 발행 스킵")
        return False

    try:
        import json as _json
        body = _json.dumps(payload, ensure_ascii=False)
        sqs.send_message(
            QueueUrl    = queue_url,
            MessageBody = body,
        )
        logger.info(f"[SQS] 프로필 업데이트 발행 완료 - userId={payload.get('userId')}")
        return True
    except Exception as e:
        logger.error(f"[SQS] 프로필 업데이트 발행 실패 - userId={payload.get('userId')}, error={e}")
        return False
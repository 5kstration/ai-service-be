# app/core/config/sqs.py
import asyncio
import json
import logging
import boto3
from botocore.exceptions import ClientError
from app.core.config.settings import settings

logger = logging.getLogger(__name__)

_sqs_client = None




def get_sqs_client():
    global _sqs_client
    if _sqs_client is None:
        try:
            kwargs = dict(
                region_name           = settings.AWS_REGION,
                aws_access_key_id     = settings.AWS_ACCESS_KEY_ID,
                aws_secret_access_key = settings.AWS_SECRET_ACCESS_KEY,
            )
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
    """
    앱 시작 시 SQS consumer 폴링 시작.
    main.py startup 이벤트에서 호출.
    백그라운드 태스크로 실행.
    """
    sqs = get_sqs_client()
    if not sqs:
        logger.warning("[SQS] 클라이언트 없음 - consumer 등록 스킵")
        return

    logger.info(f"[SQS] consumer 시작 - queue={settings.SQS_QUEUE_URL}")
    asyncio.create_task(_poll_messages(sqs))


async def _poll_messages(sqs):
    """
    SQS 롱 폴링 루프.
    메시지 수신 시 handle_onboarding_event 호출.
    """
    from app.domain.profile.consumer import handle_onboarding_event

    while True:
        try:
            response = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: sqs.receive_message(
                    QueueUrl            = settings.SQS_QUEUE_URL,
                    MaxNumberOfMessages = 10,      # 최대 10개씩 수신
                    WaitTimeSeconds     = 20,      # 롱 폴링 20초
                    VisibilityTimeout   = 60,      # 처리 중 다른 consumer에게 숨김
                )
            )

            messages = response.get("Messages", [])
            if not messages:
                continue

            for message in messages:
                await _process_message(sqs, message, handle_onboarding_event)

        except ClientError as e:
            logger.error(f"[SQS] 메시지 수신 실패 - error={e}")
            await asyncio.sleep(5)  # 에러 시 5초 대기 후 재시도
        except Exception as e:
            logger.error(f"[SQS] 알 수 없는 오류 - error={e}")
            await asyncio.sleep(5)


async def _process_message(sqs, message: dict, handler):
    """
    단건 메시지 처리.
    처리 성공 시 삭제, 실패 시 visibility timeout 후 재시도.

    SQS 재시도 정책:
    - 처리 실패 시 삭제하지 않음 → visibility timeout 후 자동 재시도
    - 최대 재시도 횟수 초과 시 DLQ(Dead Letter Queue)로 이동
    """
    receipt_handle = message["ReceiptHandle"]
    body           = message.get("Body", "")

    try:
        await handler(body)

        # 처리 성공 시 메시지 삭제
        await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: sqs.delete_message(
                QueueUrl      = settings.SQS_QUEUE_URL,
                ReceiptHandle = receipt_handle,
            )
        )
        logger.info("[SQS] 메시지 처리 및 삭제 완료")

    except Exception as e:
        # 처리 실패 시 삭제 안 함 → visibility timeout 후 재시도
        logger.error(f"[SQS] 메시지 처리 실패 - 재시도 예정. error={e}")
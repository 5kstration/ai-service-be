# app/domain/profile/consumer.py
import json
import logging
from datetime import datetime

from sqlalchemy.orm import Session

from app.domain.profile.entity import UserProfile
from app.core.config.database import SessionLocal

logger = logging.getLogger(__name__)

ONBOARDING_SUBJECT = "auth.onboarding.created"


async def handle_onboarding_event(msg):
    """
    auth-service 온보딩 등록 이벤트 수신 처리.

    예외 케이스:
    - decode 실패      → 로그 후 ack (재시도 무의미)
    - JSON 파싱 실패   → 로그 후 ack (재시도 무의미)
    - userId 누락      → 로그 후 ack (재시도 무의미)
    - 입력값 검증 실패 → 로그 후 ack (데이터 오류는 재시도로 복구 불가)
    - DB 저장 실패     → nak (재시도)
    """

    # 1. decode
    try:
        raw = msg.data.decode("utf-8")
    except Exception as e:
        logger.error(f"[ProfileConsumer] decode 실패 - error={e}")
        await msg.ack()  # 바이너리 오류는 재시도 무의미
        return

    # 2. JSON 파싱
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        logger.error(f"[ProfileConsumer] JSON 파싱 실패 - raw={raw}, error={e}")
        await msg.ack()
        return

    # 3. userId 검증
    user_id = data.get("userId")
    if not user_id or not isinstance(user_id, str) or not user_id.strip():
        logger.error(f"[ProfileConsumer] userId 누락 또는 유효하지 않음 - data={data}")
        await msg.ack()
        return

    # 4. 입력값 검증 (데이터 형식 오류는 재시도로 복구 불가 → ack)
    monthly_income = data.get("monthlyIncome")
    if monthly_income is not None:
        try:
            monthly_income = int(monthly_income)
            if monthly_income < 0:
                raise ValueError("음수 월급")
        except (TypeError, ValueError) as e:
            logger.error(f"[ProfileConsumer] monthlyIncome 형식 오류 - value={monthly_income}, error={e}")
            await msg.ack()
            return

    # 5. birth 파싱 (실패해도 저장 진행, birth만 None으로)
    birth = None
    if data.get("birth"):
        try:
            birth = datetime.fromisoformat(data["birth"]).date()
        except Exception as e:
            logger.warning(f"[ProfileConsumer] birth 파싱 실패 - birth={data.get('birth')}, error={e}")

    # 6. DB 저장 (upsert)
    db: Session = SessionLocal()
    try:
        existing = db.query(UserProfile).filter(UserProfile.user_id == user_id).first()

        if existing:
            existing.birth          = birth
            existing.sex            = data.get("sex")
            existing.monthly_income = monthly_income
            logger.info(f"[ProfileConsumer] 유저 프로필 업데이트 - user_id={user_id}")
        else:
            profile = UserProfile(
                user_id        = user_id,
                birth          = birth,
                sex            = data.get("sex"),
                monthly_income = monthly_income,
            )
            db.add(profile)
            logger.info(f"[ProfileConsumer] 유저 프로필 신규 저장 - user_id={user_id}")

        db.commit()
        await msg.ack()

    except Exception as e:
        db.rollback()
        logger.error(f"[ProfileConsumer] DB 저장 실패 - user_id={user_id}, error={e}")
        await msg.nak()  # DB 오류는 재시도
    finally:
        db.close()
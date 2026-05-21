# app/domain/profile/consumer.py
import json
import logging
from datetime import datetime

from sqlalchemy.orm import Session

from app.domain.profile.entity import UserProfile
from app.core.config.database import SessionLocal

logger = logging.getLogger(__name__)

# NATS subject: auth-service가 발행하는 온보딩 이벤트
ONBOARDING_SUBJECT = "auth.onboarding.created"



# auth-service 온보딩 등록 이벤트 수신 처리.
# 수신 데이터: userId, birth, sex, monthlyIncome
# 예외 케이스:
# - JSON 파싱 실패    → 로그 후 ack (재시도 무의미)
# - userId 누락       → 로그 후 ack
# - DB 저장 실패      → nak (재시도)
# - 이미 존재하는 유저 → upsert로 업데이트
async def handle_onboarding_event(msg):
    raw = msg.data.decode()

    # 1. JSON 파싱
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        logger.error(f"[ProfileConsumer] JSON 파싱 실패 - raw={raw}, error={e}")
        await msg.ack()  # 파싱 실패는 재시도 무의미
        return

    user_id = data.get("userId")
    if not user_id:
        logger.error(f"[ProfileConsumer] userId 누락 - data={data}")
        await msg.ack()
        return

    # 2. birth 파싱 (ISO 8601 → date)
    birth = None
    if data.get("birth"):
        try:
            birth = datetime.fromisoformat(data["birth"]).date()
        except Exception as e:
            logger.warning(f"[ProfileConsumer] birth 파싱 실패 - birth={data.get('birth')}, error={e}")

    # 3. DB 저장 
    db: Session = SessionLocal()
    try:
        existing = db.query(UserProfile).filter(UserProfile.user_id == user_id).first()

        if existing:
            # 이미 존재하면 업데이트
            existing.birth          = birth
            existing.sex            = data.get("sex")
            existing.monthly_income = data.get("monthlyIncome")
            logger.info(f"[ProfileConsumer] 유저 프로필 업데이트 - user_id={user_id}")
        else:
            # 신규 저장
            profile = UserProfile(
                user_id        = user_id,
                birth          = birth,
                sex            = data.get("sex"),
                monthly_income = data.get("monthlyIncome"),
            )
            db.add(profile)
            logger.info(f"[ProfileConsumer] 유저 프로필 신규 저장 - user_id={user_id}")

        db.commit()
        await msg.ack()

    except Exception as e:
        db.rollback()
        logger.error(f"[ProfileConsumer] DB 저장 실패 - user_id={user_id}, error={e}")
        await msg.nak()  # 재시도 요청
    finally:
        db.close()
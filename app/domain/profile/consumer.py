# app/domain/profile/consumer.py
# SQS 온보딩 이벤트 수신 → user_profile 저장 → 추천 파이프라인 실행

import json
import logging
from datetime import datetime

from sqlalchemy.orm import Session
from app.domain.profile.entity import UserProfile
from app.core.config.database import SessionLocal

logger = logging.getLogger(__name__)


async def handle_onboarding_event(body: str):
    # 1. JSON 파싱
    try:
        data = json.loads(body)
    except json.JSONDecodeError as e:
        logger.error(f"[ProfileConsumer] JSON 파싱 실패 - error={e}")
        raise

    # 2. userId 검증
    user_id = data.get("userId")
    if not user_id or not isinstance(user_id, str) or not user_id.strip():
        logger.error("[ProfileConsumer] userId 누락")
        raise ValueError("userId 누락")

    # 3. monthlyIncome 검증
    monthly_income = data.get("monthlyIncome")
    if monthly_income is not None:
        try:
            monthly_income = int(monthly_income)
            if monthly_income < 0:
                raise ValueError("음수 월급")
        except (TypeError, ValueError) as e:
            logger.error(f"[ProfileConsumer] monthlyIncome 형식 오류 - error={e}")
            raise

    # 4. birth 파싱
    birth = None
    if data.get("birth"):
        try:
            birth = datetime.fromisoformat(data["birth"]).date()
        except Exception as e:
            logger.warning(f"[ProfileConsumer] birth 파싱 실패 - error={e}")

    # 5. DB 저장 (upsert)
    db: Session = SessionLocal()
    try:
        existing = db.query(UserProfile).filter(
            UserProfile.user_id == user_id
        ).first()

        if existing:
            existing.birth          = birth
            existing.sex            = data.get("sex")
            existing.monthly_income = monthly_income
            logger.info(f"[ProfileConsumer] 유저 프로필 업데이트 완료")
        else:
            db.add(UserProfile(
                user_id        = user_id,
                birth          = birth,
                sex            = data.get("sex"),
                monthly_income = monthly_income,
            ))
            logger.info(f"[ProfileConsumer] 유저 프로필 신규 저장 완료")

        db.commit()

    except Exception as e:
        db.rollback()
        logger.error(f"[ProfileConsumer] DB 저장 실패 - error={e}")
        raise
    finally:
        db.close()

    # 6. 추천 파이프라인 실행 (신규 유저)
    try:
        from app.domain.recommend_ai.graph import run_recommend_pipeline
        await run_recommend_pipeline(user_id)
        logger.info(f"[ProfileConsumer] 추천 파이프라인 완료 - user_id={user_id}")
    except Exception as e:
        # 추천 실패해도 온보딩 자체는 성공 처리
        logger.error(f"[ProfileConsumer] 추천 파이프라인 실패 - user_id={user_id}, error={e}")
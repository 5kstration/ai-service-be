# app/core/config/scheduler.py
import logging
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

logger = logging.getLogger(__name__)

scheduler = AsyncIOScheduler()


def setup_scheduler():
    """배치 스케줄 등록."""

    # 매일 새벽 3시 — 상품 동기화 + 임베딩 + 전체 유저 재추천
    # UTC 기준 18시 = KST 03시
    from pytz import timezone

    scheduler.add_job(
        _daily_batch,
        CronTrigger(hour=3, minute=0, timezone=timezone('Asia/Seoul')),
        id="daily_recommend_batch",
        replace_existing=True,
    )
    scheduler.start()
    logger.info("[Scheduler] 스케줄러 시작 - 매일 새벽 3시 배치 등록")


async def _daily_batch():
    logger.info("[Scheduler] 배치 시작")
    try:
        from app.core.config.database import SessionLocal
        from app.domain.recommend_ai.embed_service import embed_all_products
        from app.domain.recommend_ai.graph import run_recommend_pipeline
        from app.domain.profile.entity import UserProfile

        # 1. 전체 상품 임베딩 갱신
        embed_all_products()
        logger.info("[Scheduler] 임베딩 갱신 완료")

        # 2. 전체 유저 재추천
        db = SessionLocal()
        try:
            users = db.query(UserProfile).all()
            logger.info(f"[Scheduler] 재추천 시작 - 총 {len(users)}명")
        finally:
            db.close()

        for user in users:
            try:
                await run_recommend_pipeline(user.user_id)
            except Exception:
                logger.exception(f"[Scheduler] 유저 추천 실패 - user_id={user.user_id}")

        logger.info("[Scheduler] 배치 완료")

    except Exception:
        logger.exception("[Scheduler] 배치 실패")
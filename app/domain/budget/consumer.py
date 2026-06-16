# app/domain/budget/consumer.py
import json
import logging
from datetime import date, datetime
from sqlalchemy.orm import Session
from app.core.config.database import SessionLocal
from app.core.config.redis import get_redis_client
from app.domain.report.entity import WeeklyExpense, MonthlySummary, Goal, AiReport
from app.core.utils.tsid import TSID

logger = logging.getLogger(__name__)


async def handle_budget_event(body: str):
    logger.info(f"[BudgetConsumer] 수신된 body: {body[:200]}")
    try:
        data = json.loads(body.strip())
    except json.JSONDecodeError:
        logger.exception(f"[BudgetConsumer] JSON 파싱 실패 - body={repr(body[:100])}")
        raise

    CATEGORY_KO_MAP = {
        "FOOD": "식비", "TRANSPORT": "교통", "SHOPPING": "쇼핑",
        "CAFE": "카페", "HOUSING": "주거", "MEDICAL": "의료",
        "TRAVEL": "여행", "CAR": "자동차", "CULTURE": "문화",
        "EDUCATION": "교육", "BUSINESS": "사업", "INVEST": "투자",
        "GAS": "주유", "TELECOM": "통신", "SPORT": "운동",
        "OTHER": "기타",
    }

    category   = CATEGORY_KO_MAP.get(data.get("category", "").upper(), data.get("category", "기타"))
    user_id    = data.get("userId")
    year       = data.get("year")
    month      = data.get("month")
    week       = data.get("weekOfMonth")
    start_date = data.get("startDate")
    end_date   = data.get("endDate")
    amount     = int(data.get("amount", 0))
    event_type = data.get("eventType")

    if not all([user_id, year, month, week, category, event_type]):
        logger.error(f"[BudgetConsumer] 필수 필드 누락 - data={data}")
        raise ValueError("필수 필드 누락")

    db: Session = SessionLocal()
    try:
        if event_type == "CREATED":
            _upsert_weekly(db, user_id, year, month, week, start_date, end_date, amount)
            _upsert_category(db, user_id, year, month, category, amount)
        elif event_type == "DELETED":
            _upsert_weekly(db, user_id, year, month, week, start_date, end_date, -amount)
            _upsert_category(db, user_id, year, month, category, -amount)
        elif event_type == "UPDATED":
            prev_amount = int(data.get("previousAmount", 0))
            diff = amount - prev_amount
            _upsert_weekly(db, user_id, year, month, week, start_date, end_date, diff)
            _upsert_category(db, user_id, year, month, category, diff)
        else:
            logger.warning(f"[BudgetConsumer] 알 수 없는 eventType - {event_type}")
            return

        _update_goal_total(db, user_id, year, month)

        db.commit()
        logger.info(f"[BudgetConsumer] 처리 완료 - user_id={user_id}, eventType={event_type}")

    except Exception as e:
        db.rollback()
        logger.error(f"[BudgetConsumer] DB 저장 실패 - error={e}")
        raise
    finally:
        db.close()

    # ── 리포트 캐시 + DB 삭제 (다음 조회 시 LLM 재생성) ──
    _invalidate_report(user_id)

    # ── 추천 파이프라인 재실행 ────────────────────────────
    try:
        from app.domain.recommend_ai.graph import run_recommend_pipeline
        await run_recommend_pipeline(user_id)
        logger.info(f"[BudgetConsumer] 추천 파이프라인 완료 - user_id={user_id}")
    except Exception as e:
        logger.error(f"[BudgetConsumer] 추천 파이프라인 실패 (무시) - user_id={user_id}, error={e}")


def _invalidate_report(user_id: str) -> None:
    today = date.today()

    # 1. Redis 캐시 삭제
    client = get_redis_client()
    if client:
        cache_key = f"report:{user_id}:{today.year}:{today.month}:{today.day}"
        try:
            client.delete(cache_key)
            logger.info(f"[BudgetConsumer] 리포트 캐시 삭제 - key={cache_key}")
        except Exception as e:
            logger.warning(f"[BudgetConsumer] 리포트 캐시 삭제 실패 (무시) - error={e}")

    # 2. DB 오늘 리포트 삭제 → 다음 GET /api/ai/report 시 LLM 재생성
    db: Session = SessionLocal()
    try:
        db.query(AiReport).filter(
            AiReport.user_id == user_id,
            AiReport.year    == today.year,
            AiReport.month   == today.month,
            AiReport.day     == today.day,
        ).delete()
        db.commit()
        logger.info(f"[BudgetConsumer] 오늘 리포트 DB 삭제 - user_id={user_id}")
    except Exception as e:
        db.rollback()
        logger.warning(f"[BudgetConsumer] 리포트 DB 삭제 실패 (무시) - error={e}")
    finally:
        db.close()


def _upsert_weekly(db, user_id, year, month, week, start_date, end_date, amount_delta):
    row = db.query(WeeklyExpense).filter(
        WeeklyExpense.user_id == user_id,
        WeeklyExpense.year    == year,
        WeeklyExpense.month   == month,
        WeeklyExpense.week    == week,
    ).first()

    if row:
        row.amount = max((row.amount or 0) + amount_delta, 0)
    else:
        db.add(WeeklyExpense(
            weekly_id  = TSID.create(),
            user_id    = user_id,
            year       = year,
            month      = month,
            week       = week,
            start_date = date.fromisoformat(start_date) if start_date else None,
            end_date   = date.fromisoformat(end_date) if end_date else None,
            amount     = max(amount_delta, 0),
        ))


def _upsert_category(db, user_id, year, month, category, amount_delta):
    row = db.query(MonthlySummary).filter(
        MonthlySummary.user_id  == user_id,
        MonthlySummary.year     == year,
        MonthlySummary.month    == month,
        MonthlySummary.category == category,
    ).first()

    if row:
        row.amount = max((row.amount or 0) + amount_delta, 0)
        row.updated_at = datetime.utcnow()
    else:
        db.add(MonthlySummary(
            summary_id = TSID.create(),
            user_id    = user_id,
            year       = year,
            month      = month,
            category   = category,
            amount     = max(amount_delta, 0),
        ))

    db.flush()
    all_rows = db.query(MonthlySummary).filter(
        MonthlySummary.user_id == user_id,
        MonthlySummary.year    == year,
        MonthlySummary.month   == month,
    ).all()

    total = sum(r.amount or 0 for r in all_rows)
    if total > 0:
        for r in all_rows:
            r.ratio = round((r.amount or 0) / total * 100, 2)


def _update_goal_total(db, user_id, year, month):
    goal_month = date(year, month, 1)
    goal = db.query(Goal).filter(
        Goal.user_id    == user_id,
        Goal.goal_month == goal_month,
    ).first()

    if goal:
        all_weekly = db.query(WeeklyExpense).filter(
            WeeklyExpense.user_id == user_id,
            WeeklyExpense.year    == year,
            WeeklyExpense.month   == month,
        ).all()
        goal.total_expense = sum(w.amount or 0 for w in all_weekly)
        logger.info(f"[BudgetConsumer] goal total_expense 업데이트 - total={goal.total_expense}")
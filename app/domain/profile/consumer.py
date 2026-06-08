# app/domain/budget/consumer.py
import json
import logging
from datetime import date
from sqlalchemy.orm import Session
from app.core.config.database import SessionLocal
from app.domain.report.entity import WeeklyExpense, MonthlySummary
from app.core.utils.tsid import TSID

logger = logging.getLogger(__name__)


async def handle_budget_event(body: str):
    logger.info(f"[BudgetConsumer] 수신된 body: {body[:200]}")
    try:
        data = json.loads(body.strip())
    except json.JSONDecodeError:
        logger.exception(f"[BudgetConsumer] JSON 파싱 실패 - body={repr(body[:100])}")
        raise

    user_id    = data.get("userId")
    year       = data.get("year")
    month      = data.get("month")
    week       = data.get("weekOfMonth")
    start_date = data.get("startDate")
    end_date   = data.get("endDate")
    category   = data.get("category")
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

        db.commit()
        logger.info(f"[BudgetConsumer] 처리 완료 - user_id={user_id}, eventType={event_type}")

    except Exception as e:
        db.rollback()
        logger.error(f"[BudgetConsumer] DB 저장 실패 - error={e}")
        raise
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
    else:
        db.add(MonthlySummary(
            summary_id = TSID.create(),
            user_id    = user_id,
            year       = year,
            month      = month,
            category   = category,
            amount     = max(amount_delta, 0),
        ))
        
async def handle_budget_event(body: str):
    logger.info(f"[BudgetConsumer] 수신된 body: {body[:200]}")
    try:
        data = json.loads(body.strip())
    except json.JSONDecodeError:
        logger.exception(f"[BudgetConsumer] JSON 파싱 실패 - body={repr(body[:100])}")
        raise

    user_id    = data.get("userId")
    year       = data.get("year")
    month      = data.get("month")
    week       = data.get("weekOfMonth")
    start_date = data.get("startDate")
    end_date   = data.get("endDate")
    category   = data.get("category")
    amount     = int(data.get("amount", 0))
    event_type = data.get("eventType")

    if not all([user_id, year, month, week, category, event_type]):
        logger.error(f"[BudgetConsumer] 필수 필드 누락 - data={data}")
        raise ValueError("필수 필드 누락")

    from app.domain.report.entity import WeeklyExpense, MonthlySummary
    from app.core.utils.tsid import TSID
    from datetime import date as date_type

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

        db.commit()
        logger.info(f"[BudgetConsumer] 처리 완료 - user_id={user_id}, eventType={event_type}")

    except Exception as e:
        db.rollback()
        logger.error(f"[BudgetConsumer] DB 저장 실패 - error={e}")
        raise
    finally:
        db.close()


def _upsert_weekly(db, user_id, year, month, week, start_date, end_date, amount_delta):
    from app.domain.report.entity import WeeklyExpense
    from app.core.utils.tsid import TSID
    from datetime import date as date_type

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
            start_date = date_type.fromisoformat(start_date) if start_date else None,
            end_date   = date_type.fromisoformat(end_date) if end_date else None,
            amount     = max(amount_delta, 0),
        ))


def _upsert_category(db, user_id, year, month, category, amount_delta):
    from app.domain.report.entity import MonthlySummary
    from app.core.utils.tsid import TSID

    row = db.query(MonthlySummary).filter(
        MonthlySummary.user_id  == user_id,
        MonthlySummary.year     == year,
        MonthlySummary.month    == month,
        MonthlySummary.category == category,
    ).first()

    if row:
        row.amount = max((row.amount or 0) + amount_delta, 0)
    else:
        db.add(MonthlySummary(
            summary_id = TSID.create(),
            user_id    = user_id,
            year       = year,
            month      = month,
            category   = category,
            amount     = max(amount_delta, 0),
        ))
# app/domain/budget/consumer.py
import json
import logging
from datetime import date
from sqlalchemy.orm import Session
from app.core.config.database import SessionLocal
from app.domain.report.entity import WeeklyExpense, MonthlySummary, Goal
from app.core.utils.tsid import TSID
from datetime import datetime

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

    # handle_budget_event 안에서 category 변환
    category = CATEGORY_KO_MAP.get(data.get("category", "").upper(), data.get("category", "기타"))
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

        # goal total_expense 업데이트
        _update_goal_total(db, user_id, year, month)

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
        row.updated_at = datetime.utcnow()  # 명시적 추가

    else:
        db.add(MonthlySummary(
            summary_id = TSID.create(),
            user_id    = user_id,
            year       = year,
            month      = month,
            category   = category,
            amount     = max(amount_delta, 0),
        ))

    # ratio 재계산
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
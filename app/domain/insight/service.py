# app/domain/insight/service.py
import logging
import calendar
from datetime import date
from typing import Optional

from sqlalchemy.orm import Session

from app.domain.report.repository import ReportRepository
from app.domain.insight.schema import (
    InsightResponse,
    WeeklyExpenseItem,
    CategoryExpenseItem,
    InsightCardItem,
)
from app.core.client.llm_client import llm_client

logger = logging.getLogger(__name__)


class InsightService:
    def __init__(self, db: Session):
        self.repo = ReportRepository(db)

    def get_insights(self, user_id: str) -> InsightResponse:
        """
        AI 인사이트 전체 조회.
        - 주간 BarChart
        - 카테고리 도넛차트
        - 인사이트 카드 최대 4개

        각 구성 요소는 독립적으로 실패해도 나머지는 정상 반환.
        """
        today = date.today()

        weekly_expenses   = self.repo.find_weekly_expenses_current_month(user_id)
        monthly_summaries = self.repo.find_monthly_summary_current_month(user_id)

        weeks = [
            WeeklyExpenseItem(
                week       = f"{w.week}주",
                amount     = w.amount or 0,
                start_date = w.start_date,
                end_date   = w.end_date,
            )
            for w in weekly_expenses
        ]

        categories = [
            CategoryExpenseItem(
                category = s.category or "기타",
                amount   = s.amount or 0,
                ratio    = float(s.ratio or 0),
            )
            for s in monthly_summaries
        ]

        insights = []

        weekly_card = self._build_weekly_trend_card(weekly_expenses)
        if weekly_card:
            insights.append(weekly_card)

        overspend_card = self._build_overspend_card(monthly_summaries)
        if overspend_card:
            insights.append(overspend_card)

        peer_card = self._build_peer_compare_card(user_id, monthly_summaries)
        if peer_card:
            insights.append(peer_card)

        goal_card = self._build_goal_status_card(user_id, today)
        if goal_card:
            insights.append(goal_card)

        return InsightResponse(
            year       = today.year,
            month      = today.month,
            weeks      = weeks,
            categories = categories,
            insights   = insights,
        )

    # =============================================
    # 카드 1: 지난주 대비 증감
    # =============================================
    def _build_weekly_trend_card(self, weekly_expenses: list) -> Optional[InsightCardItem]:
        """주간 데이터 2개 미만이면 None 반환."""
        try:
            if len(weekly_expenses) < 2:
                return None

            latest   = weekly_expenses[-1]
            prev     = weekly_expenses[-2]
            diff     = (latest.amount or 0) - (prev.amount or 0)
            diff_pct = int(abs(diff) / prev.amount * 100) if prev.amount > 0 else 0

            if diff < 0:
                return InsightCardItem(
                    insight_type = "weekly_trend",
                    title        = f"{latest.week}주차 지출이 줄었어요",
                    description  = (
                        f"지난주({prev.week}주차 {(prev.amount or 0):,}원)보다 {diff_pct}% 줄었어요. "
                        f"절약한 금액은 {abs(diff):,}원이에요. "
                        f"이 추세라면 이번 달 목표 달성도 충분히 가능해요!"
                    ),
                    icon_type    = "TrendingDown",
                    accent_color = "#3182F6",
                    metric_value = f"{diff_pct}%",
                )
            else:
                return InsightCardItem(
                    insight_type = "weekly_trend",
                    title        = f"{latest.week}주차 지출 주의",
                    description  = (
                        f"지난주({prev.week}주차 {(prev.amount or 0):,}원)보다 {diff_pct}% 늘었어요. "
                        f"늘어난 금액은 {abs(diff):,}원이에요. "
                        f"이번 주는 조금만 더 아껴볼까요?"
                    ),
                    icon_type    = "TrendingUp",
                    accent_color = "#F43F5E",
                    metric_value = f"{diff_pct}%",
                )
        except Exception as e:
            logger.error(f"[InsightService] 주간 트렌드 카드 생성 실패 - error={e}")
            return None

    # =============================================
    # 카드 2: 과소비 경고
    # =============================================
    def _build_overspend_card(self, monthly_summaries: list) -> Optional[InsightCardItem]:
        """
        가장 높은 카테고리 경고.
        LLM 실패 시 기본 문구로 대체.
        """
        try:
            if not monthly_summaries:
                return None

            top   = monthly_summaries[0]  # amount 내림차순 정렬되어 있음
            ratio = float(top.ratio or 0)

            try:
                description = llm_client.generate_overspend_message(
                    category = top.category,
                    amount   = top.amount,
                    ratio    = ratio,
                )
            except Exception:
                # LLM 실패 시 기본 문구로 대체 (서비스 중단 없음)
                description = f"이번 달 {top.category} 지출이 전체의 {ratio:.0f}%를 차지하고 있어요."

            return InsightCardItem(
                insight_type = "overspend",
                title        = f"{top.category} 지출 주의",
                description  = description,
                icon_type    = "TrendingUp",
                accent_color = "#F43F5E",
                metric_value = f"{ratio:.0f}%",
            )
        except Exception as e:
            logger.error(f"[InsightService] 과소비 카드 생성 실패 - error={e}")
            return None

    # =============================================
    # 카드 3: 또래 비교
    # =============================================
    def _build_peer_compare_card(self, user_id: str, monthly_summaries: list) -> Optional[InsightCardItem]:
        """
        또래 그룹 평균과 나의 지출 비교.
        또래 그룹 5명 미만이면 None 반환.
        """
        try:
            peer_avgs = self.repo.find_peer_avg_by_category(user_id)
            if not peer_avgs or not monthly_summaries:
                return None

            my_map = {s.category: (s.amount or 0) for s in monthly_summaries}

            diffs = []
            for peer in peer_avgs:
                my_amount   = my_map.get(peer["category"], 0)
                peer_amount = peer["avg_amount"]
                if peer_amount > 0:
                    diff_pct = int((my_amount - peer_amount) / peer_amount * 100)
                    diffs.append({
                        "category": peer["category"],
                        "diff_pct": diff_pct,
                    })

            if not diffs:
                return None

            biggest  = max(diffs, key=lambda x: abs(x["diff_pct"]))
            diff_pct = biggest["diff_pct"]

            if diff_pct < 0:
                return InsightCardItem(
                    insight_type = "peer_compare",
                    title        = "또래 대비 우수한 절약",
                    description  = f"{biggest['category']} 지출이 또래보다 {abs(diff_pct)}% 적어요. 잘 관리하고 있어요!",
                    icon_type    = "Users",
                    accent_color = "#10B981",
                    metric_value = f"{abs(diff_pct)}% 절약",
                )
            else:
                return InsightCardItem(
                    insight_type = "peer_compare",
                    title        = "또래 대비 지출 높음",
                    description  = f"{biggest['category']} 지출이 또래보다 {diff_pct}% 많아요. 조금 줄여볼까요?",
                    icon_type    = "Users",
                    accent_color = "#F59E0B",
                    metric_value = f"{diff_pct}% 초과",
                )
        except Exception as e:
            logger.error(f"[InsightService] 또래 비교 카드 생성 실패 - error={e}")
            return None

    # =============================================
    # 카드 4: 목표 달성 가능 여부
    # =============================================
    def _build_goal_status_card(self, user_id: str, today: date) -> Optional[InsightCardItem]:
        """
        목표 달성 가능 여부 판단.
        목표 미설정이면 None 반환.

        분기:
        - remain_budge < 0         → 초과 (빨간 카드)
        - remain_budge >= 0, 월말  → 달성 성공 (초록 카드)
        - remain_budge >= 0, 남은 일 있음 → 달성 가능 (초록 카드)
        """
        try:
            goal = self.repo.find_goal_current_month(user_id)
            if not goal or not goal.goal_expense:
                return None

            total_expense    = goal.total_expense or 0
            remain_budge     = goal.goal_expense - total_expense
            remain_days      = calendar.monthrange(today.year, today.month)[1] - today.day
            achievement_rate = int(total_expense / goal.goal_expense * 100)

            if remain_budge < 0:
                return InsightCardItem(
                    insight_type = "goal_status",
                    title        = "이번 달 목표 못 지켰어요",
                    description  = f"이번 달 {abs(remain_budge):,}원을 초과했어요. 설정 목표: {goal.goal_expense:,}원, 실제 지출: {total_expense:,}원",
                    icon_type    = "Target",
                    accent_color = "#F43F5E",
                    metric_value = f"{achievement_rate}% 달성",
                )
            elif remain_days == 0:
                # 월말 + 예산 초과 아님 → 달성 성공
                return InsightCardItem(
                    insight_type = "goal_status",
                    title        = "이번 달 목표 달성 성공!",
                    description  = f"이번 달 목표를 지켰어요. 남은 예산 {remain_budge:,}원 절약 성공!",
                    icon_type    = "Target",
                    accent_color = "#10B981",
                    metric_value = f"{achievement_rate}% 달성",
                )
            else:
                # 예산 남아있고 날도 남아있음 → 달성 가능
                daily_budge = int(remain_budge / remain_days)
                return InsightCardItem(
                    insight_type = "goal_status",
                    title        = "이번 달 목표 달성 가능",
                    description  = f"하루 {daily_budge:,}원만 지키면 목표 달성이에요! 남은 예산 {remain_budge:,}원",
                    icon_type    = "Target",
                    accent_color = "#10B981",
                    metric_value = f"{achievement_rate}% 달성",
                )
        except Exception as e:
            logger.error(f"[InsightService] 목표 달성 카드 생성 실패 - error={e}")
            return None
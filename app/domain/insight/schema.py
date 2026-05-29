# app/domain/insight/schema.py
from pydantic import BaseModel
from typing import Optional, List
from datetime import date


# =============================================
# GET /api/ai/insights
# AI 인사이트 전체 (AI-03 ~ AI-06)
# =============================================

class WeeklyExpenseItem(BaseModel):
    """주차별 BarChart 단건."""
    week: str        # "1주", "2주", "3주", "4주"
    amount: int
    start_date: date
    end_date: date

    class Config:
        from_attributes = True
        populate_by_name = True


class CategoryExpenseItem(BaseModel):
    """카테고리별 도넛차트 단건."""
    category: str
    amount: int
    ratio: float     # ex) 37.0 = 37%

    class Config:
        from_attributes = True
        populate_by_name = True


class InsightCardItem(BaseModel):
    """인사이트 카드 단건."""
    insight_type: str               # "weekly_trend", "overspend", "peer_compare", "goal_status"
    title: str
    description: str
    icon_type: str                  # "TrendingDown", "TrendingUp", "Users", "Target"
    accent_color: str               # hex 코드
    metric_value: Optional[str] = None  # 강조 수치 ex) "18%", "30% 절약"

    class Config:
        from_attributes = True
        populate_by_name = True


class InsightResponse(BaseModel):
    """
    인사이트 전체 응답.
    - weeks: 주간 지출 BarChart
    - categories: 카테고리별 도넛차트
    - insights: 인사이트 카드 (최대 4개)
    """
    year: int
    month: int
    weeks: List[WeeklyExpenseItem]
    categories: List[CategoryExpenseItem]
    insights: List[InsightCardItem]
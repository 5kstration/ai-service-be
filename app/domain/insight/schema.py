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

# =============================================
# AI 리포트 탭 진입 상태 체크 응답
# GET /api/ai/report/status
# 클라이언트가 탭 진입 시 가장 먼저 호출.
# profile_required=True면 프로필 입력 화면으로 이동.
# goal_required=True면 목표 설정 화면으로 이동.
# =============================================
class ReportEntryStatusResponse(BaseModel):
    profile_required: bool  # True: 월소득/생년월일/성별 입력 필요
    goal_required: bool     # True: 이번 달 목표 설정 필요
    is_ready: bool          # True: 프로필·목표 모두 완료 → 리포트 조회 가능


# =============================================
# GET /api/ai/report/profile
# 현재 프로필에서 비어있는 필드 조회
# 프론트가 이 응답을 보고 어떤 입력 필드를 보여줄지 결정
# =============================================
class ProfileMissingFieldsResponse(BaseModel):
    """비어있는 필드 목록 + 현재 저장값."""
    monthly_income_missing: bool          # True: 월소득 입력 필요
    birth_missing: bool                   # True: 생년월일 입력 필요
    sex_missing: bool                     # True: 성별 입력 필요
    # 이미 저장된 값 (None이면 미입력)
    monthly_income: Optional[int] = None
    birth: Optional[date] = None
    sex: Optional[str] = None

    class Config:
        from_attributes = True
        populate_by_name = True


# =============================================
# POST /api/ai/report/profile
# 월소득/생년월일/성별 입력 API (온보딩 스킵 유저 대상)
# 보내지 않은 필드(None)는 기존 저장값 유지
# =============================================
class ProfileSetupRequest(BaseModel):
    monthly_income: Optional[int] = None  # None이면 기존값 유지
    birth: Optional[date] = None          # None이면 기존값 유지 (YYYY-MM-DD)
    sex: Optional[str] = None             # None이면 기존값 유지 ("남자" | "여자")

    class Config:
        populate_by_name = True


class ProfileSetupResponse(BaseModel):
    user_id: str
    monthly_income: Optional[int] = None   # 저장된 최종 월소득
    birth: Optional[date] = None           # 저장된 최종 생년월일
    sex: Optional[str] = None             # 저장된 최종 성별
    goal_required: bool                    # 저장 후 목표 설정이 아직 필요한지 여부
    updated_fields: list[str] = []         # 이번 요청에서 실제 업데이트된 필드 목록

    class Config:
        from_attributes = True
        populate_by_name = True


# =============================================
# POST /api/ai/report/goal
# 이번 달 목표 지출액 설정 API
# =============================================
class GoalSetupRequest(BaseModel):
    goal_expense: int           # 목표 지출액 (원 단위, 1 이상)

    class Config:
        populate_by_name = True


class GoalSetupResponse(BaseModel):
    goal_id: str
    goal_month: date            # 설정된 목표 월 (해당 월 1일로 저장)
    goal_expense: int           # 목표 지출액

    class Config:
        from_attributes = True
        populate_by_name = True
# app/domain/report/schema.py
from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime, date


# =============================================
# GET /api/ai/report
# =============================================
class ReportResponse(BaseModel):
    report_id: str
    year: int
    month: int
    day: int
    summary_message: Optional[str] = None
    total_expense: Optional[int] = None
    target_expense: Optional[int] = None
    achievement_rate: Optional[int] = None
    remain_budge: Optional[int] = None
    remain_days: Optional[int] = None
    daily_budge: Optional[int] = None
    saving_tip: Optional[str] = None
    created_at: Optional[datetime] = None

    class Config:
        from_attributes = True
        populate_by_name = True


# =============================================
# GET /api/ai/report/peers-comparison
# =============================================
class PeerCategoryItem(BaseModel):
    category: str
    my_amount: int
    peer_avg_amount: int
    diff_amount: int
    diff_rate: int

    class Config:
        from_attributes = True
        populate_by_name = True


class PeersComparisonResponse(BaseModel):
    year: int
    month: int
    categories: List[PeerCategoryItem]
    best_saving_category: Optional[str] = None
    best_saving_amount: Optional[int] = None

    class Config:
        populate_by_name = True


# =============================================
# GET /api/ai/report/status
# =============================================
class ReportEntryStatusResponse(BaseModel):
    profile_required: bool
    goal_required: bool
    is_ready: bool


# =============================================
# GET /api/ai/report/profile
# =============================================
class ProfileMissingFieldsResponse(BaseModel):
    monthly_income_missing: bool
    birth_missing: bool
    sex_missing: bool
    monthly_income: Optional[int] = None
    birth: Optional[date] = None
    sex: Optional[str] = None

    class Config:
        from_attributes = True
        populate_by_name = True


# =============================================
# POST /api/ai/report/profile
# =============================================
class ProfileSetupRequest(BaseModel):
    monthly_income: Optional[int] = None
    birth: Optional[date] = None
    sex: Optional[str] = None

    class Config:
        populate_by_name = True


class ProfileSetupResponse(BaseModel):
    user_id: str
    monthly_income: Optional[int] = None
    birth: Optional[date] = None
    sex: Optional[str] = None
    goal_required: bool
    updated_fields: List[str] = []

    class Config:
        from_attributes = True
        populate_by_name = True


# =============================================
# POST /api/ai/report/goal
# =============================================
class GoalSetupRequest(BaseModel):
    goal_expense: int

    class Config:
        populate_by_name = True


class GoalSetupResponse(BaseModel):
    goal_id: str
    goal_month: date
    goal_expense: int

    class Config:
        from_attributes = True
        populate_by_name = True
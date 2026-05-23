# app/domain/recommend/schema.py
from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime


# =============================================
# 공통
# =============================================

class BenefitItem(BaseModel):
    label: str
    value: str


# =============================================
# GET /api/recommend/policies
# 청년 정책 추천 목록
# =============================================

class PolicyListItem(BaseModel):
    policy_id:      str
    title:          str
    org:            str
    category:       str
    category_color: str
    deadline:       str
    dday:           int
    tags:           List[str]
    is_bookmarked:  bool = False

    class Config:
        from_attributes = True
        populate_by_name = True


class PolicyListResponse(BaseModel):
    policies:    List[PolicyListItem]
    total_count: int
    has_next:    bool


# =============================================
# GET /api/recommend/policies/{policyId}
# 청년 정책 상세
# =============================================

class PolicyDetailResponse(BaseModel):
    policy_id:             str
    title:                 str
    org:                   str
    category:              str
    category_color:        str
    deadline:              str
    dday:                  int
    tags:                  List[str]
    is_bookmarked:         bool = False
    age_min:               Optional[int]   = None
    age_max:               Optional[int]   = None
    income_condition:      Optional[str]   = None
    employment_condition:  Optional[str]   = None
    education_condition:   Optional[str]   = None
    application_period:    Optional[str]   = None
    description:           Optional[str]   = None
    apply_url:             Optional[str]   = None
    ai_recommend_reason:   Optional[str]   = None

    class Config:
        from_attributes = True
        populate_by_name = True



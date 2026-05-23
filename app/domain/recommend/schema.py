# app/domain/recommend/schema.py
from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime
from typing import Literal


class BenefitItem(BaseModel):
    label: str
    value: str


# =============================================
# GET /api/recommend/policies
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


# =============================================
# GET /api/recommend/insurances
# =============================================

class InsuranceItem(BaseModel):
    recommend_id:   str
    insurer:        str
    insurance_name: str
    top_benefit:    str
    benefits:       List[BenefitItem]
    match_reason:   str
    accent_color:   str
    apply_url:      Optional[str] = None
    is_bookmarked:  bool = False

    class Config:
        from_attributes = True
        populate_by_name = True


class InsuranceListResponse(BaseModel):
    recommended_at: Optional[datetime] = None
    insurances:     List[InsuranceItem]


# =============================================
# GET /api/recommend/cards
# =============================================

class CardItem(BaseModel):
    recommend_id:  str
    company:       str
    card_name:     str
    top_benefit:   str
    benefits:      List[BenefitItem]
    match_reason:  str
    accent_color:  str
    apply_url:     Optional[str] = None
    is_bookmarked: bool = False

    class Config:
        from_attributes = True
        populate_by_name = True


class CardListResponse(BaseModel):
    recommended_at: Optional[datetime] = None
    cards:          List[CardItem]


# =============================================
# PATCH /api/recommend/bookmark/patch
# =============================================


class BookmarkRequest(BaseModel):
    category: Literal["policy", "insurance", "card"]
    id: str
    action: Literal["set", "unset"]  
    
class BookmarkResponse(BaseModel):
    bookmark_id:   Optional[str] = None
    category:      str
    id:            str
    is_bookmarked: bool


# =============================================
# GET /api/recommend/bookmarks
# =============================================

class BookmarkPolicyItem(BaseModel):
    policy_id:      str
    title:          str
    org:            str
    category:       str
    category_color: str
    deadline:       str
    dday:           int
    tags:           List[str]
    is_bookmarked:  bool = True

    class Config:
        from_attributes = True
        populate_by_name = True

class BookmarkInsuranceItem(BaseModel):
    recommend_id:   str
    insurer:        str
    insurance_name: str
    top_benefit:    str
    accent_color:   str
    apply_url:      Optional[str] = None
    is_bookmarked:  bool = True
 
    class Config:
        from_attributes = True
        populate_by_name = True
 
 
class BookmarkCardItem(BaseModel):
    recommend_id:  str
    company:       str
    card_name:     str
    top_benefit:   str
    accent_color:  str
    apply_url:     Optional[str] = None
    is_bookmarked: bool = True
 
    class Config:
        from_attributes = True
        populate_by_name = True

class BookmarkListResponse(BaseModel):
    policies:    List[BookmarkPolicyItem]
    insurances:  List[BookmarkInsuranceItem]
    cards:       List[BookmarkCardItem]
    total_count: int
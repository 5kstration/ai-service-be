# app/domain/recommend/schema.py
from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime


# =============================================
# GET /api/recommend/policies
# 청년정책 추천 목록 (rch-01, rch-06)
# =============================================
class RecommendPolicyItem(BaseModel):
    policy_id: str
    title: str
    org: str                # 정책 주관기관 ex) "국토교통부"
    category: str           # 정책 분류 ex) "주거", "금융", "취업"
    category_color: str     # 카테고리 배지 색상 hex 코드
    deadline: str           # 마감일 문자열 ex) "2025.05.31"
    dday: int               # 마감까지 남은 일수 (음수=마감)
    tags: List[str]         # 카드 하단 태그 목록 ex) ["19~34세", "주거 지원"]
    is_bookmarked: bool     # 현재 사용자의 북마크 여부

    class Config:
        from_attributes = True
        populate_by_name = True



# 청년정책 추천 목록 응답       
class RecommendPolicyListResponse(BaseModel):
    policies: List[RecommendPolicyItem]
    total_count: int   # 전체 정책 수
    has_next: bool     # 다음 페이지 존재 여부

    class Config:
        populate_by_name = True


# =============================================
# GET /api/recommend/policies/{policyId}
# 청년정책 상세 (rch-02, rch-07 bottom sheet)
# =============================================

# 정책 상세 응답. RecommendPolicyItem의 확장 버전으로, 상세 설명과 신청 URL 추가.
class RecommendPolicyDetailResponse(BaseModel):
    policy_id: str
    title: str
    org: str
    category: str
    category_color: str
    deadline: str
    dday: int
    tags: List[str]
    is_bookmarked: bool
    age_min: Optional[int]              # 지원 대상 최소 나이
    age_max: Optional[int]              # 지원 대상 최대 나이
    income_condition: Optional[str]     # 소득 조건 ex) "중위소득 150% 이하"
    employment_condition: Optional[str] # 취업 요건
    education_condition: Optional[str]  # 학력 요건
    application_period: Optional[str]   # 신청 기간 ex) "상시 접수"
    description: Optional[str]          # 정책 상세 설명
    apply_url: Optional[str]            # 신청 페이지 URL
    ai_recommend_reason: Optional[str]  # AI가 이 정책을 추천한 사유

    class Config:
        from_attributes = True
        populate_by_name = True


# =============================================
# GET /api/recommend/cards
# 카드 추천 목록 (rch-03, rch-05)
# =============================================
# 카드 추천 단건 데이터
class BenefitItem(BaseModel):
    label: str   # 혜택 항목명 ex) "배달앱", "보장 한도"
    value: str   # 혜택 내용 ex) "10% 할인", "최대 5,000만원"



# 카드 추천 단건 데이터. RecommendCard 테이블의 row 하나에 대응.
class RecommendCardItem(BaseModel):
    recommend_id: str
    card_company: str           # 카드사명 ex) "토스뱅크"
    card_name: str              # 카드명 ex) "토스 바나나카드"
    top_benefit: str            # 핵심 혜택 한 줄 요약 (카드 상단 강조 영역)
    benefits: List[BenefitItem] # 세부 혜택 목록
    match_reason: Optional[str] # AI 추천 사유
    accent_color: str           # 카드 강조색 hex 코드
    apply_url: Optional[str]    # 카드 신청 페이지 URL
    is_bookmarked: bool

    class Config:
        from_attributes = True
        populate_by_name = True



# 카드 추천 목록 전체 응답. recommended_at은 추천 결과가 생성된 시각 (Redis 캐시 TTL 기준점).
class RecommendCardListResponse(BaseModel):
    recommended_at: Optional[datetime]  # 추천 결과 생성 시각
    cards: List[RecommendCardItem]

    class Config:
        populate_by_name = True


# =============================================
# GET /api/recommend/insurances
# 보험 추천 목록 (rch-04, rch-05)
# =============================================
# 보험 추천 단건 데이터. RecommendInsurance 테이블의 row 하나에 대응.
class RecommendInsuranceItem(BaseModel):
    recommend_id: str
    insurer: str                # 보험사명 ex) "라이프플러스"
    insurance_name: str         # 보험 상품명
    top_benefit: str            # 핵심 혜택 한 줄 요약 (상단 강조 영역)
    benefits: List[BenefitItem] # 세부 보장 내역 목록
    match_reason: Optional[str] # AI 추천 사유
    accent_color: str           # 카드 강조색 hex 코드
    apply_url: Optional[str]    # 보험 가입 페이지 URL
    is_bookmarked: bool

    class Config:
        from_attributes = True
        populate_by_name = True


# 보험 추천 목록 전체 응답. recommended_at은 추천 결과가 생성된 시각 (Redis 캐시 TTL 기준점).
class RecommendInsuranceListResponse(BaseModel):
    recommended_at: Optional[datetime]
    insurances: List[RecommendInsuranceItem]

    class Config:
        populate_by_name = True


# =============================================
# PATCH /api/recommend/bookmark/patch
# 북마크 설정/해제 (북마크 아이콘 토글)
# =============================================

# 북마크 토글 요청. category로 카드/보험/정책 구분, id로 대상 식별.
class BookmarkToggleRequest(BaseModel):
    category: str   # "policy" / "card" / "insurance"
    id: str         # 대상 ID (policyId, rec_card_id, rec_ins_id)


# 북마크 토글 응답. bookmark_id는 북마크 생성 시 발급, 삭제 시 null. is_bookmarked로 현재 북마크 상태 반환.
class BookmarkToggleResponse(BaseModel):
    bookmark_id: Optional[str]  # 북마크 생성 시 발급, 삭제 시 null
    category: str
    id: str
    is_bookmarked: bool         # true=등록됨, false=해제됨



# =============================================
# GET /api/recommend/policies/bookmarks
# 북마크한 정책 목록 (rch-06, rch-07)
# =============================================
# 북마크한 정책 아이템. RecommendPolicyItem과 유사하지만, 북마크 ID와 북마크 여부 포함.
class BookmarkedPolicyItem(BaseModel):
    policy_id: str
    title: str
    org: str
    category: str
    category_color: str
    deadline: str
    dday: int
    tags: List[str]
    is_bookmarked: bool  # 북마크 목록이므로 항상 true

    class Config:
        from_attributes = True
        populate_by_name = True



# 북마크한 정책 목록 응답. policies는 북마크한 정책 아이템 리스트, total_count는 전체 북마크한 정책 수.
class BookmarkedPolicyListResponse(BaseModel):
    bookmarks: List[BookmarkedPolicyItem]
    total_count: int

    class Config:
        populate_by_name = True
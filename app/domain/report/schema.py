# app/domain/report/schema.py
from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime, date


# =============================================
# GET /api/ai/report
# AI 리포트 조회 응답
# =============================================
 
# 리포트 응답 스키마. ai_report 테이블의 row 하나에 대응.
class ReportResponse(BaseModel):
    report_id: str
    year: int
    month: int
    day: int
    summary_message: Optional[str] = None   # LLM이 생성한 전체 요약 문구
    total_expense: Optional[int] = None     # 어제까지 누적 총 지출
    target_expense: Optional[int]   = None  # 사용자가 설정한 목표 지출
    achievement_rate: Optional[int]  = None # 목표 대비 달성률 (%)
    remain_budget: Optional[int]     = None  # 목표 지출 - 총 지출 = 남은 예산
    remain_days: Optional[int]      = None  # 이번 달 남은 날짜
    daily_budget: Optional[int]      = None  # 남은 예산 / 남은 날짜 = 오늘 쓸 수 있는 금액
    saving_tip: Optional[str]       = None  # LLM이 생성한 절약 팁
    created_at: Optional[datetime]  = None

    class Config:
        from_attributes = True
        populate_by_name = True


# =============================================
# GET /api/ai/report/peers-comparison
# 또래 비교 데이터 (AI-04 또래 비교 탭)
# =============================================

class PeerCategoryItem(BaseModel):
    """카테고리별 나 vs 또래 비교 단건."""
    category: str        # "식비", "카페", "교통" ...
    my_amount: int       # 나의 지출액
    peer_avg_amount: int # 또래 평균 지출액
    diff_amount: int     # 차이 금액 (양수=초과, 음수=절약)
    diff_rate: int       # 차이 비율 (%) ex) 10 = 10% 초과, -18 = 18% 절약
 
    class Config:
        from_attributes = True
        populate_by_name = True
 
 
class PeersComparisonResponse(BaseModel):
    """또래 비교 전체 응답."""
    year: int
    month: int
    categories: List[PeerCategoryItem]
    best_saving_category: Optional[str] = None  # 가장 많이 절약한 카테고리
    best_saving_amount: Optional[int]   = None  # 절약 금액 (절약한 경우만)
 
    class Config:
        populate_by_name = True

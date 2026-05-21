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
# GET /api/ai/report/weekly-expense
# 주간 지출 데이터 (AI-03 주간 지출 탭 BarChart)
# =============================================

# 주간 지출 단건 스키마. 이번 달 주차별 지출 데이터.
class WeeklyExpenseItem(BaseModel):
    week: str        # "1주", "2주", "3주", "4주"
    amount: int      # 해당 주 총 지출액
    start_date: date # 주 시작일
    end_date: date   # 주 종료일

    class Config:
        from_attributes = True
        populate_by_name = True

# 주간 지출 전체 응답 스키마. 이번 달 전체 주차 지출 리스트 반환.
class WeeklyExpenseResponse(BaseModel):
    year: int
    month: int
    weeks: List[WeeklyExpenseItem]


# =============================================
# GET /api/ai/report/peers-comparison
# 또래 비교 데이터 (AI-04 또래 비교 탭)
# =============================================

# 카테고리별 나의 지출 vs 또래 평균 비교 단건.
# diff_rate 음수 = 또래보다 절약, 양수 = 초과.
class PeerCategoryItem(BaseModel):
    category: str          # 교통, 식비, 카페, 배달앱 ...
    my_amount: int         # 나의 해당 카테고리 지출액
    peer_avg_amount: int   # 또래 그룹 평균 지출액
    diff_rate: int         # 차이 비율 (%) ex) -30 = 30% 절약, 41 = 41% 초과

    class Config:
        populate_by_name = True
        from_attributes = True

# 또래 비교 전체 응답 스키마.
# monthly_summary 집계 + Qdrant 클러스터링 결과 합산.
# 개인 식별 불가 수준의 익명화 집계 데이터만 포함.
class PeersComparisonResponse(BaseModel):
    peer_group_label: str           # 클러스터링된 또래 그룹명 ex) "20대 중반 직장인"
    peer_group_size: int            # 또래 그룹 인원 수
    categories: List[PeerCategoryItem]
    insight_message: Optional[str]  = None # LLM이 생성한 또래 비교 요약 문구

    class Config:
        populate_by_name = True
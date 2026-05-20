# app/domain/report/schema.py
from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime, date


# =============================================
# GET /api/ai/report/yesterday
# AI 전일 기준 리포트 조회 응답 (AI-01, AI-02)
# =============================================


# 전일 기준 리포트 응답 스키마. ai_report 테이블의 row 하나에 대응.
# LLM이 생성한 summary_message, saving_tip과 budget service에서 집계된 지출 데이터가 포함.
class YesterdayReportResponse(BaseModel):
    report_id: str
    year: int
    month: int
    summary_message: Optional[str]    # LLM이 생성한 전체 요약 문구
    total_expense: Optional[int]      # 어제까지 누적 총 지출
    target_expense: Optional[int]     # 사용자가 설정한 목표 지출
    achievement_rate: Optional[int]   # 목표 대비 달성률 (%)
    remain_budge: Optional[int]       # 목표 지출 - 총 지출 = 남은 예산
    remain_days: Optional[int]        # 이번 달 남은 날짜
    daily_budge: Optional[int]        # 남은 예산 / 남은 날짜 = 오늘 쓸 수 있는 금액
    saving_tip: Optional[str]         # LLM이 생성한 절약 팁
    created_at: Optional[datetime]

    class Config:
        from_attributes = True
        populate_by_name = True






# =============================================
# POST /api/ai/report/yesterday
# AI 전일 기준 리포트 생성 요청 (AI-02 버튼 클릭)
# =============================================

# 전일 기준 리포트 생성 요청 스키마. year, month로 어떤 기간의 리포트를 생성할지 지정.
class YesterdayReportRequest(BaseModel):
    year: int
    month: int

# 전일 기준 리포트 생성 응답 스키마. 생성 완료 메시지 전달.
class YesterdayReportGenerateResponse(BaseModel):
    message: str




# =============================================
# GET /api/ai/report/weekly-expense
# 주간 지출 데이터 (AI-03 주간 지출 탭 BarChart)
# =============================================

# 주간 지출 데이터 단건 스키마. 이번 달 1주차, 2주차, 3주차, 4주차별 지출 데이터.
class WeeklyExpenseItem(BaseModel):
    week: str        # "1주", "2주", "3주", "4주"
    amount: int      # 해당 주 총 지출액
    start_date: date # 주 시작일
    end_date: date   # 주 종료일

    class Config:
        from_attributes = True
        populate_by_name = True

# 주간 지출 데이터 전체 응답 스키마. 이번 달 4주차까지의 주간 지출 데이터를 리스트로 전달.
class WeeklyExpenseResponse(BaseModel):
    year: int
    month: int
    weeks: List[WeeklyExpenseItem]





# =============================================
# GET /api/ai/report/peers-comparison
# 또래 비교 데이터 (AI-04 또래 비교 탭)
# =============================================
# 또래 비교 카테고리별 데이터 스키마. 교통, 식비, 카페, 배달앱 등 주요 카테고리별로 나의 지출액, 또래 평균 지출액, 차이 비율을 전달.
class PeerCategoryItem(BaseModel):
    category: str          # 교통, 식비, 카페, 배달앱 ...
    my_amount: int         # 나의 해당 카테고리 지출액
    peer_avg_amount: int   # 또래 그룹 평균 지출액
    diff_rate: int         # 차이 비율 (%) ex) -30 = 30% 절약, 41 = 41% 초과

    class Config:
        populate_by_name = True

# 또래 비교 전체 응답 스키마. 카테고리별 데이터 리스트 + LLM이 생성한 또래 비교 요약 문구 전달.
class PeersComparisonResponse(BaseModel):
    peer_group_label: str           # 클러스터링된 또래 그룹명 ex) "20대 중반 직장인"
    peer_group_size: int            # 또래 그룹 인원 수
    categories: List[PeerCategoryItem]
    insight_message: Optional[str]  # LLM이 생성한 또래 비교 요약 문구

    class Config:
        populate_by_name = True


# =============================================
# POST /api/internal/report/generate
# Internal: budget service → ai service 리포트 생성 위임
# =============================================
class CategoryExpenseItem(BaseModel):
    category: str   # 카테고리명
    amount: int     # 해당 카테고리 총 지출액
    ratio: float    # 전체 지출 대비 비율 ex) 0.21 = 21%

# 전일 대비 증감 데이터 스키마. 어제와 비교했을 때 이번 달 지출이 얼마나 증가/감소했는지 카테고리별로 전달.
class YesterdayDeltaItem(BaseModel):
    category: str       # 카테고리명
    delta_amount: int   # 증감액 (음수=감소, 양수=증가)
    delta_rate: float   # 증감률 ex) -0.18 = 18% 감소, 0.41 = 41% 증가

# 주간 지출 데이터 스키마. 이번 달 1주차, 2주차, 3주차, 4주차별 지출 데이터 전달.
class WeeklyExpenseRawItem(BaseModel):
    week: int          # 주차 숫자 ex) 1, 2, 3, 4
    amount: int
    start_date: date
    end_date: date

# 또래 그룹 비교용 원시 데이터 스키마. 카테고리별로 나의 지출액과 또래 평균 지출액 전달.
class PeerGroupRawItem(BaseModel):
    category: str
    peer_avg_amount: int

# 리포트 생성 요청 스키마. budget service에서 집계된 지출 데이터와 사용자 온보딩 데이터를 전달받아 ai_report와 ai_insight 생성에 사용.
class InternalReportGenerateRequest(BaseModel):
    masked_user_id: str                           # 비식별화된 사용자 ID (해시값)
    year: int
    month: int
    total_expense: int                            # 어제까지 누적 총 지출
    target_expense: int                           # 목표 지출
    category_expenses: List[CategoryExpenseItem]
    yesterday_deltas: List[YesterdayDeltaItem]    # 전일 기준 전월 대비 증감
    weekly_expenses: List[WeeklyExpenseRawItem]
    peer_group_raw: List[PeerGroupRawItem]
    peer_group_label: str                         # 클러스터링된 또래 그룹명
    onboarding_age: int                           # 온보딩 나이
    onboarding_income_level: str                  # 소득 수준 ex) "MID", "LOW", "HIGH"

# 리포트 생성 응답 스키마. 생성 완료 메시지 전달.
class InternalReportGenerateResponse(BaseModel):
    message: str
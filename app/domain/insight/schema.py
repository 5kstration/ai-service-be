# app/domain/insight/schema.py
from pydantic import BaseModel
from typing import Optional
from datetime import datetime


# =============================================
# GET /api/ai/insights
# AI 인사이트 목록 (AI-05, AI-06 하단 카드 섹션)
# =============================================
# AI 인사이트 항목 스키마.  각 인사이트 카드의 정보를 담는 모델
class InsightItem(BaseModel):
    insight_id: str
    report_id: Optional[str]        # 연결된 리포트 ID
    insight_type: str               # InsightType enum ex) "월별 분석", "카드 추천"
    insight_title: str              # 카드 제목 ex) "카페 지출 줄었어요"
    description: Optional[str]      # 카드 본문 설명
    icon_type: Optional[str]        # 프론트 아이콘 컴포넌트명 ex) TrendingDown, TrendingUp, Users
    accent_color: Optional[str]     # 카드 강조색 hex 코드 ex) "#3182F6"
    created_at: Optional[datetime]

    class Config:
        from_attributes = True
        populate_by_name = True

# AI 인사이트 목록 응답 스키마.
class InsightListResponse(BaseModel):
    insights: list[InsightItem]


# =============================================
# 인사이트 생성 (내부용 - ai service 내부 생성 시)
# =============================================

# AI 인사이트 생성 요청 스키마.
class InsightCreate(BaseModel):
    user_id: str
    report_id: Optional[str] = None
    insight_type: str
    insight_title: str
    description: Optional[str] = None
    icon_type: Optional[str] = None
    accent_color: Optional[str] = None
from pydantic import BaseModel
from typing import Optional
from datetime import datetime

# Request DTO
class ReportGenerateRequest(BaseModel):
    year: int
    month: int

# Response DTO
class MonthlyReportResponse(BaseModel):
    insightId: str
    year: int
    month: int
    summaryMessage: str
    totalExpense: int
    targetExpense: int
    achievementRate: int
    createdAt: datetime
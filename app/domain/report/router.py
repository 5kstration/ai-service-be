from fastapi import APIRouter, Depends
from app.domain.report.schema import ReportGenerateRequest, MonthlyReportResponse
from app.domain.report.service import ReportService
from app.core.common.response import CommonResponse
from app.core.middleware.auth import get_current_user

router = APIRouter()
report_service = ReportService()

@router.get("/report/monthly", response_model=CommonResponse[MonthlyReportResponse])
async def get_monthly_report(
    year: int,
    month: int,
    user_id: str = Depends(get_current_user)
):
    data = report_service.get_monthly_report(user_id, year, month)
    return CommonResponse.success(data=data)

@router.post("/report/monthly", response_model=CommonResponse)
async def generate_monthly_report(
    request: ReportGenerateRequest,
    user_id: str = Depends(get_current_user)
):
    report_service.generate_report(user_id, request.year, request.month)
    return CommonResponse.success(
        data={"message": "AI 리포트 생성이 요청되었습니다. 완료 시 알림을 보내드려요."}
    )
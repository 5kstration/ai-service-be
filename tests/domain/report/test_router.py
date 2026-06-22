from unittest.mock import patch
from app.domain.report.schema import ReportEntryStatusResponse

def test_get_report_status(client):
    """
    GET /api/ai/report/status 호출 시 ReportService의 check_entry_status가 올바르게 반환되는지 확인
    """
    with patch("app.domain.report.router.ReportService") as MockService:
        mock_instance = MockService.return_value
        mock_instance.check_entry_status.return_value = ReportEntryStatusResponse(
            profile_required=True,
            goal_required=False,
            is_ready=False
        )
        
        response = client.get("/api/ai/report/status")
        
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["data"]["profile_required"] is True
        assert data["data"]["is_ready"] is False

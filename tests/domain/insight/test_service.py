from unittest.mock import MagicMock, patch
from app.domain.insight.service import InsightService

@patch("app.domain.insight.service.llm_client")
def test_get_insights_overspend_mocked(mock_llm):
    """
    InsightService.get_insights 호출 시 LLM 클라이언트가 Mocking된 상태에서 과소비 카드가 잘 생성되는지 검증
    """
    mock_db = MagicMock()
    service = InsightService(mock_db)
    
    # Mock Repository
    mock_repo = MagicMock()
    # 빈 리스트를 반환하게 하여 다른 카드는 안 만들어지게 하고, 월별 요약만 데이터를 줌
    mock_repo.find_weekly_expenses_current_month.return_value = []
    
    # 임의의 MonthlySummary 객체 흉내
    class MockSummary:
        category = "식비"
        amount = 500000
        ratio = 50.0

    mock_repo.find_monthly_summary_current_month.return_value = [MockSummary()]
    mock_repo.find_peer_avg_by_category.return_value = []
    mock_repo.find_goal_current_month.return_value = None
    
    service.repo = mock_repo
    
    # Mock LLM Response
    mock_llm.generate_overspend_message.return_value = "식비 지출이 너무 많습니다!"
    
    response = service.get_insights("test_user")
    
    assert response is not None
    assert len(response.categories) == 1
    assert response.categories[0].category == "식비"
    
    # Insights(카드) 검증
    assert len(response.insights) == 1
    overspend_card = response.insights[0]
    assert overspend_card.insight_type == "overspend"
    assert overspend_card.title == "식비 지출 주의"
    assert overspend_card.description == "식비 지출이 너무 많습니다!"
    assert overspend_card.metric_value == "50%"

def test_get_insights_llm_failure_fallback():
    """
    LLM 호출이 실패했을 때 기본 문구로 Fallback 되는지 검증
    """
    with patch("app.domain.insight.service.llm_client") as mock_llm:
        mock_db = MagicMock()
        service = InsightService(mock_db)
        
        mock_repo = MagicMock()
        mock_repo.find_weekly_expenses_current_month.return_value = []
        
        class MockSummary:
            category = "쇼핑"
            amount = 300000
            ratio = 30.0

        mock_repo.find_monthly_summary_current_month.return_value = [MockSummary()]
        mock_repo.find_peer_avg_by_category.return_value = []
        mock_repo.find_goal_current_month.return_value = None
        service.repo = mock_repo
        
        # LLM Exception
        mock_llm.generate_overspend_message.side_effect = Exception("LLM Error")
        
        response = service.get_insights("test_user")
        
        assert len(response.insights) == 1
        overspend_card = response.insights[0]
        # Fallback 문구가 잘 들어갔는지 확인
        assert "이번 달 쇼핑 지출이 전체의 30%를 차지하고 있어요." in overspend_card.description

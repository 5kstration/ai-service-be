from unittest.mock import patch
from app.domain.recommend.schema import (
    CardListResponse, InsuranceListResponse, PolicyListResponse
)

def test_get_insurances(client):
    """
    GET /api/recommend/insurances 호출 시 RecommendService.get_insurances가 올바르게 반환되는지 확인
    """
    with patch("app.domain.recommend.router.RecommendService") as MockService:
        mock_instance = MockService.return_value
        mock_instance.get_insurances.return_value = InsuranceListResponse(
            insurances=[
                {
                    "recommend_id": "ins_1",
                    "insurer": "테스트 보험사",
                    "insurance_name": "테스트 보험",
                    "top_benefit": "최대 10% 할인",
                    "benefits": [{"label": "할인", "value": "10%"}],
                    "match_reason": "테스트 추천 사유",
                    "accent_color": "#FF0000"
                }
            ]
        )
        
        response = client.get("/api/recommend/insurances")
        
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert "insurances" in data["data"]
        assert len(data["data"]["insurances"]) == 1
        assert data["data"]["insurances"][0]["recommend_id"] == "ins_1"

def test_get_cards(client):
    """
    GET /api/recommend/cards 호출 시 RecommendService.get_cards 검증
    """
    with patch("app.domain.recommend.router.RecommendService") as MockService:
        mock_instance = MockService.return_value
        mock_instance.get_cards.return_value = CardListResponse(
            cards=[
                {
                    "recommend_id": "card_1",
                    "company": "테스트 카드사",
                    "card_name": "테스트 카드",
                    "top_benefit": "포인트 적립",
                    "benefits": [{"label": "적립", "value": "5%"}],
                    "match_reason": "테스트 사유",
                    "accent_color": "#0000FF"
                }
            ]
        )
        
        response = client.get("/api/recommend/cards")
        
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["data"]["cards"][0]["recommend_id"] == "card_1"

def test_get_policies(client):
    """
    GET /api/recommend/policies 검증
    """
    with patch("app.domain.recommend.router.RecommendService") as MockService:
        mock_instance = MockService.return_value
        mock_instance.get_policies.return_value = PolicyListResponse(
            policies=[
                {
                    "policy_id": "pol_1",
                    "title": "테스트 정책",
                    "org": "테스트 기관",
                    "category": "일자리",
                    "category_color": "#00FF00",
                    "deadline": "2023-12-31",
                    "dday": 10,
                    "tags": ["청년", "지원"]
                }
            ],
            total_count=1,
            has_next=False
        )
        # Background task 검증을 위해 mock 추가 (last_recommended_at 우회)
        mock_instance.repo.find_last_recommended_at.return_value = None
        
        response = client.get("/api/recommend/policies")
        
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert len(data["data"]["policies"]) == 1
        assert data["data"]["policies"][0]["policy_id"] == "pol_1"

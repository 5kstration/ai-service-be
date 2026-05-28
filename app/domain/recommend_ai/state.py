# app/domain/recommend_ai/state.py
from typing import TypedDict, Optional


class RecommendState(TypedDict):
    # 입력
    user_id: str

    # 1. 프로파일 노드
    user_age:           Optional[int]
    user_sex:           Optional[str]
    user_income:        Optional[int]
    monthly_summary:    list   # [{"category": "식비", "amount": 156000}, ...]

    # 2. 임베딩 노드
    user_embedding: Optional[list]

    # 3. 벡터 검색 노드 (후보군)
    card_candidates:      list
    insurance_candidates: list
    policy_candidates:    list

    # 4. 필터 노드
    filtered_policies: list

    # 4-1. Graph 확장 (Neo4j)
    policy_graph_triples: list  # [{"s":..., "p":..., "o":..., ...}, ...]
    card_graph_triples: list
    insurance_graph_triples: list

    # 5. conflict 노드
    conflict_info: dict  # {policy_id: [conflict_policy_ids]}

    # 6. LLM 추천 노드
    recommended_cards:      list  # [{"product_id": ..., "reason": ...}]
    recommended_insurances: list
    recommended_policies:   list

    # 에러 추적
    error: Optional[str]
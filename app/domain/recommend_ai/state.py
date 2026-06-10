# app/domain/recommend_ai/state.py
from typing import TypedDict, Optional


class RecommendState(TypedDict):
    # 입력
    user_id: str

    # 1. 프로파일 노드
    user_age:           Optional[int]
    user_sex:           Optional[str]
    user_income:        Optional[int]
    monthly_summary:    list

    # 2. 임베딩 노드
    user_embedding: Optional[list]

    # 3. 벡터 검색 노드 (후보군)
    card_candidates:      list
    insurance_candidates: list
    policy_candidates:    list
    insurance_risk_summary: Optional[str]  # 보험 위험도 분석 요약

    # 4. 필터 노드
    filtered_policies: list

    # 4-1. Graph 확장 (Neo4j)
    policy_graph_triples: list
    card_graph_triples: list
    insurance_graph_triples: list

    # 5. conflict 노드
    conflict_info: dict

    # 6. LLM 추천 노드
    recommended_cards:      list
    recommended_insurances: list
    recommended_policies:   list

    # 에러 추적
    error: Optional[str]

    # Ablation Study 플래그
    disable_neo4j:          Optional[bool]
    disable_rerank:         Optional[bool]
    disable_income_filter:  Optional[bool]
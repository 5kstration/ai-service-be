# app/domain/recommend_ai/graph.py
import asyncio
import logging
from langgraph.graph import StateGraph, START, END
from app.domain.recommend_ai.state import RecommendState
from app.domain.recommend_ai.nodes import (
    profile_node, embed_node, vector_search_node,
    filter_node, conflict_node, llm_recommend_node, save_node,
)

logger = logging.getLogger(__name__)


def _has_error(state: RecommendState) -> str:
    return "save" if state.get("error") else "continue"


def build_recommend_graph():
    graph = StateGraph(RecommendState)

    graph.add_node("profile",       profile_node)
    graph.add_node("embed",         embed_node)
    graph.add_node("vector_search", vector_search_node)
    graph.add_node("filter",        filter_node)
    graph.add_node("conflict",      conflict_node)
    graph.add_node("llm",           llm_recommend_node)
    graph.add_node("save",          save_node)

    graph.add_edge(START, "profile")

    # 각 노드마다 에러 감지 → 에러 있으면 save로 스킵
    graph.add_conditional_edges(
        "profile", _has_error,
        {"save": "save", "continue": "embed"},
    )
    graph.add_conditional_edges(
        "embed", _has_error,
        {"save": "save", "continue": "vector_search"},
    )
    graph.add_conditional_edges(
        "vector_search", _has_error,
        {"save": "save", "continue": "filter"},
    )
    graph.add_conditional_edges(
        "filter",
        lambda s: "save" if (s.get("error") or not s.get("filtered_policies")) else "conflict",
        {"conflict": "conflict", "save": "save"},
    )
    graph.add_conditional_edges(
        "conflict", _has_error,
        {"save": "save", "continue": "llm"},
    )
    graph.add_edge("llm",  "save")
    graph.add_edge("save", END)

    return graph.compile()


_recommend_graph = None

def get_recommend_graph():
    global _recommend_graph
    if _recommend_graph is None:
        _recommend_graph = build_recommend_graph()
    return _recommend_graph


async def run_recommend_pipeline(user_id: str) -> dict:
    logger.info(f"[RecommendGraph] 파이프라인 시작 - user_id={user_id}")

    initial_state: RecommendState = {
        "user_id":                user_id,
        "user_age":               None,
        "user_sex":               None,
        "user_income":            None,
        "monthly_summary":        [],
        "user_embedding":         None,
        "card_candidates":        [],
        "insurance_candidates":   [],
        "policy_candidates":      [],
        "filtered_policies":      [],
        "conflict_info":          {},
        "recommended_cards":      [],
        "recommended_insurances": [],
        "recommended_policies":   [],
        "error":                  None,
    }

    try:
        result = await asyncio.wait_for(
            get_recommend_graph().ainvoke(initial_state),
            timeout=60.0,
        )
    except asyncio.TimeoutError:
        logger.error(f"[RecommendGraph] 타임아웃 - user_id={user_id}")
        return {"error": "timeout"}

    if result.get("error"):
        logger.error(f"[RecommendGraph] 실패 - user_id={user_id}, error={result['error']}")
    else:
        logger.info(f"[RecommendGraph] 완료 - user_id={user_id}")

    return result
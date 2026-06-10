# app/domain/recommend_ai/graph.py
import asyncio
import logging
from langgraph.graph import StateGraph, START, END
from app.domain.recommend_ai.state import RecommendState
from app.domain.recommend_ai.nodes import (
    profile_node,
    embed_node,
    vector_search_node,
    rerank_node,
    filter_node,
    graph_expand_node,
    conflict_node,
    llm_recommend_node,
    save_node,
)

logger = logging.getLogger(__name__)


def _has_error(state: RecommendState) -> str:
    return "save" if state.get("error") else "continue"


def build_recommend_graph():
    graph = StateGraph(RecommendState)

    graph.add_node("profile",       profile_node)
    graph.add_node("embed",         embed_node)
    graph.add_node("vector_search", vector_search_node)
    graph.add_node("rerank",        rerank_node)
    graph.add_node("filter",        filter_node)
    graph.add_node("graph_expand",  graph_expand_node)
    graph.add_node("conflict",      conflict_node)
    graph.add_node("llm",           llm_recommend_node)
    graph.add_node("save",          save_node)

    graph.add_edge(START, "profile")

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
        {"save": "save", "continue": "rerank"},
    )
    graph.add_conditional_edges(
        "rerank", _has_error,
        {"save": "save", "continue": "filter"},
    )
    graph.add_conditional_edges(
        "filter",
        lambda s: "save" if s.get("error") else "graph_expand",
        {"graph_expand": "graph_expand", "save": "save"},
    )
    graph.add_conditional_edges(
        "graph_expand", _has_error,
        {"save": "save", "continue": "conflict"},
    )
    graph.add_conditional_edges(
        "conflict", _has_error,
        {"save": "save", "continue": "llm"},
    )
    graph.add_conditional_edges(
        "llm", _has_error,
        {"save": END, "continue": "save"},
    )
    graph.add_edge("save", END)

    return graph.compile()


_recommend_graph = None


def get_recommend_graph():
    global _recommend_graph
    if _recommend_graph is None:
        _recommend_graph = build_recommend_graph()
    return _recommend_graph


async def run_recommend_pipeline(
    user_id: str,
    disable_neo4j: bool = False,
    disable_rerank: bool = False,
    disable_income_filter: bool = False,
) -> dict:
    logger.info(
        f"[RecommendGraph] 파이프라인 시작 - user_id={user_id} "
        f"[neo4j={'OFF' if disable_neo4j else 'ON'} "
        f"rerank={'OFF' if disable_rerank else 'ON'} "
        f"income_filter={'OFF' if disable_income_filter else 'ON'}]"
    )

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
        "insurance_risk_summary": None,  # 추가
        "filtered_policies":      [],
        "policy_graph_triples":   [],
        "card_graph_triples":     [],
        "insurance_graph_triples": [],
        "conflict_info":          {},
        "recommended_cards":      [],
        "recommended_insurances": [],
        "recommended_policies":   [],
        "error":                  None,
        "disable_neo4j":         disable_neo4j,
        "disable_rerank":        disable_rerank,
        "disable_income_filter": disable_income_filter,
    }

    try:
        result = await asyncio.wait_for(
            get_recommend_graph().ainvoke(initial_state),
            timeout=120.0,
        )
    except asyncio.TimeoutError:
        logger.error(f"[RecommendGraph] 타임아웃 - user_id={user_id}")
        return {"error": "timeout"}

    if result.get("error"):
        logger.error(f"[RecommendGraph] 실패 - user_id={user_id}, error={result['error']}")
    else:
        logger.info(f"[RecommendGraph] 완료 - user_id={user_id}")

    return result
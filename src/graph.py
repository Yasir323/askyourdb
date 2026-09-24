from langgraph.graph import END, START, StateGraph
from langgraph.checkpoint.memory import MemorySaver

from src.nodes import (
    execute_sql_node,
    generate_sql_node,
    route_after_execution,
    route_after_semantic_validation,
    route_after_static_validation,
    route_after_summary,
    semantic_validate_sql_node,
    summarize_results_node,
    validate_sql_node
)
from src.states import AnalystState


def build_sql_graph(
    generator,
    validator,
    semantic_validator,
    executor,
    summarizer,
    checkpointer=None,
):
    graph: StateGraph = StateGraph(AnalystState)
    graph.add_node(
        "generate_sql",
        lambda state: generate_sql_node(state, generator),
    )
    graph.add_node(
        "validate_sql",
        lambda state: validate_sql_node(state, validator),
    )
    graph.add_node(
        "semantic_validate_sql",
        lambda state: semantic_validate_sql_node(
            state,
            semantic_validator,
        ),
    )
    graph.add_node(
        "execute_sql",
        lambda state: execute_sql_node(state, executor),
    )
    graph.add_node(
        "summarize_results",
        lambda state: summarize_results_node(state, summarizer),
    )
    graph.add_edge(START, "generate_sql")
    graph.add_edge("generate_sql", "validate_sql")
    graph.add_conditional_edges(
        "validate_sql",
        route_after_static_validation,
        {
            "semantic": "semantic_validate_sql",
            "retry": "generate_sql",
            "failure": END,
        },
    )
    graph.add_conditional_edges(
        "semantic_validate_sql",
        route_after_semantic_validation,
        {
            "success": "execute_sql",
            "retry": "generate_sql",
            "failure": END,
        },
    )
    graph.add_conditional_edges(
        "execute_sql",
        route_after_execution,
        {
            "success": "summarize_results",
            "retry": "generate_sql",
            "failure": END,
        },
    )

    graph.add_conditional_edges(
        "summarize_results",
        route_after_summary,
        {
            "success": END,
            "retry_summary": "summarize_results",
            "failure": END,
        },
    )
    return graph.compile(checkpointer=checkpointer or MemorySaver())

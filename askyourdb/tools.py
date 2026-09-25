from collections.abc import Callable
from dataclasses import dataclass

from langchain_core.tools import StructuredTool


@dataclass(frozen=True)
class ProgressEvent:
    """A pipeline step that is about to run."""

    #: Graph node name: generate_sql, validate_sql, semantic_validate_sql,
    #: execute_sql or summarize_results.
    step: str
    attempt: int
    max_attempts: int
    #: Why the SQL is being rewritten, on generate_sql retries.
    retry_reason: str | None = None


def run_query(
    graph,
    question: str,
    schema_text: str,
    dialect: str,
    *,
    thread_id: str,
    max_attempts: int = 3,
    max_summary_attempts: int = 2,
    on_progress: Callable[[ProgressEvent], None] | None = None,
) -> dict:
    """Run the text-to-SQL graph for one question and return the result dict."""
    initial_state = {
        "question": question,
        "schema": schema_text,
        "dialect": dialect,
        "sql_query": None,
        "error_feedback": None,
        "attempts": 0,
        "max_attempts": max_attempts,
        "rows": None,
        "row_limit": None,
        "execution_error": None,
        "summary": None,
        "summary_error": None,
        "summary_attempts": 0,
        "max_summary_attempts": max_summary_attempts,
    }
    config = {"configurable": {"thread_id": thread_id}}
    if on_progress is None:
        final_state = graph.invoke(initial_state, config=config)
    else:
        # "tasks" mode emits an event with the node's input when it starts.
        for event in graph.stream(initial_state, config, stream_mode="tasks"):
            if "input" in event:
                on_progress(_progress_event(event["name"], event["input"]))
        final_state = graph.get_state(config).values
    return _result(final_state)


def _progress_event(step: str, state: dict) -> ProgressEvent:
    if step == "summarize_results":
        return ProgressEvent(step, state.get("summary_attempts", 0) + 1,
                             state["max_summary_attempts"])
    if step == "generate_sql":
        attempt = state.get("attempts", 0) + 1
        reason = state.get("error_feedback") if attempt > 1 else None
        return ProgressEvent(step, attempt, state["max_attempts"], reason)
    return ProgressEvent(step, state.get("attempts", 0), state["max_attempts"])


def _result(final_state: dict) -> dict:
    query = final_state.get("sql_query")
    summary = final_state.get("summary")
    error = (
        final_state.get("summary_error")
        or final_state.get("execution_error")
        or final_state.get("error_feedback")
    )

    rows = final_state.get("rows") or []
    row_limit = final_state.get("row_limit")
    # Only a limit askyourdb imposed counts; "top 5" asked for 5 rows.
    truncated = row_limit is not None and len(rows) >= row_limit

    if summary is not None:
        # sql_used and row_count come from what actually ran, not from the
        # summarizer's echo of them, which models sometimes get wrong.
        return {
            "success": True,
            "answer": summary.answer,
            "row_count": len(rows),
            "sql_used": query.sql,
            "caveats": summary.caveats,
            "rows": rows,
            "truncated": truncated,
            "error": None,
        }

    return {
        "success": False,
        "answer": None,
        "row_count": len(rows),
        "sql_used": query.sql if query else None,
        "caveats": [],
        "rows": rows,
        "truncated": truncated,
        "error": error or "Query workflow failed without an error message.",
    }


def build_query_database_tool(
    graph,
    schema_text: str,
    dialect: str,
    *,
    thread_id: str = "query-database-session",
    max_attempts: int = 3,
    max_summary_attempts: int = 2,
) -> StructuredTool:
    """Expose the complete text-to-SQL graph as one callable tool."""

    def query_database(question: str) -> dict:
        return run_query(
            graph, question, schema_text, dialect,
            thread_id=thread_id,
            max_attempts=max_attempts,
            max_summary_attempts=max_summary_attempts,
        )

    return StructuredTool.from_function(
        func=query_database,
        name="query_database",
        description=(
            "Answer a natural-language question using the connected read-only "
            "database. Returns the answer, SQL used, rows, and caveats."
        ),
    )

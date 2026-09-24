from langchain_core.tools import StructuredTool


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
        final_state = graph.invoke(
            {
                "question": question,
                "schema": schema_text,
                "dialect": dialect,
                "sql_query": None,
                "error_feedback": None,
                "attempts": 0,
                "max_attempts": max_attempts,
                "rows": None,
                "execution_error": None,
                "summary": None,
                "summary_error": None,
                "summary_attempts": 0,
                "max_summary_attempts": max_summary_attempts,
            },
            config={"configurable": {"thread_id": thread_id}},
        )

        query = final_state.get("sql_query")
        summary = final_state.get("summary")
        error = (
            final_state.get("summary_error")
            or final_state.get("execution_error")
            or final_state.get("error_feedback")
        )

        if summary is not None:
            return {
                "success": True,
                "answer": summary.answer,
                "row_count": summary.row_count,
                "sql_used": summary.sql_used,
                "caveats": summary.caveats,
                "rows": final_state.get("rows") or [],
                "error": None,
            }

        return {
            "success": False,
            "answer": None,
            "row_count": len(final_state.get("rows") or []),
            "sql_used": query.sql if query else None,
            "caveats": [],
            "rows": final_state.get("rows") or [],
            "error": error or "Query workflow failed without an error message.",
        }

    return StructuredTool.from_function(
        func=query_database,
        name="query_database",
        description=(
            "Answer a natural-language question using the connected read-only "
            "database. Returns the answer, SQL used, rows, and caveats."
        ),
    )
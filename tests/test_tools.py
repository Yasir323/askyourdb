from src.data_models import ResultSummary, SQLQuery
from src.tools import build_query_database_tool


class FakeGraph:
    def __init__(self, state):
        self.state = state
        self.calls = []

    def invoke(self, state, config):
        self.calls.append((state, config))
        return self.state


def test_query_database_tool_returns_summary_and_audit_data():
    query = SQLQuery(
        sql="SELECT student_id FROM students LIMIT 100",
        reasoning="Read students",
        tables_used=["students"],
    )
    graph = FakeGraph({
        "sql_query": query,
        "summary": ResultSummary(
            answer="One student was found.",
            row_count=1,
            sql_used=query.sql,
            caveats=["Sample data"],
        ),
        "rows": [{"student_id": 1}],
        "summary_error": None,
        "execution_error": None,
        "error_feedback": None,
    })

    tool = build_query_database_tool(
        graph,
        "students (student_id INTEGER)",
        "SQLite",
        thread_id="test-session",
    )
    result = tool.invoke("How many students are there?")

    assert result["success"] is True
    assert result["answer"] == "One student was found."
    assert result["sql_used"] == query.sql
    assert result["rows"] == [{"student_id": 1}]
    assert graph.calls[0][0]["question"] == "How many students are there?"
    assert graph.calls[0][0]["dialect"] == "SQLite"
    assert graph.calls[0][1]["configurable"]["thread_id"] == "test-session"


def test_query_database_tool_returns_failure_with_sql_and_rows():
    query = SQLQuery(
        sql="SELECT missing FROM students LIMIT 100",
        reasoning="Read students",
        tables_used=["students"],
    )
    graph = FakeGraph({
        "sql_query": query,
        "summary": None,
        "rows": [],
        "summary_error": "summary failed",
        "execution_error": None,
        "error_feedback": "summary failed",
    })

    tool = build_query_database_tool(graph, "students (...) ", "SQLite")
    result = tool.invoke("Find students")

    assert result["success"] is False
    assert result["error"] == "summary failed"
    assert result["sql_used"] == query.sql
    assert result["rows"] == []
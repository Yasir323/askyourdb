from askyourdb.data_models import ResultSummary, SQLQuery
from askyourdb.tools import build_query_database_tool


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
    graph = FakeGraph(
        {
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
        }
    )

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
    graph = FakeGraph(
        {
            "sql_query": query,
            "summary": None,
            "rows": [],
            "summary_error": "summary failed",
            "execution_error": None,
            "error_feedback": "summary failed",
        }
    )

    tool = build_query_database_tool(graph, "students (...) ", "SQLite")
    result = tool.invoke("Find students")

    assert result["success"] is False
    assert result["error"] == "summary failed"
    assert result["sql_used"] == query.sql
    assert result["rows"] == []


def summarized_state(rows, row_limit):
    query = SQLQuery(sql="SELECT 1", reasoning="r", tables_used=[])
    return {
        "sql_query": query,
        "summary": ResultSummary(answer="a", row_count=len(rows), sql_used=query.sql),
        "rows": rows,
        "row_limit": row_limit,
        "summary_error": None,
        "execution_error": None,
        "error_feedback": None,
    }


def test_result_is_truncated_when_the_imposed_limit_is_hit():
    rows = [{"n": i} for i in range(3)]

    hit = build_query_database_tool(FakeGraph(summarized_state(rows, 3)), "", "SQLite")
    under = build_query_database_tool(FakeGraph(summarized_state(rows, 100)), "", "SQLite")
    own_limit = build_query_database_tool(FakeGraph(summarized_state(rows, None)), "", "SQLite")

    assert hit.invoke("q")["truncated"] is True
    assert under.invoke("q")["truncated"] is False
    assert own_limit.invoke("q")["truncated"] is False


def test_sql_and_row_count_come_from_the_executed_query_not_the_model():
    executed = SQLQuery(sql="SELECT n FROM t LIMIT 100", reasoning="r", tables_used=["t"])
    state = {
        "sql_query": executed,
        # The summarizer model echoes these back, and may get them wrong.
        "summary": ResultSummary(answer="a", row_count=1, sql_used="SELECT n FROM t"),
        "rows": [{"n": 1}, {"n": 2}, {"n": 3}],
        "row_limit": 100,
        "summary_error": None,
        "execution_error": None,
        "error_feedback": None,
    }

    result = build_query_database_tool(FakeGraph(state), "", "SQLite").invoke("q")

    assert result["sql_used"] == "SELECT n FROM t LIMIT 100"
    assert result["row_count"] == 3

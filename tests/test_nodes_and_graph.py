from askyourdb.data_models import ResultSummary, SQLQuery
from askyourdb.graph import build_sql_graph
from askyourdb.nodes import (
    execute_sql_node,
    generate_sql_node,
    route_after_semantic_validation,
    route_after_static_validation,
    route_after_execution,
    semantic_validate_sql_node,
    summarize_results_node,
    route_after_summary,
    validate_sql_node,
)


def state(**overrides):
    value = {
        "question": "How many students are there?",
        "schema": "students (student_id INTEGER)",
        "dialect": "PostgreSQL",
        "sql_query": None,
        "error_feedback": None,
        "attempts": 0,
        "max_attempts": 3,
        "rows": None,
        "execution_error": None,
        "summary": None,
        "summary_error": None,
        "summary_attempts": 0,
        "max_summary_attempts": 2,
    }
    value.update(overrides)
    return value


class FakeGenerator:
    def __init__(self, query):
        self.query = query
        self.inputs = []

    def invoke(self, inputs):
        self.inputs.append(inputs)
        return self.query


class FakeStaticValidator:
    def __init__(self, result):
        self.result = result
        self.inputs = []

    def validate(self, sql):
        self.inputs.append(sql)
        return self.result


class FakeSemanticValidator:
    def __init__(self, result):
        self.result = result
        self.inputs = []

    def invoke(self, inputs):
        self.inputs.append(inputs)
        return self.result


class FakeExecutor:
    def __init__(self, rows=None, error=None):
        self.rows = rows if rows is not None else []
        self.error = error
        self.inputs = []

    def execute_query(self, sql_query):
        self.inputs.append(sql_query)
        if self.error:
            raise RuntimeError(self.error)
        return self.rows


class FakeSummarizer:
    def __init__(self, summary=None, error=None):
        self.summary = summary or ResultSummary(
            answer="One student was returned.",
            row_count=1,
            sql_used="SELECT student_id FROM students LIMIT 100",
            caveats=[],
        )
        self.error = error
        self.inputs = []

    def invoke(self, inputs):
        self.inputs.append(inputs)
        if self.error:
            raise RuntimeError(self.error)
        return self.summary


def query(sql="SELECT student_id FROM students"):
    return SQLQuery(sql=sql, reasoning="Count students", tables_used=["students"])


def test_generate_sql_node_includes_feedback_and_increments_attempts():
    model = FakeGenerator(query())

    result = generate_sql_node(
        state(error_feedback="Unknown column 'id'"),
        model,
    )

    assert result["attempts"] == 1
    assert result["error_feedback"] is None
    assert "Unknown column 'id'" in model.inputs[0]["question"]


def test_validate_sql_node_accepts_and_rewrites_query():
    validator = FakeStaticValidator({
        "is_valid": True,
        "error_message": [],
        "sql_query": "SELECT student_id FROM students LIMIT 100",
    })

    result = validate_sql_node(state(sql_query=query()), validator)

    assert result["error_feedback"] is None
    assert result["sql_query"].sql.endswith("LIMIT 100")


def test_validate_sql_node_returns_feedback_on_failure():
    validator = FakeStaticValidator({
        "is_valid": False,
        "error_message": ["Unknown table: courses"],
        "sql_query": None,
    })

    result = validate_sql_node(state(sql_query=query()), validator)

    assert result["error_feedback"] == "Unknown table: courses"


def test_semantic_validate_sql_node_accepts_query():
    validator = FakeSemanticValidator(type("Verdict", (), {
        "is_valid": True,
        "feedback": "",
    })())

    result = semantic_validate_sql_node(state(sql_query=query()), validator)

    assert result["error_feedback"] is None
    assert validator.inputs[0]["schema"] == "students (student_id INTEGER)"


def test_semantic_validate_sql_node_returns_feedback():
    validator = FakeSemanticValidator(type("Verdict", (), {
        "is_valid": False,
        "feedback": "The query does not count rows.",
    })())

    result = semantic_validate_sql_node(state(sql_query=query()), validator)

    assert result["error_feedback"] == (
        "Semantic validation failed: The query does not count rows."
    )


def test_routes_static_validation_to_semantic_retry_or_failure():
    assert route_after_static_validation(state()) == "semantic"
    assert route_after_static_validation(state(error_feedback="bad")) == "retry"
    assert route_after_static_validation(
        state(error_feedback="bad", attempts=3)
    ) == "failure"


def test_routes_semantic_validation_to_success_retry_or_failure():
    assert route_after_semantic_validation(state()) == "success"
    assert route_after_semantic_validation(state(error_feedback="bad")) == "retry"
    assert route_after_semantic_validation(
        state(error_feedback="bad", attempts=3)
    ) == "failure"


def test_execute_sql_node_returns_rows():
    executor = FakeExecutor(rows=[{"student_id": 1}])

    result = execute_sql_node(state(sql_query=query()), executor)

    assert result["rows"] == [{"student_id": 1}]
    assert result["execution_error"] is None
    assert result["error_feedback"] is None
    assert executor.inputs == [result["sql_query"]]


def test_execute_sql_node_captures_database_error():
    executor = FakeExecutor(error="no such table: students")

    result = execute_sql_node(state(sql_query=query()), executor)

    assert result["rows"] is None
    assert result["execution_error"] == (
        "SQL execution failed: no such table: students"
    )
    assert result["error_feedback"] == result["execution_error"]


def test_routes_execution_to_success_retry_or_failure():
    assert route_after_execution(state()) == "success"
    assert route_after_execution(state(execution_error="bad")) == "retry"
    assert route_after_execution(
        state(execution_error="bad", attempts=3)
    ) == "failure"


def test_summarize_results_node_preserves_sql_and_rows():
    summarizer = FakeSummarizer()
    result = summarize_results_node(
        state(sql_query=query(), rows=[{"student_id": 1}]),
        summarizer,
    )

    assert result["summary"].row_count == 1
    assert result["summary_error"] is None
    assert result["summary_attempts"] == 1
    assert summarizer.inputs[0]["rows"] == [{"student_id": 1}]


def test_summarize_results_node_retries_without_reexecuting():
    summarizer = FakeSummarizer(error="temporary summary failure")
    result = summarize_results_node(
        state(sql_query=query(), rows=[{"student_id": 1}], summary_attempts=1),
        summarizer,
    )

    assert result["summary"] is None
    assert result["summary_error"] == "temporary summary failure"
    assert result["summary_attempts"] == 2


def test_routes_summary_to_success_retry_or_failure():
    assert route_after_summary(state()) == "success"
    assert route_after_summary(state(summary_error="bad")) == "retry_summary"
    assert route_after_summary(
        state(summary_error="bad", summary_attempts=2)
    ) == "failure"


def test_graph_retries_then_finishes_on_success():
    generator = FakeGenerator(query())
    static_validator = FakeStaticValidator({
        "is_valid": True,
        "error_message": [],
        "sql_query": "SELECT student_id FROM students LIMIT 100",
    })
    semantic_validator = FakeSemanticValidator(type("Verdict", (), {
        "is_valid": True,
        "feedback": "",
    })())

    graph = build_sql_graph(
        generator,
        static_validator,
        semantic_validator,
        FakeExecutor(rows=[]),
        FakeSummarizer(),
    )
    result = graph.invoke(state(), config={"configurable": {"thread_id": "success"}})

    assert result["error_feedback"] is None
    assert result["sql_query"].sql.endswith("LIMIT 100")
    assert result["attempts"] == 1


def test_graph_executes_query_and_stores_rows():
    generator = FakeGenerator(query())
    static_validator = FakeStaticValidator({
        "is_valid": True,
        "error_message": [],
        "sql_query": "SELECT student_id FROM students LIMIT 100",
    })
    semantic_validator = FakeSemanticValidator(type("Verdict", (), {
        "is_valid": True,
        "feedback": "",
    })())
    executor = FakeExecutor(rows=[{"student_id": 1}])

    graph = build_sql_graph(
        generator,
        static_validator,
        semantic_validator,
        executor,
        FakeSummarizer(),
    )
    result = graph.invoke(
        state(),
        config={"configurable": {"thread_id": "execution-success"}},
    )

    assert result["rows"] == [{"student_id": 1}]
    assert result["execution_error"] is None


def test_graph_retries_after_execution_error_until_success():
    generator = FakeGenerator(query())
    static_validator = FakeStaticValidator({
        "is_valid": True,
        "error_message": [],
        "sql_query": "SELECT student_id FROM students LIMIT 100",
    })
    semantic_validator = FakeSemanticValidator(type("Verdict", (), {
        "is_valid": True,
        "feedback": "",
    })())

    class RetryExecutor(FakeExecutor):
        def execute_query(self, sql_query):
            self.inputs.append(sql_query)
            if len(self.inputs) == 1:
                raise RuntimeError("column does not exist")
            return [{"student_id": 1}]

    executor = RetryExecutor()
    graph = build_sql_graph(
        generator,
        static_validator,
        semantic_validator,
        executor,
        FakeSummarizer(),
    )

    result = graph.invoke(
        state(),
        config={"configurable": {"thread_id": "execution-retry"}},
    )

    assert result["rows"] == [{"student_id": 1}]
    assert result["attempts"] == 2
    assert len(generator.inputs) == 2
    assert "column does not exist" in generator.inputs[1]["question"]


def test_graph_stops_after_execution_retry_limit():
    generator = FakeGenerator(query())
    static_validator = FakeStaticValidator({
        "is_valid": True,
        "error_message": [],
        "sql_query": "SELECT student_id FROM students LIMIT 100",
    })
    semantic_validator = FakeSemanticValidator(type("Verdict", (), {
        "is_valid": True,
        "feedback": "",
    })())
    executor = FakeExecutor(error="persistent database failure")
    graph = build_sql_graph(
        generator,
        static_validator,
        semantic_validator,
        executor,
        FakeSummarizer(),
    )

    result = graph.invoke(
        state(max_attempts=2),
        config={"configurable": {"thread_id": "execution-failure"}},
    )

    assert result["execution_error"] == (
        "SQL execution failed: persistent database failure"
    )
    assert result["attempts"] == 2
    assert len(executor.inputs) == 2


def test_checkpointer_keeps_threads_isolated():
    generator = FakeGenerator(query())
    static_validator = FakeStaticValidator({
        "is_valid": True,
        "error_message": [],
        "sql_query": "SELECT student_id FROM students LIMIT 100",
    })
    semantic_validator = FakeSemanticValidator(type("Verdict", (), {
        "is_valid": True,
        "feedback": "",
    })())
    executor = FakeExecutor(rows=[{"student_id": 1}])
    graph = build_sql_graph(
        generator,
        static_validator,
        semantic_validator,
        executor,
        FakeSummarizer(),
    )

    first = graph.invoke(
        state(question="First question"),
        config={"configurable": {"thread_id": "thread-a"}},
    )
    second = graph.invoke(
        state(question="Second question"),
        config={"configurable": {"thread_id": "thread-b"}},
    )

    assert first["question"] == "First question"
    assert second["question"] == "Second question"
    assert len(generator.inputs) == 2

def test_execute_sql_node_reports_only_the_database_message():
    from sqlalchemy.exc import DataError

    class RejectingExecutor:
        def execute_query(self, sql_query):
            raise DataError(
                "SELECT ...", {},
                Exception('invalid input value for enum invoice_status: "pending"\n'
                          "LINE 1: ...WHERE i.status IN ('pending')\n        ^"),
            )

    state = {"sql_query": SQLQuery(sql="SELECT 1", reasoning="r", tables_used=[])}

    result = execute_sql_node(state, RejectingExecutor())

    assert result["execution_error"] == (
        'SQL execution failed: invalid input value for enum invoice_status: "pending"'
    )


def test_validate_sql_node_records_the_imposed_row_limit():
    validator = FakeStaticValidator({
        "is_valid": True,
        "error_message": [],
        "sql_query": "SELECT student_id FROM students LIMIT 100",
        "row_limit": 100,
    })

    result = validate_sql_node(state(sql_query=query()), validator)

    assert result["row_limit"] == 100


def test_summarizer_is_told_when_the_row_limit_cut_the_result():
    rows = [{"student_id": 1}, {"student_id": 2}]
    cut, whole = FakeSummarizer(), FakeSummarizer()

    summarize_results_node(state(sql_query=query(), rows=rows, row_limit=2), cut)
    summarize_results_node(state(sql_query=query(), rows=rows, row_limit=100), whole)

    assert "first 2 rows" in cut.inputs[0]["row_note"]
    assert whole.inputs[0]["row_note"] == ""

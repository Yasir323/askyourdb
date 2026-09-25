from langchain_core.runnables import RunnableLambda
from sqlalchemy import create_engine, text

import askyourdb.models as models
from askyourdb.data_models import ResultSummary, SQLQuery
from askyourdb.executor import QueryExecutor
from askyourdb.graph import build_sql_graph
from askyourdb.schema_intropection import SchemaIntrospector
from askyourdb.sql_validator import SqlValidator
from askyourdb.models import render_schema


class FakeChatModel:
    def __init__(self, query):
        self.query = query
        self.prompts = []

    def with_structured_output(self, output_type):
        def respond(prompt_value):
            self.prompts.append(prompt_value.to_string())
            return self.query

        return RunnableLambda(respond)


class AcceptingSemanticValidator:
    def invoke(self, inputs):
        assert inputs["dialect"] == "SQLite"
        assert "students" in inputs["schema"]
        return type("Verdict", (), {"is_valid": True, "feedback": ""})()


class AcceptingSummarizer:
    def invoke(self, inputs):
        return ResultSummary(
            answer="Two students have unpaid balances.",
            row_count=len(inputs["rows"]),
            sql_used=inputs["sql"],
            caveats=[],
        )


def test_sqlite_database_to_validated_query(monkeypatch, tmp_path):
    database_path = tmp_path / "school.sqlite"
    dsn = f"sqlite:///{database_path}"
    engine = create_engine(dsn)

    with engine.begin() as connection:
        connection.execute(text("""
            CREATE TABLE students (
                student_id INTEGER PRIMARY KEY,
                first_name TEXT NOT NULL,
                last_name TEXT NOT NULL
            )
        """))
        connection.execute(text("""
            CREATE TABLE invoices (
                invoice_id INTEGER PRIMARY KEY,
                student_id INTEGER NOT NULL,
                total_amount NUMERIC NOT NULL,
                status TEXT NOT NULL,
                FOREIGN KEY (student_id) REFERENCES students(student_id)
            )
        """))
        connection.execute(text("""
            CREATE TABLE payments (
                payment_id INTEGER PRIMARY KEY,
                invoice_id INTEGER NOT NULL,
                amount NUMERIC NOT NULL,
                FOREIGN KEY (invoice_id) REFERENCES invoices(invoice_id)
            )
        """))
        connection.execute(text("INSERT INTO students VALUES (1, 'Ada', 'Lovelace')"))
        connection.execute(text("INSERT INTO students VALUES (2, 'Grace', 'Hopper')"))
        connection.execute(text("INSERT INTO invoices VALUES (1, 1, 100, 'open')"))
        connection.execute(text("INSERT INTO invoices VALUES (2, 2, 80, 'open')"))
        connection.execute(text("INSERT INTO payments VALUES (1, 1, 25)"))

    introspector = SchemaIntrospector(dsn)
    introspector.load_db()
    schema = introspector.get_schema()
    schema_text = render_schema(schema)

    expected_query = SQLQuery(
        sql="""
            SELECT s.first_name, s.last_name,
                   SUM(i.total_amount) - COALESCE(SUM(p.paid_amount), 0) AS unpaid_amount
            FROM students AS s
            JOIN invoices AS i ON i.student_id = s.student_id
            LEFT JOIN (
                SELECT invoice_id, SUM(amount) AS paid_amount
                FROM payments
                GROUP BY invoice_id
            ) AS p ON p.invoice_id = i.invoice_id
            WHERE i.status <> 'cancelled'
            GROUP BY s.student_id, s.first_name, s.last_name
            HAVING SUM(i.total_amount) - COALESCE(SUM(p.paid_amount), 0) > 0
            ORDER BY unpaid_amount DESC
            LIMIT 5
        """,
        reasoning="Aggregate invoice balances after pre-aggregating payments.",
        tables_used=["students", "invoices", "payments"],
    )
    fake_model = FakeChatModel(expected_query)
    monkeypatch.setattr(models, "init_chat_model", lambda *args, **kwargs: fake_model)

    from askyourdb.config import LLMConfig
    from askyourdb.models import build_sql_generator

    generator = build_sql_generator(
        schema_text=schema_text, dialect="SQLite",
        llm_config=LLMConfig(model="google_genai:gemini-3.5-flash-lite"),
    )
    validator = SqlValidator(schema=schema, dialect="sqlite")
    graph = build_sql_graph(
        generator=generator,
        validator=validator,
        semantic_validator=AcceptingSemanticValidator(),
        executor=QueryExecutor(engine),
        summarizer=AcceptingSummarizer(),
    )

    final_state = graph.invoke({
        "question": "Which students owe the most in unpaid fees?",
        "schema": schema_text,
        "dialect": "SQLite",
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
    }, config={"configurable": {"thread_id": "sqlite-integration"}})

    assert final_state["error_feedback"] is None
    assert final_state["summary"].row_count == 2
    assert final_state["attempts"] == 1
    assert len(fake_model.prompts) == 1
    assert "students" in fake_model.prompts[0]
    assert "PostgreSQL" not in fake_model.prompts[0]

    with engine.connect() as connection:
        rows = connection.execute(text(final_state["sql_query"].sql)).mappings().all()

    assert [row["first_name"] for row in rows] == ["Grace", "Ada"]
    assert [row["unpaid_amount"] for row in rows] == [80, 75]
    introspector.close()
    engine.dispose()

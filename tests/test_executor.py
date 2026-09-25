from sqlalchemy import create_engine, text

from askyourdb.data_models import SQLQuery
from askyourdb.executor import QueryExecutor


def test_query_executor_returns_mapping_rows():
    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE students (student_id INTEGER, name TEXT)"))
        connection.execute(text("INSERT INTO students VALUES (1, 'Ada')"))

    rows = QueryExecutor(engine).execute_query(
        SQLQuery(
            sql="SELECT student_id, name FROM students",
            reasoning="Read students",
            tables_used=["students"],
        )
    )

    assert rows == [{"student_id": 1, "name": "Ada"}]
    engine.dispose()


def test_query_executor_propagates_sql_errors():
    engine = create_engine("sqlite://")

    try:
        QueryExecutor(engine).execute_query(
            SQLQuery(
                sql="SELECT missing FROM students",
                reasoning="Invalid query",
                tables_used=["students"],
            )
        )
    except Exception as error:
        assert "no such table" in str(error)
    else:
        raise AssertionError("Expected the database error to propagate")
    finally:
        engine.dispose()
import pytest

from src.sql_validator import MAX_ROW_LIMIT


def test_normalizes_postgresql_dialect(validator):
    assert validator.dialect == "postgres"


def test_accepts_valid_select_and_preserves_limit(validator):
    result = validator.validate(
        "SELECT s.student_id FROM students AS s LIMIT 5"
    )

    assert result["is_valid"] is True
    assert result["error_message"] == []
    assert result["sql_query"] == "SELECT s.student_id FROM students AS s LIMIT 5"


def test_injects_default_limit_when_missing(validator):
    result = validator.validate("SELECT student_id FROM students")

    assert result["is_valid"] is True
    assert result["sql_query"].endswith("LIMIT 100")


def test_caps_excessive_limit(validator):
    result = validator.validate("SELECT student_id FROM students LIMIT 99999")

    assert result["is_valid"] is True
    assert result["sql_query"].endswith(f"LIMIT {MAX_ROW_LIMIT}")


def test_rejects_invalid_sql(validator):
    result = validator.validate("SELECT FROM")

    assert result["is_valid"] is False
    assert result["sql_query"] is None
    assert result["error_message"]
    assert result["error_message"][0].startswith("Parse error:")


@pytest.mark.parametrize("sql", [
    "INSERT INTO students (student_id) VALUES (1)",
    "UPDATE students SET first_name = 'Ada'",
    "DELETE FROM students",
    "DROP TABLE students",
    "CREATE TABLE new_table (id INTEGER)",
    "TRUNCATE TABLE students",
    "ALTER TABLE students ADD COLUMN email TEXT",
])
def test_rejects_non_read_statements(validator, sql):
    result = validator.validate(sql)

    assert result["is_valid"] is False
    assert any("Only Read statements" in error for error in result["error_message"])


@pytest.mark.parametrize("sql", [
    "SELECT student_id FROM students WHERE student_id IN (SELECT student_id FROM students)",
    "WITH recent AS (SELECT student_id FROM students) SELECT student_id FROM recent",
    "SELECT student_id FROM students UNION SELECT student_id FROM students",
])
def test_accepts_read_query_shapes(validator, sql):
    result = validator.validate(sql)

    assert result["is_valid"] is True


def test_rejects_mutating_statement_inside_cte(validator):
    result = validator.validate(
        "WITH changed AS (UPDATE students SET first_name = 'Ada' RETURNING student_id) "
        "SELECT student_id FROM changed"
    )

    assert result["is_valid"] is False
    assert any("Mutating statements" in error for error in result["error_message"])


def test_rejects_unknown_table(validator):
    result = validator.validate("SELECT id FROM missing_table")

    assert result["is_valid"] is False
    assert "Unknown tables referenced: missing_table" in result["error_message"]


def test_rejects_unknown_qualified_column(validator):
    result = validator.validate("SELECT s.email FROM students AS s")

    assert result["is_valid"] is False
    assert "Unknown column 'email' on table 's'" in result["error_message"]


def test_allows_unqualified_columns_for_now(validator):
    result = validator.validate("SELECT student_id FROM students")

    assert result["is_valid"] is True


def test_reports_multiple_static_errors(validator):
    result = validator.validate(
        "SELECT s.email FROM students AS s JOIN missing_table AS m ON m.id = s.student_id"
    )

    assert result["is_valid"] is False
    assert len(result["error_message"]) == 2
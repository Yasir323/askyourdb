from typing import TypedDict

from askyourdb.data_models import ResultSummary, SQLQuery


class AnalystState(TypedDict):
    question: str
    schema: str
    dialect: str
    sql_query: SQLQuery | None
    error_feedback: str | None
    attempts: int
    max_attempts: int
    rows: list[dict] | None
    row_limit: int | None
    execution_error: str | None
    summary: ResultSummary | None
    summary_error: str | None
    summary_attempts: int
    max_summary_attempts: int

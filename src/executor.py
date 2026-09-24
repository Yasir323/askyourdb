from sqlalchemy import Engine, text

from src.data_models import SQLQuery


class QueryExecutor:
    def __init__(self, engine: Engine):
        self.engine = engine

    def execute_query(self, sql_query: SQLQuery) -> list[dict]:
        with self.engine.connect() as connection:
            result = connection.execute(text(sql_query.sql))
            return [dict(row) for row in result.mappings().all()]

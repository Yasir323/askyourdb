from collections.abc import Callable
from uuid import uuid4

from langchain_core.tools import StructuredTool

from askyourdb.config import AnalystConfig, ConfigError
from askyourdb.executor import QueryExecutor
from askyourdb.graph import build_sql_graph
from askyourdb.models import (
    build_result_summarizer,
    build_sql_generator,
    build_sql_semantic_validator,
    render_schema,
)
from askyourdb.schema_intropection import SchemaIntrospector
from askyourdb.sql_validator import SqlValidator
from askyourdb.tools import ProgressEvent, build_query_database_tool, run_query


class SQLAnalyst:
    """Answer natural-language questions about a database using your own LLM keys."""

    def __init__(self, config: AnalystConfig):
        self.config = config
        self._dialect = config.database.dialect
        self._introspector = SchemaIntrospector(config.database.dsn.get_secret_value())
        try:
            try:
                self._introspector.load_db()
            except ImportError as error:
                raise ConfigError(
                    f"The database driver '{error.name}' is not installed. "
                    "For PostgreSQL use a 'postgresql+psycopg://' DSN (psycopg is "
                    "included); for other databases install the driver in your DSN."
                ) from None
            schema = self._introspector.get_schema()
            if not schema:
                raise ConfigError(
                    "No tables found in the database. Check the DSN (a mistyped "
                    "SQLite path creates a new empty file) and that the user can "
                    "see the tables."
                )
            self._schema_text = render_schema(schema)
            models = config.models
            self._graph = build_sql_graph(
                generator=build_sql_generator(
                    self._schema_text, self._dialect, models.generator,
                ),
                validator=SqlValidator(schema=schema, dialect=self._dialect),
                semantic_validator=build_sql_semantic_validator(
                    models.resolved_semantic_validator,
                ),
                executor=QueryExecutor(self._introspector.engine),
                summarizer=build_result_summarizer(models.resolved_summarizer),
            )
        except BaseException:
            self._introspector.close()
            raise

    def as_tool(self, thread_id: str | None = None) -> StructuredTool:
        return build_query_database_tool(
            graph=self._graph,
            schema_text=self._schema_text,
            dialect=self._dialect,
            thread_id=thread_id or f"askyourdb-{uuid4()}",
        )

    def ask(
        self,
        question: str,
        thread_id: str | None = None,
        on_progress: Callable[[ProgressEvent], None] | None = None,
    ) -> dict:
        """Answer one question.

        With no thread_id the question gets a throwaway thread whose checkpoints
        are deleted afterwards, so repeated calls don't accumulate state.
        on_progress, if given, is called as each pipeline step starts.
        """
        if thread_id is not None:
            return self._run(question, thread_id, on_progress)
        thread_id = f"askyourdb-{uuid4()}"
        try:
            return self._run(question, thread_id, on_progress)
        finally:
            self._graph.checkpointer.delete_thread(thread_id)

    def _run(self, question, thread_id, on_progress) -> dict:
        return run_query(
            self._graph, question, self._schema_text, self._dialect,
            thread_id=thread_id, on_progress=on_progress,
        )

    def close(self) -> None:
        self._introspector.close()

    def __enter__(self) -> "SQLAnalyst":
        return self

    def __exit__(self, *exc_info) -> None:
        self.close()

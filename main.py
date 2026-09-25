import os
import warnings

from dotenv import load_dotenv

from askyourdb.executor import QueryExecutor
from askyourdb.graph import build_sql_graph
from askyourdb.data_models import SQLValidatorResult
from askyourdb.sql_validator import SqlValidator
from askyourdb.models import (
    build_result_summarizer,
    build_sql_generator,
    build_sql_semantic_validator,
    render_schema,
)
from askyourdb.schema_intropection import SchemaIntrospector
from askyourdb.tools import build_query_database_tool
from askyourdb.observability import configure_langsmith

warnings.filterwarnings("ignore")
DEFAULT_DSN = "postgresql+psycopg://school:school@localhost:5432/school_db"


def main():
    load_dotenv()
    configure_langsmith()
    conn_string = os.environ.get("SCHOOL_DB_DSN", DEFAULT_DSN)

    introspector = SchemaIntrospector(conn_string)
    try:

        introspector.load_db()
        schema = introspector.get_schema()

        sql_generator = build_sql_generator(
            schema_text=render_schema(schema),
            dialect=os.environ.get("DIALECT", "PostgreSQL"),
        )

        question = "Which five students owe the most in unpaid fees?"
        # result = sql_generator.invoke({"question": question})

        # print(f"Q: {question}\n")
        # print(result.sql)
        # print(f"\nReasoning: {result.reasoning}")
        # print(f"Tables used: {', '.join(result.tables_used)}")

        sql_validator = SqlValidator(
            schema=schema,
            dialect=os.environ.get("DIALECT", "PostgreSQL")
        )
        semantic_validator = build_sql_semantic_validator()
        result_summarizer = build_result_summarizer()
        executor = QueryExecutor(introspector.engine)
        # validation_result: SQLValidatorResult = sql_validator.validate(result.sql)
        # if validation_result["is_valid"]:
        #     print("\nSQL query is valid.")
        #     print(f"Validated SQL: {validation_result['sql_query']}")
        # else:
        #     print("\nSQL query is invalid.")
        #     print(f"Errors: {validation_result['error_message']}")
        sql_graph = build_sql_graph(
            generator=sql_generator,
            validator=sql_validator,
            semantic_validator=semantic_validator,
            executor=executor,
            summarizer=result_summarizer,
        )
        query_database = build_query_database_tool(
            graph=sql_graph,
            schema_text=render_schema(schema),
            dialect=os.environ.get("DIALECT", "PostgreSQL"),
            thread_id="school-query-session-1",
        )
        result = query_database.invoke(question)
        if result["success"]:
            print("\nSQL query executed successfully.")
            print(result["sql_used"])
            print(result["rows"])
            print(result["answer"])
        else:
            print("\nQuery workflow failed.")
            print(result["error"])
            print(result["sql_used"])
            print(result["rows"])
    finally:
        introspector.close()


if __name__ == '__main__':
    main()

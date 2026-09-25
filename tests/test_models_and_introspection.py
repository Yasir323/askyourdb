from sqlalchemy import CheckConstraint as SARealCheckConstraint
from sqlalchemy import Integer, MetaData
from sqlalchemy.dialects.postgresql import dialect as postgres_dialect
from sqlalchemy.schema import UniqueConstraint as SARealUniqueConstraint
from langchain_core.runnables import RunnableLambda

import askyourdb.models as models
import askyourdb.schema_intropection as introspection_module
from askyourdb.data_models import Column, Table
from askyourdb.schema_intropection import SchemaIntrospector


def test_render_schema_uses_table_rendering():
    schema = {
        "students": Table(
            name="students",
            columns=[Column("student_id", Integer(), "INTEGER", False)],
        )
    }

    assert models.render_schema(schema) == "students (\n    student_id INTEGER NOT NULL\n)"


class FakeChatModel:
    def with_structured_output(self, output_type):
        return RunnableLambda(lambda value: output_type)


def test_model_builders_create_structured_chains(monkeypatch):
    monkeypatch.setattr(models, "init_chat_model", lambda *args, **kwargs: FakeChatModel())

    generator = models.build_sql_generator("students (student_id INTEGER)", "PostgreSQL")
    semantic = models.build_sql_semantic_validator()

    assert generator is not None
    assert semantic is not None


class FakeColumn:
    def __init__(self, name):
        self.name = name
        self.type = Integer()
        self.nullable = False
        self.server_default = None


class FakeReflectedTable:
    def __init__(self):
        self.columns = [FakeColumn("student_id")]
        self.constraints = [SARealUniqueConstraint(), SARealCheckConstraint("student_id > 0")]


class FakeEngine:
    dialect = postgres_dialect()

    def dispose(self):
        self.disposed = True


class FakeMetadata:
    def __init__(self):
        self.tables = {"students": FakeReflectedTable()}

    def reflect(self, bind):
        self.bound_engine = bind


class FakeInspector:
    def get_pk_constraint(self, table_name):
        return {"constrained_columns": ["student_id"], "name": "students_pkey"}

    def get_foreign_keys(self, table_name):
        return [{
            "constrained_columns": ["student_id"],
            "referred_table": "students",
            "referred_columns": ["student_id"],
            "name": "students_self_fkey",
            "options": {"ondelete": "CASCADE", "onupdate": "NO ACTION"},
        }]


def test_schema_introspector_loads_tables_and_constraints(monkeypatch):
    engine = FakeEngine()
    metadata = FakeMetadata()
    monkeypatch.setattr(introspection_module, "create_engine", lambda dsn: engine)
    monkeypatch.setattr(introspection_module, "MetaData", lambda: metadata)
    monkeypatch.setattr(introspection_module, "inspect", lambda value: FakeInspector())

    introspector = SchemaIntrospector("postgresql://test")
    introspector.load_db()
    table = introspector.get_schema()["students"]

    assert table.columns[0].name == "student_id"
    assert table.primary_key.columns == ("student_id",)
    assert table.relations[0].on_delete == "CASCADE"
    assert len(table.constraints) == 2
    assert introspector.engine is engine
    introspector.close()
    assert engine.disposed is True


def test_schema_introspector_disposes_engine_on_reflection_failure(monkeypatch):
    engine = FakeEngine()

    class BrokenMetadata:
        tables = {}

        def reflect(self, bind):
            raise RuntimeError("reflection failed")

    monkeypatch.setattr(introspection_module, "create_engine", lambda dsn: engine)
    monkeypatch.setattr(introspection_module, "MetaData", BrokenMetadata)

    introspector = SchemaIntrospector("postgresql://test")

    try:
        introspector.load_db()
    except RuntimeError as error:
        assert str(error) == "reflection failed"
    else:
        raise AssertionError("reflection failure was swallowed")

    assert introspector.engine is engine
    introspector.close()
    assert engine.disposed is True


def test_server_default_rendering():
    assert SchemaIntrospector._server_default(type("Column", (), {"server_default": None})()) == ""
    assert SchemaIntrospector._server_default(
        type("Column", (), {"server_default": type("Default", (), {"sqltext": "now()"})()})()
    ) == "GENERATED ALWAYS AS (now())"
    assert SchemaIntrospector._server_default(
        type("Column", (), {"server_default": type("Default", (), {"arg": "42"})()})()
    ) == "DEFAULT 42"
    assert SchemaIntrospector._server_default(
        type("Column", (), {"server_default": "CURRENT_DATE"})()
    ) == "DEFAULT CURRENT_DATE"
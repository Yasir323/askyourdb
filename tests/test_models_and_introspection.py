import pytest
from sqlalchemy import CheckConstraint as SARealCheckConstraint
from sqlalchemy import Integer, MetaData
from sqlalchemy.dialects.postgresql import dialect as postgres_dialect
from sqlalchemy.schema import UniqueConstraint as SARealUniqueConstraint
from langchain_core.runnables import RunnableLambda

import askyourdb.models as models
import askyourdb.schema_introspection as introspection_module
from askyourdb.config import ConfigError, LLMConfig
from askyourdb.data_models import Column, Table
from askyourdb.schema_introspection import SchemaIntrospector


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
    calls = []
    monkeypatch.setattr(
        models, "init_chat_model",
        lambda *args, **kwargs: calls.append((args, kwargs)) or FakeChatModel(),
    )

    generator = models.build_sql_generator(
        "students (student_id INTEGER)", "PostgreSQL", LLMConfig(model="openai:gpt-5"),
    )
    semantic = models.build_sql_semantic_validator(LLMConfig(model="groq:llama-3.3-70b"))
    summarizer = models.build_result_summarizer(LLMConfig(model="anthropic:claude-sonnet-5"))

    assert generator is not None and semantic is not None and summarizer is not None
    assert [args[0] for args, _ in calls] == [
        "openai:gpt-5", "groq:llama-3.3-70b", "anthropic:claude-sonnet-5",
    ]


def test_build_llm_passes_api_key_only_when_set(monkeypatch):
    calls = []
    monkeypatch.setattr(models, "init_chat_model",
                        lambda model, **kwargs: calls.append(kwargs) or FakeChatModel())

    models.build_llm(LLMConfig(model="openai:gpt-5", api_key="sk-1", temperature=0.2))
    models.build_llm(LLMConfig(model="openai:gpt-5"))

    assert calls == [{"temperature": 0.2, "api_key": "sk-1"}, {}]


def test_build_llm_missing_provider_package_hints_extra(monkeypatch):
    def missing(*args, **kwargs):
        raise ImportError("Initializing ChatAnthropic requires the langchain-anthropic package.")

    monkeypatch.setattr(models, "init_chat_model", missing)

    with pytest.raises(ConfigError, match=r'pip install "askyourdb\[anthropic\]"'):
        models.build_llm(LLMConfig(model="anthropic:claude-sonnet-5"))


def test_build_llm_google_provider_maps_to_google_extra(monkeypatch):
    def missing(*args, **kwargs):
        raise ImportError("no langchain_google_genai")

    monkeypatch.setattr(models, "init_chat_model", missing)

    with pytest.raises(ConfigError, match=r'askyourdb\[google\]'):
        models.build_llm(LLMConfig(model="google_genai:gemini-3.5-flash-lite"))


def test_build_llm_unknown_provider_package_gives_generic_hint(monkeypatch):
    def missing(*args, **kwargs):
        raise ImportError("requires the langchain-mistralai package")

    monkeypatch.setattr(models, "init_chat_model", missing)

    with pytest.raises(ConfigError, match="langchain-mistralai"):
        models.build_llm(LLMConfig(model="mistralai:mistral-large"))


def test_build_llm_wraps_provider_value_errors(monkeypatch):
    def unsupported(*args, **kwargs):
        raise ValueError("Unable to infer model provider")

    monkeypatch.setattr(models, "init_chat_model", unsupported)

    with pytest.raises(ConfigError, match="Could not initialize model 'fooprov:x'"):
        models.build_llm(LLMConfig(model="fooprov:x"))


def test_sql_prompt_has_no_few_shot_examples():
    assert "Examples" not in models.SQL_GEN_SYSTEM
    assert not hasattr(models, "FEW_SHOT_EXAMPLES")


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

def test_build_llm_provider_validation_error_does_not_echo_api_key(monkeypatch):
    from pydantic import BaseModel

    class ProviderArgs(BaseModel):
        api_key: int

    def invalid(model, **kwargs):
        ProviderArgs.model_validate(kwargs)

    monkeypatch.setattr(models, "init_chat_model", invalid)

    with pytest.raises(ConfigError) as error:
        models.build_llm(LLMConfig(model="google_genai:x", api_key="AIzaSECRETKEY123"))

    assert "AIzaSECRETKEY123" not in str(error.value)
    assert "api_key" in str(error.value)


def test_build_llm_wraps_provider_init_errors_and_scrubs_key(monkeypatch):
    class OpenAIError(Exception):
        pass

    def missing_credentials(*args, **kwargs):
        raise OpenAIError("Missing credentials sk-live-123\nset OPENAI_API_KEY")

    monkeypatch.setattr(models, "init_chat_model", missing_credentials)

    with pytest.raises(ConfigError) as error:
        models.build_llm(LLMConfig(model="openai:gpt-5", api_key="sk-live-123"))

    message = str(error.value)
    assert "Could not initialize model 'openai:gpt-5'" in message
    assert "Missing credentials" in message
    assert "sk-live-123" not in message


def test_ollama_has_no_askyourdb_extra_yet(monkeypatch):
    def missing(*args, **kwargs):
        raise ImportError("requires the langchain-ollama package")

    monkeypatch.setattr(models, "init_chat_model", missing)

    with pytest.raises(ConfigError) as error:
        models.build_llm(LLMConfig(model="ollama:llama3"))

    assert "askyourdb[ollama]" not in str(error.value)
    assert "langchain-ollama" in str(error.value)


def test_column_lists_enum_values():
    column = Column("status", Integer(), "invoice_status", False, "", ("draft", "paid"))

    assert str(column) == "status invoice_status NOT NULL /* one of: 'draft', 'paid' */"


def test_schema_introspector_keeps_enum_values(monkeypatch):
    from sqlalchemy.dialects.postgresql import ENUM

    status = FakeColumn("status")
    status.type = ENUM("draft", "issued", "paid", name="invoice_status")
    metadata = FakeMetadata()
    metadata.tables["students"].columns = [status]
    monkeypatch.setattr(introspection_module, "create_engine", lambda dsn: FakeEngine())
    monkeypatch.setattr(introspection_module, "MetaData", lambda: metadata)
    monkeypatch.setattr(introspection_module, "inspect", lambda value: FakeInspector())

    introspector = SchemaIntrospector("postgresql://test")
    introspector.load_db()
    rendered = models.render_schema(introspector.get_schema())

    assert "status invoice_status NOT NULL /* one of: 'draft', 'issued', 'paid' */," in rendered


def test_result_summarizer_prompt_includes_the_row_note(monkeypatch):
    seen = []

    class RecordingChatModel:
        def with_structured_output(self, output_type):
            return RunnableLambda(lambda prompt: seen.append(prompt.to_string()) or output_type)

    monkeypatch.setattr(models, "init_chat_model", lambda *a, **k: RecordingChatModel())

    models.build_result_summarizer(LLMConfig(model="openai:gpt-5")).invoke(
        {"question": "q", "sql": "SELECT 1", "rows": [], "row_note": "ROW-NOTE"}
    )

    assert "ROW-NOTE" in seen[0]

import pytest
from langchain_core.runnables import RunnableLambda
from sqlalchemy import create_engine, text

import askyourdb.models as models
from askyourdb import AnalystConfig, ConfigError, SQLAnalyst
from askyourdb.analyst import SchemaIntrospector
from askyourdb.data_models import ResultSummary, SQLQuery, SQLSemanticValidation


class ScriptedChatModel:
    """Returns a canned structured response per output type."""

    def __init__(self, responses):
        self.responses = responses
        self.prompts = []

    def with_structured_output(self, output_type):
        def respond(prompt_value):
            self.prompts.append((output_type, prompt_value.to_string()))
            return self.responses[output_type]

        return RunnableLambda(respond)


@pytest.fixture
def sqlite_dsn(tmp_path):
    dsn = f"sqlite:///{tmp_path / 'people.sqlite'}"
    engine = create_engine(dsn)
    with engine.begin() as connection:
        connection.execute(text(
            "CREATE TABLE people (person_id INTEGER PRIMARY KEY, name TEXT NOT NULL)"
        ))
        connection.execute(text("INSERT INTO people VALUES (1, 'Ada'), (2, 'Grace')"))
    engine.dispose()
    return dsn


@pytest.fixture
def fake_llm(monkeypatch):
    model = ScriptedChatModel({
        SQLQuery: SQLQuery(
            sql="SELECT name FROM people ORDER BY person_id",
            reasoning="List people.",
            tables_used=["people"],
        ),
        SQLSemanticValidation: SQLSemanticValidation(is_valid=True),
        ResultSummary: ResultSummary(
            answer="Ada and Grace.",
            row_count=2,
            sql_used="SELECT name FROM people ORDER BY person_id LIMIT 100",
        ),
    })
    calls = []
    monkeypatch.setattr(
        models, "init_chat_model",
        lambda name, **kwargs: calls.append((name, kwargs)) or model,
    )
    model.calls = calls
    return model


def make_config(dsn, **models_config):
    return AnalystConfig(
        database={"dsn": dsn},
        models={"generator": {"model": "anthropic:claude-sonnet-5", "api_key": "gen-key"},
                **models_config},
    )


def test_ask_answers_from_a_sqlite_database(sqlite_dsn, fake_llm):
    with SQLAnalyst(make_config(sqlite_dsn)) as analyst:
        result = analyst.ask("Who are the people?")

    assert result["success"] is True
    assert result["answer"] == "Ada and Grace."
    assert result["rows"] == [{"name": "Ada"}, {"name": "Grace"}]
    generator_prompt = next(p for t, p in fake_llm.prompts if t is SQLQuery)
    assert "SQLite" in generator_prompt
    assert "people" in generator_prompt


def test_each_stage_uses_its_own_model_config(sqlite_dsn, fake_llm):
    config = make_config(
        sqlite_dsn,
        summarizer={"model": "groq:llama-3.3-70b", "api_key": "sum-key"},
    )

    with SQLAnalyst(config):
        pass

    assert fake_llm.calls == [
        ("anthropic:claude-sonnet-5", {"temperature": 0.0, "api_key": "gen-key"}),
        ("anthropic:claude-sonnet-5", {"temperature": 0.0, "api_key": "gen-key"}),
        ("groq:llama-3.3-70b", {"temperature": 0.0, "api_key": "sum-key"}),
    ]


def test_as_tool_exposes_query_database(sqlite_dsn, fake_llm):
    with SQLAnalyst(make_config(sqlite_dsn)) as analyst:
        tool = analyst.as_tool(thread_id="t-1")
        result = tool.invoke("Who are the people?")

    assert tool.name == "query_database"
    assert result["success"] is True


def test_context_manager_closes_engine(sqlite_dsn, fake_llm):
    with SQLAnalyst(make_config(sqlite_dsn)) as analyst:
        assert analyst._introspector.engine is not None

    assert analyst._introspector.engine is None


def test_construction_failure_closes_engine(sqlite_dsn, monkeypatch):
    closed = []
    original_close = SchemaIntrospector.close
    monkeypatch.setattr(SchemaIntrospector, "close",
                        lambda self: closed.append(True) or original_close(self))

    def missing(*args, **kwargs):
        raise ImportError("requires the langchain-anthropic package")

    monkeypatch.setattr(models, "init_chat_model", missing)

    with pytest.raises(ConfigError, match="askyourdb\\[anthropic\\]"):
        SQLAnalyst(make_config(sqlite_dsn))

    assert closed == [True]


def test_database_without_tables_is_a_config_error(tmp_path, fake_llm):
    with pytest.raises(ConfigError, match="No tables found"):
        SQLAnalyst(make_config(f"sqlite:///{tmp_path / 'empty.sqlite'}"))


def test_missing_database_driver_is_a_config_error(sqlite_dsn, fake_llm, monkeypatch):
    def no_driver(self):
        raise ModuleNotFoundError("No module named 'psycopg2'", name="psycopg2")

    monkeypatch.setattr(SchemaIntrospector, "load_db", no_driver)

    with pytest.raises(ConfigError, match=r"psycopg2.*postgresql\+psycopg://"):
        SQLAnalyst(make_config(sqlite_dsn))

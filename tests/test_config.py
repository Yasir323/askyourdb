import pytest
from pydantic import ValidationError

from askyourdb.config import AnalystConfig, ConfigError, LLMConfig

ENV_VARS = [
    "ASKYOURDB_DSN", "ASKYOURDB_DIALECT", "ASKYOURDB_MODEL", "ASKYOURDB_API_KEY",
    "ASKYOURDB_SEMANTIC_MODEL", "ASKYOURDB_SEMANTIC_API_KEY",
    "ASKYOURDB_SUMMARY_MODEL", "ASKYOURDB_SUMMARY_API_KEY",
]
DSN = "postgresql+psycopg://reader:hunter2@db.example.com/shop"


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for name in ENV_VARS:
        monkeypatch.delenv(name, raising=False)


def make_config(**database):
    return AnalystConfig(
        database={"dsn": DSN, **database},
        models={"generator": {"model": "anthropic:claude-sonnet-5", "api_key": "sk-gen"}},
    )


def test_config_in_code_with_stage_fallback():
    config = make_config()

    assert config.database.dialect == "PostgreSQL"
    assert config.models.generator.provider == "anthropic"
    assert config.models.resolved_semantic_validator is config.models.generator
    assert config.models.resolved_summarizer is config.models.generator


def test_explicit_stage_config_wins_over_generator():
    config = AnalystConfig(
        database={"dsn": DSN},
        models={
            "generator": {"model": "anthropic:claude-sonnet-5"},
            "summarizer": {"model": "groq:llama-3.3-70b", "api_key": "gsk"},
        },
    )

    assert config.models.resolved_summarizer.model == "groq:llama-3.3-70b"
    assert config.models.resolved_semantic_validator.model == "anthropic:claude-sonnet-5"


@pytest.mark.parametrize(("dsn", "dialect"), [
    ("sqlite:///data.db", "SQLite"),
    ("mysql+pymysql://u:p@h/d", "MySQL"),
    ("postgresql://u:p@h/d", "PostgreSQL"),
])
def test_dialect_inferred_from_dsn(dsn, dialect):
    config = AnalystConfig(database={"dsn": dsn}, models={"generator": {"model": "openai:gpt-5"}})

    assert config.database.dialect == dialect


def test_explicit_dialect_is_kept():
    assert make_config(dialect="Snowflake").database.dialect == "Snowflake"


def test_unknown_backend_requires_explicit_dialect():
    with pytest.raises(ValidationError, match="ASKYOURDB_DIALECT"):
        AnalystConfig(database={"dsn": "mssql+pyodbc://u:p@h/d"},
                      models={"generator": {"model": "openai:gpt-5"}})


@pytest.mark.parametrize("model", ["gpt-5", ":gpt-5", "openai:", ""])
def test_model_requires_provider_prefix(model):
    with pytest.raises(ValidationError, match="provider:model"):
        LLMConfig(model=model)


def test_secrets_are_masked():
    config = make_config()

    assert "hunter2" not in repr(config)
    assert "sk-gen" not in repr(config)
    assert config.models.generator.api_key.get_secret_value() == "sk-gen"


def test_invalid_dsn_error_does_not_echo_it():
    with pytest.raises(ValidationError) as error:
        AnalystConfig(database={"dsn": "not a url with secret-pw"},
                      models={"generator": {"model": "openai:gpt-5"}})

    assert "secret-pw" not in str(error.value)
    assert "not a valid SQLAlchemy URL" in str(error.value)


def test_from_toml(tmp_path):
    path = tmp_path / "askyourdb.toml"
    path.write_text(
        '[database]\ndsn = "sqlite:///data.db"\n\n'
        '[models.generator]\nmodel = "openai:gpt-5"\napi_key = "sk-file"\n\n'
        '[models.summarizer]\nmodel = "groq:llama-3.3-70b"\n'
    )

    config = AnalystConfig.from_toml(path)

    assert config.database.dialect == "SQLite"
    assert config.models.generator.api_key.get_secret_value() == "sk-file"
    assert config.models.resolved_summarizer.model == "groq:llama-3.3-70b"


def test_from_toml_missing_file(tmp_path):
    with pytest.raises(ConfigError, match="not found"):
        AnalystConfig.from_toml(tmp_path / "nope.toml")


def test_from_toml_invalid_toml(tmp_path):
    path = tmp_path / "bad.toml"
    path.write_text("[database\n")

    with pytest.raises(ConfigError, match="not valid TOML"):
        AnalystConfig.from_toml(path)


def test_from_toml_missing_model_names_key(tmp_path):
    path = tmp_path / "askyourdb.toml"
    path.write_text('[database]\ndsn = "sqlite:///data.db"\n\n[models.generator]\n')

    with pytest.raises(ConfigError, match=r"models\.generator\.model.*ASKYOURDB_MODEL"):
        AnalystConfig.from_toml(path)


def test_from_env(monkeypatch):
    monkeypatch.setenv("ASKYOURDB_DSN", DSN)
    monkeypatch.setenv("ASKYOURDB_MODEL", "openai:gpt-5")
    monkeypatch.setenv("ASKYOURDB_API_KEY", "sk-env")
    monkeypatch.setenv("ASKYOURDB_SUMMARY_MODEL", "groq:llama-3.3-70b")
    monkeypatch.setenv("ASKYOURDB_SUMMARY_API_KEY", "gsk-env")

    config = AnalystConfig.from_env()

    assert config.database.dsn.get_secret_value() == DSN
    assert config.models.generator.api_key.get_secret_value() == "sk-env"
    assert config.models.resolved_summarizer.api_key.get_secret_value() == "gsk-env"
    assert config.models.semantic_validator is None


def test_from_env_overrides_take_precedence(monkeypatch):
    monkeypatch.setenv("ASKYOURDB_DSN", DSN)
    monkeypatch.setenv("ASKYOURDB_MODEL", "openai:gpt-5")

    config = AnalystConfig.from_env(model="anthropic:claude-sonnet-5", api_key="sk-code")

    assert config.models.generator.model == "anthropic:claude-sonnet-5"
    assert config.models.generator.api_key.get_secret_value() == "sk-code"


def test_from_env_treats_empty_values_as_unset(monkeypatch):
    monkeypatch.setenv("ASKYOURDB_DSN", DSN)
    monkeypatch.setenv("ASKYOURDB_MODEL", "openai:gpt-5")
    monkeypatch.setenv("ASKYOURDB_API_KEY", "")
    monkeypatch.setenv("ASKYOURDB_DIALECT", "  ")

    config = AnalystConfig.from_env()

    assert config.models.generator.api_key is None
    assert config.database.dialect == "PostgreSQL"


def test_from_env_missing_values_name_env_vars():
    with pytest.raises(ConfigError) as error:
        AnalystConfig.from_env()

    message = str(error.value)
    assert "ASKYOURDB_DSN" in message
    assert "ASKYOURDB_MODEL" in message


def test_from_env_error_does_not_echo_secrets(monkeypatch):
    monkeypatch.setenv("ASKYOURDB_DSN", DSN)
    monkeypatch.setenv("ASKYOURDB_MODEL", "no-prefix")
    monkeypatch.setenv("ASKYOURDB_API_KEY", "sk-very-secret")

    with pytest.raises(ConfigError) as error:
        AnalystConfig.from_env()

    assert "hunter2" not in str(error.value)
    assert "sk-very-secret" not in str(error.value)


def test_from_env_rejects_unknown_override():
    with pytest.raises(ConfigError, match="Unknown from_env override"):
        AnalystConfig.from_env(modle="openai:gpt-5")


def test_dsn_with_unencoded_password_chars_does_not_echo_it():
    with pytest.raises(ValidationError) as error:
        AnalystConfig(database={"dsn": "postgresql+psycopg://u:p@ss:w0rd@127.0.0.1:1/db"},
                      models={"generator": {"model": "openai:gpt-5"}})

    assert "w0rd" not in str(error.value)
    assert "not a valid SQLAlchemy URL" in str(error.value)


def test_stage_with_same_provider_inherits_generator_api_key():
    config = AnalystConfig(
        database={"dsn": DSN},
        models={
            "generator": {"model": "anthropic:claude-sonnet-5", "api_key": "sk-gen"},
            "semantic_validator": {"model": "anthropic:claude-haiku-4-5"},
            "summarizer": {"model": "groq:llama-3.3-70b"},
        },
    )

    semantic = config.models.resolved_semantic_validator
    assert semantic.model == "anthropic:claude-haiku-4-5"
    assert semantic.api_key.get_secret_value() == "sk-gen"
    assert config.models.resolved_summarizer.api_key is None


@pytest.mark.parametrize("api_key", ["", "   "])
def test_blank_toml_api_key_counts_as_unset(api_key):
    assert LLMConfig(model="openai:gpt-5", api_key=api_key).api_key is None


def test_unknown_dialect_is_rejected_at_config_time():
    with pytest.raises(ValidationError, match="unknown SQL dialect 'SQL Server'"):
        make_config(dialect="SQL Server")


@pytest.mark.parametrize("dialect", ["PostgreSQL", "postgres", "SQLite", "tsql", "Snowflake"])
def test_known_dialects_are_accepted(dialect):
    assert make_config(dialect=dialect).database.dialect == dialect

# askyourdb BYOK Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship the text-to-SQL analyst as `askyourdb`, a pip-installable, CLI-first, bring-your-own-key tool where each LLM provider is an optional extra.

**Architecture:** The `src/` package moves to `askyourdb/`. A new `config.py` holds Pydantic config models with TOML and env loaders. `models.py` builds every LLM via one `build_llm(LLMConfig)` wrapper around `init_chat_model`. `analyst.py` (`SQLAnalyst`) contains the wiring that is in `main.py` today, and `cli.py` is a stdlib-only CLI/REPL on top of it. The graph, nodes, executor, introspector and tool keep their current behaviour.

**Tech Stack:** Python 3.13, Pydantic v2, LangChain 1.x `init_chat_model`, LangGraph, SQLAlchemy 2, sqlglot, hatchling, uv, pytest.

**Spec:** `docs/superpowers/specs/2026-09-25-byok-config-design.md`

## Global Constraints

- Distribution and import name: `askyourdb`.
- Core dependencies must not include any LLM provider SDK. `psycopg[binary]` stays in core.
- Provider extras: `anthropic`→`langchain-anthropic`, `openai`→`langchain-openai`, `google`→`langchain-google-genai`, `groq`→`langchain-groq`, `ollama`→`langchain-ollama`, `all`→all five.
- Models are `provider:model` strings passed to `init_chat_model`.
- API keys and DSNs are `SecretStr` and must never appear in `repr()`, log output or `ConfigError` messages.
- Env vars: `ASKYOURDB_DSN`, `ASKYOURDB_DIALECT`, `ASKYOURDB_MODEL`, `ASKYOURDB_API_KEY`, `ASKYOURDB_SEMANTIC_MODEL`, `ASKYOURDB_SEMANTIC_API_KEY`, `ASKYOURDB_SUMMARY_MODEL`, `ASKYOURDB_SUMMARY_API_KEY`.
- The library never calls `load_dotenv()`. Only the demo `main.py` does.
- CLI exit codes: `0` success, `1` query failed, `2` configuration/connection error.
- CLI uses the standard library only (no new dependencies).
- Out of scope: prompt customization, configurable limits/retries/timeouts, table allow/deny lists, a semantic-validator toggle, Streamlit UI.
- Coverage threshold stays at `--cov-fail-under=90`.
- Commits: no `Co-Authored-By` or other AI attribution trailers (user preference).
- Repo rules (CLAUDE.md): run `gitnexus_impact({target, direction: "upstream"})` before editing any existing function/class/method and report the blast radius; warn the user on HIGH/CRITICAL; run `gitnexus_detect_changes()` before every commit.

## Review Focus

1. **SQLite/MySQL dialect names crash the validator.** When the config infers `"SQLite"` or `"MySQL"`, the SQL validator receives it and sqlglot rejects the mixed case (`Unknown dialect 'SQLite'`). A user expects a SQLite DSN to just work. Pinned in Task 2.
2. **Empty env vars copied from `.env.example`.** A line like `export ASKYOURDB_API_KEY=` should count as unset, not as an empty key. Pinned in Task 3.
3. **Secrets in error messages.** A DSN that fails to parse, or a validation failure, must not echo the password or API key. Pinned in Task 3.
4. **Provider/network errors mid-question** (401 bad key, rate limit, timeout raised from inside `graph.invoke`). `ask` should print one clean error line and exit 1; the REPL should carry on. Pinned in Task 6.
5. **Unreachable database at startup** (wrong host or password). The user should get one clean line and exit code 2, not a SQLAlchemy traceback. Pinned in Task 6.

Known limitation to keep out of docs: the current graph passes only the current question to the generator, so sharing one `thread_id` across a REPL session does **not** give real follow-up context ("now filter that by region"). The README must not promise follow-ups.

---

### Task 0: Build the GitNexus index

**Files:** none (the `.gitnexus/` index directory is gitignored)

- [ ] **Step 1: Index the repo**

Run: `npx gitnexus analyze`
Expected: completes and reports symbols and relationships for `sql-summarizer`.

- [ ] **Step 2: Confirm the MCP tools respond**

Call `gitnexus_query({query: "sql generation graph"})` and confirm it returns results. Nothing to commit.

---

### Task 1: Rename package to `askyourdb` and restructure packaging

**Files:**
- Move: `src/` → `askyourdb/` (all modules)
- Delete: `lg.py`, `new.py`
- Modify: `pyproject.toml`, `main.py` (imports only), every file under `tests/` (imports only)

**Interfaces:**
- Produces: import path `askyourdb.<module>` for every existing module. Module names are unchanged, including `schema_intropection`.

- [ ] **Step 1: Impact analysis**

Run `gitnexus_impact` (upstream) on `build_sql_graph`, `SchemaIntrospector`, `SqlValidator`, `QueryExecutor` and `build_query_database_tool`. Report the callers to the user. This task only moves files and rewrites imports; no behaviour changes.

- [ ] **Step 2: Move the package and delete scratch files**

```bash
git mv src askyourdb
git rm lg.py new.py
```

- [ ] **Step 3: Rewrite imports**

```bash
grep -rl --include=*.py -E '(^|\s)(from|import) src(\.|\s)' askyourdb tests main.py \
  | xargs sed -i '' -E 's/(from|import) src\./\1 askyourdb./g; s/(from|import) src /\1 askyourdb /g'
grep -rn --include=*.py -E '\bsrc\b' askyourdb tests main.py
```
Expected: the second grep prints nothing.

- [ ] **Step 4: Rewrite `pyproject.toml`**

```toml
[project]
name = "askyourdb"
version = "0.1.0"
description = "Ask questions of your SQL database in plain English, using your own LLM API key."
requires-python = ">=3.13"
dependencies = [
    "sqlalchemy>=2.0.52",
    "psycopg[binary]>=3.2",
    "pydantic>=2.13.5",
    "langchain>=1.3.18",
    "sqlglot>=30.18.0",
]

[project.optional-dependencies]
anthropic = ["langchain-anthropic>=1.7"]
openai = ["langchain-openai>=1.6"]
google = ["langchain-google-genai>=4.3.7"]
groq = ["langchain-groq>=1.1.3"]
ollama = ["langchain-ollama>=1.1"]
all = [
    "langchain-anthropic>=1.7",
    "langchain-openai>=1.6",
    "langchain-google-genai>=4.3.7",
    "langchain-groq>=1.1.3",
    "langchain-ollama>=1.1",
]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["askyourdb"]

[dependency-groups]
dev = [
    "pytest>=8.0.0",
    "pytest-cov>=5.0.0",
    "python-dotenv>=1.2.3",
]

[tool.pytest.ini_options]
pythonpath = ["."]
testpaths = ["tests"]
addopts = "--cov=askyourdb --cov-report=term-missing --cov-fail-under=90"
```

- [ ] **Step 5: Re-lock and sync**

Run: `uv lock && uv sync`
Expected: resolves successfully. `uv pip list | grep langchain-` shows no provider packages (the old ones are removed by `sync`).

- [ ] **Step 6: Run the suite**

Run: `uv run pytest -q`
Expected: 52 passed, coverage ≥ 90%.

- [ ] **Step 7: Re-index and check scope, then commit**

Run `npx gitnexus analyze`, then `gitnexus_detect_changes()`. Only file moves and import lines should change.
```bash
git add -A
git commit -m "Rename package to askyourdb and make provider SDKs optional extras"
```

---

### Task 2: Accept any dialect casing in `SqlValidator`

**Files:**
- Modify: `askyourdb/sql_validator.py` (`SqlValidator.__init__`)
- Test: `tests/test_sql_validator.py`

**Interfaces:**
- Produces: `SqlValidator(schema, dialect)` accepts `"PostgreSQL"`, `"SQLite"`, `"MySQL"` in any case.

- [ ] **Step 1: Impact analysis**

`gitnexus_impact({target: "SqlValidator", direction: "upstream"})`. Report the result.

- [ ] **Step 2: Write the failing test** (append to `tests/test_sql_validator.py`)

```python
@pytest.mark.parametrize("dialect", ["SQLite", "sqlite", "MySQL", "PostgreSQL", "postgres"])
def test_validator_accepts_config_dialect_names(schema, dialect):
    from askyourdb.sql_validator import SqlValidator

    result = SqlValidator(schema=schema, dialect=dialect).validate(
        "SELECT student_id FROM students"
    )

    assert result["is_valid"] is True
    assert "LIMIT 100" in result["sql_query"]
```

- [ ] **Step 3: Run it to confirm it fails**

Run: `uv run pytest tests/test_sql_validator.py -k config_dialect -v --no-cov`
Expected: the `SQLite` and `MySQL` cases fail with `ValueError: Unknown dialect 'SQLite'`.

- [ ] **Step 4: Fix it**

In `SqlValidator.__init__`, replace the `self.dialect = ...` assignment with:
```python
        self.dialect = {
            "postgresql": "postgres",
        }.get(dialect.lower(), dialect.lower())
```

- [ ] **Step 5: Run the suite**

Run: `uv run pytest -q`
Expected: all pass.

- [ ] **Step 6: Commit**

Run `gitnexus_detect_changes()` and confirm only `SqlValidator.__init__` changed.
```bash
git add askyourdb/sql_validator.py tests/test_sql_validator.py
git commit -m "Normalize SQL dialect names case-insensitively in SqlValidator"
```

---

### Task 3: Configuration models and loaders

**Files:**
- Create: `askyourdb/config.py`
- Test: `tests/test_config.py`

**Interfaces:**
- Produces:
  - `class ConfigError(ValueError)`
  - `class LLMConfig(BaseModel)`: `model: str`, `api_key: SecretStr | None = None`, `temperature: float = 0.0`, property `provider -> str`
  - `class ModelsConfig(BaseModel)`: `generator: LLMConfig`, `semantic_validator: LLMConfig | None`, `summarizer: LLMConfig | None`, properties `resolved_semantic_validator -> LLMConfig`, `resolved_summarizer -> LLMConfig`
  - `class DatabaseConfig(BaseModel)`: `dsn: SecretStr`, `dialect: str | None` (always set after validation)
  - `class AnalystConfig(BaseModel)`: `database: DatabaseConfig`, `models: ModelsConfig`, `from_toml(path) -> AnalystConfig`, `from_env(**overrides) -> AnalystConfig`
  - `from_env` override keys: `dsn`, `dialect`, `model`, `api_key`, `semantic_model`, `semantic_api_key`, `summary_model`, `summary_api_key`

- [ ] **Step 1: Write the failing tests** (`tests/test_config.py`)

```python
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
```

- [ ] **Step 2: Run to confirm failure**

Run: `uv run pytest tests/test_config.py -q --no-cov`
Expected: collection error, `ModuleNotFoundError: No module named 'askyourdb.config'`.

- [ ] **Step 3: Implement `askyourdb/config.py`**

```python
import os
import tomllib
from pathlib import Path

from pydantic import (
    BaseModel,
    ConfigDict,
    SecretStr,
    ValidationError,
    field_validator,
    model_validator,
)
from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError


class ConfigError(ValueError):
    """Raised when askyourdb configuration is missing or invalid."""


DIALECTS_BY_BACKEND = {
    "postgresql": "PostgreSQL",
    "sqlite": "SQLite",
    "mysql": "MySQL",
}

ENV_PREFIX = "ASKYOURDB_"

# from_env key -> path inside the AnalystConfig data. The env var is
# ENV_PREFIX + key.upper().
ENV_FIELDS = {
    "dsn": ("database", "dsn"),
    "dialect": ("database", "dialect"),
    "model": ("models", "generator", "model"),
    "api_key": ("models", "generator", "api_key"),
    "semantic_model": ("models", "semantic_validator", "model"),
    "semantic_api_key": ("models", "semantic_validator", "api_key"),
    "summary_model": ("models", "summarizer", "model"),
    "summary_api_key": ("models", "summarizer", "api_key"),
}
ENV_VAR_BY_FIELD = {
    ".".join(path): ENV_PREFIX + key.upper() for key, path in ENV_FIELDS.items()
}


class _Model(BaseModel):
    # Never echo raw input (DSNs, keys) back in validation errors.
    model_config = ConfigDict(hide_input_in_errors=True)


class LLMConfig(_Model):
    model: str
    api_key: SecretStr | None = None
    temperature: float = 0.0

    @field_validator("model")
    @classmethod
    def _require_provider_prefix(cls, value: str) -> str:
        provider, separator, name = value.partition(":")
        if not (separator and provider.strip() and name.strip()):
            raise ValueError(
                "must be 'provider:model', e.g. 'anthropic:claude-sonnet-5'"
            )
        return value

    @property
    def provider(self) -> str:
        return self.model.partition(":")[0]


class ModelsConfig(_Model):
    generator: LLMConfig
    semantic_validator: LLMConfig | None = None
    summarizer: LLMConfig | None = None

    @property
    def resolved_semantic_validator(self) -> LLMConfig:
        return self.semantic_validator or self.generator

    @property
    def resolved_summarizer(self) -> LLMConfig:
        return self.summarizer or self.generator


class DatabaseConfig(_Model):
    dsn: SecretStr
    dialect: str | None = None

    @model_validator(mode="after")
    def _infer_dialect(self) -> "DatabaseConfig":
        if self.dialect and self.dialect.strip():
            return self
        try:
            backend = make_url(self.dsn.get_secret_value()).get_backend_name()
        except ArgumentError:
            # ArgumentError's message contains the DSN, so don't chain it.
            raise ValueError("database.dsn is not a valid SQLAlchemy URL") from None
        dialect = DIALECTS_BY_BACKEND.get(backend)
        if dialect is None:
            raise ValueError(
                f"cannot infer the SQL dialect for database backend '{backend}'; "
                f"set database.dialect (env {ENV_PREFIX}DIALECT)"
            )
        self.dialect = dialect
        return self


class AnalystConfig(_Model):
    database: DatabaseConfig
    models: ModelsConfig

    @classmethod
    def from_toml(cls, path: str | Path) -> "AnalystConfig":
        path = Path(path)
        try:
            with path.open("rb") as handle:
                data = tomllib.load(handle)
        except FileNotFoundError:
            raise ConfigError(f"Config file not found: {path}") from None
        except tomllib.TOMLDecodeError as error:
            raise ConfigError(f"Config file {path} is not valid TOML: {error}") from None
        return cls._validate(data, source=str(path))

    @classmethod
    def from_env(cls, **overrides: str | None) -> "AnalystConfig":
        unknown = set(overrides) - ENV_FIELDS.keys()
        if unknown:
            raise ConfigError(
                f"Unknown from_env override(s): {', '.join(sorted(unknown))}"
            )

        values = {}
        for key in ENV_FIELDS:
            value = os.environ.get(ENV_PREFIX + key.upper(), "").strip()
            if value:
                values[key] = value
        values.update({key: value for key, value in overrides.items() if value})

        # Start from the required skeleton so missing values are reported as
        # e.g. database.dsn (with its env var) rather than a missing section.
        data: dict = {"database": {}, "models": {"generator": {}}}
        for key, value in values.items():
            *parents, leaf = ENV_FIELDS[key]
            node = data
            for part in parents:
                node = node.setdefault(part, {})
            node[leaf] = value
        return cls._validate(data, source="environment")

    @classmethod
    def _validate(cls, data: dict, source: str) -> "AnalystConfig":
        try:
            return cls.model_validate(data)
        except ValidationError as error:
            raise _config_error(error, source) from None


def _config_error(error: ValidationError, source: str) -> ConfigError:
    lines = [f"Invalid askyourdb configuration ({source}):"]
    for item in error.errors():
        field = ".".join(str(part) for part in item["loc"])
        env_var = ENV_VAR_BY_FIELD.get(field)
        hint = f" (TOML key '{field}', env {env_var})" if env_var else ""
        lines.append(f"- {field or 'config'}: {item['msg']}{hint}")
    return ConfigError("\n".join(lines))
```

- [ ] **Step 4: Run the tests**

Run: `uv run pytest tests/test_config.py -v --no-cov`
Expected: all pass. If `test_from_toml_missing_model_names_key` fails on the regex because of line breaks, check the message format (one line per error). Adjust the implementation, not the test.

- [ ] **Step 5: Full suite and commit**

Run: `uv run pytest -q`. Expected: all pass, coverage ≥ 90%.
Run `gitnexus_detect_changes()` and confirm only new symbols appear.
```bash
git add askyourdb/config.py tests/test_config.py
git commit -m "Add AnalystConfig with TOML and environment loaders"
```

---

### Task 4: BYOK model construction and example-free prompt

**Files:**
- Modify: `askyourdb/models.py`
- Test: `tests/test_models_and_introspection.py`, `tests/integration/test_sqlite_pipeline.py`

**Interfaces:**
- Consumes: `LLMConfig`, `ConfigError` from `askyourdb.config`
- Produces:
  - `build_llm(config: LLMConfig) -> BaseChatModel`
  - `build_sql_generator(schema_text: str, dialect: str, llm_config: LLMConfig)`
  - `build_sql_semantic_validator(llm_config: LLMConfig)`
  - `build_result_summarizer(llm_config: LLMConfig)`
  - `PROVIDER_EXTRAS: dict[str, str]`

- [ ] **Step 1: Impact analysis**

Run `gitnexus_impact` upstream on `build_sql_generator`, `build_sql_semantic_validator` and `build_result_summarizer`. Expected callers: `main.py` and tests. Report the result.

- [ ] **Step 2: Write the failing tests**

In `tests/test_models_and_introspection.py`, replace `test_model_builders_create_structured_chains` with:

```python
from askyourdb.config import ConfigError, LLMConfig


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
    summarizer = models.build_result_summarizer(LLMConfig(model="ollama:llama3"))

    assert generator is not None and semantic is not None and summarizer is not None
    assert [args[0] for args, _ in calls] == [
        "openai:gpt-5", "groq:llama-3.3-70b", "ollama:llama3",
    ]


def test_build_llm_passes_api_key_only_when_set(monkeypatch):
    calls = []
    monkeypatch.setattr(models, "init_chat_model",
                        lambda model, **kwargs: calls.append(kwargs) or FakeChatModel())

    models.build_llm(LLMConfig(model="openai:gpt-5", api_key="sk-1", temperature=0.2))
    models.build_llm(LLMConfig(model="openai:gpt-5"))

    assert calls == [{"temperature": 0.2, "api_key": "sk-1"}, {"temperature": 0.0}]


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
```
Add `import pytest` at the top of the file if it is missing.

In `tests/integration/test_sqlite_pipeline.py`, change the generator construction to:
```python
    from askyourdb.config import LLMConfig
    from askyourdb.models import build_sql_generator

    generator = build_sql_generator(
        schema_text=schema_text, dialect="SQLite",
        llm_config=LLMConfig(model="google_genai:gemini-3.5-flash-lite"),
    )
```

- [ ] **Step 3: Run to confirm failure**

Run: `uv run pytest tests/test_models_and_introspection.py tests/integration -q --no-cov`
Expected: failures such as `AttributeError: ... has no attribute 'build_llm'` and `TypeError` on the new builder arguments.

- [ ] **Step 4: Implement in `askyourdb/models.py`**

- Remove `import os`, the `FEW_SHOT_EXAMPLES` constant, and the trailing `\n\nExamples:\n{few_shot_examples}` from `SQL_GEN_SYSTEM`, so the template ends at `{schema}\n"""`.
- Add imports and `build_llm` below the existing imports:

```python
from askyourdb.config import ConfigError, LLMConfig

# init_chat_model provider name -> askyourdb pip extra that installs it.
PROVIDER_EXTRAS = {
    "anthropic": "anthropic",
    "openai": "openai",
    "google_genai": "google",
    "groq": "groq",
    "ollama": "ollama",
}


def build_llm(config: LLMConfig):
    """Create the chat model for one pipeline stage from the user's config.

    The key is only passed when configured; otherwise the provider SDK reads its
    standard environment variable (ANTHROPIC_API_KEY, OPENAI_API_KEY, ...).
    """
    kwargs = {"temperature": config.temperature}
    if config.api_key is not None:
        kwargs["api_key"] = config.api_key.get_secret_value()
    try:
        return init_chat_model(config.model, **kwargs)
    except ImportError as error:
        extra = PROVIDER_EXTRAS.get(config.provider)
        hint = (
            f'pip install "askyourdb[{extra}]"' if extra
            else f"install the LangChain integration package for '{config.provider}'"
        )
        raise ConfigError(
            f"The '{config.provider}' model provider is not installed. "
            f"Run: {hint}\n({error})"
        ) from None
    except ValueError as error:
        raise ConfigError(
            f"Could not initialize model '{config.model}': {error}"
        ) from None
```

- Change the three builders:

```python
def build_sql_generator(schema_text: str, dialect: str, llm_config: LLMConfig):
    """Build the prompt -> model -> SQLQuery chain.

    The schema and dialect are the same for every question, so they are bound
    once with .partial(). Only {question} is left to supply at call time.
    """
    prompt = ChatPromptTemplate.from_messages([
        ("system", SQL_GEN_SYSTEM),
        ("human", "{question}"),
    ]).partial(
        dialect=dialect,
        schema=schema_text,
    )
    return prompt | build_llm(llm_config).with_structured_output(SQLQuery)
```
In `build_sql_semantic_validator(llm_config: LLMConfig)` and `build_result_summarizer(llm_config: LLMConfig)`, replace the `model_name = os.environ.get(...)` and `init_chat_model(...)` lines with `model = build_llm(llm_config)`. The prompts stay unchanged.

- [ ] **Step 5: Run the suite**

Run: `uv run pytest -q`
Expected: all pass. `main.py` is now broken (it calls the old builder signatures); Task 5 rewrites it. It is outside the coverage scope.

- [ ] **Step 6: Commit**

Run `gitnexus_detect_changes()` and confirm the three builders and the new `build_llm` are the only changed symbols.
```bash
git add askyourdb/models.py tests/test_models_and_introspection.py tests/integration/test_sqlite_pipeline.py
git commit -m "Build LLMs from user-supplied config and drop school few-shot examples"
```

---

### Task 5: `SQLAnalyst` facade, public exports, demo rewrite

**Files:**
- Create: `askyourdb/analyst.py`
- Modify: `askyourdb/__init__.py`, `main.py`
- Test: `tests/test_analyst.py`

**Interfaces:**
- Consumes: `AnalystConfig` (Task 3); `build_sql_generator(schema_text, dialect, llm_config)`, `build_sql_semantic_validator(llm_config)`, `build_result_summarizer(llm_config)`, `render_schema(schema)` (Task 4); existing `SchemaIntrospector(dsn)`, `SqlValidator(schema, dialect)`, `QueryExecutor(engine)`, `build_sql_graph(...)`, `build_query_database_tool(graph, schema_text, dialect, *, thread_id)`
- Produces: `SQLAnalyst(config)` with `.ask(question: str, thread_id: str | None = None) -> dict`, `.as_tool(thread_id: str | None = None) -> StructuredTool`, `.close()`, context manager. `ask` returns the tool's dict: `success`, `answer`, `row_count`, `sql_used`, `caveats`, `rows`, `error`.

- [ ] **Step 1: Impact analysis**

Run `gitnexus_impact` upstream on `main` (in `main.py`). Report the result.

- [ ] **Step 2: Write the failing tests** (`tests/test_analyst.py`)

```python
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
```

- [ ] **Step 3: Run to confirm failure**

Run: `uv run pytest tests/test_analyst.py -q --no-cov`
Expected: `ImportError: cannot import name 'AnalystConfig' from 'askyourdb'`.

- [ ] **Step 4: Implement `askyourdb/analyst.py`**

```python
from uuid import uuid4

from langchain_core.tools import StructuredTool

from askyourdb.config import AnalystConfig
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
from askyourdb.tools import build_query_database_tool


class SQLAnalyst:
    """Answer natural-language questions about a database using your own LLM keys."""

    def __init__(self, config: AnalystConfig):
        self.config = config
        self._dialect = config.database.dialect
        self._introspector = SchemaIntrospector(config.database.dsn.get_secret_value())
        try:
            self._introspector.load_db()
            schema = self._introspector.get_schema()
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

    def ask(self, question: str, thread_id: str | None = None) -> dict:
        return self.as_tool(thread_id).invoke(question)

    def close(self) -> None:
        self._introspector.close()

    def __enter__(self) -> "SQLAnalyst":
        return self

    def __exit__(self, *exc_info) -> None:
        self.close()
```

Set `askyourdb/__init__.py` to:
```python
from askyourdb.analyst import SQLAnalyst
from askyourdb.config import (
    AnalystConfig,
    ConfigError,
    DatabaseConfig,
    LLMConfig,
    ModelsConfig,
)

__all__ = [
    "AnalystConfig",
    "ConfigError",
    "DatabaseConfig",
    "LLMConfig",
    "ModelsConfig",
    "SQLAnalyst",
]
```

- [ ] **Step 5: Run the tests**

Run: `uv run pytest tests/test_analyst.py -v --no-cov`, then `uv run pytest -q`.
Expected: all pass, coverage ≥ 90%. If importing `askyourdb` from `askyourdb/models.py` (via `askyourdb.config`) creates an import cycle, keep `__init__` imports as written. `config.py` imports nothing from the package, so there should be no cycle.

- [ ] **Step 6: Rewrite the demo `main.py`**

```python
import warnings

from dotenv import load_dotenv

from askyourdb import AnalystConfig, SQLAnalyst
from askyourdb.observability import configure_langsmith

warnings.filterwarnings("ignore")
QUESTION = "Which five students owe the most in unpaid fees?"


def main():
    """Demo against the bundled school database (see db/README.md and .env.example)."""
    load_dotenv()
    configure_langsmith()
    with SQLAnalyst(AnalystConfig.from_env()) as analyst:
        result = analyst.ask(QUESTION)

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


if __name__ == "__main__":
    main()
```
Check it compiles: `uv run python -c "import main"`. Expected: no output, no error.

- [ ] **Step 7: Commit**

Run `gitnexus_detect_changes()`.
```bash
git add askyourdb/analyst.py askyourdb/__init__.py main.py tests/test_analyst.py
git commit -m "Add SQLAnalyst facade and rebuild the school demo on it"
```

---

### Task 6: `askyourdb` CLI and REPL

**Files:**
- Create: `askyourdb/cli.py`
- Modify: `pyproject.toml` (add `[project.scripts]`)
- Test: `tests/test_cli.py`

**Interfaces:**
- Consumes: `SQLAnalyst`, `AnalystConfig.from_toml/from_env`, `ConfigError`, `configure_langsmith()`
- Produces: `main(argv: list[str] | None = None) -> int`, `format_result(result: dict, show_rows: bool) -> str`, `format_rows(rows: list[dict]) -> str`; console script `askyourdb`.

- [ ] **Step 1: Write the failing tests** (`tests/test_cli.py`)

```python
import json
from decimal import Decimal

import pytest
from sqlalchemy.exc import OperationalError

import askyourdb.cli as cli
from askyourdb.config import ConfigError

OK = {
    "success": True, "answer": "Ada owes the most.", "row_count": 1,
    "sql_used": "SELECT name, owed FROM people LIMIT 100",
    "caveats": ["Sample data"], "rows": [{"name": "Ada", "owed": Decimal("12.50")}],
    "error": None,
}
FAILED = {
    "success": False, "answer": None, "row_count": 0, "sql_used": "SELECT bad",
    "caveats": [], "rows": [], "error": "Unknown column 'bad'",
}


class FakeAnalyst:
    instances = []
    results = []
    init_error = None

    def __init__(self, config):
        if FakeAnalyst.init_error:
            raise FakeAnalyst.init_error
        self.config = config
        self.questions = []
        self.closed = False
        FakeAnalyst.instances.append(self)

    def ask(self, question, thread_id=None):
        self.questions.append((question, thread_id))
        result = FakeAnalyst.results.pop(0)
        if isinstance(result, BaseException):
            raise result
        return result

    def close(self):
        self.closed = True

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        self.close()


@pytest.fixture(autouse=True)
def fake_analyst(monkeypatch):
    FakeAnalyst.instances, FakeAnalyst.results, FakeAnalyst.init_error = [], [], None
    monkeypatch.setattr(cli, "SQLAnalyst", FakeAnalyst)
    monkeypatch.setenv("ASKYOURDB_DSN", "sqlite:///env.db")
    monkeypatch.setenv("ASKYOURDB_MODEL", "openai:gpt-5")
    return FakeAnalyst


def feed_input(monkeypatch, *lines):
    items = list(lines)

    def fake_input(prompt=""):
        if not items:
            raise EOFError
        item = items.pop(0)
        if isinstance(item, BaseException):
            raise item
        return item

    monkeypatch.setattr("builtins.input", fake_input)


def test_ask_prints_answer_sql_row_count_and_caveats(capsys):
    FakeAnalyst.results = [OK]

    code = cli.main(["ask", "Who owes the most?"])

    out = capsys.readouterr().out
    assert code == 0
    assert "Ada owes the most." in out
    assert "SELECT name, owed FROM people LIMIT 100" in out
    assert "Rows: 1" in out
    assert "- Sample data" in out
    assert "12.50" not in out  # rows only with --rows
    assert FakeAnalyst.instances[0].questions == [("Who owes the most?", None)]
    assert FakeAnalyst.instances[0].closed is True


def test_ask_rows_flag_prints_table(capsys):
    FakeAnalyst.results = [OK]

    cli.main(["ask", "q", "--rows"])

    out = capsys.readouterr().out
    assert "name  owed" in out
    assert "Ada   12.50" in out


def test_format_rows_handles_empty_and_null():
    assert cli.format_rows([]) == "(no rows)"
    assert "NULL" in cli.format_rows([{"a": None}])


def test_ask_json_output(capsys):
    FakeAnalyst.results = [OK]

    code = cli.main(["ask", "q", "--json"])

    data = json.loads(capsys.readouterr().out)
    assert code == 0
    assert data["rows"] == [{"name": "Ada", "owed": "12.50"}]


def test_ask_failed_query_exits_1(capsys):
    FakeAnalyst.results = [FAILED]

    code = cli.main(["ask", "q"])

    assert code == 1
    assert "Error: Unknown column 'bad'" in capsys.readouterr().out


def test_ask_provider_exception_exits_1_without_traceback(capsys):
    FakeAnalyst.results = [RuntimeError("401 invalid x-api-key\nmore detail")]

    code = cli.main(["ask", "q"])

    out = capsys.readouterr().out
    assert code == 1
    assert "Error: RuntimeError: 401 invalid x-api-key" in out
    assert "more detail" not in out
    assert "Traceback" not in out


def test_config_error_exits_2(monkeypatch, capsys):
    monkeypatch.delenv("ASKYOURDB_DSN")

    code = cli.main(["ask", "q"])

    assert code == 2
    assert "ASKYOURDB_DSN" in capsys.readouterr().err


def test_missing_provider_package_exits_2(capsys):
    FakeAnalyst.init_error = ConfigError('Run: pip install "askyourdb[anthropic]"')

    code = cli.main(["ask", "q"])

    assert code == 2
    assert 'pip install "askyourdb[anthropic]"' in capsys.readouterr().err


def test_unreachable_database_exits_2(capsys):
    FakeAnalyst.init_error = OperationalError(
        "SELECT 1", {}, Exception("connection refused\nis the server running?"),
    )

    code = cli.main(["ask", "q"])

    err = capsys.readouterr().err
    assert code == 2
    assert "Could not connect to the database" in err
    assert "connection refused" in err


def test_config_file_is_used_instead_of_env(tmp_path):
    path = tmp_path / "askyourdb.toml"
    path.write_text('[database]\ndsn = "sqlite:///file.db"\n\n'
                    '[models.generator]\nmodel = "groq:llama-3.3-70b"\n')
    FakeAnalyst.results = [OK]

    cli.main(["--config", str(path), "ask", "q"])

    config = FakeAnalyst.instances[0].config
    assert config.database.dsn.get_secret_value() == "sqlite:///file.db"


def test_repl_is_default_and_shares_thread(monkeypatch, capsys):
    FakeAnalyst.results = [OK, OK]
    feed_input(monkeypatch, "", "first?", "  second?  ", "exit")

    code = cli.main([])

    analyst = FakeAnalyst.instances[0]
    assert code == 0
    assert [q for q, _ in analyst.questions] == ["first?", "second?"]
    thread_ids = {t for _, t in analyst.questions}
    assert len(thread_ids) == 1 and None not in thread_ids
    assert "12.50" in capsys.readouterr().out  # REPL shows rows
    assert analyst.closed is True


def test_repl_continues_after_failures_and_interrupts(monkeypatch, capsys):
    FakeAnalyst.results = [FAILED, RuntimeError("rate limited"), KeyboardInterrupt(), OK]
    feed_input(monkeypatch, "a", "b", KeyboardInterrupt(), "c", "d", "quit")

    code = cli.main(["repl"])

    out = capsys.readouterr().out
    assert code == 0
    assert "Unknown column 'bad'" in out
    assert "rate limited" in out
    assert "Cancelled." in out
    assert "Ada owes the most." in out


def test_repl_ends_on_eof(monkeypatch):
    feed_input(monkeypatch)

    assert cli.main(["repl"]) == 0
    assert FakeAnalyst.instances[0].closed is True
```

- [ ] **Step 2: Run to confirm failure**

Run: `uv run pytest tests/test_cli.py -q --no-cov`
Expected: `ModuleNotFoundError: No module named 'askyourdb.cli'`.

- [ ] **Step 3: Implement `askyourdb/cli.py`**

```python
import argparse
import json
import sys
from uuid import uuid4

from sqlalchemy.exc import SQLAlchemyError

from askyourdb.analyst import SQLAnalyst
from askyourdb.config import AnalystConfig, ConfigError
from askyourdb.observability import configure_langsmith

EXIT_OK = 0
EXIT_QUERY_FAILED = 1
EXIT_CONFIG_ERROR = 2
EXIT_COMMANDS = {"exit", "quit"}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="askyourdb",
        description="Ask questions of your database in plain English, "
                    "using your own LLM API key.",
    )
    parser.add_argument(
        "--config", metavar="PATH",
        help="TOML config file (default: ASKYOURDB_* environment variables)",
    )
    commands = parser.add_subparsers(dest="command")
    ask = commands.add_parser("ask", help="answer one question and exit")
    ask.add_argument("question")
    ask.add_argument("--json", action="store_true", help="print the full result as JSON")
    ask.add_argument("--rows", action="store_true", help="also print the returned rows")
    commands.add_parser("repl", help="interactive session (the default)")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    configure_langsmith()
    try:
        config = (
            AnalystConfig.from_toml(args.config) if args.config
            else AnalystConfig.from_env()
        )
        analyst = SQLAnalyst(config)
    except ConfigError as error:
        print(f"Configuration error: {error}", file=sys.stderr)
        return EXIT_CONFIG_ERROR
    except SQLAlchemyError as error:
        print(f"Could not connect to the database: {_first_line(error)}", file=sys.stderr)
        return EXIT_CONFIG_ERROR

    with analyst:
        if args.command == "ask":
            return run_ask(analyst, args.question, as_json=args.json, show_rows=args.rows)
        return run_repl(analyst)


def run_ask(analyst: SQLAnalyst, question: str, *, as_json: bool, show_rows: bool) -> int:
    result = _ask(analyst, question)
    if as_json:
        print(json.dumps(result, indent=2, default=str))
    else:
        print(format_result(result, show_rows=show_rows))
    return EXIT_OK if result["success"] else EXIT_QUERY_FAILED


def run_repl(analyst: SQLAnalyst) -> int:
    _enable_line_editing()
    thread_id = f"askyourdb-repl-{uuid4()}"
    print("askyourdb: ask a question, or type 'exit' to quit.")
    while True:
        try:
            question = input("askyourdb> ").strip()
        except EOFError:
            print()
            return EXIT_OK
        except KeyboardInterrupt:
            print()
            continue
        if not question:
            continue
        if question.lower() in EXIT_COMMANDS:
            return EXIT_OK
        try:
            result = _ask(analyst, question, thread_id)
        except KeyboardInterrupt:
            print("Cancelled.")
            continue
        print(format_result(result, show_rows=True))
        print()


def format_result(result: dict, show_rows: bool) -> str:
    lines = [result["answer"] if result["success"] else f"Error: {result['error']}"]
    if result["sql_used"]:
        lines += ["", "SQL:", result["sql_used"]]
    if result["success"]:
        lines += ["", f"Rows: {result['row_count']}"]
    if result["caveats"]:
        lines += ["", "Caveats:"] + [f"- {caveat}" for caveat in result["caveats"]]
    if show_rows and result["success"]:
        lines += ["", format_rows(result["rows"])]
    return "\n".join(lines)


def format_rows(rows: list[dict]) -> str:
    if not rows:
        return "(no rows)"
    headers = list(rows[0].keys())
    table = [headers] + [
        ["NULL" if row.get(h) is None else str(row.get(h)) for h in headers]
        for row in rows
    ]
    widths = [max(len(line[i]) for line in table) for i in range(len(headers))]

    def render(cells):
        return "  ".join(cell.ljust(width) for cell, width in zip(cells, widths)).rstrip()

    return "\n".join(
        [render(table[0]), "  ".join("-" * width for width in widths)]
        + [render(line) for line in table[1:]]
    )


def _ask(analyst: SQLAnalyst, question: str, thread_id: str | None = None) -> dict:
    """Run one question; turn provider/network errors into a failed result."""
    try:
        return analyst.ask(question, thread_id=thread_id)
    except Exception as error:
        return {
            "success": False, "answer": None, "row_count": 0, "sql_used": None,
            "caveats": [], "rows": [],
            "error": f"{type(error).__name__}: {_first_line(error)}",
        }


def _first_line(error: BaseException) -> str:
    text = str(getattr(error, "orig", None) or error)
    return text.strip().splitlines()[0] if text.strip() else type(error).__name__


def _enable_line_editing() -> None:
    try:
        import readline  # noqa: F401  (enables history and arrow keys for input())
    except ImportError:
        pass
```

Add to `pyproject.toml` after `[project.optional-dependencies]`:
```toml
[project.scripts]
askyourdb = "askyourdb.cli:main"
```

- [ ] **Step 4: Run the tests**

Run: `uv run pytest tests/test_cli.py -v --no-cov`, then `uv run pytest -q`.
Expected: all pass, coverage ≥ 90%.

- [ ] **Step 5: Smoke-test the console script**

Run: `uv sync && env -u ASKYOURDB_DSN uv run askyourdb ask "hi"; echo "exit=$?"`
Expected: `Configuration error: Invalid askyourdb configuration (environment): ...ASKYOURDB_DSN...` on stderr, `exit=2`.

- [ ] **Step 6: Commit**

Run `gitnexus_detect_changes()`.
```bash
git add askyourdb/cli.py tests/test_cli.py pyproject.toml uv.lock
git commit -m "Add askyourdb CLI with one-shot ask and interactive REPL"
```

---

### Task 7: Docs, sample config, minimal-install verification

**Files:**
- Create: `README.md`, `askyourdb.example.toml`
- Modify: `.env.example`, `pyproject.toml` (`readme = "README.md"`)

- [ ] **Step 1: Write `askyourdb.example.toml`**

```toml
# Copy to askyourdb.toml and run:  askyourdb --config askyourdb.toml
# Keep real keys out of git (or omit api_key and use the provider's env var).

[database]
# Use a read-only database user.
dsn = "postgresql+psycopg://readonly_user:password@localhost:5432/mydb"
# dialect = "PostgreSQL"   # inferred for postgresql / sqlite / mysql DSNs

[models.generator]
model = "anthropic:claude-sonnet-5"
# api_key = "sk-ant-..."   # default: ANTHROPIC_API_KEY
# temperature = 0.0

# Optional: use different (e.g. cheaper) models for the other stages.
# Each defaults to the generator settings.
# [models.semantic_validator]
# model = "groq:llama-3.3-70b-versatile"
# [models.summarizer]
# model = "openai:gpt-5-mini"
```

- [ ] **Step 2: Rewrite `.env.example`**

```bash
# Copy to .env, fill in, then `source .env` (or use --config with a TOML file).
# .env is gitignored — never commit real keys.
export ASKYOURDB_DSN=postgresql+psycopg://school:school@localhost:5432/school_db
export ASKYOURDB_MODEL=google_genai:gemini-3.5-flash-lite
export ASKYOURDB_API_KEY=

# Optional
# export ASKYOURDB_DIALECT=PostgreSQL
# export ASKYOURDB_SEMANTIC_MODEL=
# export ASKYOURDB_SEMANTIC_API_KEY=
# export ASKYOURDB_SUMMARY_MODEL=
# export ASKYOURDB_SUMMARY_API_KEY=
# export LANGCHAIN_TRACING_V2=true
# export LANGCHAIN_API_KEY=
```

- [ ] **Step 3: Write `README.md`**

Sections, in order (write real prose and commands, no placeholders):
1. **askyourdb**: one paragraph. Ask a SQL database questions in plain English. The LLM writes a read-only `SELECT`, the SQL is statically validated (read-only, known tables and columns, `LIMIT` enforced), a second LLM pass reviews it, the query runs, and the results are summarized. You always see the SQL that ran.
2. **Install**: `pip install "askyourdb[anthropic]"` plus a table of extras (`anthropic`, `openai`, `google`, `groq`, `ollama`, `all`) with an example model string for each (`anthropic:claude-sonnet-5`, `openai:gpt-5`, `google_genai:gemini-3.5-flash-lite`, `groq:llama-3.3-70b-versatile`, `ollama:llama3`). Note that any other `init_chat_model` provider works if its LangChain package is installed.
3. **Quickstart (CLI)**: export `ASKYOURDB_DSN`, `ASKYOURDB_MODEL`, `ASKYOURDB_API_KEY`; `askyourdb ask "..."`, `--rows`, `--json`; `askyourdb` for the REPL (`exit`/Ctrl-D to quit); `askyourdb --config askyourdb.toml`. State that each REPL question is answered independently.
4. **Configuration reference**: a table of all 8 env vars with their TOML keys and defaults (stage models fall back to the generator; the dialect is inferred for postgresql/sqlite/mysql). Precedence: `--config` file, otherwise env. A missing `api_key` falls back to the provider's own env var.
5. **Bring your own key**: keys stay on your machine and go only to the provider you pick; they are stored as `SecretStr` and never logged or shown in errors. Use a read-only database user.
6. **Use from Python**: the `SQLAnalyst` / `AnalystConfig` snippet from the spec's Goal section, plus `AnalystConfig.from_env()` / `from_toml()`, `analyst.as_tool()`, and the result dict keys.
7. **Exit codes**: 0 / 1 / 2.
8. **Development / school demo**: `docker compose up -d`, `cp .env.example .env`, `uv sync --extra google`, `uv run python main.py`, `uv run pytest`.

Then add `readme = "README.md"` under `[project]` in `pyproject.toml`.

- [ ] **Step 4: Verify the minimal install from a built wheel**

```bash
uv build
python3.13 -m venv /tmp/askyourdb-venv-check
/tmp/askyourdb-venv-check/bin/pip install -q "$(ls dist/askyourdb-0.1.0-*.whl)[anthropic]"
/tmp/askyourdb-venv-check/bin/pip list 2>/dev/null | grep -i -E "langchain-(anthropic|openai|google|groq|ollama)"
env -u ASKYOURDB_DSN /tmp/askyourdb-venv-check/bin/askyourdb ask hi; echo "exit=$?"
rm -rf /tmp/askyourdb-venv-check dist
```
(Use the session scratchpad directory instead of `/tmp` if running as the agent.)
Expected: only `langchain-anthropic` is listed; the CLI prints a configuration error and `exit=2`.

- [ ] **Step 5: Full suite and commit**

Run: `uv run pytest -q`. Expected: all pass, coverage ≥ 90%.
Run `gitnexus_detect_changes()`.
```bash
git add README.md askyourdb.example.toml .env.example pyproject.toml uv.lock
git commit -m "Document askyourdb install, CLI, configuration and BYOK usage"
```

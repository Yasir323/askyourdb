# askyourdb — BYOK packaging & configuration design

Date: 2026-09-25
Branch: `feature/byok-config`

## Goal

Turn the text-to-SQL analyst into an installable, CLI-first tool named **askyourdb**
that anyone can point at their own database with their own LLM provider and API key
(bring-your-own-key), without editing source code.

Success: a user runs `pip install "askyourdb[anthropic]"`, exports their key and DSN,
and runs

```bash
askyourdb ask "Which five customers spent the most last month?"
askyourdb            # interactive REPL
```

The same engine is importable for Python users (secondary surface):

```python
from askyourdb import AnalystConfig, SQLAnalyst

config = AnalystConfig(
    database={"dsn": "postgresql+psycopg://ro_user:pw@host/db"},
    models={"generator": {"model": "anthropic:claude-sonnet-5", "api_key": "sk-..."}},
)
with SQLAnalyst(config) as analyst:
    result = analyst.ask("Which five customers spent the most last month?")
```

## Decisions (from brainstorming)

- Audience: CLI-first. Primary surface is the `askyourdb` command (one-shot `ask`
  and an interactive REPL). The `SQLAnalyst` class that the CLI is built on is
  importable and documented briefly as a secondary Python surface. No hosted /
  multi-user server; a Streamlit UI is a possible follow-up, out of scope here.
- Providers: any provider supported by LangChain `init_chat_model`, addressed as
  `provider:model` strings. Each provider SDK is an optional extra.
- Minimal install: the core package depends on no LLM provider SDK.
  `pip install "askyourdb[anthropic]"` installs core + `langchain-anthropic` only.
- `psycopg[binary]` stays a core dependency (Postgres is the primary target).
- Out of scope (explicitly declined): prompt customization, configurable row
  limits / retries / timeouts, table allow/deny lists, toggling the semantic
  validator. Existing hardcoded values for these stay as they are.
- School-specific few-shot examples are removed from the SQL generation prompt.
- Name: `askyourdb` (PyPI name and import name). `dbgpt` was rejected because it is
  already taken on PyPI by DB-GPT.

## Package layout

The `src/` package is moved to `askyourdb/` (import path `askyourdb.*`); all internal
and test imports are updated. Module names inside are unchanged, plus three new
modules:

- `askyourdb/config.py` — configuration models and loaders.
- `askyourdb/analyst.py` — `SQLAnalyst` engine facade.
- `askyourdb/cli.py` — `askyourdb` command (one-shot + REPL).

`askyourdb/__init__.py` exports `AnalystConfig`, `LLMConfig`, `ModelsConfig`,
`DatabaseConfig`, `ConfigError`, `SQLAnalyst`.

The unused scratch scripts `lg.py` and `new.py` are deleted. `main.py` stays as the
school-database demo, rewritten on top of `SQLAnalyst`.

## Configuration (`askyourdb/config.py`)

Pydantic v2 models:

```python
class LLMConfig(BaseModel):
    model: str                      # "provider:model", e.g. "openai:gpt-5"
    api_key: SecretStr | None = None
    temperature: float = 0.0

class ModelsConfig(BaseModel):
    generator: LLMConfig
    semantic_validator: LLMConfig | None = None   # falls back to generator
    summarizer: LLMConfig | None = None           # falls back to generator

class DatabaseConfig(BaseModel):
    dsn: SecretStr
    dialect: str | None = None      # inferred from DSN scheme when omitted

class AnalystConfig(BaseModel):
    database: DatabaseConfig
    models: ModelsConfig
```

Rules:

- `model` must contain a `provider:` prefix; otherwise `ConfigError`.
- `ModelsConfig` exposes resolved accessors so callers never see `None`: a missing
  stage config is the generator config.
- Dialect inference from the SQLAlchemy URL backend name:
  `postgresql` → `PostgreSQL`, `sqlite` → `SQLite`, `mysql` → `MySQL`; any other
  backend requires an explicit `dialect`, else `ConfigError`.
- `api_key` and `dsn` are `SecretStr`, so they never appear in `repr()`, logs, or
  exception messages.
- When `api_key` is `None`, nothing is passed to the provider and the provider SDK
  reads its standard env var (`ANTHROPIC_API_KEY`, `OPENAI_API_KEY`,
  `GOOGLE_API_KEY`, `GROQ_API_KEY`, …).

Loaders:

- **In code:** construct `AnalystConfig(...)` directly (dicts or model instances).
- **`AnalystConfig.from_toml(path)`:** reads a TOML file with `[database]`,
  `[models.generator]`, `[models.semantic_validator]`, `[models.summarizer]` tables.
  Uses stdlib `tomllib`.
- **`AnalystConfig.from_env(**overrides)`:** reads
  `ASKYOURDB_DSN`, `ASKYOURDB_DIALECT`,
  `ASKYOURDB_MODEL`, `ASKYOURDB_API_KEY` (generator),
  `ASKYOURDB_SEMANTIC_MODEL`, `ASKYOURDB_SEMANTIC_API_KEY`,
  `ASKYOURDB_SUMMARY_MODEL`, `ASKYOURDB_SUMMARY_API_KEY`.
  Keyword overrides passed in code take precedence over env values.
  The library does not call `load_dotenv()`; that is left to the application
  (the demo `main.py` does).

Errors: invalid or missing values raise `ConfigError` (subclass of `ValueError`)
whose message names the offending field and the env var / TOML key to set. Pydantic
`ValidationError`s from the loaders are wrapped into `ConfigError`.

## LLM construction

`askyourdb/config.py` (or a small helper in `models.py`) provides
`build_llm(cfg: LLMConfig) -> BaseChatModel`:

- Calls `init_chat_model(cfg.model, temperature=cfg.temperature, **key_kwargs)`,
  where `key_kwargs = {"api_key": secret}` only when `api_key` is set.
- If `init_chat_model` raises `ImportError` because the provider integration package
  is missing, re-raise as `ConfigError` with the install hint
  `pip install "askyourdb[<provider>]"` when the provider is one of the known extras,
  otherwise a generic hint naming the missing module.

## Model builders (`askyourdb/models.py`)

- `build_sql_generator(schema_text, dialect, llm_config)`,
  `build_sql_semantic_validator(llm_config)`, `build_result_summarizer(llm_config)`
  take an `LLMConfig` and use `build_llm`. All `os.environ` lookups and hardcoded
  model names are removed.
- `FEW_SHOT_EXAMPLES` and the `Examples:` section of `SQL_GEN_SYSTEM` are removed.
- Prompts otherwise unchanged.

## Public API (`askyourdb/analyst.py`)

```python
class SQLAnalyst:
    def __init__(self, config: AnalystConfig): ...
    def ask(self, question: str, thread_id: str | None = None) -> dict: ...
    def as_tool(self, thread_id: str | None = None) -> StructuredTool: ...
    def close(self) -> None: ...
    def __enter__(self) / __exit__(...)
```

- Construction introspects the DB (`SchemaIntrospector`), builds the validator,
  executor, three LLM chains and the graph — the wiring currently in `main.py`.
- `ask` delegates to the existing `query_database` tool logic and returns the same
  result dict (`success`, `answer`, `row_count`, `sql_used`, `caveats`, `rows`,
  `error`). When `thread_id` is `None` a fresh UUID is used per call.
- `as_tool` returns the existing `build_query_database_tool(...)` for use in a
  larger LangChain agent.
- `close` disposes the engine; the context manager calls it.

Existing graph, nodes, validator, executor, introspector, and tool behaviour are
unchanged apart from the import path move.

## CLI (`askyourdb/cli.py`)

Standard library only (`argparse`, `readline` when available); no new dependencies.
Console script `askyourdb = "askyourdb.cli:main"`.

Usage:

```
askyourdb [--config PATH] [ask QUESTION [--json] [--rows]]
askyourdb [--config PATH] repl
```

- No subcommand → REPL (same as `repl`).
- **Config resolution:** `--config PATH` → `AnalystConfig.from_toml(PATH)`;
  otherwise `AnalystConfig.from_env()`. The CLI does not load `.env` files
  (users `source .env`; `.env.example` uses `export` lines).
- **`ask`:** runs one question on a fresh thread and prints:
  the answer, the SQL used, row count, and caveats (if any). `--rows` also prints
  the returned rows as a plain aligned text table. `--json` prints the full result
  dict as JSON instead (rows included) for scripting.
- **REPL:** one `SQLAnalyst` and one `thread_id` for the whole session. Note: the
  current graph only passes the current question to the generator, so this does not
  yet give conversational follow-ups; each question is answered independently. Prompt `askyourdb> `; each answer printed like `ask`
  (with rows). Blank lines are ignored; `exit`, `quit`, or Ctrl-D ends the session;
  Ctrl-C cancels the current input line without exiting. Line editing/history via
  `readline` when importable.
- **Exit codes:** `0` success; `1` query workflow failed (error message printed);
  `2` configuration error (`ConfigError` message printed to stderr, no traceback).
  In the REPL a failed question prints the error and continues.
- The engine is always closed on exit (`with SQLAnalyst(...)`).

## Packaging (`pyproject.toml`)

- `name = "askyourdb"`, real description, build backend (hatchling) packaging the
  `askyourdb/` directory.
- Core dependencies: `sqlalchemy`, `psycopg[binary]`, `pydantic`, `langchain`,
  `sqlglot` (`langgraph` continues to come in via `langchain`). `langchain-google-genai`,
  `langchain-groq` and `python-dotenv` are removed from core.
- Optional extras:
  - `anthropic` → `langchain-anthropic`
  - `openai` → `langchain-openai`
  - `google` → `langchain-google-genai`
  - `groq` → `langchain-groq`
  - `ollama` → `langchain-ollama`
  - `all` → all of the above
- Dev group adds `python-dotenv` (used by the demo) and the extras needed by tests.
- `[project.scripts] askyourdb = "askyourdb.cli:main"`.
- Coverage config `--cov=askyourdb`, threshold stays at 90%.

## Docs

- `README.md`: what it is, install per provider, CLI quickstart (env / TOML,
  `ask`, REPL), short "use from Python" section, config reference, BYOK notes (keys stay local, `SecretStr`, read-only DB user
  recommended), running the school demo.
- `.env.example` updated to the `ASKYOURDB_*` variables.
- `askyourdb.example.toml` sample config.

## Testing

- `tests/test_config.py`: code/TOML/env construction; override precedence;
  stage fallback to generator; dialect inference and the explicit-dialect error;
  missing `provider:` prefix; `SecretStr` masking in `repr`; `ConfigError` messages.
- `build_llm`: `init_chat_model` stubbed — asserts `api_key` passed only when set;
  missing-SDK `ImportError` → `ConfigError` with the correct extra in the hint.
- Model builder tests updated to take `LLMConfig` with a stubbed `build_llm`;
  assert the SQL prompt no longer contains examples.
- `tests/test_analyst.py`: end-to-end `SQLAnalyst` on the existing SQLite fixture
  with fake LLMs; `ask`, `as_tool`, context-manager close.
- `tests/test_cli.py`: argument parsing; config from `--config` vs env; `ask`
  text, `--rows` and `--json` output; exit codes 0/1/2; REPL loop driven by
  patched `input` (multiple questions share one thread_id, blank lines skipped,
  `exit`/EOF end the session, a failed question does not end the session);
  engine closed on exit. `SQLAnalyst` is stubbed.
- All existing tests pass with updated imports; coverage ≥ 90%.

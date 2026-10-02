# askyourdb

[![CI](https://github.com/Yasir323/askyourdb/actions/workflows/ci.yml/badge.svg)](https://github.com/Yasir323/askyourdb/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/askyourdb)](https://pypi.org/project/askyourdb/)
[![Python](https://img.shields.io/pypi/pyversions/askyourdb)](https://pypi.org/project/askyourdb/)
[![License](https://img.shields.io/badge/license-Apache--2.0-blue)](LICENSE)

Ask a SQL database questions in plain English, using your own LLM API key.
An LLM writes a read-only `SELECT` for your question. The SQL is then validated
statically (a single read-only statement, known tables, known columns where they
are qualified with a table, and a `LIMIT` is enforced), a second LLM pass reviews it for correctness, the query runs, and the
results are summarized in plain English. You always see the SQL that ran.

## Install

Install the core package plus the extra for the LLM provider you want to use. Only
that provider's SDK is installed:

```bash
pip install "askyourdb[anthropic]"
```

| Extra       | Installs                 | Example model string                 |
|-------------|--------------------------|--------------------------------------|
| `anthropic` | `langchain-anthropic`    | `anthropic:claude-sonnet-5`          |
| `openai`    | `langchain-openai`       | `openai:gpt-5`                       |
| `google`    | `langchain-google-genai` | `google_genai:gemini-3.5-flash-lite` |
| `groq`      | `langchain-groq`         | `groq:llama-3.3-70b-versatile`       |
| `all`       | all of the above         |                                      |

Models are written as `provider:model` and passed to LangChain's
[`init_chat_model`](https://python.langchain.com/api_reference/langchain/chat_models/langchain.chat_models.base.init_chat_model.html).
Any other provider it supports also works once you install that provider's LangChain
package yourself (for example `pip install langchain-mistralai` for `mistralai:...`).

PostgreSQL support (`psycopg`) is included. For other databases, install the
SQLAlchemy driver named in your DSN (for example `pymysql` for `mysql+pymysql://...`).

## Quickstart (CLI)

```bash
export ASKYOURDB_DSN="postgresql+psycopg://readonly_user:password@localhost:5432/mydb"
export ASKYOURDB_MODEL="anthropic:claude-sonnet-5"
export ASKYOURDB_API_KEY="sk-ant-..."

askyourdb ask "How many orders were placed yesterday?"
askyourdb ask "Which five customers spent the most last month?" --verbose  # show the SQL too
askyourdb ask "List active users by signup month" --json                   # full result as JSON
```

By default you get just the result. A single value is answered in a sentence
("There are 500 students in total."). Anything else is a sentence followed by a table
of up to 20 rows; `--json` gives every row. If askyourdb's automatic row limit (100
rows unless the question asks for more, at most 1000) cut the result off, a note says so.

While a question runs, a status line shows the current step and the time so far
(`Writing SQL…`, `Checking SQL…`, `Reviewing SQL…`, `Running query…`, `Summarizing…`,
or `Rewriting SQL (2/3): <reason>` on a retry). It only appears on a terminal.

`--verbose` (before or after `ask`/`repl`) also prints the SQL that ran, the row count,
caveats, retry reasons and the time each step took, and lets provider SDK warnings
through; without it they are hidden.

Run `askyourdb` with no arguments (or `askyourdb repl`) for an interactive session.
Type a question at the `askyourdb>` prompt; type `exit` or `quit`, or press Ctrl-D, to
leave. Ctrl-C cancels the current question without leaving. Each question is
answered on its own: the REPL does not yet carry context from earlier questions, so
ask complete questions rather than follow-ups like "now filter that by region".

To use a config file instead of environment variables:

```bash
cp askyourdb.example.toml askyourdb.toml   # then edit it
askyourdb --config askyourdb.toml ask "How many products are out of stock?"
```

## Configuration reference

| Environment variable         | TOML key                          | Default                                            |
|------------------------------|-----------------------------------|----------------------------------------------------|
| `ASKYOURDB_DSN`              | `database.dsn`                    | required                                           |
| `ASKYOURDB_DIALECT`          | `database.dialect`                | inferred for `postgresql`, `sqlite` and `mysql` DSNs |
| `ASKYOURDB_MODEL`            | `models.generator.model`          | required                                           |
| `ASKYOURDB_API_KEY`          | `models.generator.api_key`        | the provider's own env var                         |
| `ASKYOURDB_SEMANTIC_MODEL`   | `models.semantic_validator.model` | the generator settings                             |
| `ASKYOURDB_SEMANTIC_API_KEY` | `models.semantic_validator.api_key` | see below                                        |
| `ASKYOURDB_SUMMARY_MODEL`    | `models.summarizer.model`         | the generator settings                             |
| `ASKYOURDB_SUMMARY_API_KEY`  | `models.summarizer.api_key`       | see below                                          |

Each model table in TOML also accepts `temperature`. By default none is sent and the
provider's default applies; set `temperature = 0.0` for more repeatable SQL on models
that allow it.

- When `--config` is given, only that file is read. Otherwise the `ASKYOURDB_*`
  environment variables are used. askyourdb does not read `.env` files itself;
  `source` them in your shell first.
- The semantic validator and summarizer use the generator's model and key unless
  you set them, so you can point those stages at a cheaper model. A stage whose
  model is set but whose key is not reuses the generator's key when both use the
  same provider; for a different provider it uses that provider's own env var.
- If `api_key` is not set, nothing is passed to the provider and its SDK reads its
  standard variable (`ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `GOOGLE_API_KEY`,
  `GROQ_API_KEY`, ...). Empty values such as `export ASKYOURDB_API_KEY=` count as unset.
- For a database other than PostgreSQL, SQLite or MySQL, set the dialect explicitly
  using a [sqlglot dialect name](https://sqlglot.com/sqlglot/dialects.html), for
  example `Snowflake`.

## Bring your own key

Your keys stay on your machine and are sent only to the provider you choose. The
DSN and API keys are held as Pydantic `SecretStr` values, so they are not shown in
`repr()`, logs or configuration error messages. Keep `askyourdb.toml` and `.env`
out of version control.

What leaves your machine: the database schema (table and column names, types and
constraints), your questions, the generated SQL and the returned rows (up to 1000
per query) are sent to the LLM provider you configured, for SQL generation, review
and summarization. If you enable LangSmith tracing (`LANGCHAIN_TRACING_V2=true`),
the same data is also sent to LangSmith. Choose a provider you are allowed to share
that data with.

Connect with a read-only database user. askyourdb rejects anything other than a
single read-only query, but a read-only role is the real guarantee.

## Use from Python

The CLI is built on `SQLAnalyst`, which you can use directly:

```python
from askyourdb import AnalystConfig, SQLAnalyst

config = AnalystConfig(
    database={"dsn": "postgresql+psycopg://ro_user:pw@host/db"},
    models={"generator": {"model": "anthropic:claude-sonnet-5", "api_key": "sk-..."}},
)
with SQLAnalyst(config) as analyst:
    result = analyst.ask("Which five customers spent the most last month?")

print(result["answer"])
print(result["sql_used"])
```

- `AnalystConfig.from_env()` reads the `ASKYOURDB_*` variables. Keyword arguments
  override them, for example `AnalystConfig.from_env(model="openai:gpt-5")`.
- `AnalystConfig.from_toml("askyourdb.toml")` reads a config file.
- `ask(question, thread_id=None)` answers on a throwaway LangGraph thread and
  discards its checkpoints afterwards; pass a `thread_id` to keep them.
- `ask()` returns a dict with the keys `success`, `answer`, `row_count`, `sql_used`,
  `caveats`, `rows` and `error`.
- `analyst.as_tool()` returns a LangChain `StructuredTool` named `query_database`
  that you can give to your own agent.
- Invalid configuration raises `askyourdb.ConfigError`.

## Safety

askyourdb sends your question and your database schema to the LLM provider you choose,
and runs the SQL the model writes. The static validator and the review pass reduce the
risk of a bad query, but they are not a security boundary. Connect with a **read-only
database account** that can see only the tables you are comfortable sharing, and read
the SQL printed with each answer. See [SECURITY.md](SECURITY.md) for details and how to
report a vulnerability.

## Exit codes

| Code | Meaning                                                          |
|------|------------------------------------------------------------------|
| `0`  | Success                                                          |
| `1`  | The question could not be answered (the error is printed to stderr; with `--json` the result goes to stdout) |
| `2`  | Configuration error, missing provider package, or the database could not be reached |
| `130`| Interrupted with Ctrl-C                                          |

## Development and the school demo

The repository includes a sample school database and a demo script:

```bash
docker compose up -d          # PostgreSQL with the school schema and data (see db/README.md)
cp .env.example .env          # fill in ASKYOURDB_API_KEY
uv sync --extra google        # the demo defaults to a Gemini model
uv run python examples/school_demo.py         # asks the school database one question
uv run pytest                 # tests, with a 90% coverage gate
```

See [CONTRIBUTING.md](CONTRIBUTING.md) before opening a pull request.

## License

askyourdb is licensed under the [Apache License 2.0](LICENSE). You may use, modify and
redistribute it, including commercially, provided you keep the [`NOTICE`](NOTICE) file
and the license text with your copies, and mark any files you changed. See the
license for the full terms.

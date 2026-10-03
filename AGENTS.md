# Notes for contributors and coding agents

askyourdb answers plain-English questions about a SQL database. An LLM writes a
read-only `SELECT`, the SQL is validated statically, a second LLM pass reviews it, the
query runs, and the result is summarized.

## Layout

- `askyourdb/` — the package. `analyst.py` is the public entry point (`SQLAnalyst`),
  `cli.py` the command line, `graph.py` and `nodes.py` the LangGraph pipeline,
  `sql_validator.py` the static checks, `executor.py` query execution.
- `tests/` — unit tests; `tests/integration/` runs the pipeline against SQLite.
- `db/` and `docker-compose.yml` — a sample PostgreSQL school database.
- `examples/school_demo.py` — a demo script against that database.

## Commands

```bash
uv sync --extra all     # install with every provider extra
uv run pytest           # tests, with a 90% coverage gate
```

## Conventions

- Keep the safety model intact: queries must stay read-only, single-statement and
  row-limited. Changes to `sql_validator.py` need tests for both the allowed and the
  rejected case.
- Never commit API keys or `.env`. Use `.env.example` and `askyourdb.example.toml` for
  documented settings.
- Match the surrounding code's style, naming and comment density.

# Contributing to askyourdb

Thanks for your interest. Bug reports, fixes, docs and new ideas are all welcome.

## Setup

You need [uv](https://docs.astral.sh/uv/) and Python 3.11 or newer.

```bash
git clone https://github.com/Yasir323/askyourdb.git
cd askyourdb
uv sync --extra all        # package, dev tools and every provider extra
uv run pytest              # tests, with a 90% coverage gate
uv run ruff check . && uv run ruff format --check .
```

The tests need no API key or database: they use fakes and an in-memory SQLite database.
To try the tool against a real model, start the sample database with
`docker compose up -d` and run `examples/school_demo.py` (see `db/README.md`).

## Making a change

1. Open an issue first for anything larger than a small fix, so we can agree on the approach.
2. Branch from `main` and keep the change focused.
3. Add or update tests. The 90% coverage gate must keep passing.
4. Run the tests and ruff before you push.
5. Open a pull request and describe what changed and why.

## The safety model

askyourdb lets an LLM write SQL against a real database, so the guardrails matter more
than usual. Changes to `askyourdb/sql_validator.py`, `executor.py` or the prompts must
keep queries read-only, single-statement and row-limited, and need tests for both an
allowed and a rejected case.

## Reporting security problems

Please do not open a public issue for a vulnerability. See [SECURITY.md](SECURITY.md).

## License

By contributing you agree that your contribution is licensed under the
[Apache License 2.0](LICENSE), the same as the project.

# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses
[Semantic Versioning](https://semver.org/).

## [0.1.0] - Unreleased

First public release. Not published on PyPI; install from GitHub.

### Added
- Ask a SQL database questions in plain English, from the `askyourdb` CLI or the
  `SQLAnalyst` Python API, with your own LLM key (Anthropic, OpenAI, Google, Groq, or any
  LangChain provider).
- Static SQL validation: a single read-only statement, known tables and columns, and an
  enforced `LIMIT`.
- A second LLM pass that reviews the generated SQL, then a plain-English summary of the result.
- Progress output, `--verbose`, `--json`, and the executed SQL shown with every answer.
- Configuration through environment variables or a TOML file.
- A sample PostgreSQL school database and demo in `examples/`.
- An accuracy evaluation in `evals/`: 43 questions with reference SQL, scored against the school database.

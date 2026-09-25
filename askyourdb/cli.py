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
    except Exception as error:
        print(f"Could not start askyourdb: {type(error).__name__}: {_first_line(error)}",
              file=sys.stderr)
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

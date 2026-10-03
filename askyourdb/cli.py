import argparse
import contextlib
import itertools
import json
import logging
import sys
import threading
import time
import warnings
from decimal import Decimal

from sqlalchemy.exc import SQLAlchemyError

from askyourdb.analyst import SQLAnalyst
from askyourdb.config import AnalystConfig, ConfigError
from askyourdb.observability import configure_langsmith
from askyourdb.tools import ProgressEvent

EXIT_OK = 0
EXIT_QUERY_FAILED = 1
EXIT_CONFIG_ERROR = 2
EXIT_INTERRUPTED = 130
EXIT_COMMANDS = {"exit", "quit"}
MAX_TABLE_ROWS = 20

STEP_LABELS = {
    "generate_sql": "Writing SQL",
    "validate_sql": "Checking SQL",
    "semantic_validate_sql": "Reviewing SQL",
    "execute_sql": "Running query",
    "summarize_results": "Summarizing",
}


VERBOSE_HELP = "also show the SQL, row count, caveats, steps and library warnings"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="askyourdb",
        description="Ask questions of your database in plain English, using your own LLM API key.",
    )
    parser.add_argument("--verbose", action="store_true", help=VERBOSE_HELP)

    # --verbose is also accepted after the subcommand. There it defaults to
    # SUPPRESS so it doesn't reset a --verbose given before the subcommand.
    # Each parser gets its own action: set_defaults() mutates shared ones.
    def verbose():
        options = argparse.ArgumentParser(add_help=False)
        options.add_argument(
            "--verbose", action="store_true", default=argparse.SUPPRESS, help=VERBOSE_HELP
        )
        return options

    parser.add_argument(
        "--config",
        metavar="PATH",
        help="TOML config file (default: ASKYOURDB_* environment variables)",
    )
    commands = parser.add_subparsers(dest="command")
    ask = commands.add_parser("ask", help="answer one question and exit", parents=[verbose()])
    ask.add_argument("question")
    ask.add_argument("--json", action="store_true", help="print the full result as JSON")
    commands.add_parser("repl", help="interactive session (the default)", parents=[verbose()])
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        with _library_output(args.verbose):
            return _run(args)
    except KeyboardInterrupt:
        # Ctrl-C during startup or a one-shot question.
        print(file=sys.stderr)
        return EXIT_INTERRUPTED


@contextlib.contextmanager
def _library_output(verbose: bool):
    """Hide provider SDK warnings and log lines unless --verbose."""
    if verbose:
        yield
        return
    previous = logging.root.manager.disable
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        logging.disable(logging.WARNING)
        try:
            yield
        finally:
            logging.disable(previous)


def _run(args: argparse.Namespace) -> int:
    configure_langsmith()
    try:
        config = AnalystConfig.from_toml(args.config) if args.config else AnalystConfig.from_env()
        analyst = SQLAnalyst(config)
    except ConfigError as error:
        print(f"Configuration error: {error}", file=sys.stderr)
        return EXIT_CONFIG_ERROR
    except SQLAlchemyError as error:
        print(f"Could not connect to the database: {_first_line(error)}", file=sys.stderr)
        return EXIT_CONFIG_ERROR
    except Exception as error:
        print(
            f"Could not start askyourdb: {type(error).__name__}: {_first_line(error)}",
            file=sys.stderr,
        )
        return EXIT_CONFIG_ERROR

    with analyst:
        if args.command == "ask":
            return run_ask(analyst, args.question, as_json=args.json, verbose=args.verbose)
        return run_repl(analyst, verbose=args.verbose)


def run_ask(analyst: SQLAnalyst, question: str, *, as_json: bool, verbose: bool) -> int:
    if as_json:
        result = _ask(analyst, question)
        print(json.dumps(result, indent=2, default=str))
    else:
        result, steps = _ask_with_progress(analyst, question)
        # Failures go to stderr so scripts can keep stdout for answers.
        print(
            format_result(result, verbose=verbose, steps=steps),
            file=sys.stdout if result["success"] else sys.stderr,
        )
    return EXIT_OK if result["success"] else EXIT_QUERY_FAILED


def run_repl(analyst: SQLAnalyst, *, verbose: bool = False) -> int:
    _enable_line_editing()
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
            result, steps = _ask_with_progress(analyst, question)
        except KeyboardInterrupt:
            print("Cancelled.")
            continue
        print(format_result(result, verbose=verbose, steps=steps))
        print()


def format_result(result: dict, verbose: bool = False, steps: list | None = None) -> str:
    rows = result["rows"]
    if not result["success"]:
        lines = [f"Error: {result['error']}"]
    else:
        lines = [result["answer"]]
        # A single value is fully answered by the sentence; anything else
        # gets the table as well.
        if not _is_scalar(rows):
            lines += ["", format_rows(rows[:MAX_TABLE_ROWS])]
            if len(rows) > MAX_TABLE_ROWS:
                lines.append(f"… {len(rows) - MAX_TABLE_ROWS} more rows (use --json for all)")
        if result.get("truncated"):
            lines += [
                "",
                f"Only the first {len(rows)} rows were fetched (row limit); "
                "ask a narrower question to see the rest.",
            ]
    if verbose:
        lines += _verbose_details(result, steps or [])
    return "\n".join(lines)


def _is_scalar(rows: list[dict]) -> bool:
    return not rows or (len(rows) == 1 and len(rows[0]) == 1)


def _verbose_details(result: dict, steps: list) -> list[str]:
    lines = []
    if result["sql_used"]:
        lines += ["", "SQL:", result["sql_used"]]
    if result["success"]:
        lines += ["", f"Rows: {result['row_count']}"]
    if result["caveats"]:
        lines += ["", "Caveats:"] + [f"- {caveat}" for caveat in result["caveats"]]
    retries = [event for event, _ in steps if event.retry_reason]
    for event in retries:
        lines.append(f"Retry {event.attempt}/{event.max_attempts}: {event.retry_reason}")
    if steps:
        lines += [
            "",
            "Steps: "
            + ", ".join(
                f"{STEP_LABELS.get(event.step, event.step)} {seconds:.1f}s"
                for event, seconds in steps
            ),
        ]
    return lines


def format_rows(rows: list[dict]) -> str:
    if not rows:
        return "(no rows)"
    headers = list(rows[0].keys())
    table = [headers] + [[_display(row.get(h)) for h in headers] for row in rows]
    widths = [max(len(line[i]) for line in table) for i in range(len(headers))]

    def render(cells):
        return "  ".join(
            cell.ljust(width) for cell, width in zip(cells, widths, strict=False)
        ).rstrip()

    return "\n".join(
        [render(table[0]), "  ".join("-" * width for width in widths)]
        + [render(line) for line in table[1:]]
    )


def _display(value) -> str:
    if value is None:
        return "NULL"
    if isinstance(value, float) or (isinstance(value, Decimal) and value != value.to_integral()):
        return f"{value:.2f}"
    return str(value)


class ProgressLine:
    """One self-updating status line on a terminal: step, elapsed time."""

    FRAMES = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"

    def __init__(self, stream, interval: float = 0.1):
        self._stream = stream
        self._enabled = stream.isatty()
        self._interval = interval
        self._label = "Starting"
        self._started = time.monotonic()
        self._frames = itertools.cycle(self.FRAMES)
        self._lock = threading.Lock()
        self._done = threading.Event()
        self._thread = threading.Thread(target=self._tick, daemon=True)

    def start(self) -> None:
        if self._enabled:
            self._thread.start()

    def update(self, event: ProgressEvent) -> None:
        self._label = _progress_label(event)
        self._draw()

    def stop(self) -> None:
        if not self._enabled:
            return
        self._done.set()
        if self._thread.is_alive():
            self._thread.join()
        with self._lock:
            self._stream.write("\r\033[K")
            self._stream.flush()

    def _tick(self) -> None:
        while not self._done.wait(self._interval):
            self._draw()

    def _draw(self) -> None:
        if not self._enabled or self._done.is_set():
            return
        elapsed = int(time.monotonic() - self._started)
        with self._lock:
            self._stream.write(f"\r\033[K{next(self._frames)} {self._label}… {elapsed}s")
            self._stream.flush()


def _progress_label(event: ProgressEvent) -> str:
    if event.step == "generate_sql" and event.attempt > 1:
        reason = event.retry_reason.splitlines()[0] if event.retry_reason else ""
        label = f"Rewriting SQL ({event.attempt}/{event.max_attempts})"
        return f"{label}: {reason[:70]}" if reason else label
    if event.step == "summarize_results" and event.attempt > 1:
        return f"Summarizing ({event.attempt}/{event.max_attempts})"
    return STEP_LABELS.get(event.step, event.step)


def _ask_with_progress(analyst: SQLAnalyst, question: str) -> tuple[dict, list]:
    """Ask while drawing progress; also return (event, seconds) for each step."""
    line = ProgressLine(sys.stderr)
    steps: list[list] = []

    def on_progress(event: ProgressEvent) -> None:
        now = time.monotonic()
        if steps:
            steps[-1][1] = now - steps[-1][1]
        steps.append([event, now])
        line.update(event)

    line.start()
    try:
        result = _ask(analyst, question, on_progress)
    finally:
        line.stop()
    if steps:
        steps[-1][1] = time.monotonic() - steps[-1][1]
    return result, [tuple(step) for step in steps]


def _ask(analyst: SQLAnalyst, question: str, on_progress=None) -> dict:
    """Run one question; turn provider/network errors into a failed result."""
    try:
        return analyst.ask(question, on_progress=on_progress)
    except Exception as error:
        return {
            "success": False,
            "answer": None,
            "row_count": 0,
            "sql_used": None,
            "caveats": [],
            "rows": [],
            "truncated": False,
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

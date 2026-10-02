import json
from decimal import Decimal

import pytest
from sqlalchemy.exc import OperationalError

import askyourdb.cli as cli
from askyourdb.config import ConfigError
from askyourdb.tools import ProgressEvent

OK = {
    "success": True,
    "answer": "Ada owes the most.",
    "row_count": 1,
    "sql_used": "SELECT name, owed FROM people LIMIT 100",
    "caveats": ["Sample data"],
    "rows": [{"name": "Ada", "owed": Decimal("12.50")}],
    "truncated": False,
    "error": None,
}
SCALAR = {
    "success": True,
    "answer": "There are 500 students in total.",
    "row_count": 1,
    "sql_used": "SELECT COUNT(*) AS n FROM students",
    "caveats": [],
    "rows": [{"n": 500}],
    "truncated": False,
    "error": None,
}
FAILED = {
    "success": False,
    "answer": None,
    "row_count": 0,
    "sql_used": "SELECT bad",
    "caveats": [],
    "rows": [],
    "truncated": False,
    "error": "Unknown column 'bad'",
}


def table_result(n_rows, truncated=False):
    rows = [{"id": i, "name": f"p{i}"} for i in range(n_rows)]
    return {
        **OK,
        "answer": f"{n_rows} people.",
        "row_count": n_rows,
        "rows": rows,
        "truncated": truncated,
    }


class FakeAnalyst:
    instances = []
    results = []
    init_error = None
    events = []
    during_ask = None

    def __init__(self, config):
        if FakeAnalyst.init_error:
            raise FakeAnalyst.init_error
        self.config = config
        self.questions = []
        self.closed = False
        FakeAnalyst.instances.append(self)

    def ask(self, question, thread_id=None, on_progress=None):
        self.questions.append((question, thread_id))
        for event in FakeAnalyst.events:
            on_progress and on_progress(event)
        if FakeAnalyst.during_ask:
            FakeAnalyst.during_ask()
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
    FakeAnalyst.events, FakeAnalyst.during_ask = [], None
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


def test_ask_scalar_result_prints_only_the_sentence(capsys):
    FakeAnalyst.results = [SCALAR]

    code = cli.main(["ask", "How many students?"])

    assert code == 0
    assert capsys.readouterr().out == "There are 500 students in total.\n"
    assert FakeAnalyst.instances[0].questions == [("How many students?", None)]
    assert FakeAnalyst.instances[0].closed is True


def test_ask_table_result_prints_sentence_and_table_without_sql(capsys):
    FakeAnalyst.results = [OK]

    cli.main(["ask", "q"])

    out = capsys.readouterr().out
    assert out.startswith("Ada owes the most.\n\n")
    assert "name  owed" in out
    assert "Ada   12.50" in out
    assert "SELECT" not in out
    assert "Sample data" not in out


def test_verbose_adds_sql_row_count_caveats_and_steps(capsys):
    FakeAnalyst.results = [OK]
    FakeAnalyst.events = [
        ProgressEvent("generate_sql", 1, 3),
        ProgressEvent("generate_sql", 2, 3, "Unknown tables referenced: ghosts"),
        ProgressEvent("summarize_results", 1, 2),
    ]

    cli.main(["ask", "q", "--verbose"])

    out = capsys.readouterr().out
    assert "SQL:\nSELECT name, owed FROM people LIMIT 100" in out
    assert "Rows: 1" in out
    assert "- Sample data" in out
    assert "Retry 2/3: Unknown tables referenced: ghosts" in out
    assert "Steps: Writing SQL " in out and "Summarizing " in out


def test_verbose_flag_works_before_the_subcommand(capsys):
    FakeAnalyst.results = [OK]

    cli.main(["--verbose", "ask", "q"])

    assert "SQL:" in capsys.readouterr().out


def test_long_tables_are_cut_to_20_rows(capsys):
    FakeAnalyst.results = [table_result(25)]

    cli.main(["ask", "q"])

    out = capsys.readouterr().out
    assert "p19" in out and "p20" not in out
    assert "… 5 more rows (use --json for all)" in out


def test_truncated_result_says_so(capsys):
    FakeAnalyst.results = [table_result(3, truncated=True)]

    cli.main(["ask", "q"])

    assert "Only the first 3 rows were fetched" in capsys.readouterr().out


def test_format_rows_rounds_decimals_for_display():
    table = cli.format_rows([{"avg": Decimal("76.5475000000000000"), "n": 3, "f": 2.0}])

    assert "76.55" in table and "76.547" not in table
    assert table.splitlines()[-1].split() == ["76.55", "3", "2.00"]


def test_library_warnings_are_hidden_unless_verbose(recwarn, caplog):
    import logging
    import warnings

    def noisy():
        warnings.warn("temperature will be ignored", UserWarning, stacklevel=2)
        logging.getLogger("google_genai.models").warning("AFC is not recommended")

    FakeAnalyst.during_ask = noisy
    FakeAnalyst.results = [OK, OK]

    cli.main(["ask", "q"])
    assert not [w for w in recwarn if "temperature" in str(w.message)]
    assert "AFC" not in caplog.text
    assert logging.root.manager.disable == logging.NOTSET  # restored afterwards

    cli.main(["ask", "q", "--verbose"])
    assert [w for w in recwarn if "temperature" in str(w.message)]
    assert "AFC" in caplog.text


def test_progress_line_draws_steps_and_clears_on_a_terminal():
    import io

    class Terminal(io.StringIO):
        def isatty(self):
            return True

    stream = Terminal()
    line = cli.ProgressLine(stream)
    line.start()
    line.update(ProgressEvent("generate_sql", 1, 3))
    line.update(ProgressEvent("generate_sql", 2, 3, "status has no value 'pending'"))
    line.stop()

    text = stream.getvalue()
    assert "Writing SQL…" in text
    assert "Rewriting SQL (2/3): status has no value 'pending'" in text
    assert text.endswith("\r\033[K")


def test_progress_line_is_silent_when_not_a_terminal():
    import io

    stream = io.StringIO()
    line = cli.ProgressLine(stream)
    line.start()
    line.update(ProgressEvent("execute_sql", 1, 3))
    line.stop()

    assert stream.getvalue() == ""


def test_format_rows_handles_empty_and_null():
    assert cli.format_rows([]) == "(no rows)"
    assert "NULL" in cli.format_rows([{"a": None}])


def test_ask_json_output(capsys):
    FakeAnalyst.results = [OK]

    code = cli.main(["ask", "q", "--json"])

    data = json.loads(capsys.readouterr().out)
    assert code == 0
    assert data["rows"] == [{"name": "Ada", "owed": "12.50"}]


def test_failed_query_shows_sql_only_when_verbose(capsys):
    FakeAnalyst.results = [FAILED, FAILED]

    cli.main(["ask", "q"])
    quiet = capsys.readouterr().err
    cli.main(["ask", "q", "--verbose"])
    loud = capsys.readouterr().err

    assert quiet == "Error: Unknown column 'bad'\n"
    assert "SQL:\nSELECT bad" in loud


def test_ask_failed_query_exits_1(capsys):
    FakeAnalyst.results = [FAILED]

    code = cli.main(["ask", "q"])

    captured = capsys.readouterr()
    assert code == 1
    assert "Error: Unknown column 'bad'" in captured.err
    assert "Error:" not in captured.out


def test_ask_provider_exception_exits_1_without_traceback(capsys):
    FakeAnalyst.results = [RuntimeError("401 invalid x-api-key\nmore detail")]

    code = cli.main(["ask", "q"])

    err = capsys.readouterr().err
    assert code == 1
    assert "Error: RuntimeError: 401 invalid x-api-key" in err
    assert "more detail" not in err
    assert "Traceback" not in err


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
        "SELECT 1",
        {},
        Exception("connection refused\nis the server running?"),
    )

    code = cli.main(["ask", "q"])

    err = capsys.readouterr().err
    assert code == 2
    assert "Could not connect to the database" in err
    assert "connection refused" in err


def test_config_file_is_used_instead_of_env(tmp_path):
    path = tmp_path / "askyourdb.toml"
    path.write_text(
        '[database]\ndsn = "sqlite:///file.db"\n\n'
        '[models.generator]\nmodel = "groq:llama-3.3-70b"\n'
    )
    FakeAnalyst.results = [OK]

    cli.main(["--config", str(path), "ask", "q"])

    config = FakeAnalyst.instances[0].config
    assert config.database.dsn.get_secret_value() == "sqlite:///file.db"


def test_repl_is_default_and_answers_each_question_on_its_own(monkeypatch, capsys):
    FakeAnalyst.results = [OK, OK]
    feed_input(monkeypatch, "", "first?", "  second?  ", "exit")

    code = cli.main([])

    analyst = FakeAnalyst.instances[0]
    assert code == 0
    # No shared thread: SQLAnalyst.ask discards each question's checkpoints.
    assert analyst.questions == [("first?", None), ("second?", None)]
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


def test_unexpected_startup_error_exits_2_without_traceback(capsys):
    FakeAnalyst.init_error = RuntimeError("boom\nlong detail")

    code = cli.main(["ask", "q"])

    err = capsys.readouterr().err
    assert code == 2
    assert "RuntimeError: boom" in err
    assert "long detail" not in err


def test_failed_query_json_stays_on_stdout(capsys):
    FakeAnalyst.results = [FAILED]

    code = cli.main(["ask", "q", "--json"])

    assert code == 1
    assert json.loads(capsys.readouterr().out)["error"] == "Unknown column 'bad'"


def test_ctrl_c_during_ask_exits_130_without_traceback(capsys):
    FakeAnalyst.results = [KeyboardInterrupt()]

    code = cli.main(["ask", "q"])

    assert code == 130
    assert FakeAnalyst.instances[0].closed is True


def test_ctrl_c_during_startup_exits_130(capsys):
    FakeAnalyst.init_error = KeyboardInterrupt()

    assert cli.main(["ask", "q"]) == 130


def test_progress_line_keeps_redrawing_the_elapsed_time():
    import io
    import time

    class Terminal(io.StringIO):
        def isatty(self):
            return True

    stream = Terminal()
    line = cli.ProgressLine(stream, interval=0.01)
    line.start()
    line.update(ProgressEvent("summarize_results", 2, 2))
    deadline = time.monotonic() + 2
    while stream.getvalue().count("Summarizing (2/2)…") < 3 and time.monotonic() < deadline:
        time.sleep(0.01)
    line.stop()

    assert stream.getvalue().count("Summarizing (2/2)…") >= 3

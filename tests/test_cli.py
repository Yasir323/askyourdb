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

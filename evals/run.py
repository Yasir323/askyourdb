"""Run the accuracy evaluation against the bundled school database.

    uv run python -m evals.run --model google_genai:gemini-3.5-flash-lite
    uv run python -m evals.run --check-gold        # validate the gold SQL, no LLM calls

See evals/README.md for what is measured and how to read the report.
"""

import argparse
import json
import os
import re
import sys
import threading
import time
import tomllib
import warnings
from collections import defaultdict
from datetime import UTC, datetime
from importlib.metadata import version
from pathlib import Path

from sqlalchemy import create_engine, text

from askyourdb import AnalystConfig, SQLAnalyst
from evals.scoring import is_decline, results_match

HERE = Path(__file__).parent
DEMO_DSN = "postgresql+psycopg://school:school@localhost:5432/school_db"
ROW_LIMIT = 100


def load_questions(path: Path, only: list[str]) -> list[dict]:
    questions = tomllib.loads(path.read_text())["question"]
    if only:
        questions = [q for q in questions if any(q["id"].startswith(prefix) for prefix in only)]
    return questions


def run_sql(engine, sql: str) -> list[dict]:
    with engine.connect() as connection:
        return [dict(row) for row in connection.execute(text(sql)).mappings().all()]


def table_counts(engine) -> dict[str, int]:
    """Row count of every table, to prove a 'safety' question changed nothing."""
    tables = [
        row["table_name"]
        for row in run_sql(
            engine,
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = 'public' AND table_type = 'BASE TABLE'",
        )
    ]
    return {name: run_sql(engine, f'SELECT COUNT(*) AS n FROM "{name}"')[0]["n"] for name in tables}


def check_gold(engine, questions: list[dict]) -> int:
    """Run every gold SQL and flag the ones that cannot serve as a reference."""
    problems = 0
    for q in questions:
        if q["category"] != "answerable":
            continue
        try:
            rows = run_sql(engine, q["gold"])
        except Exception as error:  # noqa: BLE001 - report any failure, keep checking
            print(f"FAIL {q['id']}: gold SQL error: {str(error).splitlines()[0]}")
            problems += 1
            continue
        issue = ""
        if not rows:
            issue = "gold returns no rows"
        elif len(rows) >= ROW_LIMIT:
            issue = f"gold returns {len(rows)} rows, at or over the row limit"
        status = "FAIL" if issue else "ok  "
        print(f"{status} {q['id']}: {len(rows)} row(s) {issue}")
        problems += bool(issue)
    return problems


def score_answerable(engine, question: dict, result: dict) -> tuple[str, str]:
    if not result["success"]:
        return "no_answer", result.get("error") or "pipeline gave no answer"
    gold = run_sql(engine, question["gold"])
    ok, reason = results_match(gold, result["rows"])
    return ("correct", "") if ok else ("wrong", reason)


def call_with_timeout(function, seconds: float):
    """Run function() and give up after `seconds`, so one hung provider call cannot stall the run.

    The abandoned call keeps running in a daemon thread until it finishes or the process ends.
    """
    outcome: dict = {}

    def target():
        try:
            outcome["value"] = function()
        except BaseException as error:  # noqa: BLE001 - handed back to the caller below
            outcome["error"] = error

    thread = threading.Thread(target=target, daemon=True)
    thread.start()
    thread.join(seconds)
    if thread.is_alive():
        raise TimeoutError(f"no answer after {seconds:.0f}s")
    if "error" in outcome:
        raise outcome["error"]
    return outcome["value"]


def evaluate(analyst, engine, question: dict, retries: int, timeout: float) -> dict:
    record = {"id": question["id"], "category": question["category"], "tier": question.get("tier")}
    record["question"] = question["question"]
    before = table_counts(engine) if question["category"] == "safety" else None
    result, error = None, ""
    started = time.monotonic()
    for attempt in range(retries + 1):
        try:
            result = call_with_timeout(lambda: analyst.ask(question["question"]), timeout)
            break
        except Exception as exc:  # noqa: BLE001 - provider errors vary; retry then record
            error = f"{type(exc).__name__}: {str(exc).splitlines()[0][:200]}"
            time.sleep(5 * (attempt + 1))
    record["seconds"] = round(time.monotonic() - started, 1)

    if result is None:
        record.update(outcome="error", passed=False, detail=error)
        return record

    record["sql"] = result["sql_used"]
    record["answer"] = result["answer"] if result["success"] else None
    record["error"] = result["error"]
    category = question["category"]
    if category == "answerable":
        record["outcome"], record["detail"] = score_answerable(engine, question, result)
        record["passed"] = record["outcome"] == "correct"
    elif category == "safety":
        unchanged = table_counts(engine) == before
        record["outcome"] = "refused" if not result["success"] else "answered_read_only"
        record["detail"] = "" if unchanged else "DATABASE CHANGED"
        record["passed"] = unchanged
    else:
        record["passed"] = is_decline(result)
        record["outcome"] = "declined" if record["passed"] else "answered"
        record["detail"] = "" if record["passed"] else "returned a value for unavailable data"
    return record


def provider_is_failing(records: list[dict], limit: int) -> bool:
    """True after `limit` questions in a row ended in an error (quota, outage, bad key)."""
    recent = records[-limit:]
    return len(recent) == limit and all(r["outcome"] == "error" for r in recent)


def summarize(records: list[dict], meta: dict) -> str:
    def pct(passed: int, total: int) -> str:
        return f"{passed}/{total} ({100 * passed / total:.0f}%)" if total else "n/a"

    groups: dict[str, list[dict]] = defaultdict(list)
    for r in records:
        groups[r["tier"] or r["category"]].append(r)
    answerable = [r for r in records if r["category"] == "answerable"]

    lines = [
        f"# askyourdb accuracy: {meta['model']}",
        "",
        f"askyourdb {meta['askyourdb']} · {meta['date']} · "
        f"{len(records)} questions · median {meta['median_seconds']}s per question",
        "",
        "| Group | Passed |",
        "|---|---|",
    ]
    for name in ("simple", "join", "aggregate", "subtle", "safety", "unanswerable"):
        if name in groups:
            group = groups[name]
            lines.append(f"| {name} | {pct(sum(r['passed'] for r in group), len(group))} |")
    overall = pct(sum(r["passed"] for r in answerable), len(answerable))
    lines.append(f"| **answerable overall** | **{overall}** |")

    failures = [r for r in records if not r["passed"]]
    if failures:
        lines += ["", "## Failures", ""]
        for r in failures:
            lines += [f"### {r['id']}: {r['question']}", f"- outcome: {r['outcome']}"]
            if r.get("detail"):
                lines.append(f"- detail: {r['detail']}")
            if r.get("sql"):
                lines.append(f"- sql: `{' '.join(r['sql'].split())[:400]}`")
            if r.get("answer"):
                lines.append(f"- answer: {r['answer'][:300]}")
            lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--model", help="provider:model (default: $ASKYOURDB_MODEL)")
    parser.add_argument("--api-key-env", help="name of the env var holding the API key")
    parser.add_argument("--dsn", default=os.environ.get("ASKYOURDB_DSN") or DEMO_DSN)
    parser.add_argument("--questions", type=Path, default=HERE / "questions.toml")
    parser.add_argument("--only", action="append", default=[], help="question id prefix")
    parser.add_argument("--retries", type=int, default=2, help="retries on provider errors")
    parser.add_argument("--timeout", type=float, default=120, help="seconds allowed per question")
    parser.add_argument("--max-errors", type=int, default=3, help="stop after N errors in a row")
    parser.add_argument("--delay", type=float, default=0.0, help="seconds between questions")
    parser.add_argument("--out", type=Path, default=HERE / "results")
    parser.add_argument("--check-gold", action="store_true", help="validate gold SQL and exit")
    args = parser.parse_args(argv)

    warnings.filterwarnings("ignore")
    questions = load_questions(args.questions, args.only)
    engine = create_engine(args.dsn)

    if args.check_gold:
        problems = check_gold(engine, questions)
        print(f"\n{problems} problem(s)")
        return 1 if problems else 0

    overrides = {"dsn": args.dsn, "model": args.model}
    if args.api_key_env:
        overrides["api_key"] = os.environ.get(args.api_key_env)
        if not overrides["api_key"]:
            print(f"error: ${args.api_key_env} is not set", file=sys.stderr)
            return 2
    config = AnalystConfig.from_env(**overrides)

    records: list[dict] = []
    aborted = False
    with SQLAnalyst(config) as analyst:
        for index, question in enumerate(questions, start=1):
            record = evaluate(analyst, engine, question, args.retries, args.timeout)
            records.append(record)
            mark = "pass" if record["passed"] else "FAIL"
            print(f"[{index}/{len(questions)}] {mark} {record['id']} ({record['outcome']})")
            if provider_is_failing(records, args.max_errors):
                print(
                    f"\nStopping: {args.max_errors} errors in a row ({record['detail']}). "
                    "The provider may be out of quota or rate-limiting; try again later.",
                    file=sys.stderr,
                )
                aborted = True
                break
            time.sleep(args.delay)

    seconds = sorted(r["seconds"] for r in records)
    meta = {
        "model": config.models.generator.model,
        "askyourdb": version("askyourdb"),
        "date": datetime.now(UTC).strftime("%Y-%m-%d"),
        "median_seconds": seconds[len(seconds) // 2],
    }
    report = summarize(records, meta)
    args.out.mkdir(parents=True, exist_ok=True)
    slug = re.sub(r"[^A-Za-z0-9.]+", "-", meta["model"]).strip("-")
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    (args.out / f"{slug}-{stamp}.json").write_text(
        json.dumps({"meta": meta, "records": records}, indent=2, default=str)
    )
    (args.out / f"{slug}-{stamp}.md").write_text(report)
    print("\n" + report)
    return 3 if aborted else 0


if __name__ == "__main__":
    sys.exit(main())

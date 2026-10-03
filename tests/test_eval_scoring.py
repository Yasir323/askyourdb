import tomllib
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from evals.run import call_with_timeout, load_questions, provider_is_failing
from evals.scoring import is_decline, results_match, row_matches

QUESTIONS = Path(__file__).parent.parent / "evals" / "questions.toml"


def rows(*tuples, keys=("a", "b", "c")):
    return [dict(zip(keys, t, strict=False)) for t in tuples]


def test_exact_match_ignores_column_names_and_row_order():
    gold = rows(("Grade 1", 36), ("Grade 2", 40))
    model = [{"n": 40, "level": "Grade 2"}, {"n": 36, "level": "Grade 1"}]
    assert results_match(gold, model) == (True, "")


def test_extra_columns_are_allowed():
    gold = rows((5,))
    model = [{"student_id": 7, "owed": 5}]
    assert results_match(gold, model)[0]


def test_row_count_must_match_exactly():
    ok, reason = results_match(rows((1,), (2,)), rows((1,)))
    assert not ok
    assert reason == "expected 2 row(s), got 1"


def test_numbers_match_within_rounding_but_not_beyond():
    assert results_match(rows((Decimal("82.456"),)), rows((82.46,)))[0]
    assert results_match(rows((Decimal("82.456"),)), rows((82.5,)))[0]
    assert not results_match(rows((Decimal("82.456"),)), rows((83,)))[0]
    assert not results_match(rows((500,)), rows((499,)))[0]


def test_gold_string_may_sit_inside_a_longer_model_cell():
    gold = rows(("Salma", "Halvorsen"))
    assert results_match(gold, [{"head": "Salma Halvorsen"}])[0]
    assert results_match(gold, [{"head": "salma halvorsen"}])[0]
    assert not results_match(gold, [{"head": "Salma Halverson"}])[0]


def test_dates_match_as_iso_prefix():
    gold = rows((date(2026, 4, 4),))
    assert results_match(gold, [{"d": "2026-04-04"}])[0]
    assert results_match(gold, [{"d": datetime(2026, 4, 4, 9, 30)}])[0]
    assert not results_match(gold, [{"d": "2026-04-05"}])[0]


def test_none_matches_only_none_and_bool_only_bool():
    assert row_matches([None], [None])
    assert not row_matches([None], [0])
    assert not row_matches([0], [None])
    assert row_matches([True], [True])
    assert not row_matches([True], [1])
    assert not row_matches([1], [True])


def test_a_model_row_cannot_be_reused_for_two_gold_rows():
    # Both gold rows are satisfied by the single model row "Ana Ana", so a
    # one-to-one assignment must fail even though row counts are equal.
    gold = rows(("Ana",), ("Ben",))
    model = [{"x": "Ana Ben"}, {"x": "Zed"}]
    ok, reason = results_match(gold, model)
    assert not ok
    assert reason == "values differ from the expected rows"


def test_matching_finds_an_assignment_when_greedy_would_fail():
    # Gold 0 fits model 0 or 1; gold 1 fits only model 0. Greedy would take model 0
    # for gold 0 and strand gold 1.
    gold = rows(("a",), ("b",))
    model = [{"x": "a b"}, {"x": "a"}]
    assert results_match(gold, model)[0]


def test_wrong_values_report_which_gold_row_is_missing():
    ok, reason = results_match(rows(("x", 1)), rows(("x", 2)))
    assert not ok
    assert reason == "values differ from the expected rows; no model row contains ['x', 1]"


def test_question_file_is_well_formed():
    questions = tomllib.loads(QUESTIONS.read_text())["question"]
    ids = [q["id"] for q in questions]
    assert len(ids) == len(set(ids)), "question ids must be unique"
    for q in questions:
        assert q["category"] in {"answerable", "safety", "unanswerable"}, q["id"]
        assert q["question"].strip(), q["id"]
        if q["category"] == "answerable":
            assert q["gold"].strip().upper().startswith(("SELECT", "WITH")), q["id"]
            assert q["tier"] in {"simple", "join", "aggregate", "subtle"}, q["id"]
        else:
            assert "gold" not in q and "tier" not in q, q["id"]


def test_load_questions_filters_by_id_prefix():
    everything = load_questions(QUESTIONS, [])
    subtle = load_questions(QUESTIONS, ["subtle"])
    assert subtle and len(subtle) < len(everything)
    assert all(q["id"].startswith("subtle") for q in subtle)
    assert {q["id"] for q in load_questions(QUESTIONS, ["safety-01", "simple-02"])} == {
        "safety-01",
        "simple-02",
    }


@pytest.mark.parametrize("category", ["answerable", "safety", "unanswerable"])
def test_every_category_has_questions(category):
    assert any(q["category"] == category for q in load_questions(QUESTIONS, []))


@pytest.mark.parametrize(
    ("result", "declined"),
    [
        ({"success": False, "rows": []}, True),
        ({"success": True, "rows": []}, True),
        ({"success": True, "rows": [{"average_height": None}]}, True),
        ({"success": True, "rows": [{"average_height": 0}]}, False),
        ({"success": True, "rows": [{"a": None, "b": "tall"}]}, False),
    ],
)
def test_is_decline(result, declined):
    assert is_decline(result) is declined


def test_call_with_timeout_returns_the_value_or_reraises():
    assert call_with_timeout(lambda: 42, 5) == 42
    with pytest.raises(ValueError, match="boom"):
        call_with_timeout(lambda: (_ for _ in ()).throw(ValueError("boom")), 5)


def test_call_with_timeout_gives_up_on_a_hung_call():
    import threading

    release = threading.Event()
    with pytest.raises(TimeoutError, match="no answer after"):
        call_with_timeout(lambda: release.wait(10), 0.05)
    release.set()


def test_provider_is_failing_only_after_consecutive_errors():
    error, ok = {"outcome": "error"}, {"outcome": "correct"}
    assert not provider_is_failing([error, error], 3)
    assert not provider_is_failing([error, ok, error, error], 3)
    assert provider_is_failing([ok, error, error, error], 3)

"""Compare a model's result rows with a gold result set.

The comparison is tolerant about presentation and strict about substance:

- column names, column order and row order are ignored;
- the model may return extra columns (an id next to a name, say);
- numbers match within a small tolerance, so 82.456 matches 82.46 and 82.5;
- a gold string matches when it appears inside any cell of the model's row, so a gold
  ("Salma", "Halvorsen") matches a model row with the single cell "Salma Halvorsen".

The number of rows must match exactly, and every gold row needs its own model row.
"""

from datetime import date, datetime
from decimal import Decimal

NUMBER_TOLERANCE = 0.051


def _is_number(value) -> bool:
    return isinstance(value, int | float | Decimal) and not isinstance(value, bool)


def _cell_matches(gold, cell) -> bool:
    if gold is None or cell is None:
        return gold is None and cell is None
    if isinstance(gold, bool) or isinstance(cell, bool):
        return gold is cell
    if _is_number(gold) and _is_number(cell):
        return abs(float(gold) - float(cell)) <= NUMBER_TOLERANCE
    if isinstance(gold, date | datetime):
        return str(cell)[:10] == gold.isoformat()[:10]
    if isinstance(gold, str) and isinstance(cell, str):
        return gold.strip().casefold() in cell.casefold()
    return False


def row_matches(gold_row: list, model_row: list) -> bool:
    """True when every gold value is found in the model's row."""
    return all(any(_cell_matches(g, c) for c in model_row) for g in gold_row)


def _perfect_matching(compatible: list[list[int]], right_count: int) -> bool:
    """Each left node needs its own right node (augmenting-path bipartite matching)."""
    owner = [-1] * right_count

    def assign(left: int, seen: set[int]) -> bool:
        for right in compatible[left]:
            if right in seen:
                continue
            seen.add(right)
            if owner[right] == -1 or assign(owner[right], seen):
                owner[right] = left
                return True
        return False

    return all(assign(left, set()) for left in range(len(compatible)))


def results_match(gold_rows: list[dict], model_rows: list[dict]) -> tuple[bool, str]:
    """Return (matches, reason). The reason is empty on a match."""
    if len(gold_rows) != len(model_rows):
        return False, f"expected {len(gold_rows)} row(s), got {len(model_rows)}"
    gold = [list(row.values()) for row in gold_rows]
    model = [list(row.values()) for row in model_rows]
    compatible = [[j for j, m in enumerate(model) if row_matches(g, m)] for g in gold]
    if _perfect_matching(compatible, len(model)):
        return True, ""
    unmatched = [g for g, options in zip(gold, compatible, strict=True) if not options]
    detail = f"; no model row contains {unmatched[0]}" if unmatched else ""
    return False, f"values differ from the expected rows{detail}"


def is_decline(result: dict) -> bool:
    """True when the pipeline did not hand back a value for the question.

    Used for questions the database cannot answer. Declining means failing outright,
    returning no rows, or returning only NULLs (``SELECT NULL AS average_height``). A
    real value taken from unrelated data counts as an answer, so as fabrication.
    """
    if not result["success"]:
        return True
    return all(value is None for row in result["rows"] for value in row.values())

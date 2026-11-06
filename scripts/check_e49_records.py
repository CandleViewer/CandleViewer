"""E49-Q02: every exploratory finding row carries a disposition (the "undecided = 0" query).

Reads the findings tables of ``docs/qa/e49-run-*-findings.md`` (schema: the "Findings table
schema" in docs/qa/charters/E49-README.md) and classifies each row by its Status cell:

* ``bug P0``..``bug P3`` with an issue number (``#123``) in the cell
* ``not-a-defect: <reason>`` with a non-empty reason
* ``security-private`` (the public row carries no detail)
* ``pending filing`` (a graded candidate awaiting its ticket)

``bug P0``..``bug P3`` without an issue number is ``pending`` (graded, not yet filed).
Anything else, and any empty cell, is undecided. ``pending filing`` is reported separately and only
counts as undecided with ``--closing`` (the closing PR needs it at 0). Exit 1 when undecided > 0.
"""

from __future__ import annotations

import argparse
import re
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

COLUMNS = (
    "ID",
    "Charter",
    "Oracle",
    "Area",
    "Steps",
    "Expected",
    "Actual",
    "Severity",
    "Status",
    "Evidence",
)
_ROW_ID = re.compile(r"^E49-[RB]\d+-\d+$")
_BUG = re.compile(r"^bug\s+P[0-3]\b")
_ISSUE = re.compile(r"#\d+")
_NOT_A_DEFECT = re.compile(r"^not-a-defect\s*:\s*\S")
_SEPARATOR = re.compile(r"^\|(\s*:?-{3,}:?\s*\|)+\s*$")
DEFAULT_GLOB = "docs/qa/e49-run-*-findings.md"


@dataclass(frozen=True)
class Row:
    source: str
    row_id: str
    cells: tuple[str, ...]

    @property
    def status(self) -> str:
        return self.cells[COLUMNS.index("Status")].strip()


def _split(line: str) -> list[str]:
    return [c.strip() for c in line.strip().strip("|").split("|")]


def parse_rows(text: str, source: str = "") -> list[Row]:
    """Rows of every findings table (a table whose header is ``ID | Charter | ...``).

    Fails closed: raises ValueError for a header-like line (``ID | Charter ...``, any case) that is
    not exactly ``COLUMNS``, and for a row whose first cell is a record id but which sits outside a
    recognised findings table (for example after a blank or note line inside the table).
    """
    rows: list[Row] = []
    in_table = False
    for line in text.splitlines():
        if not line.lstrip().startswith("|"):
            in_table = False
            continue
        cells = _split(line)
        if tuple(cells[: len(COLUMNS)]) == COLUMNS:
            in_table = True
            continue
        if [c.lower() for c in cells[:2]] == [c.lower() for c in COLUMNS[:2]]:
            raise ValueError(f"{source}: findings table header is not the exact schema columns")
        if _SEPARATOR.match(line.strip()):
            continue
        if not in_table:
            if _ROW_ID.match(cells[0]):
                raise ValueError(f"{source}: row {cells[0]} is outside a findings table")
            continue
        rows.append(Row(source, cells[0], tuple(cells)))
    return rows


def classify(row: Row) -> str:
    """One of: bug, not-a-defect, security-private, pending, undecided."""
    if len(row.cells) != len(COLUMNS) or not _ROW_ID.match(row.row_id):
        return "undecided"
    if any(c == "" for c in row.cells):
        return "undecided"
    status = row.status
    if _BUG.match(status):
        return "bug" if _ISSUE.search(status) else "pending"
    if _NOT_A_DEFECT.match(status):
        return "not-a-defect"
    if status == "security-private" or status.startswith("security-private:"):
        return "security-private"
    if status == "pending filing" or re.match(r"^pending filing\b[;:,.\s]", status):
        return "pending"
    return "undecided"


def summarize(rows: list[Row], closing: bool = False) -> tuple[Counter[str], list[Row]]:
    counts: Counter[str] = Counter()
    bad: list[Row] = []
    for row in rows:
        kind = classify(row)
        counts[kind] += 1
        if kind == "undecided" or (closing and kind == "pending"):
            bad.append(row)
    return counts, bad


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("records", nargs="*", type=Path, help="run records (default: all runs)")
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--closing", action="store_true", help="pending filing counts as undecided")
    args = parser.parse_args(argv)
    root = args.root.resolve()
    files = args.records or sorted(args.root.glob(DEFAULT_GLOB))
    if not files:
        print("no run records found", file=sys.stderr)
        return 1
    rows: list[Row] = []
    errors = 0
    seen: set[str] = set()
    for path in files:
        if path.is_symlink() or not path.resolve().is_relative_to(root):
            print(f"{path.name}: record must be a regular file inside --root", file=sys.stderr)
            errors += 1
            continue
        try:
            found = parse_rows(path.read_text(encoding="utf-8"), path.name)
        except (ValueError, OSError) as exc:
            print(exc, file=sys.stderr)
            errors += 1
            continue
        if not found:
            print(f"{path.name}: no findings rows", file=sys.stderr)
            errors += 1
        for row in found:
            if row.row_id in seen:
                print(f"{path.name}: duplicate id {row.row_id}", file=sys.stderr)
                errors += 1
            seen.add(row.row_id)
        rows.extend(found)
    counts, bad = summarize(rows, args.closing)
    for row in bad:
        why = (
            "pending filing is not allowed with --closing"
            if classify(row) == "pending"
            else "no valid disposition"
        )
        print(f"{row.source}: {row.row_id or '?'}: {why}: {row.status!r}")
    print(
        f"rows = {len(rows)}; bug = {counts['bug']}; not-a-defect = {counts['not-a-defect']}; "
        f"security-private = {counts['security-private']}; pending filing = {counts['pending']}"
    )
    print(f"undecided = {len(bad)}")
    return 1 if bad or errors or not rows else 0


if __name__ == "__main__":
    raise SystemExit(main())

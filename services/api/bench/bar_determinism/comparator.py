"""Plain-text, field-by-field bar comparator (E12-T04).

Byte-for-byte: each `Bar` field is rendered to its canonical string (`str(Decimal)`, ints and
bools as JSON) and compared as text, so `1.0` vs `1.00` IS a difference. Output never relies on
colour: one line per difference, `bar <index> field <name>: expected <x> actual <y>`.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal

from candleviewer.bars.models import Bar

FIELDS: tuple[str, ...] = tuple(Bar.model_fields)
OHLCV: tuple[str, ...] = ("open", "high", "low", "close", "volume")
#: Fields the row names only when true (#5396, as the wires send them): a golden written before
#: one existed stays byte-identical, and a bar that sets one is a difference.
WHEN_TRUE: frozenset[str] = frozenset({"tape_gap"})


def row(b: Bar) -> dict[str, str]:
    """The canonical text form of every field (the golden-file row)."""
    out: dict[str, str] = {}
    for f in FIELDS:
        v = getattr(b, f)
        if f in WHEN_TRUE and v is False:
            continue
        out[f] = str(v) if isinstance(v, Decimal) else json.dumps(v)
    return out


def line(b: Bar) -> str:
    return json.dumps(row(b), sort_keys=True, separators=(",", ":"))


@dataclass(frozen=True)
class Diff:
    position: int  # position in the series (== bar index for real bars)
    index: int | None
    field: str
    expected: str
    actual: str

    def __str__(self) -> str:
        idx = "-" if self.index is None else self.index
        return (
            f"bar {idx} (position {self.position}) field {self.field}: "
            f"expected {self.expected} actual {self.actual}"
        )


def compare(
    expected: Sequence[Bar], actual: Sequence[Bar], fields: Sequence[str] = FIELDS
) -> list[Diff]:
    """Every differing (bar, field); a length mismatch is reported as a `<missing>` bar."""
    diffs: list[Diff] = []
    for i in range(max(len(expected), len(actual))):
        e = row(expected[i]) if i < len(expected) else None
        a = row(actual[i]) if i < len(actual) else None
        index = (expected[i] if e is not None else actual[i]).index
        if e is None or a is None:
            diffs.append(
                Diff(
                    i,
                    index,
                    "<bar>",
                    "<missing>" if e is None else "present",
                    "<missing>" if a is None else "present",
                )
            )
            continue
        for f in fields:  # a `WHEN_TRUE` field the row leaves out is "false"
            x, y = e.get(f, "false"), a.get(f, "false")
            if x != y:
                diffs.append(Diff(i, index, f, x, y))
    return diffs


def compare_lines(expected: Sequence[str], actual: Sequence[str]) -> list[Diff]:
    """Golden-file comparison: rows as serialised JSON text."""
    diffs: list[Diff] = []
    for i in range(max(len(expected), len(actual))):
        if i >= len(expected) or i >= len(actual):
            diffs.append(
                Diff(
                    i,
                    None,
                    "<bar>",
                    "present" if i < len(expected) else "<missing>",
                    "present" if i < len(actual) else "<missing>",
                )
            )
            continue
        e, a = json.loads(expected[i]), json.loads(actual[i])
        idx = int(e.get("index", "0"))
        diffs.extend(
            Diff(i, idx, f, str(e.get(f)), str(a.get(f)))
            for f in sorted(set(e) | set(a))
            if e.get(f) != a.get(f)
        )
    return diffs


def render(diffs: Sequence[Diff], limit: int = 20) -> str:
    """At most `limit` lines plus a count of the rest; empty string when equal."""
    if not diffs:
        return ""
    lines = [str(d) for d in diffs[:limit]]
    if len(diffs) > limit:
        lines.append(f"... and {len(diffs) - limit} more differences")
    return "\n".join(lines)

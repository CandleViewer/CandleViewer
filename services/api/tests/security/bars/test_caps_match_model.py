"""E12-X02 caps reconciled with the threat model (#452 DoD: "caps reconciled"; X01 §7 "Drift
prevention"): each number X01 §7 states for SR-E12-01/02/03/04/07/12/15 is read from the model
itself and compared with the constant the code enforces, so a change on either side fails here.

X01 §7 also says "the numbers live in `candleviewer/bars/limits.py`". The SR-E12-04 spec caps
live in `bars/leases.py` instead: the values agree, the location does not (#452 findings row F5).
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Final

import pytest

from candleviewer.bars import leases, limits
from candleviewer.bars.state_store import MAX_BLOB_BYTES
from candleviewer.ws.limits import MAX_BARS_SUBSCRIPTIONS

F5: Final = "#452 findings row F5: the SR-E12-04 caps live in bars/leases.py, not bars/limits.py"
_MODEL: Final = Path(__file__).resolve().parents[5] / "docs/security/threat-models/E12-bars.md"
_DAY_US: Final = 86_400_000_000
_MIB: Final = 1024 * 1024


def _row(sr: str) -> str:
    """The X01 §7 table row of `sr` (its requirement text)."""
    text = _MODEL.read_text(encoding="utf-8")
    section = text[text.index("## 7. Controls") : text.index("## 8. Cross-references")]
    rows: list[str] = re.findall(rf"^\| {sr} +\|(.*)$", section, flags=re.M)
    assert len(rows) == 1, sr
    return rows[0]


def _num(text: str) -> int:
    return int(text.replace(" ", ""))


#: `(SR row, pattern, groups -> the model's numbers, the code's numbers)`.
_PINS: Final = [
    ("SR-E12-01", r"`limit` <= ([\d ]+) \(default ([\d ]+)\)",
     (limits.MAX_LIMIT, limits.DEFAULT_LIMIT)),
    ("SR-E12-01", r"(\d+) MiB response ceiling", (limits.RESPONSE_MAX_BYTES // _MIB,)),
    ("SR-E12-01", r"(\d+) s timeout per query", (int(limits.QUERY_TIMEOUT_S),)),
    ("SR-E12-02", r"time bars <= ([\d ]+) bars and <= (\d+) d",
     (limits.MAX_WINDOW_BARS, limits.MAX_TIME_WINDOW_US // _DAY_US)),
    ("SR-E12-02", r"non-time <= (\d+) d", (limits.MAX_NON_TIME_WINDOW_US // _DAY_US,)),
    ("SR-E12-03", r"`tick` ([\d ]+)\.\.([\d ]+);", limits.TICK_PARAM_RANGE),
    ("SR-E12-03", r">= (\d+) qty steps", (limits.QTY_PARAM_MIN_STEPS,)),
    ("SR-E12-03", r"<= 10\^(\d+)", (len(str(limits.QTY_PARAM_MAX)) - 1,)),
    ("SR-E12-03", r"`range`/`renko` ([\d ]+)\.\.([\d ]+) ticks", limits.RANGE_TICKS_RANGE),
    ("SR-E12-03", r"`range`/`renko` ([\d ]+)\.\.([\d ]+) ticks", limits.RENKO_TICKS_RANGE),
    ("SR-E12-04", r"(\d+) per user, (\d+) per symbol, (\d+) process-wide",
     (leases.CAP_PER_USER, leases.CAP_PER_SYMBOL, leases.CAP_GLOBAL)),
    ("SR-E12-07", r"`bars\.\*` <= (\d+) per connection, `history` 0\.\.(\d+)",
     (MAX_BARS_SUBSCRIPTIONS, limits.MAX_TAIL)),
    ("SR-E12-12", r"Blob: (\d+) MiB cap", (MAX_BLOB_BYTES // _MIB,)),
    ("SR-E12-15", r"at most ([\d ]+) bars or bricks", (limits.MAX_BRICKS_PER_TRADE,)),
]  # fmt: skip


@pytest.mark.parametrize(
    ("sr", "pattern", "code"), _PINS, ids=[f"{p[0]}-{p[1][:24]}" for p in _PINS]
)
def test_caps_match_model_number_in_x01_equals_the_enforced_constant(
    sr: str, pattern: str, code: tuple[int, ...]
) -> None:
    found = re.search(pattern, _row(sr))
    assert found is not None, f"{sr}: {pattern!r} no longer matches X01 §7"
    assert tuple(_num(g) for g in found.groups()) == tuple(code)


def test_caps_match_model_qty_max_is_a_power_of_ten() -> None:
    assert limits.QTY_PARAM_MAX == 10 ** (len(str(limits.QTY_PARAM_MAX)) - 1)


@pytest.mark.xfail(strict=True, raises=AssertionError, reason=F5)
def test_caps_match_model_spec_caps_live_in_limits() -> None:
    for name in ("CAP_PER_USER", "CAP_PER_SYMBOL", "CAP_GLOBAL"):
        assert getattr(limits, name, None) == getattr(leases, name), name

"""Ingest-boundary validation primitives (E08-X02 fixes #1889 / #1890 / #1892;
`docs/plan/24-internal-schemas.md` §14.2 item 10).

Venue-neutral so every adapter parser *and* the ingestion frame pump share one
rejection vocabulary. Every field check here is O(1), because book deltas and
trade prints are hot paths (C-2.20). The depth scan is linear in the frame:
`str` methods, and one possessive regex, which never backtracks, only when a
`\\"` is left once the `\\\\` pairs are dropped (SEC-G8B-B-02).

A rejection is a `FrameRejectedError` carrying a bounded `reason` (the
`ingest_rejected_total{reason}` label value) and, when known, the symbol so the
consumer can trigger a resync (C-2.5). It subclasses `ValueError` so every
existing "malformed frame" handler keeps catching it.
"""

from __future__ import annotations

import re
from decimal import Decimal
from typing import Final, Literal, get_args

__all__ = [
    "MAX_FRAME_DEPTH",
    "MAX_FUTURE_SKEW_MS",
    "MAX_PRICE",
    "MAX_QTY",
    "MAX_TS_MS",
    "REJECT_REASONS",
    "FrameRejectedError",
    "RejectReason",
    "check_event_ts",
    "check_event_window",
    "check_price",
    "check_qty",
    "json_depth_exceeds",
]

RejectReason = Literal[
    "malformed",
    "depth_limit",
    "non_finite",
    "non_positive",
    "out_of_bounds",
    "off_tick",
    "crossed",
    "ts_future",
    "ts_past",
    "internal_error",
]
#: Closed label-value set for `ingest_rejected_total{reason}` (bounded cardinality).
REJECT_REASONS: Final[frozenset[str]] = frozenset(get_args(RejectReason))

#: Deepest legitimate frame is 4 (`{"data":{"b":[["p","q"]]}}`); 32 is generous.
MAX_FRAME_DEPTH: Final[int] = 32
#: Plausibility ceilings: no USDT-linear contract trades anywhere near these.
MAX_PRICE: Final[Decimal] = Decimal("1e12")
MAX_QTY: Final[Decimal] = Decimal("1e12")
#: Absolute event-time ceiling, ms UTC (2100-01-01). The lower bound is the
#: instrument's `launchTime` and the live upper bound is the injected clock;
#: both need ingestion state, so they are applied in the streams (§14.2 rule 9).
MAX_TS_MS: Final[int] = 4_102_444_800_000
#: An event may not be stamped later than its frame envelope by more than this.
MAX_FUTURE_SKEW_MS: Final[int] = 5_000

_BRACKETS: Final[dict[int, None]] = {c: None for c in range(0x80) if chr(c) not in "[]{}"}
#: One JSON string literal once `\\` pairs are gone, so every backslash left is single: a quote
#: ends the literal unless a backslash precedes it; an unterminated literal runs to the end.
#: `[^"]` matches a newline, so no `DOTALL` is needed.
_LITERAL: Final[str] = r'"[^"]*+(?:(?<=\\)"[^"]*+)*+"?+'
#: A run of literals joined by bracket-free text is one match, not one per literal. Every
#: quantifier is possessive, so nothing backtracks and the scan stays linear.
_LITERALS: Final[re.Pattern[str]] = re.compile(_LITERAL + r'(?:[^"\[\]{}]*+' + _LITERAL + ")*+")


class FrameRejectedError(ValueError):
    """A frame failed an ingest-boundary check; nothing from it may be published."""

    def __init__(self, reason: RejectReason, detail: str, *, symbol: str | None = None) -> None:
        super().__init__(f"{reason}: {detail}")
        self.reason: RejectReason = reason
        self.symbol = symbol


def _walk(structural: str, limit: int) -> bool:
    depth = 0
    for ch in structural.translate(_BRACKETS):
        if ch in "[{":
            depth += 1
            if depth > limit:
                return True
        elif ch in "]}":
            depth -= 1
    return False


def json_depth_exceeds(frame: str, limit: int = MAX_FRAME_DEPTH) -> bool:
    """True when `frame` nests `[`/`{` deeper than `limit`, decided before any
    `json.loads` (#1889). String-aware: bracket characters inside JSON string
    literals are ignored, so they can neither raise nor lower the count.
    Fast path: fewer opening brackets than `limit` cannot nest that deep.
    A frame where no backslash precedes a quote (every venue frame) is split
    on `"` and only the even (outside-string) segments are walked. Otherwise
    `str.replace` first drops `\\\\` pairs, in literals and out, so a run of
    backslashes still escapes exactly what it did; then the split serves
    unless a `\\"` is left, when one possessive regex drops the literals
    (SEC-G8B-B-02)."""
    if frame.count("[") + frame.count("{") <= limit:
        return False
    first = frame.find("\\")  # no `\"` starts before the first backslash
    if first >= 0 and frame.find('\\"', first) >= 0:
        frame = frame.replace("\\\\", "")
        if '\\"' in frame:
            return _walk(_LITERALS.sub("", frame), limit)
    return _walk("".join(frame.split('"')[::2]), limit)


def check_price(value: Decimal, *, symbol: str | None = None) -> Decimal:
    """Finite, `> 0`, `<= MAX_PRICE`. Bounds before any arithmetic so a
    `1e308` never reaches a division (#1892, #1893)."""
    if not value.is_finite():
        raise FrameRejectedError("non_finite", "price", symbol=symbol)
    if value <= 0:
        raise FrameRejectedError("non_positive", "price", symbol=symbol)
    if value > MAX_PRICE:
        raise FrameRejectedError("out_of_bounds", "price", symbol=symbol)
    return value


def check_qty(value: Decimal, *, allow_zero: bool = False, symbol: str | None = None) -> Decimal:
    """Finite, `> 0` (or `>= 0` for a book delete), `<= MAX_QTY`."""
    if not value.is_finite():
        raise FrameRejectedError("non_finite", "qty", symbol=symbol)
    if value < 0 or (value == 0 and not allow_zero):
        raise FrameRejectedError("non_positive", "qty", symbol=symbol)
    if value > MAX_QTY:
        raise FrameRejectedError("out_of_bounds", "qty", symbol=symbol)
    return value


def check_event_ts(ts_ms: int, envelope_ms: int | None, *, symbol: str | None = None) -> int:
    """Event time under the absolute ceiling and not ahead of its own frame
    envelope by more than `MAX_FUTURE_SKEW_MS` (#1892)."""
    if ts_ms > MAX_TS_MS:
        raise FrameRejectedError("ts_future", "event time after plausible window", symbol=symbol)
    if envelope_ms is not None and ts_ms > envelope_ms + MAX_FUTURE_SKEW_MS:
        raise FrameRejectedError("ts_future", "event time ahead of envelope", symbol=symbol)
    return ts_ms


def check_event_window(
    ts_us: int,
    *,
    now_us: int | None,
    launch_us: int | None,
    future_skew_us: int = MAX_FUTURE_SKEW_MS * 1000,
    launch_grace_us: int = 0,
    symbol: str | None = None,
) -> None:
    """Clock-relative window `[launch - grace, now + skew]` (#1892); either
    side is skipped when its reference is unknown (`None`)."""
    if now_us is not None and ts_us > now_us + future_skew_us:
        raise FrameRejectedError("ts_future", "event time ahead of local clock", symbol=symbol)
    if launch_us is not None and ts_us < launch_us - launch_grace_us:
        raise FrameRejectedError("ts_past", "event time before listing", symbol=symbol)

"""Interval algebra for recording coverage (E16-T04). Pure, no I/O, epoch microseconds.

Every interval is half-open `[lo, hi)` with `lo < hi`; zero-length intervals are rejected at
construction (`Span`). Coverage = session windows minus gaps, merged with
`COVERAGE_MERGE_TOLERANCE_MS` so reconnect churn does not produce thousands of hairline
intervals. The tolerance is applied ONLY when merging covered intervals that a gap does not
separate: a real gap (even 3 s) is never merged away (ticket technical notes, ADR-0015 d7).
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Final

#: Covered intervals closer than this are merged unless a gap lies between them.
COVERAGE_MERGE_TOLERANCE_MS: Final = 1000
_TOL_US: Final = COVERAGE_MERGE_TOLERANCE_MS * 1000


@dataclass(frozen=True, slots=True, order=True)
class Span:
    lo: int
    hi: int

    def __post_init__(self) -> None:
        if self.hi <= self.lo:
            raise ValueError(f"zero-length or inverted span [{self.lo}, {self.hi})")

    def clip(self, lo: int, hi: int) -> Span | None:
        a, b = max(self.lo, lo), min(self.hi, hi)
        return Span(a, b) if b > a else None


def union(spans: Iterable[Span]) -> list[Span]:
    """Sorted union; touching or overlapping spans merge (no tolerance)."""
    out: list[Span] = []
    for s in sorted(spans):
        if out and s.lo <= out[-1].hi:
            if s.hi > out[-1].hi:
                out[-1] = Span(out[-1].lo, s.hi)
        else:
            out.append(s)
    return out


def subtract(base: Iterable[Span], holes: Iterable[Span]) -> list[Span]:
    """`base` minus `holes`; result sorted and disjoint."""
    hs = union(holes)
    out: list[Span] = []
    for b in union(base):
        lo = b.lo
        for h in hs:
            if h.hi <= lo or h.lo >= b.hi:
                continue
            if h.lo > lo:
                out.append(Span(lo, h.lo))
            lo = max(lo, h.hi)
            if lo >= b.hi:
                break
        if lo < b.hi:
            out.append(Span(lo, b.hi))
    return out


def merge_with_tolerance(covered: Sequence[Span], gaps: Sequence[Span]) -> list[Span]:
    """Merge covered spans whose separation is <= the tolerance, unless any gap intersects the
    separation (gaps are never merged away)."""
    hs = union(gaps)
    out: list[Span] = []
    for s in sorted(covered):
        if out and s.lo - out[-1].hi <= _TOL_US:
            sep_lo, sep_hi = out[-1].hi, s.lo
            blocked = any(h.lo < max(sep_hi, sep_lo + 1) and h.hi > sep_lo for h in hs)
            if not blocked:
                out[-1] = Span(out[-1].lo, max(out[-1].hi, s.hi))
                continue
        out.append(s)
    return out


def coverage(sessions: Iterable[Span], gaps: Iterable[Span]) -> list[Span]:
    """Covered intervals = union(sessions) - gaps, tolerance-merged (never across a gap)."""
    gap_list = list(gaps)
    return merge_with_tolerance(subtract(sessions, gap_list), gap_list)


def split_at(span: Span, cut: int) -> tuple[Span | None, Span | None]:
    """Split at `cut`: (part strictly before, part from `cut` on)."""
    return span.clip(span.lo, cut), span.clip(cut, span.hi)

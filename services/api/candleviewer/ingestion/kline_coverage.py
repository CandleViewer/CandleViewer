"""Coverage index for the E08-S06 kline backfill.

The ticket's own "Technical notes / design" names this the core design:
rather than tracking "how far back have we loaded" as a single watermark,
this stores the set of contiguous, already-covered `[start_us, end_us)`
ranges per `(symbol, interval)`, so a hole created by an outage or an
interrupted backfill is a first-class, fillable gap rather than something
a single watermark would paper over or force a full re-fetch to discover.

Pure, in-memory, no I/O — deliberately dependency-free so the merge/hole
logic is exhaustively unit-testable (ticket "Test plan": "coverage-index
merge/hole computation") without a database. `KlineBackfillService` (this
package) is the only caller in this ticket; a later persistence-backed
implementation (still owned by this module, not `storage`, per the M6
import-linter allowlist) can wrap this same merge algorithm around a
repository-backed range table.
"""

from __future__ import annotations

from bisect import bisect_left
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Final

_MIN_US: Final = 60_000_000
#: Interval code -> fixed bar width (µs). `M` (calendar month) has no fixed width.
BAR_WIDTH_US: Final[dict[str, int]] = {
    **{c: int(c) * _MIN_US for c in ("1", "3", "5", "15", "30", "60", "120", "240", "360", "720")},
    "D": 1440 * _MIN_US,
    "W": 7 * 1440 * _MIN_US,
}
#: Bybit weeks open on Monday 00:00 UTC; the Unix epoch was a Thursday.
_WEEK_ANCHOR_US: Final = 4 * 1440 * _MIN_US


def bar_open_us(ts_us: int, interval: str) -> int:
    """Open time of the `interval` bar containing `ts_us` on the absolute UTC grid (weeks open
    on Monday); `ts_us` itself for an interval with no fixed width (`M`)."""
    width = BAR_WIDTH_US.get(interval)
    if width is None:
        return ts_us
    anchor = _WEEK_ANCHOR_US if interval == "W" else 0
    return (ts_us - anchor) // width * width + anchor


@dataclass(frozen=True, slots=True)
class Range:
    """An inclusive-start, exclusive-end microsecond range, matching
    `storage.models.TimeRange`'s own convention (this module intentionally
    does not import `candleviewer.storage` — see the module docstring — so
    it defines its own equivalent shape rather than reaching across the M6
    import-linter boundary for one dataclass)."""

    start_us: int
    end_us: int

    def __post_init__(self) -> None:
        if self.end_us < self.start_us:
            raise ValueError("end_us must be >= start_us")

    def overlaps_or_touches(self, other: Range) -> bool:
        """True when `self` and `other` overlap or are exactly adjacent
        (touching ranges are merged into one contiguous range — two
        back-to-back pages covering `[0,100)` and `[100,200)` are one
        covered span, not two, so a later hole computation does not treat
        the shared boundary as a 0-width gap)."""
        return self.start_us <= other.end_us and other.start_us <= self.end_us


@dataclass(slots=True)
class CoverageIndex:
    """Merged, sorted, non-overlapping covered ranges for one
    `(symbol, interval)` pair.

    `mark_covered` is idempotent and commutative in the ranges it has seen
    so far — feeding the same range twice, or two ranges in either order,
    always produces the same merged result (ticket acceptance criterion
    "Interrupted backfill resumes": the index must be safely rebuildable
    from whatever partial history persistence already has).

    #3808: `horizon_us`, when set, is read at every `mark_covered` and bounds the covered set:
    nothing at or after it is ever covered, since no bar exists there yet.
    `KlineBackfillService` sets it to the open time of the bar containing now, so neither the
    forming bar nor a future window can be cached as covered, whatever window was requested.
    """

    _ranges: list[Range] = field(default_factory=list)
    horizon_us: Callable[[], int] | None = field(default=None, repr=False, compare=False)

    def mark_covered(self, rng: Range) -> None:
        """Merge `rng` into the covered set, coalescing any range it
        overlaps or touches. The part at or after the horizon is refused."""
        if self.horizon_us is not None:
            end = min(rng.end_us, self.horizon_us())
            if end <= rng.start_us:
                return
            rng = Range(rng.start_us, end)
        merged_start, merged_end = rng.start_us, rng.end_us
        kept: list[Range] = []
        for existing in self._ranges:
            merged_so_far = Range(merged_start, merged_end)
            if existing.overlaps_or_touches(rng) or merged_so_far.overlaps_or_touches(existing):
                merged_start = min(merged_start, existing.start_us)
                merged_end = max(merged_end, existing.end_us)
            else:
                kept.append(existing)
        kept.append(Range(merged_start, merged_end))
        kept.sort(key=lambda r: r.start_us)
        self._ranges = kept

    def covered_ranges(self) -> list[Range]:
        """Every merged covered range, ascending by `start_us`. Returns a
        copy — callers must not mutate the index through this list."""
        return list(self._ranges)

    def is_fully_covered(self, rng: Range) -> bool:
        """True iff every microsecond in `[rng.start_us, rng.end_us)` is
        already covered by one merged range (never spans two, since a gap
        between them would mean it is not fully covered)."""
        return not self.holes(rng)

    def holes(self, rng: Range) -> list[Range]:
        """The sub-ranges of `rng` that are NOT yet covered, ascending by
        `start_us` — exactly what a resumed/incremental backfill must still
        fetch (ticket acceptance criteria: "only the tail/holes",
        "Interrupted backfill resumes").

        Empty when `rng` is fully covered. A range with zero width
        (`start_us == end_us`) never produces a hole, matching the
        inclusive-start/exclusive-end convention used throughout."""
        if rng.end_us <= rng.start_us:
            return []
        cursor = rng.start_us
        holes: list[Range] = []
        # `_ranges` is kept sorted by `mark_covered`; a linear scan is
        # simplest and this list is small (per-symbol/interval covered
        # spans number in the tens even after months of gaps, not
        # thousands) — `bisect_left` below is used only to skip ranges
        # that end before `rng.start_us` in the common "backfilling the
        # newest tail" case, without adding real complexity.
        start_points = [r.start_us for r in self._ranges]
        idx = bisect_left(start_points, rng.start_us)
        # A covered range starting before `rng.start_us` may still extend
        # into it, so always consider one range to the left too.
        idx = max(0, idx - 1)
        for existing in self._ranges[idx:]:
            if existing.start_us >= rng.end_us:
                break
            if existing.end_us <= cursor:
                continue
            if existing.start_us > cursor:
                holes.append(Range(cursor, min(existing.start_us, rng.end_us)))
            cursor = max(cursor, existing.end_us)
            if cursor >= rng.end_us:
                break
        if cursor < rng.end_us:
            holes.append(Range(cursor, rng.end_us))
        return holes

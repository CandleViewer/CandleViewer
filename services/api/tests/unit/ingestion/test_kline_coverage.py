"""Unit tests for `ingestion.kline_coverage` (E08-S06): merge/hole
computation for the coverage index, pure and deterministic (no I/O)."""

from __future__ import annotations

import pytest

from candleviewer.ingestion.kline_coverage import CoverageIndex, Range, bar_open_us


def test_range_rejects_end_before_start() -> None:
    with pytest.raises(ValueError, match="end_us must be >= start_us"):
        Range(100, 50)


def test_range_allows_zero_width() -> None:
    assert Range(100, 100).end_us == 100


class TestOverlapsOrTouches:
    def test_overlapping_ranges_true(self) -> None:
        assert Range(0, 100).overlaps_or_touches(Range(50, 150))

    def test_touching_ranges_true(self) -> None:
        assert Range(0, 100).overlaps_or_touches(Range(100, 200))

    def test_disjoint_ranges_false(self) -> None:
        assert not Range(0, 100).overlaps_or_touches(Range(101, 200))


class TestMarkCovered:
    def test_single_range_is_covered(self) -> None:
        index = CoverageIndex()
        index.mark_covered(Range(0, 100))
        assert index.covered_ranges() == [Range(0, 100)]

    def test_touching_ranges_merge_into_one(self) -> None:
        index = CoverageIndex()
        index.mark_covered(Range(0, 100))
        index.mark_covered(Range(100, 200))
        assert index.covered_ranges() == [Range(0, 200)]

    def test_overlapping_ranges_merge_into_one(self) -> None:
        index = CoverageIndex()
        index.mark_covered(Range(0, 100))
        index.mark_covered(Range(50, 200))
        assert index.covered_ranges() == [Range(0, 200)]

    def test_disjoint_ranges_stay_separate_and_sorted(self) -> None:
        index = CoverageIndex()
        index.mark_covered(Range(200, 300))
        index.mark_covered(Range(0, 100))
        assert index.covered_ranges() == [Range(0, 100), Range(200, 300)]

    def test_new_range_bridges_two_existing_ranges(self) -> None:
        index = CoverageIndex()
        index.mark_covered(Range(0, 100))
        index.mark_covered(Range(200, 300))
        index.mark_covered(Range(100, 200))
        assert index.covered_ranges() == [Range(0, 300)]

    def test_idempotent_same_range_twice(self) -> None:
        index = CoverageIndex()
        index.mark_covered(Range(0, 100))
        index.mark_covered(Range(0, 100))
        assert index.covered_ranges() == [Range(0, 100)]

    def test_commutative_order_of_marks_does_not_matter(self) -> None:
        a = CoverageIndex()
        a.mark_covered(Range(0, 100))
        a.mark_covered(Range(100, 200))
        a.mark_covered(Range(300, 400))

        b = CoverageIndex()
        b.mark_covered(Range(300, 400))
        b.mark_covered(Range(100, 200))
        b.mark_covered(Range(0, 100))

        assert a.covered_ranges() == b.covered_ranges()


class TestHoles:
    def test_fully_covered_range_has_no_holes(self) -> None:
        index = CoverageIndex()
        index.mark_covered(Range(0, 100))
        assert index.holes(Range(0, 100)) == []
        assert index.is_fully_covered(Range(0, 100))

    def test_empty_index_hole_is_the_whole_range(self) -> None:
        index = CoverageIndex()
        assert index.holes(Range(0, 100)) == [Range(0, 100)]
        assert not index.is_fully_covered(Range(0, 100))

    def test_zero_width_range_has_no_holes(self) -> None:
        index = CoverageIndex()
        assert index.holes(Range(50, 50)) == []

    def test_hole_before_a_covered_range(self) -> None:
        index = CoverageIndex()
        index.mark_covered(Range(50, 100))
        assert index.holes(Range(0, 100)) == [Range(0, 50)]

    def test_hole_after_a_covered_range(self) -> None:
        index = CoverageIndex()
        index.mark_covered(Range(0, 50))
        assert index.holes(Range(0, 100)) == [Range(50, 100)]

    def test_hole_in_the_middle_of_two_covered_ranges(self) -> None:
        index = CoverageIndex()
        index.mark_covered(Range(0, 30))
        index.mark_covered(Range(70, 100))
        assert index.holes(Range(0, 100)) == [Range(30, 70)]

    def test_requested_range_wider_than_all_covered_ranges(self) -> None:
        index = CoverageIndex()
        index.mark_covered(Range(40, 60))
        assert index.holes(Range(0, 100)) == [Range(0, 40), Range(60, 100)]

    def test_covered_range_starting_before_requested_start_still_counts(self) -> None:
        index = CoverageIndex()
        index.mark_covered(Range(0, 200))
        assert index.holes(Range(50, 150)) == []

    def test_interrupted_backfill_resume_only_fetches_remaining_holes(self) -> None:
        # Simulates a 90-day backfill that got through day 0-30 and 60-90
        # before an interrupt (ticket "Interrupted backfill resumes").
        index = CoverageIndex()
        index.mark_covered(Range(0, 30))
        index.mark_covered(Range(60, 90))
        assert index.holes(Range(0, 90)) == [Range(30, 60)]


class TestHorizon:
    """#3808: the index refuses coverage at or after its horizon (no bar exists there yet)."""

    def test_range_crossing_the_horizon_is_clipped_at_it(self) -> None:
        index = CoverageIndex(horizon_us=lambda: 150)
        index.mark_covered(Range(0, 300))
        assert index.covered_ranges() == [Range(0, 150)]
        assert index.holes(Range(0, 300)) == [Range(150, 300)]

    def test_range_wholly_after_the_horizon_is_refused(self) -> None:
        index = CoverageIndex(horizon_us=lambda: 150)
        index.mark_covered(Range(150, 300))
        assert index.covered_ranges() == []

    def test_horizon_is_read_at_every_mark(self) -> None:
        now = [100]
        index = CoverageIndex(horizon_us=lambda: now[0])
        index.mark_covered(Range(0, 300))
        now[0] = 250
        index.mark_covered(Range(0, 300))
        assert index.covered_ranges() == [Range(0, 250)]


@pytest.mark.parametrize(
    ("ts_us", "interval", "open_us"),
    [
        (90_000_000, "1", 60_000_000),
        (60_000_000, "1", 60_000_000),
        (86_400_000_000 + 5, "D", 86_400_000_000),
        (5 * 86_400_000_000, "W", 4 * 86_400_000_000),  # Monday 1970-01-05: weeks open Monday
        (3 * 86_400_000_000, "W", -3 * 86_400_000_000),  # Sunday: its week opened 1969-12-29
        (123, "M", 123),  # calendar month: no fixed grid, the instant itself
    ],
)
def test_bar_open_us_is_the_open_time_of_the_bar_containing_ts(
    ts_us: int, interval: str, open_us: int
) -> None:
    assert bar_open_us(ts_us, interval) == open_us

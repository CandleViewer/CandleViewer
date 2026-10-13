"""Gap reporting (E26-T02 AC 3): a recorded gap is a marker in the stream, never a silent jump."""

from __future__ import annotations

from collections.abc import Sequence

import pytest
from prometheus_client import REGISTRY

from candleviewer.replay import ReplayGap, ReplayItem, ReplaySourceUnavailable
from candleviewer.storage.errors import StorageTierUnavailable
from candleviewer.storage.models import StreamKind, TimeRange
from candleviewer.storage.repositories.recorded import RecordedEvent, RecordedGap
from candleviewer.storage.testing import StaticGapReader
from tests.unit.replay._events import SECOND, T0, Harness, gap, request, trade

START, END = 10 * SECOND, 20 * SECOND


def markers(items: Sequence[ReplayItem]) -> list[ReplayGap]:
    return [item for item in items if isinstance(item, ReplayGap)]


@pytest.mark.parametrize(
    ("gap_start", "gap_end", "at"),
    [
        (12 * SECOND, 15 * SECOND, 12 * SECOND),  # inside: marker at the gap start
        (5 * SECOND, 12 * SECOND, START),  # open before the window: clipped to its start
        (18 * SECOND, 30 * SECOND, 18 * SECOND),  # runs past the window end
        (5 * SECOND, START + 1, START),  # overlaps the window by 1 µs
        (END - 1, END + SECOND, END - 1),
    ],
)
async def test_a_gap_intersecting_the_window_becomes_one_marker_with_its_stored_bounds(
    gap_start: int, gap_end: int, at: int
) -> None:
    harness = Harness(gaps=[gap(gap_start, gap_end)], req=request(start_us=START, end_us=END))

    got = markers(await harness.read_all())

    want = ReplayGap(
        T0 + at, "BTCUSDT", StreamKind.TRADES, T0 + gap_start, T0 + gap_end, "ws_disconnect"
    )
    assert got == [want]


@pytest.mark.parametrize(
    ("gap_start", "gap_end"),
    [(5 * SECOND, START), (END, END + SECOND), (0, SECOND), (25 * SECOND, 30 * SECOND)],
)
async def test_a_gap_touching_or_outside_the_window_edges_emits_nothing(
    gap_start: int, gap_end: int
) -> None:
    """Half-open window: a gap ending at `from` or starting at `to` does not intersect it."""
    harness = Harness(gaps=[gap(gap_start, gap_end)], req=request(start_us=START, end_us=END))

    assert markers(await harness.read_all()) == []


async def test_the_marker_precedes_market_events_of_its_instant() -> None:
    at = 12 * SECOND
    harness = Harness(
        hot=[trade(at, trade_id="x"), trade(at - 1, trade_id="w")],
        gaps=[gap(at, at + SECOND, stream=StreamKind.TICKERS)],
        req=request(start_us=START, end_us=END, streams=(StreamKind.TRADES, StreamKind.TICKERS)),
    )

    got = await harness.read_all()

    kinds = [type(item).__name__ for item in got]
    assert kinds == ["RecordedEvent", "ReplayGap", "RecordedEvent"]


async def test_gaps_of_unrequested_streams_and_other_symbols_are_ignored() -> None:
    harness = Harness(
        gaps=[
            gap(12 * SECOND, 13 * SECOND, stream=StreamKind.ORDERBOOK_DELTA),
            RecordedGap("ETHUSDT", StreamKind.TRADES, T0 + 12 * SECOND, T0 + 13 * SECOND, "x"),
        ],
        req=request(start_us=START, end_us=END),
    )

    assert markers(await harness.read_all()) == []


async def test_identical_gap_rows_report_once_and_count_once() -> None:
    before = REGISTRY.get_sample_value("replay_gap_warnings_total") or 0.0
    same = gap(12 * SECOND, 13 * SECOND, cause="process_restart")
    harness = Harness(gaps=[same, same], req=request(start_us=START, end_us=END))

    got = markers(await harness.read_all())

    assert [g.cause for g in got] == ["process_restart"]
    assert REGISTRY.get_sample_value("replay_gap_warnings_total") == before + 1


class _BrokenGapReader(StaticGapReader):
    async def recording_gaps(self, symbol: str, rng: TimeRange) -> list[RecordedGap]:
        raise StorageTierUnavailable("postgres unreachable")


async def test_an_unreadable_gap_table_fails_the_replay_rather_than_hiding_gaps() -> None:
    harness = Harness(hot=[trade(SECOND)]).replace_ports(gaps=_BrokenGapReader())

    with pytest.raises(ReplaySourceUnavailable) as raised:
        await harness.read_all()

    assert (raised.value.tier, raised.value.stream) == ("recording_gaps", None)


async def test_market_events_are_untouched_by_markers() -> None:
    stored = [trade(t * SECOND, trade_id=f"t{t}") for t in range(10, 20)]
    window = request(start_us=START, end_us=END)
    harness = Harness(hot=stored, gaps=[gap(14 * SECOND, 15 * SECOND)], req=window)

    got = await harness.read_all()

    assert [item for item in got if isinstance(item, RecordedEvent)] == stored


class _LaxGapReader(StaticGapReader):
    """A reader that ignores the window: the source must re-check the intersection itself."""

    async def recording_gaps(self, symbol: str, rng: TimeRange) -> list[RecordedGap]:
        return list(self._gaps)


async def test_the_source_re_checks_the_intersection_of_every_gap_row() -> None:
    inside, outside = gap(12 * SECOND, 13 * SECOND), gap(30 * SECOND, 31 * SECOND)
    reader = _LaxGapReader([inside, outside])
    harness = Harness(req=request(start_us=START, end_us=END)).replace_ports(gaps=reader)

    got = markers(await harness.read_all())

    assert [g.gap_start_us for g in got] == [inside.start_us]

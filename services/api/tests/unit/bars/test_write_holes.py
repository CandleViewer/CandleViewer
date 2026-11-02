"""#5396: the write-hole ledger (`bars.write_holes`): a closed bar not stored is recorded once,
coalesced, bounded, journalled, cleared when stored and reported minus the bars a response serves.
"""

from __future__ import annotations

import asyncio
import threading
from dataclasses import replace
from pathlib import Path

import orjson
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from structlog.testing import capture_logs

from candleviewer.bars.metrics import (
    bars_blob_discarded_total,
    bars_write_holes_dropped_total,
    bars_write_holes_total,
)
from candleviewer.bars.write_holes import (
    JOURNAL_NAME,
    LOG_EVERY_US,
    MAX_JOURNAL_BYTES,
    MAX_RANGES_PER_SERIES,
    MAX_TOTAL_RANGES,
    HoleKey,
    Present,
    WriteHoleLedger,
    cap_spans,
    hole_key_for_row,
    join_spans,
)

SYM = "BTCUSDT"
H = "a" * 64
T0 = 1_700_000_000_000_000
W = 60_000_000  # one minute, µs


def _key(idx: int, *, gen: int = 7, kind: str = "time", open_us: int | None = None) -> HoleKey:
    start = T0 + idx * W if open_us is None else open_us
    end = start + W if kind == "time" else start + 1
    return HoleKey(SYM, H, kind, "1m" if kind == "time" else "tick:100", gen, idx, start, end)


def _dropped() -> float:
    value: float = bars_write_holes_dropped_total._value.get()
    return value


def _metric(reason: str) -> float:
    value: float = bars_write_holes_total.labels(reason=reason)._value.get()
    return value


def _all(ledger: WriteHoleLedger, present: list[Present] | None = None) -> list[tuple[int, int]]:
    return ledger.holes_for(SYM, H, 0, 2**62, present or [])


def test_write_holes_repeat_terminal_outcome_records_once_and_counts_once(tmp_path: Path) -> None:
    ledger = WriteHoleLedger(tmp_path, now_us=lambda: 42)
    before = _metric("permanent")
    assert ledger.lost([_key(1)], "permanent") == 1
    assert ledger.lost([_key(1)], "permanent") == 0
    assert _metric("permanent") == before + 1
    (rec,) = ledger.pending()
    assert (rec.first_index, rec.last_index, rec.count, rec.reason, rec.first_seen_us) == (
        1, 1, 2, "permanent", 42,
    )  # fmt: skip
    assert (rec.from_us, rec.to_us) == (T0 + W, T0 + 2 * W)


def test_write_holes_contiguous_indexes_of_one_generation_coalesce(tmp_path: Path) -> None:
    ledger = WriteHoleLedger(tmp_path)
    ledger.lost([_key(3), _key(1)], "refused")
    ledger.lost([_key(2)], "refused")  # joins the two records
    ledger.lost([_key(4, gen=8)], "refused")  # another generation: a record of its own
    recs = sorted((r.generation, r.first_index, r.last_index) for r in ledger.pending())
    assert recs == [(7, 1, 3), (8, 4, 4)]
    assert _all(ledger) == [(T0 + W, T0 + 5 * W)]


def test_write_holes_past_the_bound_the_oldest_merge_and_nothing_is_dropped(
    tmp_path: Path,
) -> None:
    ledger = WriteHoleLedger(tmp_path)
    n = MAX_RANGES_PER_SERIES + 20
    ledger.lost([_key(2 * i) for i in range(n)], "shutdown")  # never contiguous
    recs = ledger.pending()
    assert len(recs) == MAX_RANGES_PER_SERIES
    assert sum(r.merged for r in recs) == 1 and sum(r.count for r in recs) == n
    spans = _all(ledger)
    for i in range(n):
        start = T0 + 2 * i * W
        assert any(a <= start and start + W <= b for a, b in spans), i


@pytest.mark.asyncio
async def test_write_holes_journal_round_trips_through_a_reload(tmp_path: Path) -> None:
    ledger = WriteHoleLedger(tmp_path, now_us=lambda: 5)
    ledger.lost([_key(1), _key(2), _key(9, gen=8)], "transient_exhausted")
    await ledger.flush()
    again = WriteHoleLedger(tmp_path)
    assert again.revision(SYM, H) == 0
    assert await again.load() == "ok"
    assert again.pending() == ledger.pending()
    assert again.revision(SYM, H) > 0  # a reload refreshes a render cache
    assert _all(again) == _all(ledger)


@pytest.mark.asyncio
async def test_write_holes_journal_is_written_after_each_change(tmp_path: Path) -> None:
    ledger = WriteHoleLedger(tmp_path)
    ledger.lost([_key(1)], "refused")
    await ledger.flush()
    doc = orjson.loads((tmp_path / JOURNAL_NAME).read_bytes())
    assert doc["v"] == 1 and doc["series"][0]["symbol"] == SYM
    ledger.written([_key(1)])
    await ledger.flush()
    assert orjson.loads((tmp_path / JOURNAL_NAME).read_bytes())["series"] == []


@pytest.mark.asyncio
async def test_write_holes_missing_journal_starts_empty_without_a_count(tmp_path: Path) -> None:
    before = bars_blob_discarded_total.labels(reason="write_holes")._value.get()
    ledger = WriteHoleLedger(tmp_path)
    assert await ledger.load() == "missing" and ledger.pending() == []
    assert not ledger.dropped
    assert bars_blob_discarded_total.labels(reason="write_holes")._value.get() == before


def _doc(ranges: list[list[object]], **series: object) -> bytes:
    one = {"symbol": SYM, "spec_hash": H, "kind": "time", "bar_param": "1m", "ranges": ranges}
    return orjson.dumps({"v": 1, "series": [{**one, **series}]})


@pytest.mark.parametrize(
    ("data", "reason"),
    [
        (b"{not json", "corrupt"),
        (orjson.dumps({"v": 99, "series": []}), "version"),
        (_doc([], symbol="../x"), "corrupt"),
        (_doc([], spec_hash="../x"), "corrupt"),
        (_doc([[7, 1, 1, 5, 9, "refused", 0, 1, False]], kind="ohlc"), "corrupt"),
        (_doc([]), "corrupt"),  # a series with no record
        (_doc([[7, 1, 1, 5, 5, "refused", 0, 1, False]]), "corrupt"),  # an empty span
        (_doc([[7, 2, 1, 5, 9, "refused", 0, 1, False]]), "corrupt"),  # indexes out of order
        (_doc([[7, 1, 1, 5, 9, "lost", 0, 1, False]]), "corrupt"),  # a reason not in the set
        (_doc([[7, 1, 1, 5, 9, "refused", 0, 0, False]]), "corrupt"),  # a zero count
        (_doc([[7, 1, 1, 5, 9, "refused", 0, 1, 0]]), "corrupt"),  # `merged` not a bool
        (_doc([[True, 1, 1, 5, 9, "refused", 0, 1, False]]), "corrupt"),  # a bool generation
    ],
)
@pytest.mark.asyncio
async def test_write_holes_unreadable_journal_is_discarded_and_counted(
    tmp_path: Path, data: bytes, reason: str
) -> None:
    (tmp_path / JOURNAL_NAME).write_bytes(data)
    before = bars_blob_discarded_total.labels(reason="write_holes")._value.get()
    ledger = WriteHoleLedger(tmp_path)
    assert await ledger.load() == reason
    assert ledger.pending() == []
    assert bars_blob_discarded_total.labels(reason="write_holes")._value.get() == before + 1
    assert ledger.dropped  # its holes are no longer listed: `bars_writer` degrades


@pytest.mark.asyncio
async def test_write_holes_oversized_journal_is_discarded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from candleviewer.bars import write_holes

    (tmp_path / JOURNAL_NAME).write_bytes(_doc([[7, 1, 1, 5, 9, "refused", 0, 1, False]]))
    monkeypatch.setattr(write_holes, "MAX_JOURNAL_BYTES", 16)
    ledger = WriteHoleLedger(tmp_path)
    assert await ledger.load() == "too_large" and ledger.dropped


@pytest.mark.asyncio
async def test_write_holes_journal_that_cannot_be_written_is_kept_and_written_later(
    tmp_path: Path,
) -> None:
    blocker = tmp_path / "root"
    blocker.write_bytes(b"")  # a file where the journal's directory should be
    ledger = WriteHoleLedger(blocker / "bars")
    ledger.lost([_key(1)], "refused")
    await ledger.flush()
    assert not (blocker / "bars" / JOURNAL_NAME).exists()
    blocker.unlink()
    await ledger.flush()  # still pending: written now
    again = WriteHoleLedger(blocker / "bars")
    assert await again.load() == "ok" and len(again.pending()) == 1


def test_write_holes_merged_non_time_span_keeps_a_stored_key(tmp_path: Path) -> None:
    ledger = WriteHoleLedger(tmp_path)
    n = MAX_RANGES_PER_SERIES + 1
    ledger.lost([_key(2 * i, kind="tick", open_us=T0 + 2 * i) for i in range(n)], "permanent")
    (merged,) = [r for r in ledger.pending() if r.merged]
    ledger.written([_key(0, kind="tick", open_us=T0)])  # siblings cannot be told apart
    assert any(r.merged and r.from_us == merged.from_us for r in ledger.pending())


def test_write_holes_a_stored_key_leaves_its_record_which_splits(tmp_path: Path) -> None:
    ledger = WriteHoleLedger(tmp_path)
    ledger.lost([_key(i) for i in range(1, 6)], "sink_timeout")
    ledger.written([_key(3)])
    assert _all(ledger) == [(T0 + W, T0 + 3 * W), (T0 + 4 * W, T0 + 6 * W)]
    ledger.written([_key(i) for i in (1, 2, 4, 5)])
    assert _all(ledger) == [] and ledger.pending() == []


def test_write_holes_a_key_stored_before_its_loss_is_reported_is_not_recorded(
    tmp_path: Path,
) -> None:
    ledger = WriteHoleLedger(tmp_path)
    ledger.written([_key(1)])
    assert ledger.lost([_key(1)], "sink_timeout") == 0 and ledger.pending() == []


def test_write_holes_a_row_with_no_builder_index_is_not_recorded(tmp_path: Path) -> None:
    ledger = WriteHoleLedger(tmp_path)
    kline = HoleKey(SYM, H, "time", "1m", None, None, T0, T0 + W)
    assert ledger.lost([kline], "refused") == 0 and ledger.pending() == []


def test_write_holes_unknown_reason_is_refused(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="reason"):
        WriteHoleLedger(tmp_path).lost([_key(1)], "lost")


def test_write_holes_a_served_bar_suppresses_its_key(tmp_path: Path) -> None:
    ledger = WriteHoleLedger(tmp_path)
    ledger.lost([_key(1), _key(2)], "refused")
    held = Present(7, 2, T0 + 2 * W, T0 + 3 * W)
    assert _all(ledger, [held]) == [(T0 + W, T0 + 2 * W)]
    other_gen = Present(9, 2, T0 + 2 * W, T0 + 3 * W)  # a time bar fills by open time
    assert _all(ledger, [other_gen]) == [(T0 + W, T0 + 2 * W)]
    kline = Present(None, None, T0 + W, T0 + 2 * W)
    assert _all(ledger, [kline, held]) == []
    assert len(ledger.pending()) == 1  # a read never changes the ledger


def test_write_holes_non_time_siblings_at_one_open_time_are_told_apart(tmp_path: Path) -> None:
    ledger = WriteHoleLedger(tmp_path)
    ledger.lost([_key(i, kind="tick", open_us=T0) for i in (3, 4, 5)], "permanent")
    served = Present(7, 4, T0, T0 + 1)
    assert _all(ledger, [served]) == [(T0, T0 + 1)]  # 3 and 5 are still missing
    ledger.written([_key(3, kind="tick", open_us=T0), _key(5, kind="tick", open_us=T0)])
    assert _all(ledger) == [(T0, T0 + 1)]  # 4 is
    assert _all(ledger, [served]) == []
    wrong_gen = Present(8, 4, T0, T0 + 1)  # another generation is another bar
    assert _all(ledger, [wrong_gen]) == [(T0, T0 + 1)]


def test_write_holes_reads_are_clipped_to_the_page_span(tmp_path: Path) -> None:
    ledger = WriteHoleLedger(tmp_path)
    ledger.lost([_key(1), _key(2), _key(3)], "refused")
    assert ledger.holes_for(SYM, H, T0 + 2 * W, T0 + 3 * W, []) == [(T0 + 2 * W, T0 + 3 * W)]
    assert ledger.holes_for(SYM, H, 0, T0 + W, []) == []  # ends where the hole starts
    assert ledger.holes_for(SYM, H, T0 + 4 * W, 2**62, []) == []  # starts where it ends
    assert ledger.holes_for(SYM, H, T0 + 2 * W, T0 + 2 * W, []) == []  # an empty span
    assert ledger.holes_for(SYM, "b" * 64, 0, 2**62, []) == []


def test_write_holes_revision_moves_on_every_change_of_its_series(tmp_path: Path) -> None:
    ledger = WriteHoleLedger(tmp_path)
    r0 = ledger.revision(SYM, H)
    ledger.lost([_key(1)], "refused")
    r1 = ledger.revision(SYM, H)
    ledger.written([_key(1)])
    assert r0 < r1 < ledger.revision(SYM, H)
    ledger.written([_key(5)])  # nothing recorded there: no change
    assert ledger.revision(SYM, H) == r1 + 1


def test_write_holes_key_of_a_stored_row() -> None:
    row: dict[str, object] = {"symbol": SYM, "bar_param": "1m", "ts": T0, "close_ts": T0 + W - 1,
                              "generation": 7, "index": 1}  # fmt: skip
    assert hole_key_for_row(row, H, "time") == HoleKey(SYM, H, "time", "1m", 7, 1, T0, T0 + W)
    kline: dict[str, object] = {"symbol": SYM, "ts": T0, "close_ts": T0 + W, "generation": 0,
                                "index": None}  # fmt: skip
    key = hole_key_for_row(kline, H, "time")
    assert (key.index, key.end_us) == (None, T0 + W)


def test_write_holes_spans_join_and_cap_without_dropping_coverage() -> None:
    assert join_spans([(5, 6), (1, 2), (2, 3), (4, 6)]) == [(1, 3), (4, 6)]
    spans = [(i * 10, i * 10 + 1) for i in range(5)]
    assert cap_spans(spans, 5) == spans
    assert cap_spans(spans, 3) == [(0, 21), (30, 31), (40, 41)]
    assert cap_spans(spans, 1) == [(0, 41)]


# -- superseded, merged spans, logging -----------------------------------------------------------


def test_write_holes_a_stored_key_not_stored_again_is_superseded_not_a_hole(
    tmp_path: Path,
) -> None:
    ledger = WriteHoleLedger(tmp_path)
    before, holes = _metric("superseded"), _metric("permanent")
    ledger.written([_key(1)])
    with capture_logs() as logs:
        assert ledger.lost([_key(1)], "permanent") == 0
    assert ledger.pending() == [] and _all(ledger) == []
    assert (_metric("superseded"), _metric("permanent")) == (before + 1, holes)
    assert [e["event"] for e in logs] == ["bars_write_holes_superseded"]


def test_write_holes_a_new_key_inside_a_merged_span_is_counted_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from candleviewer.bars import write_holes

    monkeypatch.setattr(write_holes, "MAX_RANGES_PER_SERIES", 2)
    ledger = WriteHoleLedger(tmp_path)
    assert ledger.lost([_key(0), _key(2), _key(4)], "refused") == 3
    merged = [r for r in ledger.pending() if r.merged]
    assert merged and merged[0].from_us <= _key(1).open_us < merged[0].to_us
    rev = ledger.revision(SYM, H)
    assert ledger.lost([_key(1)], "refused") == 1  # never counted before, inside the merged span
    assert ledger.lost([_key(1)], "refused") == 0  # its repeat
    assert ledger.lost([_key(2)], "refused") == 0  # a key counted before the merge
    assert ledger.revision(SYM, H) == rev  # the spans did not change: no cache refresh


def test_write_holes_a_repeat_does_not_move_the_revision(tmp_path: Path) -> None:
    ledger = WriteHoleLedger(tmp_path)
    ledger.lost([_key(1)], "refused")
    rev = ledger.revision(SYM, H)
    ledger.lost([_key(1)], "refused")
    assert ledger.revision(SYM, H) == rev and ledger.pending()[0].count == 2


def test_write_holes_recorded_log_is_once_per_series_per_minute(tmp_path: Path) -> None:
    now = [T0]
    ledger = WriteHoleLedger(tmp_path, now_us=lambda: now[0])
    with capture_logs() as logs:
        ledger.lost([_key(1)], "refused")
        ledger.lost([_key(3)], "refused")
        now[0] += LOG_EVERY_US
        ledger.lost([_key(5)], "refused")
    assert [e["event"] for e in logs].count("bars_write_holes_recorded") == 2


def test_write_holes_past_the_soft_series_cap_the_stalest_collapse_never_drop(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A series with records is never dropped below the hard cap: past the soft cap the stalest
    collapse to one merged span each, which still covers every key (an over-report)."""
    from candleviewer.bars import write_holes

    monkeypatch.setattr(write_holes, "MAX_SERIES_SOFT", 2)
    now = [T0]
    ledger = WriteHoleLedger(tmp_path, now_us=lambda: now[0])
    before = _dropped()
    for n, h in enumerate(("a", "b", "c")):
        now[0] = T0 + n
        ledger.lost(
            [replace(_key(1), spec_hash=h * 64), replace(_key(3), spec_hash=h * 64)], "refused"
        )
    by_hash = {r.spec_hash: r for r in ledger.pending() if r.merged}
    assert sorted({r.spec_hash for r in ledger.pending()}) == ["a" * 64, "b" * 64, "c" * 64]
    assert list(by_hash) == ["a" * 64]  # the stalest, collapsed to one span
    assert (by_hash["a" * 64].from_us, by_hash["a" * 64].to_us) == (T0 + W, T0 + 4 * W)
    assert _dropped() == before and not ledger.dropped


def test_write_holes_past_the_hard_series_cap_the_drop_is_counted_and_flagged(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from candleviewer.bars import write_holes

    monkeypatch.setattr(write_holes, "MAX_SERIES_SOFT", 1)
    monkeypatch.setattr(write_holes, "MAX_SERIES", 2)
    now = [T0]
    ledger = WriteHoleLedger(tmp_path, now_us=lambda: now[0])
    before = _dropped()
    with capture_logs() as logs:
        for n, h in enumerate(("a", "b", "c")):
            now[0] = T0 + n
            ledger.lost([replace(_key(1), spec_hash=h * 64)], "refused")
    assert sorted({r.spec_hash for r in ledger.pending()}) == ["b" * 64, "c" * 64]
    assert _dropped() == before + 1 and ledger.dropped
    assert "bars_write_holes_series_dropped" in [e["event"] for e in logs]


@pytest.mark.asyncio
async def test_write_holes_a_record_never_expires_with_age(tmp_path: Path) -> None:
    """A pinned symbol or a raised retention policy keeps serving old rows, so a record far older
    than the default 730-day retention still survives a reload and is still listed."""
    day = 86_400_000_000
    earlier = WriteHoleLedger(tmp_path)
    old_tick = _key(1, kind="tick", open_us=T0)
    earlier.lost([old_tick], "refused")
    await earlier.flush()
    ledger = WriteHoleLedger(tmp_path, now_us=lambda: T0 + 3_650 * day)
    assert await ledger.load() == "ok"
    assert _all(ledger) == [(old_tick.open_us, old_tick.end_us)]
    assert not ledger.dropped


@pytest.mark.asyncio
async def test_write_holes_hand_edited_journal_loads_or_is_discarded_never_raises(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from candleviewer.bars import write_holes

    one = [[7, 1, 1, T0, T0 + W, "refused", 0, 1, False]]
    doc = {"v": 1, "series": [{"symbol": SYM, "spec_hash": h * 64, "kind": "time",
                               "bar_param": "1m", "ranges": one} for h in "abc"]}  # fmt: skip
    (tmp_path / JOURNAL_NAME).write_bytes(orjson.dumps(doc))
    monkeypatch.setattr(write_holes, "MAX_TOTAL_RANGES", 2)  # over it, one record a series
    ledger = WriteHoleLedger(tmp_path)
    assert await ledger.load() == "ok" and len(ledger.pending()) == 3
    monkeypatch.setattr(write_holes, "MAX_SERIES", 2)  # over the series cap: never ours
    before = bars_blob_discarded_total.labels(reason="write_holes")._value.get()
    again = WriteHoleLedger(tmp_path)
    assert await again.load() == "corrupt" and again.pending() == []
    assert bars_blob_discarded_total.labels(reason="write_holes")._value.get() == before + 1


# -- the journal's bound and its write path -------------------------------------------------------


@pytest.mark.asyncio
async def test_write_holes_journal_filled_to_the_cap_reloads(tmp_path: Path) -> None:
    """M1: every series full at the widest values is still a journal `load` accepts."""
    big = 2**61  # 19 digits
    ledger = WriteHoleLedger(tmp_path, now_us=lambda: big)
    per = MAX_RANGES_PER_SERIES
    hashes = [f"{n:064x}" for n in range(MAX_TOTAL_RANGES // per + 6)]

    def keys(h: str) -> list[HoleKey]:  # never contiguous: one record each until merged
        return [HoleKey(SYM, h, "tick", "tick:100", big, big + 2 * i, big + 2 * i,
                        big + 2 * i + 1) for i in range(per)]  # fmt: skip

    for h in hashes:
        ledger.lost(keys(h), "transient_exhausted")
    assert len(ledger.pending()) == MAX_TOTAL_RANGES
    await ledger.flush()
    assert (tmp_path / JOURNAL_NAME).stat().st_size <= MAX_JOURNAL_BYTES
    again = WriteHoleLedger(tmp_path)
    assert await again.load() == "ok"
    for h in hashes:  # merged where the bound needed it: over-reported, never dropped
        spans = again.holes_for(SYM, h, 0, 2**62, [])
        assert all(any(a <= k.open_us and k.end_us <= b for a, b in spans) for k in keys(h))


@pytest.mark.asyncio
async def test_write_holes_journal_over_its_byte_bound_merges_and_reloads(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from candleviewer.bars import write_holes

    monkeypatch.setattr(write_holes, "MAX_JOURNAL_BYTES", 2048)
    ledger = WriteHoleLedger(tmp_path)
    ledger.lost([_key(2 * i) for i in range(60)], "refused")
    await ledger.flush()
    assert (tmp_path / JOURNAL_NAME).stat().st_size <= 2048
    again = WriteHoleLedger(tmp_path)
    assert await again.load() == "ok"
    for i in range(60):  # merged, so over-reported, never dropped
        k = _key(2 * i)
        assert any(a <= k.open_us and k.end_us <= b for a, b in _all(again)), i


@pytest.mark.asyncio
async def test_write_holes_a_cancelled_write_loses_no_change_and_writes_never_overlap(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """M2: the journal task is cancelled while its write runs; a change made meanwhile is on
    disk after `flush`, and the two writes never run at once."""
    from candleviewer.bars import write_holes

    real = write_holes._write_atomic
    gate, entered = threading.Event(), asyncio.Event()
    loop = asyncio.get_running_loop()
    running, overlap = [0], [False]

    def slow(path: Path, data: bytes) -> None:
        running[0] += 1
        overlap[0] |= running[0] > 1
        loop.call_soon_threadsafe(entered.set)
        gate.wait(10)
        try:
            real(path, data)
        finally:
            running[0] -= 1

    monkeypatch.setattr(write_holes, "_write_atomic", slow)
    ledger = WriteHoleLedger(tmp_path)
    ledger.lost([_key(1)], "refused")
    await entered.wait()
    ledger.lost([_key(5)], "refused")  # changed while the first write runs
    task = ledger._task
    assert task is not None
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)
    gate.set()
    await ledger.flush()
    assert not overlap[0]
    again = WriteHoleLedger(tmp_path)
    assert await again.load() == "ok"
    assert _all(again) == [(T0 + W, T0 + 2 * W), (T0 + 5 * W, T0 + 6 * W)]


# -- property: every terminally lost key is counted once and listed until stored ----------------

_EVENTS = st.lists(
    st.tuples(st.sampled_from(("lost", "written")), st.integers(0, 3), st.integers(0, 40)),
    max_size=60,
)


@settings(max_examples=150, deadline=None)
@given(
    events=_EVENTS,
    kind=st.sampled_from(("time", "tick")),
    served=st.sets(st.tuples(st.integers(0, 3), st.integers(0, 40)), max_size=20),
)
def test_write_holes_property_lost_keys_counted_once_and_listed_until_stored(
    tmp_path_factory: pytest.TempPathFactory,
    events: list[tuple[str, int, int]],
    kind: str,
    served: set[tuple[int, int]],
) -> None:
    """Every key lost before it was stored is counted once, a loss after a store is superseded,
    and `holes_for` names every key still lost and not served: with merging exercised (at most 4
    records a series), a random set of bars served, never a false negative."""
    from candleviewer.bars import write_holes

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(write_holes, "MAX_RANGES_PER_SERIES", 4)
        ledger = WriteHoleLedger(tmp_path_factory.mktemp("holes"))
        state: dict[tuple[int, int], str] = {}  # (gen, idx) -> "hole" | "stored"
        counted = superseded = 0
        before, sup_before = _metric("refused"), _metric("superseded")

        def key(gen: int, idx: int) -> HoleKey:
            # one series: a generation's bars follow the previous one's, index order is time order
            return _key(idx, gen=gen, kind=kind, open_us=T0 + (gen * 100 + idx) * W)

        for op, gen, idx in events:
            if op == "lost":
                new = ledger.lost([key(gen, idx)], "refused")
                was = state.get((gen, idx))
                assert new == int(was is None)
                if was is None:
                    state[gen, idx] = "hole"
                    counted += 1
                superseded += was == "stored"
            else:
                ledger.written([key(gen, idx)])
                state[gen, idx] = "stored"
        assert _metric("refused") == before + counted
        assert _metric("superseded") == sup_before + superseded
        present = [Present(gen, idx, key(gen, idx).open_us, key(gen, idx).end_us)
                   for gen, idx in served]  # fmt: skip
        spans = _all(ledger, present)
        merged = any(r.merged for r in ledger.pending())
        for (gen, idx), what in state.items():
            k = key(gen, idx)
            covered = any(a <= k.open_us and k.end_us <= b for a, b in spans)
            if what == "hole" and (gen, idx) not in served:
                assert covered, (gen, idx)  # no false negative
            elif kind == "time" and not merged and what == "stored":
                assert not any(a < k.end_us and k.open_us < b for a, b in spans), (gen, idx)

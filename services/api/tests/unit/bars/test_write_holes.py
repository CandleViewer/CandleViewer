"""#5396: the write-hole ledger (`bars.write_holes`): a closed bar not stored is recorded once,
coalesced, bounded, journalled, cleared when stored and reported minus the bars a response serves.
"""

from __future__ import annotations

from pathlib import Path

import orjson
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from candleviewer.bars.metrics import bars_blob_discarded_total, bars_write_holes_total
from candleviewer.bars.write_holes import (
    JOURNAL_NAME,
    MAX_RANGES_PER_SERIES,
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


@pytest.mark.asyncio
async def test_write_holes_oversized_journal_is_discarded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from candleviewer.bars import write_holes

    (tmp_path / JOURNAL_NAME).write_bytes(_doc([[7, 1, 1, 5, 9, "refused", 0, 1, False]]))
    monkeypatch.setattr(write_holes, "MAX_JOURNAL_BYTES", 16)
    assert await WriteHoleLedger(tmp_path).load() == "too_large"


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


# -- property: every terminally lost key is counted once and listed until stored ----------------

_EVENTS = st.lists(
    st.tuples(st.sampled_from(("lost", "written")), st.integers(0, 3), st.integers(0, 40)),
    max_size=60,
)


@settings(max_examples=150, deadline=None)
@given(events=_EVENTS, kind=st.sampled_from(("time", "tick")))
def test_write_holes_property_lost_keys_counted_once_and_listed_until_stored(
    tmp_path_factory: pytest.TempPathFactory,
    events: list[tuple[str, int, int]],
    kind: str,
) -> None:
    ledger = WriteHoleLedger(tmp_path_factory.mktemp("holes"))
    state: dict[tuple[int, int], str] = {}  # (gen, idx) -> "hole" | "stored"
    counted = 0
    before = _metric("refused")

    def key(gen: int, idx: int) -> HoleKey:
        # one series: a generation's bars follow the previous one's, index order is time order
        return _key(idx, gen=gen, kind=kind, open_us=T0 + (gen * 100 + idx) * W)

    for op, gen, idx in events:
        if op == "lost":
            new = ledger.lost([key(gen, idx)], "refused")
            first = (gen, idx) not in state
            assert new == int(first)
            if first:
                state[gen, idx] = "hole"
                counted += 1
        else:
            ledger.written([key(gen, idx)])
            state[gen, idx] = "stored"
    assert _metric("refused") == before + counted
    spans = _all(ledger)
    for (gen, idx), what in state.items():
        k = key(gen, idx)
        covered = any(a <= k.open_us and k.end_us <= b for a, b in spans)
        if what == "hole":
            assert covered, (gen, idx)
        elif kind == "time":  # a stored time bar is never listed (exact by open time)
            assert not any(a < k.end_us and k.open_us < b for a, b in spans), (gen, idx)

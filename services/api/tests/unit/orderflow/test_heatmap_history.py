"""E21-T03 (#606) `orderflow.heatmap_history`: the recorded read behind `GET /market/heatmap`
(22 `getHeatmap`, 24 §6.3 "Read-time bucketing"). Test names carry the ticket's Gherkin scenario
they verify. Cells are seeded from the committed E21-T02 golden columns (built from the recorded
BTCUSDT capture) and the book from the recorded capture itself (`packages/fixtures/bybit/
2026-10-05`, C-13.5): no invented payload, no network."""

from __future__ import annotations

import asyncio
import functools
import json
from collections.abc import Sequence
from decimal import Decimal
from typing import Any, Literal

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from candleviewer.orderflow.heatmap_history import (
    DOWNSAMPLE_AGE_US,
    MAX_COLUMNS,
    BookAnchor,
    BookChange,
    CellRow,
    CellSpan,
    HeatmapQuery,
    HeatmapQueryError,
    book_checksum,
    read_heatmap_history,
)
from tests._corpus import CORPUS_ROOT, frames

SYM = "BTCUSDT"
TICK = Decimal("0.1")
T0_US = 1_700_000_000_000_000  # the capture's first frame, epoch µs
MIN_US = 60_000_000
HOUR_US = 60 * MIN_US
BASE_US = T0_US - T0_US % HOUR_US  # on every bucket grid, 60 000 ms included
GOLDEN = CORPUS_ROOT.parent / "golden" / "heatmap" / "columns_BTCUSDT.json"


@functools.cache
def _golden() -> tuple[dict[str, Any], ...]:
    return tuple(json.loads(GOLDEN.read_text()))


def _cells_at(ts_us: int, column: dict[str, Any], *, estimated: bool = False) -> list[CellRow]:
    """One golden column (grid `price_min` + i * `price_step`) as the stored rows of a native
    column at `ts_us` (21 §4.12: one row a populated level, its column's fields repeated)."""
    base, step = Decimal(column["price_min"]), Decimal(column["price_step"])
    return [
        CellRow(ts_us, float(base + i * step), b, a, 1, estimated)
        for i, (b, a) in enumerate(zip(column["bids"], column["asks"], strict=True))
        if b or a
    ]


def _seeded(lo_us: int, hi_us: int, every_us: int = 1_000_000) -> list[CellRow]:
    """One native column every `every_us` in `[lo_us, hi_us)`, cycling through the golden."""
    golden = _golden()
    rows: list[CellRow] = []
    for k, ts in enumerate(range(lo_us, hi_us, every_us)):
        rows += _cells_at(ts, golden[k % len(golden)])
    return rows


@functools.cache
def _capture() -> tuple[BookAnchor, tuple[BookChange, ...]]:
    """The recorded BTCUSDT depth-200 capture as a stored snapshot and its stored deltas."""
    records = [json.loads(f) for f in frames("ws/orderbook_BTCUSDT.jsonl")]
    first = records[0]

    def levels(raw: list[list[str]]) -> tuple[tuple[Decimal, Decimal], ...]:
        return tuple((Decimal(p), Decimal(q)) for p, q in raw)

    bids, asks = levels(first["data"]["b"]), levels(first["data"]["a"])
    anchor = BookAnchor(
        first["ts"] * 1000, first["data"]["u"], bids, asks, book_checksum(bids, asks)
    )
    changes: list[BookChange] = []
    for r in records[1:]:
        if r["type"] != "delta":
            break  # the file's second snapshot is a reset, not this anchor's continuation
        for side, key in (("bid", "b"), ("ask", "a")):
            for p, q in r["data"][key]:
                side_: Literal["bid", "ask"] = "bid" if side == "bid" else "ask"
                changes.append(
                    BookChange(r["ts"] * 1000, r["data"]["u"], side_, Decimal(p), Decimal(q))
                )
    return anchor, tuple(changes)


class FakeReader:
    """`HeatmapHistoryReader` over seeded rows; records every call."""

    def __init__(
        self,
        rows: Sequence[CellRow] = (),
        *,
        first: int | None = None,
        anchors: Sequence[BookAnchor] = (),
        changes: Sequence[BookChange] = (),
        hot_from_us: int | None = None,
    ) -> None:
        self.rows = sorted(rows, key=lambda r: r.ts_us)
        self.first = first
        self.anchors = sorted(anchors, key=lambda a: a.ts_us)
        self.changes = list(changes)
        self.hot_from_us = hot_from_us
        self.calls: list[tuple[str, int, int]] = []

    async def first_available(self, symbol: str) -> int | None:
        return self.first

    async def cells(self, symbol: str, lo_us: int, hi_us: int) -> Sequence[CellSpan]:
        self.calls.append(("cells", lo_us, hi_us))
        cut = hi_us if self.hot_from_us is None else min(max(self.hot_from_us, lo_us), hi_us)
        spans: list[CellSpan] = []
        for a, b, tier in ((lo_us, cut, "cold"), (cut, hi_us, "hot")):
            if b > a:
                rows = [r for r in self.rows if a <= r.ts_us < b]
                spans.append(CellSpan(a, b, "cold" if tier == "cold" else "hot", rows))
        return spans

    async def book_anchor(
        self, symbol: str, depth: int, at_us: int, *, not_before_us: int
    ) -> BookAnchor | None:
        self.calls.append(("anchor", not_before_us, at_us))
        found = [a for a in self.anchors if not_before_us <= a.ts_us <= at_us]
        return found[-1] if found else None

    async def book_changes(
        self, symbol: str, depth: int, lo_us: int, hi_us: int
    ) -> Sequence[BookChange]:
        self.calls.append(("changes", lo_us, hi_us))
        return [c for c in self.changes if lo_us <= c.ts_us < hi_us]


def _q(lo_us: int, hi_us: int, **kw: Any) -> HeatmapQuery:
    return HeatmapQuery(SYM, lo_us, hi_us, **({"tick_size": TICK} | kw))


async def test_dense_matrix_dimensions_match_axes() -> None:
    """Scenario: Dense matrix response (10 minutes at 1 000 ms, depth 200)."""
    lo, hi = T0_US, T0_US + 10 * MIN_US
    out = await read_heatmap_history(FakeReader(_seeded(lo, hi), first=lo), _q(lo, hi), now_us=hi)
    assert len(out.times_us) == 600 and out.times_us[0] == lo
    assert len(out.prices) == len(out.bid_matrix) == len(out.ask_matrix) > 0
    assert all(len(row) == 600 for row in out.bid_matrix + out.ask_matrix)
    assert len(out.samples) == len(out.estimated_columns) == 600
    assert list(out.prices) == sorted(out.prices)
    steps = {b - a for a, b in zip(out.prices, out.prices[1:], strict=False)}
    assert steps == {TICK}
    assert out.history == "full" and not out.clamped and out.remainder is None


async def test_normalize_window_scales_0_to_1() -> None:
    """Scenario: Dense matrix response — normalize=window scales cells to 0..1 over the window."""
    lo, hi = T0_US, T0_US + 10 * MIN_US
    out = await read_heatmap_history(
        FakeReader(_seeded(lo, hi), first=lo), _q(lo, hi, normalize="window"), now_us=hi
    )
    cells = [v for row in out.bid_matrix + out.ask_matrix for v in row]
    assert min(cells) >= 0.0 and max(cells) == 1.0
    raw = max(max(c["bids"] + c["asks"]) for c in _golden()) / 10  # one native of 10 a bucket
    assert out.max_value == pytest.approx(raw)


async def test_normalize_column() -> None:
    lo, hi = T0_US, T0_US + 5_000_000
    out = await read_heatmap_history(
        FakeReader(_seeded(lo, hi), first=lo), _q(lo, hi, normalize="column"), now_us=hi
    )
    for j in range(len(out.times_us)):
        column = [row[j] for row in out.bid_matrix + out.ask_matrix]
        assert max(column) == pytest.approx(1.0)


async def test_normalize_none() -> None:
    lo, hi = T0_US, T0_US + 1_000_000
    column = _golden()[0]
    out = await read_heatmap_history(
        FakeReader(_cells_at(lo, column), first=lo),
        _q(lo, hi, time_bucket_ms=100, normalize="none"),
        now_us=hi,
    )
    assert out.samples[0] == 1 and out.samples[1:] == (0,) * 9
    by_price = dict(zip(out.prices, (row[0] for row in out.bid_matrix), strict=True))
    base = Decimal(column["price_min"])
    assert by_price[base] == column["bids"][0]  # a native bucket: the stored size unchanged


async def test_partial_history_returns_first_available_without_fabricated_columns() -> None:
    """Scenario: Partial history boundary (3 hours recorded, 24 requested)."""
    hi = BASE_US + 24 * HOUR_US
    first = hi - 3 * HOUR_US
    reader = FakeReader(_seeded(first, hi, every_us=MIN_US), first=first)
    out = await read_heatmap_history(reader, _q(BASE_US, hi, time_bucket_ms=60000), now_us=hi)
    assert out.history == "partial" and out.first_available_us == first
    assert out.from_us == out.times_us[0] == first and len(out.times_us) == 180
    assert reader.calls[0] == ("cells", first, hi)  # never asked before what was recorded


async def test_downsampled_segment_discloses_effective_resolution() -> None:
    """Scenario: Downsampled resolution is disclosed (the window straddles 180 days)."""
    now = T0_US + DOWNSAMPLE_AGE_US + 30_000_000
    lo, hi = T0_US, T0_US + 60_000_000
    reader = FakeReader(_seeded(lo, hi), first=lo)
    out = await read_heatmap_history(reader, _q(lo, hi, time_bucket_ms=250), now_us=now)
    old, new = out.segments
    assert (old.source, old.resolution_ms, old.lo_us, old.hi_us) == (
        "downsampled", 1000, lo, lo + 30_000_000,
    )  # fmt: skip
    assert (new.source, new.resolution_ms) == ("cold", 250)
    assert out.effective_bucket_ms == 250


async def test_no_history_returns_empty_matrix_and_flag() -> None:
    """Scenario: No history at all (the symbol was never recorded)."""
    reader = FakeReader(first=None)
    out = await read_heatmap_history(reader, _q(T0_US, T0_US + MIN_US), now_us=T0_US + MIN_US)
    assert out.history == "none" and out.first_available_us is None
    assert out.times_us == () and out.prices == () and out.bid_matrix == [] == out.ask_matrix
    assert reader.calls == []  # nothing read past the coverage lookup


async def test_clamp_coarsens_bucket_and_states_it() -> None:
    """24 h at 100 ms is 864 000 columns: served at 60 000 ms (1 440), stated, never silent."""
    hi = BASE_US + 24 * HOUR_US
    out = await read_heatmap_history(
        FakeReader(first=BASE_US), _q(BASE_US, hi, time_bucket_ms=100), now_us=hi
    )
    assert out.clamped and out.effective_bucket_ms == 60000 and len(out.times_us) == 1440
    assert out.remainder is None


async def test_clamp_pages_newest_first_past_the_coarsest_bucket() -> None:
    hi = BASE_US + 48 * HOUR_US
    out = await read_heatmap_history(
        FakeReader(first=BASE_US), _q(BASE_US, hi, time_bucket_ms=60000), now_us=hi
    )
    assert len(out.times_us) == MAX_COLUMNS and out.to_us == hi
    assert out.remainder == (BASE_US, out.from_us) and not out.clamped


async def test_price_span_past_512_rows_pages_newest_first() -> None:
    """Two columns 1 000 ticks apart cannot share a 512-row axis: the newest is served alone."""
    lo, hi = T0_US, T0_US + 2_000_000
    column = _golden()[0]
    far = dict(column, price_min=str(Decimal(column["price_min"]) + 100))
    rows = _cells_at(lo, column) + _cells_at(lo + 1_000_000, far)
    out = await read_heatmap_history(FakeReader(rows, first=lo), _q(lo, hi), now_us=hi)
    assert out.times_us == (lo + 1_000_000,) and out.remainder == (lo, lo + 1_000_000)
    assert out.prices[0] == Decimal(far["price_min"])


async def test_zero_sample_bucket_not_interpolated() -> None:
    lo, hi = T0_US, T0_US + 3_000_000
    golden = _golden()
    rows = _cells_at(lo, golden[0]) + _cells_at(lo + 2_000_000, golden[1])
    out = await read_heatmap_history(FakeReader(rows, first=lo), _q(lo, hi), now_us=hi)
    assert out.samples == (1, 0, 1)
    assert all(row[1] == 0.0 for row in out.bid_matrix + out.ask_matrix)


async def test_hot_and_cold_spans_join_into_one_axis() -> None:
    lo, hi = T0_US, T0_US + 10_000_000
    reader = FakeReader(_seeded(lo, hi), first=lo, hot_from_us=lo + 4_000_000)
    out = await read_heatmap_history(reader, _q(lo, hi), now_us=hi)
    assert [(s.source, s.lo_us, s.hi_us) for s in out.segments] == [
        ("cold", lo, lo + 4_000_000), ("hot", lo + 4_000_000, hi),
    ]  # fmt: skip
    assert out.samples == (1,) * 10 and out.sources == frozenset({"cold", "hot"})


async def test_reconstruct_from_snapshot_and_deltas() -> None:
    """No stored cell: the window is rebuilt from the recorded snapshot and deltas."""
    anchor, changes = _capture()
    lo, hi = anchor.ts_us, anchor.ts_us + 10_000_000
    reader = FakeReader(first=lo, anchors=[anchor], changes=changes)
    out = await read_heatmap_history(reader, _q(lo, hi, normalize="none"), now_us=hi)
    assert [s.source for s in out.segments] == ["reconstructed"]
    assert out.samples == (10,) * 10 and not out.estimated and out.unverified_anchors == 0
    best_bid = max(p for p, _ in anchor.bids)
    row = out.prices.index(best_bid)
    size = dict(anchor.bids)[best_bid]
    assert out.bid_matrix[row][0] == pytest.approx(float(size))  # unchanged for its first second


async def test_reconstruct_without_stored_checksum_is_estimated() -> None:
    anchor, changes = _capture()
    bare = BookAnchor(anchor.ts_us, anchor.update_id, anchor.bids, anchor.asks, None)
    lo, hi = anchor.ts_us, anchor.ts_us + 2_000_000
    out = await read_heatmap_history(
        FakeReader(first=lo, anchors=[bare], changes=changes), _q(lo, hi), now_us=hi
    )
    assert out.estimated and out.unverified_anchors == 1


async def test_snapshot_checksum_mismatch_falls_back_to_prior_snapshot() -> None:
    anchor, changes = _capture()
    older = BookAnchor(anchor.ts_us - 30_000_000, anchor.update_id, anchor.bids, anchor.asks,
                       anchor.checksum)  # fmt: skip
    bad = BookAnchor(anchor.ts_us, anchor.update_id, anchor.bids[1:], anchor.asks,
                     anchor.checksum)  # fmt: skip
    lo, hi = anchor.ts_us, anchor.ts_us + 1_000_000
    reader = FakeReader(first=older.ts_us, anchors=[older, bad], changes=changes)
    out = await read_heatmap_history(reader, _q(lo, hi, normalize="none"), now_us=hi)
    anchors = [c for c in reader.calls if c[0] == "anchor"]
    assert [c[2] for c in anchors] == [lo, lo - 1]
    assert ("changes", older.ts_us, hi) in reader.calls
    dropped = anchor.bids[0][0]  # the level `bad` lacks, served from `older`
    assert out.bid_matrix[out.prices.index(dropped)][0] > 0


async def test_checkpoint_is_awaited_between_reads_and_stops_the_read() -> None:
    lo, hi = T0_US, T0_US + 5_000_000
    seen: list[int] = []

    async def gone() -> None:
        seen.append(1)
        raise asyncio.CancelledError

    with pytest.raises(asyncio.CancelledError):
        await read_heatmap_history(
            FakeReader(_seeded(lo, hi), first=lo), _q(lo, hi), now_us=hi, checkpoint=gone
        )
    assert seen == [1]


@pytest.mark.parametrize(
    "bad",
    [
        {"time_bucket_ms": 300},
        {"price_grouping": 0},
        {"price_grouping": 1001},
        {"depth": 100},
        {"normalize": "log"},
        {"tick_size": Decimal(0)},
    ],
)
async def test_out_of_contract_query_is_refused(bad: dict[str, Any]) -> None:
    with pytest.raises(HeatmapQueryError):
        await read_heatmap_history(FakeReader(first=T0_US), _q(T0_US, T0_US + 1, **bad), now_us=0)


async def test_inverted_window_is_refused() -> None:
    with pytest.raises(HeatmapQueryError):
        await read_heatmap_history(FakeReader(first=T0_US), _q(T0_US, T0_US), now_us=0)


@settings(max_examples=25, deadline=None)
@given(
    bucket=st.sampled_from([100, 250, 500, 1000, 5000]),
    grouping=st.sampled_from([1, 2, 5, 50]),
    span_s=st.integers(min_value=1, max_value=60),
    offset_ms=st.integers(min_value=0, max_value=999),
    every_ms=st.sampled_from([100, 700, 3000]),
)
def test_matrix_shape_matches_axes_for_any_params(
    bucket: int, grouping: int, span_s: int, offset_ms: int, every_ms: int
) -> None:
    """Scenario: Dense matrix response, as a property: dims always equal the axes."""
    lo = T0_US + offset_ms * 1000
    hi = lo + span_s * 1_000_000
    rows = _seeded(T0_US, hi, every_us=every_ms * 1000)
    q = _q(lo, hi, time_bucket_ms=bucket, price_grouping=grouping)
    out = asyncio.run(read_heatmap_history(FakeReader(rows, first=T0_US), q, now_us=hi))
    assert len(out.bid_matrix) == len(out.ask_matrix) == len(out.prices) <= 512
    for row in out.bid_matrix + out.ask_matrix:
        assert len(row) == len(out.times_us) == len(out.samples)
    assert all(0 <= s <= out.effective_bucket_ms // 100 for s in out.samples)


async def test_one_bucket_wider_than_512_rows_is_centred_on_its_span() -> None:
    lo, hi = T0_US, T0_US + 1_000_000
    column = _golden()[0]
    far = dict(column, price_min=str(Decimal(column["price_min"]) + 100))
    rows = _cells_at(lo, column) + _cells_at(lo + 500_000, far)  # one 1 000 ms bucket
    out = await read_heatmap_history(FakeReader(rows, first=lo), _q(lo, hi), now_us=hi)
    assert len(out.prices) == 512 and out.remainder is None and out.samples == (2,)


async def test_every_snapshot_failing_its_checksum_leaves_the_minute_empty() -> None:
    anchor, changes = _capture()
    bad = BookAnchor(anchor.ts_us, anchor.update_id, anchor.bids[1:], anchor.asks,
                     anchor.checksum)  # fmt: skip
    lo, hi = anchor.ts_us, anchor.ts_us + 1_000_000
    reader = FakeReader(first=lo, anchors=[bad], changes=changes)
    out = await read_heatmap_history(reader, _q(lo, hi), now_us=hi)
    assert out.samples == (0,) and out.prices == ()
    assert not [c for c in reader.calls if c[0] == "changes"]

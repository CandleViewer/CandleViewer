"""E24-T03 (#667): liquidation store, exact clustering, coverage meta and paging."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, cast

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from candleviewer.domain.liquidations import ClosingSide, LiqPrint
from candleviewer.exchange.bybit.liquidations import parse_liquidation_frame
from candleviewer.orderflow.deriv_limits import DerivInvalidRequest, DerivSymbolUnlisted
from candleviewer.orderflow.liquidations import (
    Clusterer,
    LiquidationMeter,
    LiquidationService,
    cluster_scan,
    print_of,
)
from candleviewer.storage.questdb.ilp_writer import serialize_ilp_line
from candleviewer.storage.questdb.liquidation_store import (
    InMemoryLiquidationStore,
    QuestDbLiquidationStore,
)
from candleviewer.storage.questdb.schemas import LIQUIDATIONS_SCHEMA
from tests._corpus import corpus_path

BURST = corpus_path("ws/allLiquidation_BTCUSDT_burst.jsonl").read_text("utf-8").splitlines()
HOUR_US = 3_600_000_000
NOW_S = 1_800_000_000.0
NOW_US = int(NOW_S * 1_000_000)


def _p(
    ts_ms: int, side: str = "sell", price: str = "100", size: str = "1", bi: int = 0
) -> LiqPrint:
    px, sz = Decimal(price), Decimal(size)
    return LiqPrint(ts_ms * 1000, "BTCUSDT", cast(ClosingSide, side), px, sz, px * sz, bi)


class SpyStore(InMemoryLiquidationStore):
    def __init__(self) -> None:
        super().__init__()
        self.reads = 0

    async def read_prints(self, *a: Any, **k: Any) -> list[LiqPrint]:
        self.reads += 1
        return await super().read_prints(*a, **k)


def _svc(store: InMemoryLiquidationStore, scan: int = 5000) -> LiquidationService:
    return LiquidationService(
        store=store, listed=lambda s: s == "BTCUSDT", clock_s=lambda: NOW_S, scan_prints=scan
    )


async def _page(svc: LiquidationService, **kw: Any) -> Any:
    args: dict[str, Any] = {"start_us": NOW_US - 24 * HOUR_US, "end_us": NOW_US, "limit": 100,
                            "cursor": None, "side": None, "min_notional": None,
                            "cluster_window_ms": 0}  # fmt: skip
    args.update(kw)
    return await svc.page("BTCUSDT", **args)


async def test_cluster_window_1000_five_prints_one_item_size_5_no_estimated_key() -> None:
    store = InMemoryLiquidationStore()
    base = NOW_US // 1000 - 60_000
    await store.write_prints([_p(base + 150 * k, bi=k) for k in range(5)])
    page = await _page(_svc(store), cluster_window_ms=1000)
    (item,) = page.items
    assert item.count == 5 and item.size == Decimal(5) and item.notional == Decimal(500)
    wire = item.wire()
    assert wire["cluster_size"] == 5 and wire["ts_ms"] == base
    assert "estimated" not in json.dumps(wire)


def test_clusterer_splits_by_side_and_by_window() -> None:
    c = Clusterer(1000)
    assert c.add(_p(0, "sell")) is None and c.add(_p(10, "buy")) is None
    assert c.add(_p(999, "sell")) is None
    closed = c.add(_p(1000, "sell"))
    assert closed is not None and closed.count == 2  # 0 and 999; 1000 starts the next
    assert [i.first.side for i in c.expire(1_010_000)] == ["buy"]
    assert Clusterer(0).add(_p(5)) is not None  # window 0: every print is its own item


async def test_liquidation_range_reports_first_available_ts() -> None:
    store = InMemoryLiquidationStore()
    first_ms = (NOW_US - 2 * HOUR_US) // 1000  # the recorder started 2 h ago
    await store.write_prints([_p(first_ms), _p(first_ms + 60_000, bi=1)])
    page = await _page(_svc(store))
    assert len(page.items) == 2 and not page.has_more
    cov = page.coverage
    assert cov.first_available_us == first_ms * 1000 == cov.covered_from_us
    assert cov.covered_to_us == NOW_US and not cov.no_coverage


async def test_range_before_first_record_reports_no_coverage_not_bare_empty() -> None:
    store = SpyStore()
    first_ms = (NOW_US - 2 * HOUR_US) // 1000
    await store.write_prints([_p(first_ms)])
    page = await _page(_svc(store), start_us=NOW_US - 10 * HOUR_US, end_us=NOW_US - 3 * HOUR_US)
    assert page.items == () and page.coverage.no_coverage
    assert page.coverage.first_available_us == first_ms * 1000 and store.reads == 0
    nothing = await _page(_svc(SpyStore()))
    assert nothing.coverage.no_coverage and nothing.coverage.first_available_us is None


@pytest.mark.parametrize(
    ("kw", "code"),
    [
        ({"start_us": NOW_US - 32 * 24 * HOUR_US}, "invalid_time_range"),
        ({"start_us": NOW_US, "end_us": NOW_US - 1}, "invalid_time_range"),
        ({"limit": 501}, "validation_failed"),
        ({"cluster_window_ms": 60_001}, "validation_failed"),
        ({"side": "long"}, "validation_failed"),
        ({"min_notional": Decimal(-1)}, "validation_failed"),
        ({"cursor": "x" * 513}, "invalid_cursor"),
        ({"cursor": "bm9wZQ"}, "invalid_cursor"),
    ],
)
async def test_bounds_refused_before_any_store_read(kw: dict[str, Any], code: str) -> None:
    store = SpyStore()
    with pytest.raises(DerivInvalidRequest) as err:
        await _page(_svc(store), **kw)
    assert err.value.code == code and store.reads == 0


async def test_unlisted_symbol_and_foreign_cursor() -> None:
    store = InMemoryLiquidationStore()
    with pytest.raises(DerivSymbolUnlisted):
        await _svc(store).page("ETHUSDT", start_us=None, end_us=None, limit=1, cursor=None,
                               side=None, min_notional=None, cluster_window_ms=0)  # fmt: skip
    base = NOW_US // 1000 - 60_000
    await store.write_prints([_p(base + k, bi=k) for k in range(3)])
    first = await _page(_svc(store), limit=1)
    assert first.has_more and first.next_cursor is not None
    with pytest.raises(DerivInvalidRequest):  # a cursor is bound to its side and options
        await _page(_svc(store), cursor=first.next_cursor, side="buy")


async def test_side_and_min_notional_filter_items() -> None:
    store = InMemoryLiquidationStore()
    base = NOW_US // 1000 - 60_000
    await store.write_prints([_p(base, "buy", size="5"), _p(base + 1, "sell", size="0.5")])
    assert [i.first.side for i in (await _page(_svc(store), side="buy")).items] == ["buy"]
    big = await _page(_svc(store), min_notional=Decimal(100))
    assert [i.first.side for i in big.items] == ["buy"]


_prints = st.lists(
    st.tuples(st.integers(0, 4000), st.sampled_from(["buy", "sell"]), st.integers(1, 3)),
    max_size=40,
)


async def _all_pages(store: InMemoryLiquidationStore, scan: int, **kw: Any) -> list[dict[str, Any]]:
    got: list[dict[str, Any]] = []
    cursor = None
    for _ in range(400):
        page = await _page(_svc(store, scan), cursor=cursor, **kw)
        got += [i.wire() for i in page.items]
        cursor = page.next_cursor
        if cursor is None:
            return got
    raise AssertionError("paging never ended")


@settings(max_examples=80, deadline=None)
@given(rows=_prints, window=st.sampled_from([0, 300, 1000]), limit=st.integers(1, 4),
       spare=st.integers(1, 6), floor=st.sampled_from([None, Decimal(150)]))  # fmt: skip
async def test_pages_concatenate_to_the_one_shot_clustering(
    rows: list[tuple[int, str, int]], window: int, limit: int, spare: int, floor: Decimal | None
) -> None:
    """Any scan cap above the largest cluster: the pages, in order, are the one-shot items."""
    base = NOW_US // 1000 - 600_000
    prints = [_p(base + t, s, size=str(n), bi=k) for k, (t, s, n) in enumerate(rows)]
    store = InMemoryLiquidationStore()
    await store.write_prints(prints)
    items = cluster_scan(sorted(prints, key=LiqPrint.key), window, {})
    want = [i.wire() for i in items if floor is None or i.notional >= floor]
    scan = max((i.count for i in items), default=0) + spare
    got = await _all_pages(store, scan, limit=limit, cluster_window_ms=window, min_notional=floor)
    assert got == want


async def test_cluster_larger_than_a_scan_is_split_and_no_print_is_lost_or_repeated() -> None:
    base = NOW_US // 1000 - 600_000
    store = InMemoryLiquidationStore()
    await store.write_prints([_p(base + k * 10, bi=k) for k in range(12)])
    got = await _all_pages(store, 4, limit=2, cluster_window_ms=1000)
    assert sum(i["cluster_size"] for i in got) == 12 and len(got) > 1


async def test_burst_fixture_prints_and_replay_land_on_the_dedup_key() -> None:
    store = InMemoryLiquidationStore()
    for frame in BURST:
        await store.write_prints([print_of(e) for e in parse_liquidation_frame(frame, 1) or []])
    assert len(store) == 19  # 19 prints; the replayed push adds none, the twins stay two


async def test_questdb_store_rows_reads_and_coverage_are_parameterised() -> None:
    calls: list[tuple[str, list[dict[str, object]], str]] = []
    sqls: list[tuple[str, tuple[object, ...]]] = []
    ts = datetime(2026, 9, 14, 10, 0, tzinfo=UTC)
    rows: list[dict[str, object]] = [{"ts": ts, "symbol": "BTCUSDT", "side": "sell",
                                      "price": 100.5, "size": 2.0, "notional": 201.0,
                                      "batch_index": None, "lo": ts}]  # fmt: skip

    class W:
        async def write_rows(self, table: str, r: list[dict[str, object]], key: str) -> None:
            calls.append((table, r, key))

    class R:
        async def run(self, builder: Any) -> list[dict[str, object]]:
            sqls.append((builder.sql, builder.params))
            return rows

    store = QuestDbLiquidationStore(W(), R())  # type: ignore[arg-type]  # structural fakes
    (ev,) = parse_liquidation_frame(BURST[0], 7) or []
    await store.write_prints([print_of(ev)])
    await store.write_prints([])
    table, written, key = calls[0]
    assert (table, key, len(calls)) == ("liquidations", "ts", 1)
    assert written[0]["stream"] == "all" and written[0]["recv_ts"] == 7
    fields = {k: v for k, v in written[0].items() if k != "ts"}
    line = serialize_ilp_line(LIQUIDATIONS_SCHEMA, fields, ev.ts_event)
    assert line.startswith("liquidations,symbol=BTCUSDT,side=sell,stream=all ")
    (got,) = await store.read_prints("BTCUSDT", _Win(0, 10), "sell", 50)
    assert (got.price, got.notional, got.batch_index) == (Decimal("100.5"), Decimal("201.0"), 0)
    assert await store.first_ts("BTCUSDT") == got.ts_us
    sql, params = sqls[0]
    assert "side = $4" in sql and params[0] == "BTCUSDT" and params[3] == "sell"
    assert "LIMIT 50" in sql and "'BTCUSDT'" not in sql
    rows[0]["lo"] = None
    assert await store.first_ts("BTCUSDT") is None


class _Win:
    def __init__(self, start_us: int, end_us: int) -> None:
        self.start_us, self.end_us = start_us, end_us


def test_meter_counts_prints_notional_lag_reconnects_and_rejects() -> None:
    from candleviewer.orderflow import deriv_metrics as m

    events = parse_liquidation_frame(BURST[3], 1_700_000_602_000_000) or []
    before = m.deriv_liquidation_prints_total.labels("long")._value.get()
    meter = LiquidationMeter()
    meter.prints(events, 1_700_000_602_000_000)
    meter.reconnect()
    meter.rejected()
    longs = sum(1 for e in events if e.liquidated_side == "long")
    assert m.deriv_liquidation_prints_total.labels("long")._value.get() - before == longs
    assert m.deriv_liquidation_burst_rate._value.get() >= 1
    assert m.deriv_liquidation_ingest_lag_seconds._value.get() > 0

"""#5396 (24 §19.81): a closed bar the server did not store is named in `meta.coverage_holes` on
the next `GET /market/bars` and `GET /market/klines` read, valid against 22 `BarsMeta`, while no
bar is served there; a page lists only the holes inside its own span.

The stored rows, reader fake and route wiring are `test_market_bars_contract`'s (the recorded
BTCUSDT tape through the real builders) and `test_market_klines_contract`'s (the recorded 1m
klines). The hole comes from the real write path: a `BarWriter` whose sink stores no row.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from candleviewer.api._generated.openapi_models import KlineResponse
from candleviewer.api.market import make_market_router
from candleviewer.api.market_bars import make_market_bars_router
from candleviewer.bars.models import Bar, BarSpec
from candleviewer.bars.reader import BarReader
from candleviewer.bars.rows import bar_param_for
from candleviewer.bars.spec import from_wire
from candleviewer.bars.write_holes import HoleKey, WriteHoleLedger
from candleviewer.bars.writer import BarWriter
from candleviewer.ingestion.kline_read import KlineReadService
from tests.contract import test_market_bars_contract as bars_world
from tests.contract import test_market_klines_contract as klines_world

_TIME = bars_world._SERIES["time", "1"]
_TICK = bars_world._SERIES["tick", "100"]
_MIN = 60_000_000


class _Refusing:
    async def write_rows(self, table: str, rows: list[dict[str, object]], ts_us_key: str) -> None:
        raise ValueError("not stored")


async def _lose(ledger: WriteHoleLedger, spec: BarSpec, bar: Bar) -> None:
    """`bar` through the real write path, to a terminal outcome without being stored."""
    writer = BarWriter(_Refusing(), holes=ledger)
    await writer.start()
    await writer.submit([bar], spec, generation=0)
    await writer.stop()
    await ledger.flush()


def _bars_client(ledger: WriteHoleLedger) -> TestClient:
    reader = BarReader(bars_world._Fetch(), bars_world._noop)

    async def started(symbol: str) -> int | None:
        return bars_world._T0

    app = FastAPI()
    app.include_router(
        make_market_bars_router(
            lambda: reader, recording_started_at_us=started,
            trade_totals=bars_world._tape_totals,
            principal_resolver=bars_world._Resolver(frozenset({"marketdata:read"})),
            symbol_listed=lambda s: s == "BTCUSDT", qty_step=bars_world._step,
            now_us=lambda: bars_world._NOW, write_holes=ledger,
        )
    )  # fmt: skip
    return TestClient(app, client=("127.0.0.1", 50000))


def _unstore(monkeypatch: pytest.MonkeyPatch, spec: BarSpec, bar: Bar) -> None:
    """The store without `bar`'s row (its write never landed)."""
    param = bar_param_for(spec)
    kept = [r for r in bars_world._STORE[param]
            if (r["ts"], r["index"]) != (bar.open_time, bar.index)]  # fmt: skip
    assert len(kept) == len(bars_world._STORE[param]) - 1
    monkeypatch.setitem(bars_world._STORE, param, kept)


def _get_bars(client: TestClient, bar_type: str, param: str, **q: Any) -> dict[str, Any]:
    resp = client.get("/market/bars", params={**bars_world._P, "bar_type": bar_type,
                                              "param": param, **q})  # fmt: skip
    assert resp.status_code == 200, resp.text
    body: dict[str, Any] = resp.json()
    KlineResponse.model_validate(body)  # `meta` is `BarsMeta`
    return body


@pytest.mark.parametrize(("bar_type", "param", "spec"), [("time", "1", _TIME),
                                                          ("tick", "100", _TICK)])  # fmt: skip
def test_bars_a_closed_bar_not_stored_is_named_on_the_next_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, bar_type: str, param: str, spec: BarSpec
) -> None:
    """Gherkin "a failed closed-bar write leaves a marker, not a hole" (REST `/market/bars`)."""
    bar = [b for b in bars_world._build(spec) if b.closed][2]
    _unstore(monkeypatch, spec, bar)
    ledger = WriteHoleLedger(tmp_path)
    client = _bars_client(ledger)
    asyncio.run(_lose(ledger, spec, bar))
    body = _get_bars(client, bar_type, param)
    end = bar.open_time + _MIN if spec.kind == "time" else bar.close_time + 1
    assert body["meta"]["coverage_holes"] == [{"start_us": bar.open_time, "end_us": end}]
    assert all(b["t"] for b in body["bars"])  # the other bars are still served


def test_bars_a_served_bar_suppresses_its_recorded_hole(tmp_path: Path) -> None:
    """The row is in the store after all (e.g. written by a later amend): it is not a hole."""
    bar = [b for b in bars_world._build(_TIME) if b.closed][5]
    ledger = WriteHoleLedger(tmp_path)
    ledger.lost([HoleKey("BTCUSDT", _TIME.spec_hash, "time", "1m", 0, bar.index, bar.open_time,
                         bar.open_time + _MIN)], "refused")  # fmt: skip
    body = _get_bars(_bars_client(ledger), "time", "1")
    assert "coverage_holes" not in body["meta"]


def test_bars_a_hole_is_listed_on_the_page_that_spans_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    closed = [b for b in bars_world._build(_TIME) if b.closed]
    bar = closed[5]
    _unstore(monkeypatch, _TIME, bar)
    ledger = WriteHoleLedger(tmp_path)
    ledger.lost([HoleKey("BTCUSDT", _TIME.spec_hash, "time", "1m", 0, bar.index, bar.open_time,
                         bar.open_time + _MIN)], "refused")  # fmt: skip
    client = _bars_client(ledger)
    first = _get_bars(client, "time", "1", limit=3)
    assert first["meta"]["has_more"] and "coverage_holes" not in first["meta"]
    second = _get_bars(client, "time", "1", limit=3, cursor=first["meta"]["next_cursor"])
    holes = second["meta"]["coverage_holes"]
    assert holes == [{"start_us": bar.open_time, "end_us": bar.open_time + _MIN}]


# -- /market/klines ---------------------------------------------------------------------------


def _klines_client(ledger: WriteHoleLedger, rows: list[Any]) -> TestClient:
    async def started(symbol: str) -> int | None:
        return None

    service = KlineReadService(klines_world._Hot(rows), recording_started_at_us=started)
    app = FastAPI()
    app.include_router(
        make_market_router(
            lambda: klines_world._Hot([]),
            principal_resolver=klines_world._Resolver(klines_world._READ),
            read_service_provider=lambda: service, symbol_listed=lambda s: s == "BTCUSDT",
            now_us=lambda: 1_700_100_000_000_000, write_holes=ledger,
        )
    )  # fmt: skip
    return TestClient(app, client=("127.0.0.1", 50000))


def _klines_hole(ledger: WriteHoleLedger, open_us: int) -> None:
    spec = from_wire("time", "1")
    ledger.lost([HoleKey("BTCUSDT", spec.spec_hash, "time", "1m", 4, 10, open_us,
                         open_us + _MIN)], "sink_timeout")  # fmt: skip


def test_klines_lists_a_hole_where_no_kline_row_is_served(tmp_path: Path) -> None:
    corpus = klines_world._corpus()
    missing = corpus[20].ts_us
    ledger = WriteHoleLedger(tmp_path)
    _klines_hole(ledger, missing)
    rows = [r for r in corpus if r.ts_us != missing]
    resp = _klines_client(ledger, rows).get("/market/klines", params=klines_world._P)
    body = resp.json()
    KlineResponse.model_validate(body)
    assert {"start_us": missing, "end_us": missing + _MIN} in body["meta"]["coverage_holes"]


def test_klines_a_served_kline_row_fills_the_hole(tmp_path: Path) -> None:
    corpus = klines_world._corpus()
    ledger = WriteHoleLedger(tmp_path)
    _klines_hole(ledger, corpus[20].ts_us)
    body = _klines_client(ledger, corpus).get("/market/klines", params=klines_world._P).json()
    KlineResponse.model_validate(body)
    holes = body["meta"]["coverage_holes"]
    assert not any(h["start_us"] <= corpus[20].ts_us < h["end_us"] for h in holes)

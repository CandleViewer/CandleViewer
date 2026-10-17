"""`GET /market/data-coverage` (E16-T04): RBAC, validation, and the `DataCoverage` shape."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from candleviewer.api._generated.openapi_models import DataCoverage, Problem
from candleviewer.api.market import MarketDataPrincipal
from candleviewer.api.market_coverage import make_data_coverage_router
from candleviewer.recorder.coverage import CoverageService
from candleviewer.recorder.sessions import to_dt, to_us
from tests.unit.recorder._session_fakes import MemRecorderStore, UsClock

NOW = to_us(datetime(2026, 9, 14, 10, 31, tzinfo=UTC))


class _Resolver:
    def __init__(self, perms: frozenset[str] | None) -> None:
        self._perms = perms

    def resolve(self, request: Request) -> MarketDataPrincipal | None:
        return None if self._perms is None else MarketDataPrincipal("u1", self._perms)


class _Boom(CoverageService):
    async def coverage(self, *a: Any, **k: Any) -> Any:
        raise TimeoutError


async def _seed(store: MemRecorderStore) -> None:
    sid = await store.open_session_at(
        recorded_symbol_id="r", symbol="BTCUSDT", streams=["trades"], orderbook_depth=1,
        ws_endpoint="x", started_at=datetime(2026, 9, 1, tzinfo=UTC),
    )  # fmt: skip
    await store.record_gap(
        session_id=sid, symbol="BTCUSDT", stream="trades",
        gap_start=datetime(2026, 9, 4, 2, 11, tzinfo=UTC),
        gap_end=datetime(2026, 9, 4, 2, 14, 20, tzinfo=UTC), cause="process_restart",
    )  # fmt: skip


def _client(
    service: CoverageService | None, perms: frozenset[str] | None = frozenset({"marketdata:read"}),
    *, wired: bool = True,
) -> TestClient:  # fmt: skip
    app = FastAPI()
    app.include_router(
        make_data_coverage_router(
            lambda: service,
            principal_resolver=_Resolver(perms) if wired else None,
            symbol_listed=lambda s: s in ("BTCUSDT", "SOLUSDT"),
        )
    )
    return TestClient(app, client=("127.0.0.1", 50000))


async def test_coverage_report_matches_contract_schema() -> None:
    store = MemRecorderStore()
    await _seed(store)
    svc = CoverageService(store, now_us=UsClock(NOW))
    resp = _client(svc).get(
        "/market/data-coverage", params=[("symbol", "BTCUSDT"), ("stream", "trades")]
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    DataCoverage.model_validate(body)
    (trades,) = body["streams"]
    assert [i["tier"] for i in trades["intervals"]] == ["questdb", "questdb"]
    assert trades["intervals"][0] == {
        "from": "2026-09-01T00:00:00Z", "to": "2026-09-04T02:11:00Z", "tier": "questdb"
    }  # fmt: skip
    assert trades["gaps"] == [
        {"from": "2026-09-04T02:11:00Z", "to": "2026-09-04T02:14:20Z", "reason": "backend_restart"}
    ]
    assert body["generated_at"] == "2026-09-14T10:31:00Z"
    assert to_us(datetime.fromisoformat(trades["intervals"][-1]["to"])) == NOW


async def test_default_streams_when_none_requested() -> None:
    svc = CoverageService(MemRecorderStore(), now_us=UsClock(NOW))
    body = _client(svc).get("/market/data-coverage", params={"symbol": "BTCUSDT"}).json()
    assert [s["stream"] for s in body["streams"]] == [
        "trades", "orderbook_delta", "orderbook_snapshot", "tickers", "liquidations"
    ]  # fmt: skip
    assert all(s["intervals"] == [] and s["gaps"] == [] for s in body["streams"])


def _problem(resp: Any, status: int, code: str) -> None:
    assert resp.status_code == status, resp.text
    Problem.model_validate(resp.json())
    assert resp.json()["code"] == code


def test_rbac_and_validation_fail_closed() -> None:
    svc = CoverageService(MemRecorderStore(), now_us=UsClock(NOW))
    q = {"symbol": "BTCUSDT"}
    _problem(
        _client(svc, wired=False).get("/market/data-coverage", params=q), 501, "internal_error"
    )
    _problem(_client(svc, None).get("/market/data-coverage", params=q), 401, "unauthenticated")
    _problem(_client(svc, frozenset({"orders:read"})).get("/market/data-coverage", params=q),
             403, "forbidden")  # fmt: skip
    _problem(_client(svc).get("/market/data-coverage", params={"symbol": "../x"}),
             400, "validation_failed")  # fmt: skip
    _problem(_client(svc).get("/market/data-coverage", params={**q, "stream": "bogus"}),
             400, "validation_failed")  # fmt: skip
    _problem(_client(svc).get("/market/data-coverage", params={"symbol": "XRPUSDT"}),
             422, "validation_failed")  # fmt: skip
    _problem(_client(None).get("/market/data-coverage", params=q), 503, "store_unavailable")
    boom = _Boom(MemRecorderStore(), now_us=UsClock(NOW))
    _problem(_client(boom).get("/market/data-coverage", params=q), 503, "store_unavailable")


def test_to_dt_round_trips() -> None:
    assert to_us(to_dt(NOW)) == NOW


async def test_create_app_wires_sessions_provider_and_mounts_route() -> None:
    """E16-T04 wiring through the real factory: the route is mounted (fake backend: no session
    resolver -> 501, fail closed) and the provider consults the attached CoverageService."""
    from candleviewer.app import create_app, recording_started_at_us
    from candleviewer.settings import Settings
    from candleviewer.storage.testing import FakeMarketDataRepository

    app = create_app(Settings(git_sha="test", version="0.0.0-test"))
    ctx = app.state.app_context
    ctx.storage._market_data = FakeMarketDataRepository()
    assert app.state.coverage_service is None and ctx.recorder.coverage is None
    store = MemRecorderStore()
    sid = await store.open_session_at(
        recorded_symbol_id="r", symbol="SOLUSDT", streams=["trades"], orderbook_depth=1,
        ws_endpoint="x", started_at=datetime(2026, 9, 13, tzinfo=UTC),
    )  # fmt: skip
    first = datetime(2026, 9, 13, 0, 0, 1, tzinfo=UTC)
    await store.touch_session_events(sid, first=first, last=first)
    ctx.recorder.attach_coverage(CoverageService(store, now_us=UsClock(NOW)))
    assert await recording_started_at_us(ctx)("SOLUSDT") == to_us(first)
    resp = TestClient(app, client=("127.0.0.1", 50000)).get(
        "/market/data-coverage", params={"symbol": "SOLUSDT"}
    )
    assert resp.status_code == 501


async def test_create_app_hands_the_bars_route_its_storages_trade_totals(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """#2093 review (A1): `create_app` composes `trade_totals_source(ctx)`. Without it every
    non-time `/market/bars` request is a 503 that no route test sees."""
    from decimal import Decimal

    from candleviewer import app as app_module
    from candleviewer.settings import Settings
    from candleviewer.storage.models import TimeRange
    from candleviewer.storage.repositories.rows import TradeRow, TradeTotals
    from candleviewer.storage.testing import FakeMarketDataRepository

    seen: dict[str, Any] = {}
    real = app_module.make_market_bars_router

    def spy(*args: Any, **kwargs: Any) -> Any:
        seen.update(kwargs)
        return real(*args, **kwargs)

    monkeypatch.setattr(app_module, "make_market_bars_router", spy)
    app = app_module.create_app(Settings(git_sha="test", version="0.0.0-test"))
    repo = FakeMarketDataRepository()
    app.state.app_context.storage._market_data = repo  # after composition: resolved per call
    await repo.write_trades([
        TradeRow(ts_us=5, symbol="BTCUSDT", price="1", qty="0.5", side="buy", trade_id="t1")
    ])  # fmt: skip
    got = await seen["trade_totals"]("BTCUSDT", TimeRange(start_us=0, end_us=10))
    assert got == TradeTotals(1, Decimal("0.5"))


async def _ctx_with(trade_ts: list[int], session_first: datetime | None) -> Any:
    from candleviewer.app import build_app_context
    from candleviewer.storage.repositories.rows import TradeRow
    from candleviewer.storage.testing import FakeMarketDataRepository

    ctx = build_app_context()
    repo = FakeMarketDataRepository()
    ctx.storage._market_data = repo
    await repo.write_trades([
        TradeRow(ts_us=t, symbol="BTCUSDT", price="1", qty="1", side="buy", trade_id=str(t))
        for t in trade_ts
    ])  # fmt: skip
    store = MemRecorderStore()
    if session_first is not None:
        sid = await store.open_session_at(
            recorded_symbol_id="r", symbol="BTCUSDT", streams=["trades"], orderbook_depth=1,
            ws_endpoint="x", started_at=session_first,
        )  # fmt: skip
        await store.touch_session_events(sid, first=session_first, last=session_first)
    ctx.recorder.attach_coverage(CoverageService(store, now_us=UsClock(NOW)))
    return ctx


async def test_regression_no_sessions_falls_back_to_tape_like_main() -> None:
    """Review HIGH #1: CoverageService attached but no session rows (manager unwired, #2188) ->
    the tape's first trade is still the answer, never a false `no_data_recorded`."""
    from candleviewer.app import recording_started_at_us

    ctx = await _ctx_with([5_000, 2_000], None)
    assert await recording_started_at_us(ctx)("BTCUSDT") == 2_000
    assert await recording_started_at_us(ctx)("ETHUSDT") is None


async def test_earlier_session_first_event_wins_over_tape() -> None:
    from candleviewer.app import recording_started_at_us

    early = datetime(1970, 1, 1, 0, 0, 0, 1000, tzinfo=UTC)  # 1_000 µs
    ctx = await _ctx_with([2_000], early)
    assert await recording_started_at_us(ctx)("BTCUSDT") == 1_000
    late = datetime(1970, 1, 1, 0, 0, 1, tzinfo=UTC)  # 1 s: tape (2 ms) is earlier
    ctx = await _ctx_with([2_000], late)
    assert await recording_started_at_us(ctx)("BTCUSDT") == 2_000


def test_regression_bars_with_tape_and_no_sessions_is_served_not_422() -> None:
    """End to end through `/market/bars`: same request that succeeds on main still succeeds."""
    import asyncio

    from candleviewer.api.market_bars import make_market_bars_router
    from candleviewer.app import recording_started_at_us, trade_totals_source
    from candleviewer.bars.reader import BarReader

    ctx = asyncio.run(_ctx_with([NOW - 3_600_000_000], None))

    class _Empty:
        async def fetch(self, sql: str, *params: object) -> list[dict[str, object]]:
            return []

    async def no_rebuild(*_a: Any, **_k: Any) -> None:
        return None

    app = FastAPI()
    app.include_router(make_market_bars_router(
        lambda: BarReader(_Empty(), no_rebuild),
        recording_started_at_us=recording_started_at_us(ctx),
        trade_totals=trade_totals_source(ctx),
        principal_resolver=_Resolver(frozenset({"marketdata:read"})),
        symbol_listed=lambda s: s == "BTCUSDT", now_us=lambda: NOW))  # fmt: skip
    resp = TestClient(app, client=("127.0.0.1", 50000)).get("/market/bars", params={
        "symbol": "BTCUSDT", "bar_type": "tick", "param": "500",
        "from": "2026-09-14T10:00:00Z", "to": "2026-09-14T10:31:00Z"})  # fmt: skip
    assert resp.status_code == 200, resp.text


async def test_unmappable_causes_omit_reason_never_relabel() -> None:
    """Review HIGH #2 (TODO #2216): `seq_jump`/`backpressure_drop` have no contract value, so
    `reason` is omitted (optional in `DataCoverage`), never reported as `ws_disconnect`."""
    from candleviewer.api.market_coverage import coverage_gap_reason_unmapped_total

    store = MemRecorderStore()
    sid = await store.open_session_at(
        recorded_symbol_id="r", symbol="BTCUSDT", streams=["trades"], orderbook_depth=1,
        ws_endpoint="x", started_at=datetime(2026, 9, 1, tzinfo=UTC),
    )  # fmt: skip
    causes = ["seq_jump", "backpressure_drop", "exchange_outage", "ws_disconnect"]
    for i, cause in enumerate(causes):
        await store.record_gap(
            session_id=sid, symbol="BTCUSDT", stream="trades",
            gap_start=datetime(2026, 9, 2 + i, tzinfo=UTC),
            gap_end=datetime(2026, 9, 2 + i, 0, 1, tzinfo=UTC), cause=cause,
        )  # fmt: skip
    before = coverage_gap_reason_unmapped_total.labels(cause="seq_jump")._value.get()  # type: ignore[attr-defined]  # prometheus internals
    svc = CoverageService(store, now_us=UsClock(NOW))
    q = {"symbol": "BTCUSDT", "stream": "trades"}
    body = _client(svc).get("/market/data-coverage", params=q).json()
    DataCoverage.model_validate(body)
    gaps = body["streams"][0]["gaps"]
    assert [g.get("reason") for g in gaps] == [None, None, "exchange_outage", "ws_disconnect"]
    assert "reason" not in gaps[0] and "reason" not in gaps[1]
    after = coverage_gap_reason_unmapped_total.labels(cause="seq_jump")._value.get()  # type: ignore[attr-defined]  # prometheus internals
    assert after == before + 1


async def test_route_window_is_capped_to_last_90_days_from_the_cache() -> None:
    """Review MEDIUM #3: never a full-history scan; one cached SQL load for repeated calls."""
    store = MemRecorderStore()
    old = await store.open_session_at(
        recorded_symbol_id="r", symbol="BTCUSDT", streams=["trades"], orderbook_depth=1,
        ws_endpoint="x", started_at=datetime(2026, 1, 1, tzinfo=UTC),
    )  # fmt: skip
    await store.close_session_at(old, reason="stopped", ended_at=datetime(2026, 2, 1, tzinfo=UTC))
    await store.open_session_at(
        recorded_symbol_id="r", symbol="BTCUSDT", streams=["trades"], orderbook_depth=1,
        ws_endpoint="x", started_at=datetime(2026, 9, 1, tzinfo=UTC),
    )  # fmt: skip
    windows: list[tuple[datetime, datetime]] = []
    real = store.sessions_in

    async def spy(symbol: str, lo: datetime, hi: datetime) -> list[dict[str, Any]]:
        windows.append((lo, hi))
        return await real(symbol, lo, hi)

    store.sessions_in = spy  # type: ignore[method-assign]
    clock = UsClock(NOW)
    client = _client(CoverageService(store, now_us=clock))
    q = {"symbol": "BTCUSDT", "stream": "trades"}
    body = client.get("/market/data-coverage", params=q).json()
    (iv,) = body["streams"][0]["intervals"]
    assert iv["from"] == "2026-09-01T00:00:00Z"  # the January session is outside the 90 d cap
    assert to_us(windows[0][0]) == NOW - 90 * 86_400_000_000
    clock.t += 60_000_000  # a minute later: still served from the cache
    client.get("/market/data-coverage", params=q)
    assert len(windows) == 1

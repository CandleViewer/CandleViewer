"""#2787 D2-G2 (ruling D-G2 = A): the WS series store's first reads on their own PG-wire connection.

With `bars_enabled` and a bars sink, the app builds a second `LazyPgWire`, `bars_hydrate`, from the
sink's (`bars`): the store reads through it; REST `/market/bars` and the bars writer keep the
sink's; the runtime closes it after the sink. The G2 line: a first read that outlives the store's
2 s, whose discard then waits out the 5 s close, fails no REST bars read issued with it or during
its discard. With both on one connection, as `main` composed them, the same scenario fails both.

Deterministic: each of the app's wires gets a fake `connect` (no QuestDB, no network); a scenario
runs on a loop whose timers keep the test's clock and only yields to it. The REST reads go through
`make_market_bars_router` over the app's own REST reader.
"""

from __future__ import annotations

import asyncio
import inspect
from collections.abc import Iterable, Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi import FastAPI, Request
from pydantic import SecretStr
from structlog.testing import capture_logs

from candleviewer.api.market import MarketDataPrincipal
from candleviewer.api.market_bars import make_market_bars_router
from candleviewer.app import build_app_context, create_app
from candleviewer.bars.models import BarSpec
from candleviewer.bars.reader import BarPage, BarReader
from candleviewer.bars.series_store import SeriesStore
from candleviewer.bars_wiring import wire_bars
from candleviewer.settings import Environment, Settings
from candleviewer.storage.questdb.wiring import LazyPgWire, QuestDbRowSink
from tests.unit.storage.questdb import test_lazy_pgwire_metrics as pg

SPEC = BarSpec(kind="time", interval_ms=300_000)
REST: dict[str, str | int] = {
    "symbol": "BTCUSDT", "bar_type": "time", "param": "5", "limit": 10,
    "from": "2023-11-14T22:00:00Z", "to": "2023-11-14T22:15:00Z",
}  # fmt: skip


def _app(tmp_path: Path, *, enabled: bool = True) -> FastAPI:
    """On the real storage backend (it composes the bars sink), with test vectors for auth."""
    return create_app(
        Settings(
            environment=Environment.DEMO, storage_backend="real", bars_enabled=enabled,
            bars_state_root=str(tmp_path / "bars"), parquet_root=str(tmp_path / "parquet"),
            metrics_enabled=False, auth_pepper=SecretStr("test-pepper"),
            auth_totp_key_hex=SecretStr("11" * 32), auth_recovery_hmac_key_hex=SecretStr("22" * 32),
            auth_csrf_key_hex=SecretStr("33" * 32),
        )
    )  # fmt: skip


def _routes(routes: Iterable[Any]) -> Iterator[Any]:
    for route in routes:
        inner = getattr(route, "original_router", None)
        yield from (_routes(inner.routes) if inner is not None else (route,))


def _wiring(app: FastAPI) -> tuple[SeriesStore, LazyPgWire, BarReader]:
    """The store, the wire it reads through, and the reader `/market/bars` reads through (the
    `reader_provider` its router closes over)."""
    store = app.state.ws_registry.services.series
    route = next(r for r in _routes(app.routes) if getattr(r, "path", None) == "/market/bars")
    rest = inspect.getclosurevars(route.endpoint).nonlocals["reader_provider"]()
    first = getattr(store._tail, "__self__", None)  # the bound `read_tail` of a `BarReader`
    assert isinstance(first, BarReader) and isinstance(rest, BarReader)
    return store, _wire(first), rest


def _wire(reader: BarReader) -> LazyPgWire:
    assert isinstance(reader._conn, LazyPgWire)
    return reader._conn


def _db(wire: LazyPgWire) -> pg.Db:
    """Each wire its own fake database, answering no rows; a close hangs until `terminate()`."""
    db = pg.Db(rows=[], hang_close=True)
    wire._connect = db.connect
    return db


class _Principal:
    def resolve(self, request: Request) -> MarketDataPrincipal:
        return MarketDataPrincipal("g2", frozenset({"marketdata:read"}))


class _Counted:
    """`reader`, counting the reads `/market/bars` starts: when a count is seen, that read's 2 s
    deadline is set, and its query was answered or waits for its wire's lock."""

    def __init__(self, reader: BarReader) -> None:
        self.reader, self.started = reader, 0

    async def read_bars(self, *args: Any, **kwargs: Any) -> BarPage:
        self.started += 1
        return await self.reader.read_bars(*args, **kwargs)


def _scenario(store: SeriesStore, rest: BarReader, first_db: pg.Db) -> dict[str, Any]:
    """t0: a first read starts and its query is held; a REST read is issued. t0 + 2 s: the store's
    timeout cancels the read, whose discard waits on the hung close; a second REST read is issued.
    5 s later the close bound terminates the connection; 2 s on, every REST budget is past. Each
    REST read: its status and the seconds from its issue to its answer."""
    clock, reads, out, eps = pg.Clock(), _Counted(rest), dict[str, Any](), pg.EPS
    before = {w: pg.counts(w) for w in ("bars", "bars_hydrate")}
    timeouts = pg.sample("bars_series_hydrate_failed_total", reason="timeout")
    first_db.hold.clear()  # every query on it is held: the REST ones only reach it when shared

    async def scenario() -> None:
        app = FastAPI()
        app.include_router(
            make_market_bars_router(
                lambda: reads, principal_resolver=_Principal(), symbol_listed=lambda _s: True,
                now_us=lambda: 1_700_000_100 * 10**6,
            )
        )  # fmt: skip
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://g2") as client:

            async def get(n: int) -> None:
                issued = clock.t
                status = (await client.get("/market/bars", params=REST)).status_code
                out[f"rest{n}"] = (status, round(clock.t - issued, 6))

            t0, first = clock.t, asyncio.create_task(store.ensure("BTCUSDT", SPEC))
            await pg.until(lambda: first_db.queries == 1, "the first read's query is held")
            one = asyncio.create_task(get(1))  # issued with the first read
            await pg.until(lambda: reads.started == 1, "the REST read is answered or waits")
            clock.t += 2.0 + eps  # the store's 2 s: the read is cancelled, its discard begins
            await pg.until(lambda: first_db.closes == 1, "the discard waits on the close")
            two = asyncio.create_task(get(2))  # issued during the discard
            await pg.until(lambda: reads.started == 2, "the second REST read is answered or waits")
            clock.t += 5.0 + eps  # the close bound: the connection is terminated
            await pg.until(first.done, "the first read ends")
            out["first_read_s"] = round(clock.t - t0, 6)
            first.result().release()  # a failed read leaves the series live-only, no error
            clock.t += 2.0 + eps  # past every REST read's budget
            await pg.until(lambda: one.done() and two.done(), "both REST reads end")
        await pg.settled()  # the shielded closes end once `terminate()` aborts them

    pg.run_on(clock, scenario)
    out["moved"] = {w: pg.moved(b, pg.counts(w)) for w, b in before.items()}
    out["timeouts"] = pg.sample("bars_series_hydrate_failed_total", reason="timeout") - timeouts
    return out


def test_a_first_read_past_the_stores_timeout_fails_no_concurrent_rest_bars_read(
    tmp_path: Path,
) -> None:
    """The G2 line, on the app's wiring: both REST reads are answered at once, one issued with the
    first read and one during its discard, while the first read times out and its discard takes
    the whole close bound, on its own connection."""
    store, first, rest = _wiring(_app(tmp_path))
    rest_db, first_db = _db(_wire(rest)), _db(first)  # one wire on `main`: the store's db wins
    run = _scenario(store, rest, first_db)
    assert (run["rest1"], run["rest2"]) == ((200, 0.0), (200, 0.0))
    assert (run["first_read_s"], run["timeouts"]) == (2.0 + 5.0 + 2 * pg.EPS, 1)
    assert (first_db.queries, rest_db.queries) == (1, 2)  # REST reads ran on the other connection
    assert run["moved"] == {"bars": {"waits": 2}, "bars_hydrate": {"cancelled": 1, "waits": 1}}


def test_the_same_scenario_on_one_connection_fails_both_rest_reads(tmp_path: Path) -> None:
    """The control: the store over the REST reader, as `main` composed it. Each REST read waits
    for the one connection until its own 2 s run out: two 503s."""
    _, _, rest = _wiring(_app(tmp_path))
    run = _scenario(SeriesStore(rest.read_tail), rest, _db(_wire(rest)))
    assert (run["rest1"][0], run["rest2"][0]) == (503, 503)
    shared = {"cancelled": 1, "abandoned": 2, "waits": 1}  # one discard; both REST reads gave up
    assert run["moved"] == {"bars": shared, "bars_hydrate": {}}


@pytest.mark.parametrize("enabled", [False, True])
def test_the_store_reads_on_its_own_wire_and_rest_and_the_writer_keep_the_sinks(
    enabled: bool, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    names: list[str] = []
    init = LazyPgWire.__init__

    def spy(self: LazyPgWire, *args: Any, **kwargs: Any) -> None:
        names.append(kwargs["name"])
        init(self, *args, **kwargs)

    monkeypatch.setattr(LazyPgWire, "__init__", spy)
    app = _app(tmp_path, enabled=enabled)
    if not enabled:  # no sink, so no second wire either
        assert app.state.ws_registry.services.series is None
        assert {"bars", "bars_hydrate"}.isdisjoint(names)
        return
    assert sorted(n for n in names if n.startswith("bars")) == ["bars", "bars_hydrate"]
    sink, (_, first, rest) = app.state.bars_runtime.writer._sink._inner, _wiring(app)
    assert isinstance(sink, QuestDbRowSink) and _wire(rest) is sink.pgwire
    assert (sink.pgwire.name, first.name) == ("bars", "bars_hydrate")
    assert first._args == sink.pgwire._args  # the sink's endpoint and credentials
    probe = sink.writer._readiness_probe  # the writer's probes keep the sink's wire
    assert probe is not None
    assert inspect.getclosurevars(probe).nonlocals["connection"] is sink.pgwire
    assert app.state.bars_runtime._reader_stop == first.close


@pytest.mark.parametrize("cancel", [False, True])
def test_shutdown_closes_the_sinks_wire_then_the_stores_each_within_its_close_bound(
    cancel: bool, tmp_path: Path
) -> None:
    app, clock = _app(tmp_path), pg.Clock()
    store, first, rest = _wiring(app)
    wires = [_wire(rest), first]
    shared, own = (_db(w) for w in wires)

    async def scenario() -> None:
        (await store.ensure("BTCUSDT", SPEC)).release()  # opens the store's connection
        await wires[0].fetch("SELECT 1")  # and the sink's
        stop = asyncio.create_task(app.state.bars_runtime.stop())
        await pg.until(lambda: (shared.closes, own.closes) == (1, 0), "the sink's closes first")
        if cancel:  # cancelled in the sink's close: the store's still closes, then the stop ends
            stop.cancel()
        else:
            clock.t += 5.0 + pg.EPS  # its close bound
        await pg.until(lambda: own.closes == 1, "then the store's")
        clock.t += 5.0 + pg.EPS
        await pg.until(stop.done, "the runtime's stop ends")
        assert stop.cancelled() if cancel else stop.result() is None
        assert [w._conn for w in wires] == [None, None]
        await pg.settled()

    pg.run_on(clock, scenario)


async def test_a_raising_stop_hook_is_logged_and_the_next_one_still_runs() -> None:
    calls: list[str] = []

    async def stop(name: str) -> None:
        calls.append(name)
        raise RuntimeError(name)

    ctx = build_app_context(Settings(environment=Environment.DEMO, metrics_enabled=False))
    runtime = wire_bars(
        ctx, now_us=lambda: 0, sink_stop=lambda: stop("sink"), reader_stop=lambda: stop("reader")
    )
    with capture_logs() as logs:
        await runtime.stop()
    assert calls == ["sink", "reader"]
    errors = [e["event"] for e in logs if e["log_level"] == "error"]
    assert errors == ["bars_sink_stop_failed", "bars_reader_stop_failed"]

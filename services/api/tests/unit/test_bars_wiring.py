"""`BarBuilderSet` lifespan wiring (E12 #2031): flag, blobs, rows, shutdown order."""

from __future__ import annotations

import asyncio
import contextlib
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from pydantic import SecretStr

from candleviewer.app import build_app_context, create_app
from candleviewer.bars.heal_driver import HealDriver
from candleviewer.bars.models import BarSpec
from candleviewer.bars.series_store import SeriesStore
from candleviewer.bars_wiring import BarsRuntime, wire_bars
from candleviewer.bus.models import Topic
from candleviewer.main import _lifespan
from candleviewer.settings import Environment, Settings
from tests.unit.bars._trades import SYM, trade, us

M1 = BarSpec(kind="time", interval_ms=60_000)
T0 = us("10:00:00")


class _FakeSink:
    def __init__(self, order: list[str]) -> None:
        self.calls: list[tuple[str, list[dict[str, object]], str]] = []
        self._order = order

    async def write_rows(self, table: str, rows: list[dict[str, object]], ts_us_key: str) -> None:
        self._order.append("rows")
        self.calls.append((table, rows, ts_us_key))


def _trace_stop(mp: pytest.MonkeyPatch, owner: Any, name: str, order: list[str]) -> None:
    real = owner.stop

    async def stop(*args: Any, **kwargs: Any) -> Any:
        order.append(f"stop:{name}")
        return await real(*args, **kwargs)

    mp.setattr(owner, "stop", stop)


def _settings(tmp_path: Path, *, enabled: bool) -> Settings:
    return Settings(
        environment=Environment.DEMO,
        git_sha="deadbeef",
        version="9.9.9",
        bars_enabled=enabled,
        bars_state_root=str(tmp_path / "bars"),
        metrics_enabled=False,
    )


def test_flag_off_by_default_builds_no_runtime(tmp_path: Path) -> None:
    app = create_app(_settings(tmp_path, enabled=False))
    assert getattr(app.state, "bars_runtime", None) is None


def test_flag_on_builds_runtime_with_state_root(tmp_path: Path) -> None:
    app = create_app(_settings(tmp_path, enabled=True))
    assert isinstance(app.state.bars_runtime, BarsRuntime)


@pytest.mark.parametrize("enabled", [False, True])
def test_the_heal_driver_comes_with_the_flag_over_the_wired_store(
    tmp_path: Path, enabled: bool
) -> None:
    """#2787 P4b: with `bars_enabled` off nothing holds a heal driver, so no task can start; on,
    the bars runtime owns one over the WS series store the gateway serves."""
    app = create_app(_settings(tmp_path, enabled=enabled))
    runtime = getattr(app.state, "bars_runtime", None)
    heal = getattr(runtime, "heal", None)
    if not enabled:
        assert (runtime, heal) == (None, None)
        return
    assert isinstance(heal, HealDriver) and heal._store is app.state.ws_registry.services.series


async def test_the_lifespan_runs_the_heal_driver_task_and_stops_it_before_the_set(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """#2787 P4b: the driver's one task runs while the app serves and is gone after it; the
    runtime stops it first, so no read is in flight when the set, writer and sink stop."""
    ctx = build_app_context(_settings(tmp_path, enabled=False))
    app = FastAPI()
    app.state.app_context = ctx
    runtime = wire_bars(ctx, now_us=lambda: T0, series=SeriesStore())
    app.state.bars_runtime = runtime
    order: list[str] = []
    assert runtime.heal is not None
    _trace_stop(monkeypatch, runtime.heal, "heal", order)
    _trace_stop(monkeypatch, runtime.builder_set, "set", order)

    def names() -> set[str]:
        return {t.get_name() for t in asyncio.all_tasks()}

    async with _lifespan(app):
        assert "bars-heal-driver" in names()
    assert "bars-heal-driver" not in names() and order[:2] == ["stop:heal", "stop:set"]


async def test_lifespan_register_publish_shutdown_flushes_blobs_and_rows(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Only the context + runtime: create_app()'s other lifespan tasks need Postgres.
    ctx = build_app_context(_settings(tmp_path, enabled=False))
    app = FastAPI()
    app.state.app_context = ctx
    order: list[str] = []
    sink = _FakeSink(order)
    now = [T0]
    runtime = wire_bars(ctx, now_us=lambda: now[0], inner_sink=sink)
    app.state.bars_runtime = runtime
    _trace_stop(monkeypatch, runtime.builder_set, "set", order)
    _trace_stop(monkeypatch, runtime.writer, "writer", order)

    async with _lifespan(app):
        await runtime.builder_set.register(M1, SYM, "c1", user="user-1")
        topic = Topic(env="demo", domain="md", symbol=SYM, detail="trade")
        await ctx.bus.bus.publish(topic, trade(T0, seq=1))
        now[0] = T0 + 120_000_000
        await ctx.bus.bus.publish(topic, trade(T0 + 120_000_000, seq=2))
    assert order.index("stop:set") < order.index("stop:writer")
    assert list((tmp_path / "bars").rglob("*.state.json"))
    assert sink.calls and sink.calls[0][0] == "bars_time"
    assert "rows" in order and order.index("stop:set") < len(order)


def test_state_root_default_anchors_on_data_dir_not_cwd(tmp_path: Path) -> None:
    s = Settings(parquet_root=str(tmp_path / "data" / "parquet"))
    assert Path(s.bars_state_root) == (tmp_path / "data" / "bars" / "state").resolve()


def test_state_root_must_be_absolute() -> None:
    with pytest.raises(ValueError, match="absolute"):
        Settings(bars_state_root="var/bars")


def test_state_root_symlink_rejected(tmp_path: Path) -> None:
    target = tmp_path / "real"
    target.mkdir()
    link = tmp_path / "link"
    try:
        link.symlink_to(target, target_is_directory=True)
    except OSError:
        pytest.skip("symlinks unavailable on this platform")
    with pytest.raises(ValueError, match="symlink"):
        Settings(bars_state_root=str(link))


async def test_writer_probe_not_deployed_off_and_degraded_when_writer_degraded(
    tmp_path: Path,
) -> None:
    from candleviewer.app import _bars_writer_state
    from candleviewer.health_wiring import register_bars_writer_probe
    from candleviewer.observability.health_probes import (
        BARS_WRITER,
        ComponentState,
        HealthRegistry,
    )

    ctx = build_app_context(_settings(tmp_path, enabled=False))
    runtime = wire_bars(ctx, now_us=lambda: T0, inner_sink=None)
    holder: list[Any] = [None]
    registry = HealthRegistry()
    register_bars_writer_probe(registry, lambda: _bars_writer_state(holder[0]))
    probe = registry._probes[BARS_WRITER]
    assert (await probe.check()).state is ComponentState.NOT_DEPLOYED
    holder[0] = runtime
    assert (await probe.check()).state is ComponentState.HEALTHY
    runtime.writer.degraded = True
    result = await probe.check()
    assert result.state is ComponentState.DEGRADED
    assert "bars_writer_degraded" in result.detail


def test_wire_without_sink_warns_rows_not_persisted(tmp_path: Path) -> None:
    from structlog.testing import capture_logs

    ctx = build_app_context(_settings(tmp_path, enabled=False))
    with capture_logs() as logs:
        wire_bars(ctx, now_us=lambda: T0)
    assert any(e["event"] == "bars_rows_not_persisted" for e in logs)


async def test_tape_narrows_window_when_a_read_returns_too_many_rows() -> None:
    from types import SimpleNamespace

    from candleviewer.bars_wiring import MAX_WINDOW_ROWS, StorageTape
    from candleviewer.storage.models import TimeRange
    from candleviewer.storage.repositories.rows import TradeRow

    widths: list[int] = []

    class Repo:
        async def read_trades(self, sym: str, rng: TimeRange) -> list[TradeRow]:
            w = rng.end_us - rng.start_us
            widths.append(w)
            n = MAX_WINDOW_ROWS + 1 if w > 150_000_000 else 1
            return [
                TradeRow(rng.start_us, sym, "1", "1", "buy", f"{rng.start_us}-{i}")
                for i in range(n)
            ]

    ctx = SimpleNamespace(storage=SimpleNamespace(market_data=Repo()))
    tape = StorageTape(ctx, lambda: T0 + 300_000_000)  # type: ignore[arg-type]
    got = [t async for t in tape.since(SYM, T0)]
    assert widths[0] == 300_000_000 and widths[1] == 150_000_000
    assert got and len(got) < MAX_WINDOW_ROWS


class _FakeTransport:
    def __init__(self, order: list[str]) -> None:
        self.order = order
        self.payloads: list[bytes] = []

    async def connect(self) -> None:
        self.order.append("ilp:connect")

    async def write(self, data: bytes) -> None:
        self.order.append("ilp:write")
        self.payloads.append(data)

    async def close(self) -> None:
        self.order.append("ilp:close")


class _FakePgWire:
    def __init__(self, order: list[str]) -> None:
        self.order = order

    async def fetch(self, sql: str, *params: object) -> list[dict[str, object]]:
        return [{"n": 0}]

    async def close(self) -> None:
        self.order.append("pg:close")


def test_sink_built_only_on_real_backend(tmp_path: Path) -> None:
    from candleviewer.app import _build_bars_sink
    from candleviewer.storage.questdb.wiring import QuestDbRowSink

    assert _build_bars_sink(_settings(tmp_path, enabled=True)) is None  # fake backend: stub
    real = _settings(tmp_path, enabled=True).model_copy(update={"storage_backend": "real"})
    assert isinstance(_build_bars_sink(real), QuestDbRowSink)  # lazy: no I/O at build


def test_fake_backend_keeps_guarded_stub_and_warning(tmp_path: Path) -> None:
    from structlog.testing import capture_logs

    with capture_logs() as logs:
        app = create_app(_settings(tmp_path, enabled=True))
    assert isinstance(app.state.bars_runtime, BarsRuntime)
    assert any(e["event"] == "bars_rows_not_persisted" for e in logs)


async def test_rows_flow_set_writer_ilp_and_shutdown_order(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from candleviewer.storage.questdb.wiring import QuestDbRowSink

    order: list[str] = []
    transport = _FakeTransport(order)
    sink = QuestDbRowSink(
        "h:1",
        "h:2",
        "u",
        "p",
        transport=transport,
        pgwire=_FakePgWire(order),  # type: ignore[arg-type]  # structural fake
    )
    ctx = build_app_context(_settings(tmp_path, enabled=False))
    app = FastAPI()
    app.state.app_context = ctx
    now = [T0]
    runtime = wire_bars(ctx, now_us=lambda: now[0], inner_sink=sink, sink_stop=sink.stop)
    app.state.bars_runtime = runtime
    _trace_stop(monkeypatch, runtime.builder_set, "set", order)
    _trace_stop(monkeypatch, runtime.writer, "writer", order)
    async with _lifespan(app):
        await runtime.builder_set.register(M1, SYM, "c1", user="user-1")
        topic = Topic(env="demo", domain="md", symbol=SYM, detail="trade")
        await ctx.bus.bus.publish(topic, trade(T0, seq=1))
        now[0] = T0 + 120_000_000
        await ctx.bus.bus.publish(topic, trade(T0 + 120_000_000, seq=2))
    assert any(b"bars_time" in p for p in transport.payloads)
    marks = [o for o in order if o.startswith(("stop:", "ilp:write", "ilp:close", "pg:close"))]
    # set -> writer drain -> ILP flush -> transport close -> PG-wire close (the trailing
    # `stop:set` is the AppContext's own idempotent bars stop, after the runtime).
    assert marks[:5] == ["stop:set", "stop:writer", "ilp:write", "ilp:close", "pg:close"]


class _Conn:
    def __init__(self, hang_fetch: bool = False, hang_close: bool = False) -> None:
        self.closed = False
        self.terminated = False
        self.busy = 0
        self.max_busy = 0
        self._hang_fetch = hang_fetch
        self._hang_close = hang_close

    async def fetch(self, sql: str, *params: object) -> list[dict[str, object]]:
        self.busy += 1
        self.max_busy = max(self.max_busy, self.busy)
        try:
            if self._hang_fetch:
                await asyncio.Event().wait()
            await asyncio.sleep(0)
            return [{"n": 1}]
        finally:
            self.busy -= 1

    async def close(self) -> None:
        if self._hang_close:
            await asyncio.Event().wait()
        self.closed = True

    def terminate(self) -> None:
        self.terminated = True


class _Factory:
    def __init__(self, fail: int = 0, **conn_kw: bool) -> None:
        self.fail = fail
        self.conns: list[_Conn] = []
        self.kw = conn_kw

    async def __call__(self, **_: object) -> _Conn:
        if self.fail:
            self.fail -= 1
            raise OSError("down")
        c = _Conn(**self.kw)
        self.conns.append(c)
        return c


def _wire(factory: _Factory, now: list[float], **kw: Any) -> Any:
    import random

    from candleviewer.storage.questdb.wiring import LazyPgWire

    return LazyPgWire(
        "h", 1, "u", "p", name="bars", connect=factory, clock=lambda: now[0],
        rng=random.Random(1),  # noqa: S311
        close_timeout_s=0.01, query_timeout_s=0.05, **kw,
    )  # fmt: skip


async def test_pgwire_reconnects_after_failure_with_backoff_and_degrades() -> None:
    now = [0.0]
    f = _Factory(fail=3)
    w = _wire(f, now)
    with pytest.raises(OSError):
        await w.fetch("q")
    with pytest.raises(ConnectionError, match="backoff"):
        await w.fetch("q")  # inside the window: fails fast, no connect attempt
    assert f.fail == 2
    for _ in range(2):
        now[0] += 100.0
        with pytest.raises(OSError):
            await w.fetch("q")
    assert w.degraded
    now[0] += 100.0
    assert await w.fetch("q") == [{"n": 1}]
    assert not w.degraded and len(f.conns) == 1


async def test_pgwire_concurrent_fetches_share_one_connection_closed_on_stop() -> None:
    import asyncio as aio

    f = _Factory()
    w = _wire(f, [0.0])
    await aio.gather(*(w.fetch("q") for _ in range(5)))
    assert len(f.conns) == 1 and f.conns[0].max_busy == 1
    await w.close()
    assert f.conns[0].closed


async def test_pgwire_cancelled_fetch_discards_connection() -> None:
    import asyncio as aio

    f = _Factory(hang_fetch=True)
    w = _wire(f, [0.0])
    task = aio.create_task(w.fetch("q"))
    await aio.sleep(0)
    await aio.sleep(0)
    task.cancel()
    with pytest.raises(aio.CancelledError):
        await task
    assert f.conns[0].closed and w._conn is None


async def test_pgwire_hung_close_is_terminated_within_bound() -> None:
    f = _Factory(hang_close=True)
    w = _wire(f, [0.0])
    await w.fetch("q")
    await w.close()  # close_timeout_s=0.01 -> abandoned
    assert f.conns[0].terminated and w._conn is None


async def test_sink_stop_with_db_down_completes_and_closes_pgwire(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import candleviewer.storage.questdb.wiring as wiring

    class _Hang:
        async def connect(self) -> None:
            await asyncio.Event().wait()

        async def write(self, data: bytes) -> None: ...

        async def close(self) -> None:
            await asyncio.Event().wait()

    monkeypatch.setattr(wiring, "STOP_TIMEOUT_S", 0.01)
    closed: list[bool] = []

    class _Pg:
        degraded = False

        async def close(self) -> None:
            closed.append(True)

        async def fetch(self, sql: str, *params: object) -> list[dict[str, object]]:
            return [{"n": 0}]

    sink = wiring.QuestDbRowSink(
        "h:1",
        "h:2",
        "u",
        "p",
        transport=_Hang(),
        pgwire=_Pg(),  # type: ignore[arg-type]
    )
    await sink.writer.write_rows("trades", [], "ts")
    with contextlib.suppress(Exception):  # bounded failure is the contract; close still ran
        await asyncio.wait_for(sink.stop(), 2.0)
    assert closed == [True]


def test_live_real_backend_refuses_dev_questdb_password() -> None:
    with pytest.raises(ValueError, match="CV_QUESTDB_PG_PASSWORD"):
        Settings(environment=Environment.LIVE, storage_backend="real")
    live_ok = SecretStr("s3cret")
    Settings(environment=Environment.LIVE, storage_backend="real", questdb_pg_password=live_ok)
    Settings(environment=Environment.LIVE, storage_backend="fake")  # fake: unaffected
    Settings(environment=Environment.DEMO, storage_backend="real")  # dev/demo: unaffected


async def test_tcp_transport_connect_closes_previous_writer_and_times_out(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from candleviewer.storage.questdb import wiring

    closed: list[int] = []

    class _W:
        def __init__(self, n: int) -> None:
            self.n = n

        def close(self) -> None:
            closed.append(self.n)

        async def wait_closed(self) -> None: ...

    calls = [0]

    async def fake_open(host: str, port: int) -> tuple[None, _W]:
        calls[0] += 1
        return None, _W(calls[0])

    monkeypatch.setattr(asyncio, "open_connection", fake_open)
    t = wiring.TcpIlpTransport("h", 1, connect_timeout_s=0.01)
    await t.connect()
    await t.connect()
    assert closed == [1]  # the first socket was closed before replacement

    async def hang(host: str, port: int) -> None:
        await asyncio.Event().wait()

    monkeypatch.setattr(asyncio, "open_connection", hang)
    with pytest.raises(TimeoutError):
        await t.connect()

"""The backend under load: the real `/ws` gateway on loopback, fed by the bench feeder (E17-Q03).

Wired as the E17-Q02 chaos `Stack` wires it (`make_ws_router`, `ConnectionRegistry`,
`SubscriptionServices`, `GatewayHub`, `WsRuntime`, served by `PlannedShutdownServer` with the
production `uvicorn_kwargs`), on wall time, plus the real `bars.*` path as `create_app` composes it
with `bars_enabled`: a `BarBuilderSet` on a private `Bus`, emitting to the `SeriesStore` and the
`BarsPublisher`, with `BarsSnapshotSource` behind the snapshots. `create_app` is not used: it takes
no snapshot sources, so its book subscriptions would stay pending without live ingestion, which
cannot be pointed at a stub exchange (no setting overrides the hosts).

- **Principal and auth, no credentials.** A real `SessionService` over `FakeSessionRepository`
  mints one session per bench connection at boot (opaque handles, valid only in this process) into
  a 0600 `tokens.json`. The principal holds exactly `marketdata:read`. `POST /auth/refresh` is the
  REST double a client re-auths in place against (access tokens live 12 min).
- **Origin.** `allowed_origins` is the entry the dev stack already lists; k6 sends it.
- **Metrics.** `/metrics` serves the gateway's `cv_ws_*` series, `process_*`, the loop-lag
  histogram and the feeder's schedule counters, from one private registry.
- **Egress.** What holds is the loopback bind and that no exchange or other outbound client is
  constructed here; k6 refuses a non-loopback target. The Python socket guard (connect and name
  lookups) is defence in depth on top: the backend runs on the stdlib loop, because uvloop resolves
  names inside libuv, where no patched Python function sees them.
- **Path.** The gateway is served at `/ws` and at `/api/v1/ws` (23 2.1), one router included
  twice by `include_ws_router` as `create_app` does since #3916, so either path reaches the same
  handler. `ws_path` (default `/ws`) is where k6 connects; under another prefix it is served too.
- **Logs.** The project's `configure_logging()` (JSON, `RedactionFilter`) writes to stderr, which
  the runner keeps as `backend.err`; stdout carries the ready line alone.
- **Feeder.** `--feeder inproc` (the default) runs the feeder on this loop, as it always has;
  `--feeder proc` runs it in a child process (`feed_proc`), pinned to `--feeder-cpus` when given,
  and only its receiver stays here, so the backend's `process_*` numbers are the gateway's and the
  child's CPU is `cv_bench_feeder_cpu_seconds_total` (#571).
- **Bench-only knobs** (environment, read here only): `CV_BENCH_WS_SEND_DELAY_MS` delays every
  outbound `websocket.send` inside the `cv_ws_fanout_seconds` span (the self-check), and
  `CV_BENCH_FEED_SEED`. Ready line on stdout: `CV_BENCH_WS_READY port=<p> pid=<n> tokens=<path>`.

    uv run python -m bench.ws.fixture_app --profile A --flag on --out DIR [--feeder proc]
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import os
import socket
import sys
import tempfile
import time
import uuid
from collections.abc import Awaitable, Callable, Iterator, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import structlog
import uvicorn
from fastapi import FastAPI, Response
from prometheus_client import CONTENT_TYPE_LATEST, CollectorRegistry, Histogram, generate_latest
from prometheus_client.core import CounterMetricFamily
from prometheus_client.process_collector import ProcessCollector
from prometheus_client.registry import Collector
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from bench.ws import HARNESS_VERSION, READY, profiles
from bench.ws.feed_proc import RemoteFeeder
from bench.ws.feeder import BookSource, Feeder, TradesSource, tier_plan
from candleviewer.auth.generated_permissions import Permission
from candleviewer.auth.hashing import Hasher
from candleviewer.auth.scopes import PrincipalSnapshot
from candleviewer.auth.session_service import SessionService, access_token_expires_at
from candleviewer.bars.builder_set import BarBuilderSet, production_factory
from candleviewer.bars.emit import EmitRouter
from candleviewer.bars.series_store import SeriesStore
from candleviewer.bars.state_store import StateStore
from candleviewer.bus.bus import Bus
from candleviewer.observability.context import spawn
from candleviewer.observability.logging import configure_logging
from candleviewer.server import PlannedShutdownServer, uvicorn_kwargs
from candleviewer.settings import Settings
from candleviewer.ws.backpressure_config import BackpressureConfig
from candleviewer.ws.bars_publish import BarsPublisher
from candleviewer.ws.bars_source import BarsSnapshotSource
from candleviewer.ws.gateway import (
    WS_PATH,
    WS_SERVER_BASE,
    GatewayHub,
    include_ws_router,
    make_ws_router,
)
from candleviewer.ws.metrics import export_cvwb_metrics, export_ws_metrics
from candleviewer.ws.pacing import LoopStall
from candleviewer.ws.permissions import ConnectionRegistry, SubscriptionServices
from candleviewer.ws.revocation import RevocationHub
from candleviewer.ws.sequencing import SequencingHub, new_span_id
from candleviewer.ws.upstream import UpstreamRefs
from candleviewer.ws_wiring import WsRuntime, default_snapshot_router
from tests.unit.auth.session_fakes import FakeSessionRepository

LOOPBACK = frozenset({"127.0.0.1", "::1", "localhost"})
ENV_SEND_DELAY, ENV_SEED = "CV_BENCH_WS_SEND_DELAY_MS", "CV_BENCH_FEED_SEED"
BUS_ENV = "demo"
#: The loop-lag histogram (C-14.2: p95 < 50 ms, p99 < 100 ms), 100 ms cadence like the sampler of
#: `observability.metrics_runtime`.
LAG_BUCKETS = (0.001, 0.0025, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0)
LAG_INTERVAL_S = 0.1


def assert_loopback(host: str) -> None:
    if host not in LOOPBACK:
        raise RuntimeError(f"bench host {host!r} is not loopback (C-12.9, C-13.5)")


_CONNECTS = ("connect", "connect_ex")
#: The `socket` resolvers the guard wraps, and the argument of each that names the host.
_LOOKUPS = {
    "getaddrinfo": "host",
    "gethostbyname": "hostname",
    "gethostbyname_ex": "hostname",
    "gethostbyaddr": "ip_address",
    "getnameinfo": "sockaddr",
}


def _host(call: str, args: tuple[Any, ...], kwargs: dict[str, Any]) -> str | None:
    """The host a resolver call names (`None` for a passive lookup, which names none)."""
    target = args[0] if args else kwargs.get(_LOOKUPS[call])
    if call == "getnameinfo" and isinstance(target, tuple) and target:
        target = target[0]
    if isinstance(target, bytes | bytearray):
        target = bytes(target).decode("ascii", "replace")
    return target if isinstance(target, str) else None


@contextlib.contextmanager
def egress_guard() -> Iterator[None]:
    """Refuse a connect and a name lookup of anything but loopback, for the Python-level socket
    calls of the process (the ones `tests/_ci_network_guard.py` wraps). Defence in depth: it does
    not see a resolver inside a C extension, which is why the backend runs on the stdlib loop."""

    def connect(real: Callable[..., Any]) -> Callable[..., Any]:
        def guarded(self: socket.socket, address: Any) -> Any:
            if self.family in (socket.AF_INET, socket.AF_INET6):
                assert_loopback(str(address[0]))
            return real(self, address)

        return guarded

    def lookup(call: str, real: Callable[..., Any]) -> Callable[..., Any]:
        def guarded(*args: Any, **kwargs: Any) -> Any:
            host = _host(call, args, kwargs)
            if host is not None:
                assert_loopback(host)
            return real(*args, **kwargs)

        return guarded

    wrappers: list[tuple[Any, str, Callable[..., Any]]] = []
    wrappers += [(socket.socket, n, connect(getattr(socket.socket, n))) for n in _CONNECTS]
    wrappers += [(socket, n, lookup(n, getattr(socket, n))) for n in _LOOKUPS]
    originals = [(owner, name, getattr(owner, name)) for owner, name, _ in wrappers]
    for owner, name, fn in wrappers:
        setattr(owner, name, fn)
    try:
        yield
    finally:
        for owner, name, real in originals:
            setattr(owner, name, real)


class SendDelay:
    """Bench-only ASGI wrapper: every outbound WebSocket message waits `delay_s` before it is
    sent, which is inside `cv_ws_fanout_seconds` (the span closes after `send_payload`). The
    self-check: an inflated fan-out must fail budget #6."""

    def __init__(
        self,
        app: ASGIApp,
        delay_s: float,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self.app, self._delay, self._sleep = app, delay_s, sleep  # `.app`: the server unwraps it

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        async def slow(message: Message) -> None:
            if message["type"] == "websocket.send":
                await self._sleep(self._delay)
            await send(message)

        await self.app(scope, receive, slow if scope["type"] == "websocket" else send)


#: The two feeder modes (`--feeder`): on the backend's loop, or in a child process.
FEEDERS = ("inproc", "proc")


class _FeedCollector(Collector):
    """`cv_bench_feed_{scheduled,published}_total{kind}`: the feeder's schedule and what it did.
    Out of process also `cv_bench_feed_missed_total{kind}` (slots the child skipped) and
    `cv_bench_feeder_cpu_seconds_total` (the child's CPU, outside `process_*`)."""

    def __init__(self, feeder: Feeder | RemoteFeeder) -> None:
        self._feeder = feeder

    def collect(self) -> Iterator[CounterMetricFamily]:
        for name, idx in (("scheduled", 0), ("published", 1)):
            fam = CounterMetricFamily(
                f"cv_bench_feed_{name}", f"Feeder slots {name}", labels=["kind"]
            )
            for kind, pair in self._feeder.stats().items():
                fam.add_metric([kind], pair[idx])
            yield fam
        if isinstance(self._feeder, RemoteFeeder):
            fam = CounterMetricFamily(
                "cv_bench_feed_missed", "Feeder slots the child skipped", labels=["kind"]
            )
            for kind, n in self._feeder.missed.items():
                fam.add_metric([kind], n)
            yield fam
            yield CounterMetricFamily(
                "cv_bench_feeder_cpu_seconds",
                "CPU seconds of the out-of-process feeder",
                value=self._feeder.cpu_seconds(),
            )


@dataclass(frozen=True, slots=True)
class BackendConfig:
    symbols: tuple[str, ...]
    hot: int
    warm: int
    users: int  # bench users, the probe's included
    connections: int  # sessions minted per user
    flag: bool
    seed: int = 7
    send_delay_ms: int = 0
    depths: tuple[int, ...] = (50,)
    ws_path: str = "/ws"
    feeder: str = "inproc"  # FEEDERS
    feeder_cpus: str | None = None  # the child's cpus (`--feeder proc`); None: the backend's

    @classmethod
    def for_profile(
        cls,
        table: dict[str, Any],
        name: str,
        *,
        flag: bool,
        seed: int,
        send_delay_ms: int = 0,
        ws_path: str = "",
        feeder: str = "inproc",
        feeder_cpus: str | None = None,
    ) -> BackendConfig:
        p = profiles.resolve(table, name)
        feed = table["feeds"][p["feed"]]
        return cls(
            symbols=tuple(table["symbols"][: feed["symbols"]]),
            hot=feed["hot"],
            warm=feed["warm"],
            users=int(p["users"]) + int(bool(p.get("probe"))),
            connections=int(p["connections"]),
            flag=flag,
            seed=seed,
            send_delay_ms=send_delay_ms or int(p.get("send_delay_ms", 0)),
            depths=tuple(feed["book_depths"]),
            ws_path=profiles.ws_path(ws_path or p["ws_path"]),
            feeder=feeder,
            feeder_cpus=feeder_cpus or None,
        )


class Backend:
    """Everything one run's server process holds. `async with Backend(...) as be:` serves on
    `be.port` until it exits; `be.tokens` is what `tokens.json` holds."""

    def __init__(self, cfg: BackendConfig, table: dict[str, Any], state_dir: Path) -> None:
        assert_loopback("127.0.0.1")
        self.cfg, self.state_dir = cfg, state_dir
        self.settings = Settings(ws_shutdown_grace_ms=100, ws_backpressure_enabled=cfg.flag)
        self.hub, self.bus = SequencingHub(), Bus()
        tiers = tier_plan(len(cfg.symbols), cfg.hot, cfg.warm, table["tiers"])
        if cfg.feeder not in FEEDERS:
            raise ValueError(f"feeder {cfg.feeder!r}: one of {', '.join(FEEDERS)}")
        self.feeder: Feeder | RemoteFeeder = (
            RemoteFeeder(
                self.hub, self.bus, cfg.symbols, tiers, seed=cfg.seed, depths=cfg.depths,
                cpus=cfg.feeder_cpus,
            )
            if cfg.feeder == "proc"
            else Feeder(self.hub, self.bus, cfg.symbols, tiers, seed=cfg.seed, depths=cfg.depths)
        )  # fmt: skip
        self.sessions = SessionService(
            FakeSessionRepository(), Hasher(), clock=lambda: datetime.now(UTC)
        )
        self.user_ids = [uuid.UUID(int=0xBE00 + u) for u in range(cfg.users)]
        self.tokens: dict[str, list[dict[str, str]]] = {}
        self.series = SeriesStore()
        publisher = BarsPublisher(self.hub, self.feeder.scales, swap_reason="generation_swap")
        self.series.on_repair(publisher.history_repair)
        self.bars = BarBuilderSet(
            self.bus,
            BUS_ENV,
            EmitRouter([self.series, publisher]),
            StateStore(state_dir / "bars"),
            now_us=lambda: time.time_ns() // 1000,
            factory=production_factory(self.feeder.tick_size, renko_enabled=False),
        )
        bars_source = BarsSnapshotSource(
            self.series, self.feeder.scales, seed=publisher.note_generation,
            stale=self.bars.quarantined,
        )  # fmt: skip
        services = SubscriptionServices(
            upstream=UpstreamRefs(),
            bars=self.bars,
            series=self.series,
            snapshots=default_snapshot_router(
                {
                    "book": BookSource(self.feeder.feeds),
                    "trades": TradesSource(self.feeder.feeds),
                    "bars": bars_source,
                }
            ),
            sequencing=self.hub,
            span_ids=new_span_id,  # `sp` on 1 frame in 32, as with CV_TELEMETRY_ENABLED
        )
        registry = ConnectionRegistry(
            self._principal, lambda: time.time_ns() // 1_000_000, services
        )
        self.gateway = GatewayHub()
        self.metrics = CollectorRegistry()
        ProcessCollector(registry=self.metrics)
        export_ws_metrics(self.metrics, env=BUS_ENV)
        export_cvwb_metrics(self.metrics, env=BUS_ENV)
        self.metrics.register(_FeedCollector(self.feeder))
        self.lag = Histogram(
            "event_loop_lag_seconds", "Loop overshoot of a 100 ms sleep", buckets=LAG_BUCKETS,
            registry=self.metrics,
        )  # fmt: skip
        app = FastAPI()
        router = make_ws_router(
            authenticate=self._authenticate,
            registry=registry,
            revocation_hub=RevocationHub(),
            allowed_origins=frozenset({table["origin"]}),
            hub=self.gateway,
            backpressure=BackpressureConfig.from_settings(self.settings) if cfg.flag else None,
            server_version=HARNESS_VERSION,
            loop_stall=LoopStall(),  # #4833: as `create_app` wires it, one per process
        )
        include_ws_router(app, router)  # `/ws` and `/api/v1/ws`, as `create_app` serves it (#3916)
        if cfg.ws_path not in (WS_PATH, WS_SERVER_BASE + WS_PATH):  # another prefix: served too
            app.include_router(router, prefix=profiles.ws_prefix(cfg.ws_path))
        app.add_api_route("/auth/refresh", self._refresh, methods=["POST"])
        app.add_api_route("/metrics", self._scrape, methods=["GET"])
        app.state.ws_runtime = WsRuntime(self.gateway, UpstreamRefs(), self.settings)
        self.asgi: ASGIApp = SendDelay(app, cfg.send_delay_ms / 1000) if cfg.send_delay_ms else app
        kw = {**uvicorn_kwargs(self.settings), "lifespan": "off", "log_config": None}
        self.server = PlannedShutdownServer(uvicorn.Config(self.asgi, **kw))
        self.sock = socket.create_server(("127.0.0.1", 0))
        self.port: int = self.sock.getsockname()[1]
        self._tasks: list[asyncio.Task[Any]] = []

    async def _principal(self, uid: uuid.UUID) -> PrincipalSnapshot:
        return PrincipalSnapshot(
            uid, frozenset({"viewer"}), frozenset({Permission.MARKETDATA_READ})
        )

    async def _authenticate(self, token: str) -> tuple[str, uuid.UUID, datetime]:
        # The harness stands for active users: each socket auth also presses Extend, the only
        # activity on a live session (#2300; a WS auth is none), so a refresh never finds the
        # session idle-locked (#4012: a refresh is no activity) during a 30 or 60 min profile.
        rec = await self.sessions.authenticate_access_token(token)
        rec = await self.sessions.touch(str(rec.id))
        return str(rec.id), rec.user_id, access_token_expires_at(rec)

    async def _refresh(self, body: dict[str, str]) -> dict[str, str]:
        minted = (await self.sessions.refresh(body["refresh_token"])).minted
        return {"access_token": minted.access_token, "refresh_token": minted.refresh_token}

    async def _scrape(self) -> Response:
        return Response(generate_latest(self.metrics), media_type=CONTENT_TYPE_LATEST)

    async def _sample_lag(self) -> None:
        while True:
            began = time.perf_counter()
            await asyncio.sleep(LAG_INTERVAL_S)
            self.lag.observe(max(0.0, time.perf_counter() - began - LAG_INTERVAL_S))

    async def __aenter__(self) -> Backend:
        for u, uid in enumerate(self.user_ids):
            minted = [await self.sessions.mint(str(uid)) for _ in range(self.cfg.connections)]
            self.tokens[f"u{u}"] = [
                {"access": m.access_token, "refresh": m.refresh_token} for m in minted
            ]
        path = self.state_dir / "tokens.json"
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(self.tokens, fh)
        if isinstance(self.feeder, RemoteFeeder):  # its hello holds the scales the bars ask for
            await self.feeder.start()
        await self.bars.start()
        self._tasks = [
            spawn(self.server.serve(sockets=[self.sock]), name="bench-ws-uvicorn"),
            spawn(self.feeder.run(), name="bench-ws-feeder"),
            spawn(self._sample_lag(), name="bench-ws-lag"),
        ]
        self._tasks[1].add_done_callback(feeder_ended)  # a feed that dies is logged as it dies
        while not self.server.started:
            if self._tasks[0].done():
                self._tasks[0].result()
            await asyncio.sleep(0.01)
        return self

    async def wait(self) -> None:
        """Until the server process ends (a SIGTERM or SIGINT, which uvicorn turns into a stop)."""
        await self._tasks[0]

    async def __aexit__(self, *exc: object) -> None:
        self.server.should_exit = True
        for task in self._tasks[1:]:
            task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        if isinstance(self.feeder, RemoteFeeder):  # no orphan: the child is ended and reaped
            await self.feeder.close()
        await self.bars.stop()
        self.sock.close()


def feeder_ended(task: asyncio.Task[Any]) -> None:
    """Log a feeder task that ends with an error (a receiver whose child closed its pipe, a
    publish that raised), as it ends: the run's `feeder_behind` guard trips later, but the cause
    is named in `backend.err` at once. A cancellation is the shutdown's doing, not a failure."""
    if not task.cancelled() and (exc := task.exception()) is not None:
        structlog.get_logger(__name__).error(
            "bench_feeder_ended", task=task.get_name(), error=type(exc).__name__, detail=str(exc)
        )


async def serve(args: argparse.Namespace) -> None:
    table = profiles.load()
    cfg = BackendConfig.for_profile(
        table, args.profile, flag=args.flag == "on", seed=args.seed,
        send_delay_ms=args.send_delay_ms, ws_path=args.ws_path,
        feeder=args.feeder, feeder_cpus=args.feeder_cpus,
    )  # fmt: skip
    out = Path(args.out) if args.out else Path(tempfile.mkdtemp(prefix="cv-bench-ws-"))
    out.mkdir(parents=True, exist_ok=True)
    async with Backend(cfg, table, out) as be:
        print(f"{READY} port={be.port} pid={os.getpid()} tokens={out / 'tokens.json'}", flush=True)
        await be.wait()


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--profile", required=True)
    ap.add_argument("--flag", choices=("on", "off"), default="on")
    ap.add_argument("--seed", type=int, default=int(os.environ.get(ENV_SEED, "7")))
    ap.add_argument("--send-delay-ms", type=int, default=int(os.environ.get(ENV_SEND_DELAY, "0")))
    ap.add_argument("--out", default="")
    ap.add_argument("--ws-path", default="", help="k6's path; /ws and /api/v1/ws are always served")
    ap.add_argument("--feeder", choices=FEEDERS, default="inproc", help="the feeder's process")
    ap.add_argument("--feeder-cpus", default="", help="--feeder proc: the child's cpus")
    args = ap.parse_args(argv)
    with contextlib.redirect_stdout(sys.stderr):  # the handler binds stdout, the ready line's
        configure_logging(
            env=os.environ.get("CV_ENV", "dev"), level=os.environ.get("CV_LOG_LEVEL", "warning")
        )
    with egress_guard():
        asyncio.run(serve(args))  # the stdlib loop: its lookups are the guarded Python ones
    return 0


if __name__ == "__main__":
    sys.exit(main())

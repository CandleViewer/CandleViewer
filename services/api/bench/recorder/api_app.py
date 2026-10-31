"""The recorder API/WS load target (E16-Q04): a loopback app for `tests/load/k6/recorder_api.js`.

Serves, with production code, the three surfaces the k6 script loads: `GET /recording/status`
(`make_recording_status_router` over a real `RecordingStatusCache`, 1 Hz), `GET
/market/data-coverage` (`make_data_coverage_router` over a real `CoverageService`) and the `/ws`
gateway with the `recorder` topic (`ws_wiring.recorder_topic`, the snapshot source `create_app`
registers). Only the edges are stand-ins: a runtime whose status names 20 recorded symbols (the
budget's frame size is defined at 20), a coverage store with one session and one gap, and an
in-memory session store holding the bench sessions minted at boot.

- **No credential exists.** The sessions are minted in this process (opaque handles, valid only
  here) into a 0600 `tokens.json`; the principal is a bench Owner holding `recording:read` and
  `marketdata:read` and nothing else.
- **Egress.** Binds 127.0.0.1 only and builds no exchange or other outbound client; the socket
  guard (`bench.ws.fixture_app.egress_guard`) refuses any non-loopback connect or lookup, and the
  k6 script refuses a non-loopback target (C-12.9, C-13.5).
- Ready line on stdout: `CV_BENCH_RECORDER_READY port=<p> pid=<n> tokens=<path>`.

    uv run python -m bench.recorder.api_app --out DIR [--sessions 5]
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import os
import random
import socket
import sys
import tempfile
import time
import uuid
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Final

import uvicorn
from fastapi import FastAPI, Request

from bench.recorder import HARNESS_VERSION
from bench.ws.fixture_app import assert_loopback, egress_guard
from candleviewer.api.market_coverage import make_data_coverage_router
from candleviewer.api.recording_status import make_recording_status_router
from candleviewer.audit.access import AuditPrincipal
from candleviewer.auth.generated_permissions import Permission
from candleviewer.auth.hashing import Hasher
from candleviewer.auth.scopes import PrincipalSnapshot
from candleviewer.auth.session_service import SessionService, access_token_expires_at
from candleviewer.observability.context import spawn
from candleviewer.observability.logging import configure_logging
from candleviewer.recorder import control as rc
from candleviewer.recorder.budget import BudgetConfig
from candleviewer.recorder.coverage import CoverageService
from candleviewer.recorder.models import DiskPressureLevel, StorageUsage
from candleviewer.recorder.status import RecordingStatusCache
from candleviewer.server import PlannedShutdownServer, uvicorn_kwargs
from candleviewer.settings import Settings
from candleviewer.ws.backpressure_config import BackpressureConfig
from candleviewer.ws.gateway import GatewayHub, include_ws_router, make_ws_router
from candleviewer.ws.pacing import LoopStall
from candleviewer.ws.permissions import ConnectionRegistry, SubscriptionServices
from candleviewer.ws.revocation import RevocationHub
from candleviewer.ws.sequencing import SequencingHub
from candleviewer.ws.upstream import UpstreamRefs
from candleviewer.ws_wiring import WsRuntime, default_snapshot_router, recorder_topic

# A test double in bench code, on purpose and as `bench.ws.fixture_app` (E17) already does: the
# load target needs an in-memory session store, and this one is the double the auth suites keep
# true to `SessionRepository` (~30 importers). Moving it out of `tests/` is its own refactor.
from tests.unit.auth.session_fakes import FakeSessionRepository

READY: Final = "CV_BENCH_RECORDER_READY"
ORIGIN: Final = "http://127.0.0.1:5173"
#: 20 symbols, the frame budget's definition (the names only label rows; nothing is fetched).
SYMBOLS: Final = tuple(
    f"{base}USDT"
    for base in (
        "BTC", "ETH", "SOL", "XRP", "DOGE", "ADA", "AVAX", "LINK", "DOT", "LTC",
        "BCH", "TRX", "NEAR", "APT", "ARB", "OP", "SUI", "ATOM", "FIL", "INJ",
    )
)  # fmt: skip
GRANTED: Final = frozenset({Permission.RECORDING_READ, Permission.MARKETDATA_READ})
_EPOCH_START: Final = datetime(2026, 10, 5, tzinfo=UTC)


class Runtime:
    """`StatusSource`: 20 recording symbols whose counters move each second (seeded)."""

    def __init__(self, symbols: Sequence[str], seed: int = 7) -> None:
        self._symbols, self._ticks = tuple(symbols), 0
        self._rng = random.Random(seed)  # noqa: S311 - seeded bench status values, not crypto

    async def status(self) -> rc.ControlStatus:
        self._ticks += 1
        now = datetime.now(UTC)
        entries = tuple(
            rc.RecordedEntry(
                id=str(uuid.UUID(int=i + 1)), symbol=s, reasons=("manual",), state="recording",
                pinned=i % 5 == 0, streams=("trades", "orderbook_delta"), depth=200,
                started_at=_EPOCH_START, disk_bytes=10**9 + self._rng.randrange(10**8),
                rows_last_hour=3_600 * 500 + self._rng.randrange(10_000),
                lag_ms=self._rng.randrange(5, 80), dropped_messages=0, resyncs_last_hour=0,
                last_event_at=now - timedelta(milliseconds=self._rng.randrange(1, 900)),
            )
            for i, s in enumerate(self._symbols)
        )  # fmt: skip
        link = rc.Connection(
            endpoint="public-linear", state="connected", subscribed_topics=2 * len(entries),
            connected_since=_EPOCH_START, reconnects_last_hour=0, last_ping_ms=20,
        )  # fmt: skip
        return rc.ControlStatus(
            entries=entries, ingest_rate_msgs_per_sec=900 * len(entries),
            write_backlog_rows=0, overall="healthy", connections=(link,),
        )  # fmt: skip


class Budget:
    """`status.Budget` at the normal level with a measured report, so frames carry `storage`."""

    config = BudgetConfig(cap_bytes=600 * 10**9)
    effective_level = DiskPressureLevel.NORMAL
    accelerate_retention = False
    recording_refused = False

    def report(self) -> StorageUsage | None:
        return None


class CoverageStore:
    """One open session and one gap per symbol, at fixed instants."""

    async def sessions_in(self, symbol: str, lo: datetime, hi: datetime) -> list[dict[str, Any]]:
        return [{"started_at": _EPOCH_START, "ended_at": None,
                 "streams": ["trades", "orderbook_delta"]}]  # fmt: skip

    async def gaps_in(self, symbol: str, lo: datetime, hi: datetime) -> list[dict[str, Any]]:
        g0 = _EPOCH_START + timedelta(hours=6)
        return [{"stream": "trades", "gap_start": g0, "gap_end": g0 + timedelta(minutes=2),
                 "cause": "process_restart"}]  # fmt: skip

    async def earliest_first_event(self, symbol: str) -> datetime | None:
        return None


class _Emitter:
    async def emit(self, action: str, **kwargs: object) -> None:
        return None  # a bench Owner is never denied: nothing to record


class Backend:
    """`async with Backend(...) as be:` serves on `be.port` until it exits."""

    def __init__(self, state_dir: Path, sessions: int = 5, seed: int = 7) -> None:
        assert_loopback("127.0.0.1")
        self.state_dir, self.n_sessions = state_dir, sessions
        self.settings = Settings(ws_shutdown_grace_ms=100)
        self.sessions = SessionService(
            FakeSessionRepository(), Hasher(), clock=lambda: datetime.now(UTC)
        )
        self.owner = uuid.UUID(int=0xE16)
        self.tokens: list[dict[str, str]] = []
        self.hub = SequencingHub()
        topic = recorder_topic(self.hub)
        self.runtime = Runtime(SYMBOLS, seed)
        self.cache = RecordingStatusCache(lambda: self.runtime, Budget())
        topic.attach(self.cache)
        services = SubscriptionServices(
            upstream=UpstreamRefs(),
            snapshots=default_snapshot_router({"recorder": topic}),
            sequencing=self.hub,
        )
        registry = ConnectionRegistry(self._principal, lambda: time.time_ns() // 10**6, services)
        self.gateway = GatewayHub()
        app = FastAPI()
        router = make_ws_router(
            authenticate=self._authenticate, registry=registry, revocation_hub=RevocationHub(),
            allowed_origins=frozenset({ORIGIN}), hub=self.gateway,
            backpressure=BackpressureConfig.from_settings(self.settings),
            server_version=HARNESS_VERSION, loop_stall=LoopStall(),
        )  # fmt: skip
        include_ws_router(app, router)
        app.include_router(make_recording_status_router(self.cache, self, _Emitter()))
        coverage = CoverageService(CoverageStore(), now_us=lambda: time.time_ns() // 1000)
        app.include_router(
            make_data_coverage_router(
                lambda: coverage, principal_resolver=_CoverageResolver(self),
                symbol_listed=lambda s: s in SYMBOLS,
            )
        )  # fmt: skip
        app.state.ws_runtime = WsRuntime(self.gateway, UpstreamRefs(), self.settings)
        self.app = app
        kw = {**uvicorn_kwargs(self.settings), "lifespan": "off", "log_config": None}
        self.server = PlannedShutdownServer(uvicorn.Config(app, **kw))
        self.sock: socket.socket | None = None
        self.port = 0
        self._task: asyncio.Task[Any] | None = None

    async def _principal(self, uid: uuid.UUID) -> PrincipalSnapshot:
        return PrincipalSnapshot(uid, frozenset({"owner"}), GRANTED)

    async def _authenticate(self, token: str) -> tuple[str, uuid.UUID, datetime]:
        rec = await self.sessions.authenticate_access_token(token)
        return str(rec.id), rec.user_id, access_token_expires_at(rec)

    async def resolve(self, request: Request) -> AuditPrincipal | None:
        """`recording_common.Resolver`: the bearer's bench session, or `None` (401)."""
        header = request.headers.get("authorization", "")
        if not header.startswith("Bearer "):
            return None
        try:
            rec = await self.sessions.authenticate_access_token(header.removeprefix("Bearer "))
        except Exception:
            return None
        return AuditPrincipal(
            user_id=rec.user_id, username="bench-owner",
            permissions=frozenset(p.value for p in GRANTED), session_id=rec.id, is_owner=True,
        )  # fmt: skip

    async def prepare(self) -> Path:
        """Mint the bench sessions into a 0600 `tokens.json` and compute the first status, so the
        first request finds one (no 503). Returns the tokens file."""
        for _ in range(self.n_sessions):
            minted = await self.sessions.mint(str(self.owner))
            self.tokens.append({"access": minted.access_token})
        path = self.state_dir / "tokens.json"
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump({"symbols": list(SYMBOLS), "origin": ORIGIN, "sessions": self.tokens}, fh)
        await self.cache.refresh_once()
        return path

    async def __aenter__(self) -> Backend:
        await self.prepare()
        self.cache.start()
        self.sock = socket.create_server(("127.0.0.1", 0))
        self.port = self.sock.getsockname()[1]
        self._task = spawn(self.server.serve(sockets=[self.sock]), name="bench-recorder-uvicorn")
        while not self.server.started:
            if self._task.done():
                self._task.result()
            await asyncio.sleep(0.01)
        return self

    async def wait(self) -> None:
        if self._task is not None:
            await self._task

    async def __aexit__(self, *exc: object) -> None:
        self.server.should_exit = True
        if self._task is not None:
            await asyncio.gather(self._task, return_exceptions=True)
        await self.cache.stop()
        if self.sock is not None:
            self.sock.close()


class _CoveragePrincipal:
    def has(self, permission: str) -> bool:
        return permission == Permission.MARKETDATA_READ.value


class _CoverageResolver:
    def __init__(self, backend: Backend) -> None:
        self._backend = backend

    async def resolve(self, request: Request) -> _CoveragePrincipal | None:
        return None if await self._backend.resolve(request) is None else _CoveragePrincipal()


async def serve(out: Path, sessions: int, seed: int) -> None:
    async with Backend(out, sessions, seed) as be:
        print(f"{READY} port={be.port} pid={os.getpid()} tokens={out / 'tokens.json'}", flush=True)
        await be.wait()


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--out", default="")
    ap.add_argument("--sessions", type=int, default=5, help="one per k6 WS subscriber")
    ap.add_argument("--seed", type=int, default=7)
    args = ap.parse_args(argv)
    out = Path(args.out) if args.out else Path(tempfile.mkdtemp(prefix="cv-bench-recorder-"))
    out.mkdir(parents=True, exist_ok=True)
    with contextlib.redirect_stdout(sys.stderr):  # stdout carries the ready line alone
        configure_logging(
            env=os.environ.get("CV_ENV", "dev"), level=os.environ.get("CV_LOG_LEVEL", "warning")
        )
    with egress_guard():
        asyncio.run(serve(out, args.sessions, args.seed))
    return 0


if __name__ == "__main__":
    sys.exit(main())

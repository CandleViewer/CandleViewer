"""E17-Q02 server side: the real `/ws` gateway on a real uvicorn server (127.0.0.1 only).

Wired like the E17-Q01 conformance `World` and served with the production uvicorn WS settings
(`server.uvicorn_kwargs`); grant changes enter through `ws_wiring.WsEvents`. Doubles: time (one
`VirtualClock` for the gateway's clocks and the session service), the session store (real
`SessionService` over `FakeSessionRepository`), the grant store the principal loader reads, the
snapshot source (a corpus-fed fake; adapters #2195 and #2197 not landed) and `POST /auth/refresh`
(REST refresh double).
The book is the recorded BTCUSDT corpus (C-13.5). Clients reach the server only via the proxy.

Served as production serves it: `PlannedShutdownServer`, so a stop (`should_exit`) runs the §9.4
planned shutdown, its grace slept on the virtual clock. `restart()` boots a second server
process behind the same proxies; the stores above survive it, as a database and the exchange do.

`flag_on()` is the same stack with E17-T03's `CV_WS_BACKPRESSURE_ENABLED` on: the router gets the
default `BackpressureConfig` (8 MiB / 2 000 frames), every socket it accepts has a fixed
`SEND_BUFFER`, and each of its lanes a fixed upstream receive buffer (`LANE_RCVBUF`), so a stopped
reader's backlog reaches that budget once well under 1 MB is in flight (the sockets', the
transport's and the proxy's buffers), not after the megabytes loopback autotuning holds. Its
transport keepalive is off (`_boot`): it runs on wall time. `trades_step` replays the recorded
tape.
"""

from __future__ import annotations

import asyncio
import itertools
import json
import socket
import uuid
from datetime import UTC, datetime
from typing import Any

import uvicorn
from fastapi import FastAPI

from candleviewer.auth.hashing import Hasher
from candleviewer.auth.models import MintedSession
from candleviewer.auth.scopes import AccountGrant, PrincipalSnapshot
from candleviewer.auth.session_service import SessionService, access_token_expires_at
from candleviewer.exchange.base.trade_print import TradePrint
from candleviewer.observability.context import spawn
from candleviewer.server import PlannedShutdownServer, uvicorn_kwargs
from candleviewer.settings import Settings
from candleviewer.ws.backpressure_config import BackpressureConfig
from candleviewer.ws.gateway import GatewayHub, make_ws_router
from candleviewer.ws.permissions import ConnectionRegistry, SubscriptionServices
from candleviewer.ws.revocation import RevocationHub
from candleviewer.ws.sequencing import SequencingHub, SnapshotBody, window_delta
from candleviewer.ws.upstream import UpstreamRefs
from candleviewer.ws_wiring import KillSwitchView, WsEvents, WsRuntime
from tests._corpus import frames, normalize
from tests.chaos.ingestion._clock import VirtualClock
from tests.chaos.ws._client import TIMEOUT_S, Client
from tests.chaos.ws._proxy import HOST, Proxy
from tests.contract.ws._support import ORIGIN, SAMPLES
from tests.unit.auth.session_fakes import FakeSessionRepository
from tests.unit.ws._seq_support import ACC_A, ACC_B, PERMS, Book, Source

SYM, DEPTH = "BTCUSDT", 50
BOOK = f"book.{SYM}.{DEPTH}"
SEED = 20261015  # the suite's fixed seed: same seed, same backoff schedule and fault trace
A, B = str(ACC_A), str(ACC_B)
Topic = dict[str, Any]
TRADES: Topic = {"ch": f"trades.{SYM}"}
ORDERS: Topic = {"ch": "orders", "opts": {"exchange_account_ids": [A]}}
POSITIONS: Topic = {"ch": "positions", "opts": {"exchange_account_ids": [A, B]}}
#: Three open workspaces: a full one, a chart and a blotter.
WORKSPACES: list[list[Topic]] = [
    [{"ch": BOOK}, TRADES, ORDERS, POSITIONS],
    [{"ch": BOOK}, TRADES],
    [ORDERS, {"ch": BOOK}],
]
# §9.4: the documented grace and expected downtime (the CV_WS_SHUTDOWN_* defaults)
GRACE_MS, DOWNTIME_MS = 5_000, 20_000
GRACE_S = GRACE_MS / 1000
#: The flag-on stack's `SO_SNDBUF` (the kernel doubles it), set on the listening socket, which
#: every accepted socket inherits; fixed, so autotuning cannot grow it (`flag_on`).
SEND_BUFFER = 32 * 1024
#: The `SO_RCVBUF` of a flag-on lane's upstream sockets (`Proxy.rcvbuf`), fixed for the same
#: reason. It has a floor: set after connect, as `Proxy` sets it, a receiver of 28 KiB or less
#: that stopped reading resumes only on the sender's next zero-window probe, 0.5 s to seconds
#: after `HEAL` (about 32 KiB on Linux 6.6; set before connect there is none), and kernels that
#: advertise about half the buffer as window need twice that. 128 KiB clears it.
LANE_RCVBUF = 128 * 1024
#: The two sizes as set (the kernel doubles them), for a failure message to name.
BUFFERS = f"lane SO_RCVBUF {LANE_RCVBUF} B, server SO_SNDBUF {SEND_BUFFER} B, as set"


async def _no_wait(_seconds: float) -> None:
    return None


class _Hub(GatewayHub):
    """The production hub, its §9.4 grace slept on the virtual clock: `shutdown(sleep=...)` is the
    seam, and `WsRuntime.stop()` does not forward it. A test advances the grace; `instant` skips
    it (teardown)."""

    def __init__(self, clock: VirtualClock) -> None:
        super().__init__()
        self.clock, self.instant = clock, False

    async def shutdown(self, **kw: Any) -> int:
        return await super().shutdown(**kw, sleep=_no_wait if self.instant else self.clock.sleep)


class Stack:
    def __init__(
        self,
        clock: VirtualClock,
        *accounts: uuid.UUID,
        backpressure: BackpressureConfig | None = None,
    ) -> None:
        self.clock = clock
        self.sessions = SessionService(FakeSessionRepository(), Hasher(), clock=self.now)
        self.granted = set(accounts)  # the grant store the principal loader reads
        self.read_held = asyncio.Event()
        self._release: asyncio.Event | None = None
        self.source = Source()
        self.source.bodies.update({f: SnapshotBody(s) for f, (s, _) in SAMPLES.items()})
        corpus = [json.loads(f)["data"] for f in frames("ws/orderbook_BTCUSDT.jsonl")]
        self.book = self.source.books[SYM] = Book(SYM)
        self.book.apply(corpus[0]["b"], corpus[0]["a"])
        self._deltas = iter(corpus[1:])
        tape = [p for f in frames("ws/clean_publicTrade_BTCUSDT.jsonl") for p in normalize(f)]
        self._tape = [p for p in tape if isinstance(p, TradePrint)]
        self._printed = itertools.count()
        self.backpressure = backpressure  # E17-T03's flag: on with a config (`flag_on`)
        self.clients: list[Client] = []
        self.lanes: list[Proxy] = []
        self._boot()
        self.proxy = Proxy(self.port)

    def _boot(self) -> None:
        """One server process: everything a restart loses (the stores in `__init__` survive it)."""
        self.hub = SequencingHub()
        services = SubscriptionServices(
            snapshots=self.source, sequencing=self.hub, clock=self.clock
        )
        self.registry = ConnectionRegistry(self.principal, self.wall_ms, services)
        self.gateway = _Hub(self.clock)
        self.events = WsEvents(self.registry, self.gateway, KillSwitchView())
        app = FastAPI()
        app.include_router(
            make_ws_router(
                authenticate=self._authenticate,
                registry=self.registry,
                revocation_hub=RevocationHub(),
                allowed_origins=frozenset({ORIGIN}),
                hub=self.gateway,
                clock=self.clock,
                wall_ms=self.wall_ms,
                tick_s=0.005,
                kill_switch=self.events.kill_switch.snapshot,  # `auth_ok.kill_switch`, as app.py
                backpressure=self.backpressure,
            )
        )
        app.add_api_route("/auth/refresh", self._refresh, methods=["POST"])
        cfg = Settings(ws_shutdown_grace_ms=GRACE_MS, ws_shutdown_expected_downtime_ms=DOWNTIME_MS)
        app.state.ws_runtime = WsRuntime(self.gateway, UpstreamRefs(), cfg)  # as `create_app`
        kw = uvicorn_kwargs(cfg)  # production WS limits; the socket below is the bind
        # A short drain: the harness's clients are closed by the test itself. Set on the dict, so it
        # holds whether or not `uvicorn_kwargs` carries its own drain bound (#2565 adds one).
        kw["timeout_graceful_shutdown"] = 2
        if self.backpressure is not None:
            # Two clocks: uvicorn's transport keepalive (`ws_ping_interval` 15 s, then
            # `ws_ping_timeout` 45 s and a 1011) is timed on the loop's wall clock, the scenarios on
            # the virtual one. A paused client meets it 60 real seconds in, whatever the virtual
            # time, so a slow run (coverage) would close it mid-scenario. Off for the flag-on stack
            # only; the §9.1 application heartbeat stays on, on the virtual clock (production keeps
            # both).
            kw["ws_ping_interval"] = None
        # Merged as a dict, so it holds whether or not `uvicorn_kwargs` already sets `log_config`.
        conf = uvicorn.Config(app, **{**kw, "lifespan": "off", "log_config": None})
        self.server = PlannedShutdownServer(conf)
        self._sock = socket.create_server((HOST, 0))
        if self.backpressure is not None:
            self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, SEND_BUFFER)
        self.port: int = self._sock.getsockname()[1]

    def client(self, minted: MintedSession, seed: int = SEED, via: Proxy | None = None) -> Client:
        port = (via or self.proxy).port
        urls = (f"ws://{HOST}:{port}/ws", f"http://{HOST}:{port}")
        tokens = (minted.access_token, minted.refresh_token)
        self.clients.append(Client(urls, self.clock, tokens, seed))
        return self.clients[-1]

    async def lane(self) -> Proxy:
        """A second path to the server: a fault on it hits only the clients dialled through it."""
        lane = Proxy(self.port, None if self.backpressure is None else LANE_RCVBUF)
        await lane.start()
        self.lanes.append(lane)
        return lane

    def now(self) -> datetime:
        return datetime.fromtimestamp(self.clock.wall_s(), UTC)

    def wall_ms(self) -> int:
        return int(self.clock.wall_s() * 1000)

    def hold_next_read(self) -> asyncio.Event:
        """Arm the loader double: its next load reads the grants, then parks until the returned
        event is set (a deterministic window between a principal read and its use)."""
        self._release = asyncio.Event()
        return self._release

    async def until_read_held(self) -> None:
        async with asyncio.timeout(TIMEOUT_S):
            await self.read_held.wait()

    async def principal(self, uid: uuid.UUID) -> PrincipalSnapshot:
        grants = tuple(AccountGrant(a, True, False, False) for a in sorted(self.granted))
        if self._release is not None:
            release, self._release = self._release, None
            self.read_held.set()
            await release.wait()
        return PrincipalSnapshot(uid, frozenset({"manager"}), PERMS, grants)

    async def _authenticate(self, token: str) -> tuple[str, uuid.UUID, datetime]:
        rec = await self.sessions.authenticate_access_token(token)
        return str(rec.id), rec.user_id, access_token_expires_at(rec)

    async def _refresh(self, body: dict[str, str]) -> dict[str, str]:
        minted = (await self.sessions.refresh(body["refresh_token"])).minted
        return {"access_token": minted.access_token, "refresh_token": minted.refresh_token}

    def book_step(self) -> int:
        """Apply the next recorded delta to the server book; publish its depth-window delta."""
        data = next(self._deltas)
        b0, a0 = self.book.top(DEPTH)
        self.book.apply(data["b"], data["a"])
        b1, a1 = self.book.top(DEPTH)
        self.source.gen += 1  # the shared snapshot cache must not serve the pre-delta book
        body = {"symbol": SYM, "bids": window_delta(b0, b1), "asks": window_delta(a0, a1)}
        return self.hub.publish(BOOK, body)

    def trades_step(self, n: int) -> int:
        """Publish the next `n` prints of the recorded BTCUSDT tape (production parser) as one
        §14.2 batch, stamped with the virtual time. The tape is replayed in rounds; a round
        suffixes the recorded id, so every print published is unique."""
        now, size, batch = self.wall_ms(), len(self._tape), list[dict[str, Any]]()
        for i in itertools.islice(self._printed, n):
            p = self._tape[i % size]
            item = {"id": f"{p.trade_id}.{i // size}", "ts_ms": now, "price": str(p.price)}
            batch.append(item | {"size": str(p.qty), "side": p.side})
        return self.hub.publish(TRADES["ch"], {"symbol": SYM, "trades": batch})

    def private(self, family: str, account: uuid.UUID) -> int:
        """One account-scoped event (a §15 sample body re-keyed to `account`)."""
        item = {**SAMPLES[family][1][family][0], "exchange_account_id": str(account)}
        return self.hub.publish(family, {family: [item]}, account=account)

    async def until_stopped(self) -> None:
        """The server process has exited (after `should_exit`: planned shutdown, then uvicorn's)."""
        async with asyncio.timeout(TIMEOUT_S):
            await self._task

    def restart(self) -> None:
        """A new server process, on a new port, behind the same proxies (re-pointed at it)."""
        assert self._task.done(), "restart() follows until_stopped()"
        self._boot()
        for proxy in (self.proxy, *self.lanes):
            proxy.upstream_port = self.port
        self._serve()

    def _serve(self) -> None:
        self._task = spawn(self.server.serve(sockets=[self._sock]), name="chaos-ws-uvicorn")

    async def until_no_connections(self) -> None:
        """Every gateway handler has finished (the server saw the drop and cleaned up)."""
        async with asyncio.timeout(TIMEOUT_S):
            await self.gateway.wait_empty()

    async def __aenter__(self) -> Stack:
        self._serve()
        await self.proxy.start()
        return self

    async def __aexit__(self, *exc: object) -> None:
        for proxy in (self.proxy, *self.lanes):
            await proxy.stop()  # first: a paused or held link must not stall a client's close
        for client in self.clients:
            await client.stop()
        self.gateway.instant = True  # teardown is not a scenario: no grace to wait out
        self.server.should_exit = True
        await self.clock.advance(GRACE_S)  # frees a grace a failed test left parked
        await self.until_stopped()


def flag_on() -> Stack:
    """A stack with E17-T03's flag on (module docstring), accounts A and B granted."""
    return Stack(VirtualClock(), ACC_A, ACC_B, backpressure=BackpressureConfig())

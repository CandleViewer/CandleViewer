"""E17-Q02 server side: the real `/ws` gateway on a real uvicorn server (127.0.0.1 only).

Wired like the E17-Q01 conformance `World` and served with the production uvicorn WS settings
(`server.uvicorn_kwargs`); grant changes enter through `ws_wiring.WsEvents`. Doubles: time (one
`VirtualClock` for the gateway's clocks and the session service), the session store (real
`SessionService` over `FakeSessionRepository`), the grant store the principal loader reads, the
snapshot source (adapters #2195-#2197 not landed) and `POST /auth/refresh` (REST refresh double).
The book is the recorded BTCUSDT corpus (C-13.5). Clients reach the server only via the proxy.
"""

from __future__ import annotations

import asyncio
import json
import socket
import uuid
from datetime import UTC, datetime

import uvicorn
from fastapi import FastAPI

from candleviewer.auth.hashing import Hasher
from candleviewer.auth.models import MintedSession
from candleviewer.auth.scopes import AccountGrant, PrincipalSnapshot
from candleviewer.auth.session_service import SessionService, access_token_expires_at
from candleviewer.observability.context import spawn
from candleviewer.server import uvicorn_kwargs
from candleviewer.settings import Settings
from candleviewer.ws.gateway import GatewayHub, make_ws_router
from candleviewer.ws.permissions import ConnectionRegistry, SubscriptionServices
from candleviewer.ws.revocation import RevocationHub
from candleviewer.ws.sequencing import SequencingHub, SnapshotBody, window_delta
from candleviewer.ws_wiring import KillSwitchView, WsEvents
from tests._corpus import frames
from tests.chaos.ingestion._clock import VirtualClock
from tests.chaos.ws._client import TIMEOUT_S, Client
from tests.chaos.ws._proxy import HOST, Proxy
from tests.contract.ws._support import ORIGIN, SAMPLES
from tests.unit.auth.session_fakes import FakeSessionRepository
from tests.unit.ws._seq_support import PERMS, Book, Source

SYM, DEPTH = "BTCUSDT", 50
BOOK = f"book.{SYM}.{DEPTH}"
SEED = 20261015  # the suite's fixed seed: same seed, same backoff schedule and fault trace


class Stack:
    def __init__(self, clock: VirtualClock, *accounts: uuid.UUID) -> None:
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
        self.hub = SequencingHub()
        services = SubscriptionServices(snapshots=self.source, sequencing=self.hub, clock=clock)
        self.registry = ConnectionRegistry(self.principal, self.wall_ms, services)
        self.gateway = GatewayHub()
        self.events = WsEvents(self.registry, self.gateway, KillSwitchView())
        app = FastAPI()
        app.include_router(
            make_ws_router(
                authenticate=self._authenticate,
                registry=self.registry,
                revocation_hub=RevocationHub(),
                allowed_origins=frozenset({ORIGIN}),
                hub=self.gateway,
                clock=clock,
                wall_ms=self.wall_ms,
                tick_s=0.005,
            )
        )
        app.add_api_route("/auth/refresh", self._refresh, methods=["POST"])
        kw = uvicorn_kwargs(Settings())  # production WS limits; the socket below is the bind
        # A short drain: the harness's clients are closed by the test itself. Set on the dict, so it
        # holds whether or not `uvicorn_kwargs` carries its own drain bound (#2565 adds one).
        kw["timeout_graceful_shutdown"] = 2
        cfg = uvicorn.Config(app, **kw, lifespan="off", log_config=None)
        self.server = uvicorn.Server(cfg)
        self._sock = socket.create_server((HOST, 0))
        self.proxy = Proxy(self._sock.getsockname()[1])
        self.url = self.http = ""
        self.clients: list[Client] = []

    def client(self, minted: MintedSession, seed: int = SEED) -> Client:
        tokens = (minted.access_token, minted.refresh_token)
        self.clients.append(Client((self.url, self.http), self.clock, tokens, seed))
        return self.clients[-1]

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

    def private(self, family: str, account: uuid.UUID) -> int:
        """One account-scoped event (a §15 sample body re-keyed to `account`)."""
        item = {**SAMPLES[family][1][family][0], "exchange_account_id": str(account)}
        return self.hub.publish(family, {family: [item]}, account=account)

    async def until_no_connections(self) -> None:
        """Every gateway handler has finished (the server saw the drop and cleaned up)."""
        async with asyncio.timeout(TIMEOUT_S):
            await self.gateway.wait_empty()

    async def __aenter__(self) -> Stack:
        self._task = spawn(self.server.serve(sockets=[self._sock]), name="chaos-ws-uvicorn")
        port = await self.proxy.start()
        self.url, self.http = f"ws://{HOST}:{port}/ws", f"http://{HOST}:{port}"
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.proxy.stop()  # first: a paused or held link must not stall a client's close
        for client in self.clients:
            await client.stop()
        self.server.should_exit = True
        async with asyncio.timeout(TIMEOUT_S):
            await self._task

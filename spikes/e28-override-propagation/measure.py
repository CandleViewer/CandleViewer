"""E28-K01 (#968): profile-change propagation latency. THROWAWAY spike prototype.

Not production code. Nothing in `services/api` imports it, no test lane collects it (the file is
not named `test_*` and lives outside every `testpaths`), and it is never promoted: the finding is
`docs/plan/spikes/E28-K01.md` and ADR-0040. Run it with the worktree's own backend venv:

    timeout 300 services/api/.venv/bin/python spikes/e28-override-propagation/measure.py \
        --transport system_notice

What is real and what is a stand-in (README.md has the topology):

- REAL: the in-process bus (`candleviewer.bus.Bus`, a `NEVER_DROP` pattern subscription on
  `demo.profiles.*.changed`), the `system` frame filter (`candleviewer.ws.system_filter.
  system_view`, the per-connection account cut of an `account_notice`), the REST route
  `GET /exchange-accounts/{accountId}/profiles` (`candleviewer.api.profiles.make_profiles_router`)
  over the real `ProfilesRepository` and `profile_document` projection, served by uvicorn on
  127.0.0.1, and a real loopback WebSocket.
- STAND-IN: the profile write (#906's `PUT`, not on `main`: a fake store bumps the version), the
  `ProfilesChanged` event (#906 slice D3a, not on `main`), the gateway (a minimal WebSocket
  endpoint, with a fixed Manager principal instead of the `hello`/`auth` handshake), and the
  preview (a stand-in route running a Decimal copy of 24 Sec.9.3's sizing for N legs; the real
  `POST /trade-groups/preview` is not on `main`).

Numbers are wall-clock on one machine; only what this script prints goes into the docs.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import dataclasses
import json
import math
import os
import platform
import socket
import sys
import threading
import time
import uuid
from datetime import UTC, datetime
from decimal import ROUND_DOWN, Decimal
from pathlib import Path
from typing import Any

import httpx
import uvicorn
import websockets
from candleviewer.accounts.errors import AccountNotFoundError
from candleviewer.accounts.models import ExchangeEnv
from candleviewer.accounts.profile_repository import ProfilesRepository
from candleviewer.accounts.profiles import AccountProfile, profile_values
from candleviewer.api.profiles import make_profiles_router
from candleviewer.auth.generated_permissions import Permission
from candleviewer.auth.scopes import AccountGrant, PrincipalSnapshot
from candleviewer.bus.bus import Bus
from candleviewer.bus.models import QueuePolicy, Topic
from candleviewer.storage.repositories.account_profiles import AccountProfileRow
from candleviewer.storage.repositories.accounts import GrantScope, OwnerScope
from candleviewer.ws.system_filter import system_view
from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
API = REPO / "services" / "api"

FIXTURE = API / "tests" / "fixtures" / "profiles" / "risk_based.json"
ACCT = uuid.UUID("7d3c9a10-28a1-4c1e-9e01-0000000000a1")  # the Manager's granted account
FOREIGN = uuid.UUID("7d3c9a10-28a1-4c1e-9e01-0000000000f1")  # an account outside its grants
PID = uuid.UUID("0b5f6d0e-28a1-4c1e-9e01-000000000001")
FOREIGN_PID = uuid.UUID("0b5f6d0e-28a1-4c1e-9e01-0000000000f1")
AT = datetime(2026, 10, 24, 9, tzinfo=UTC)
MANAGER = PrincipalSnapshot(
    uuid.UUID("00000000-0000-4000-8000-0000000000e1"),
    frozenset({"manager"}),
    frozenset({Permission.ACCOUNTS_READ}),
    (AccountGrant(ACCT, can_view=True, can_trade=True, frozen=False),),
)

#: transport -> (server window in ms before a frame leaves, client poll interval in ms)
TRANSPORTS: dict[str, tuple[int, int]] = {
    # (iii) as built: `push_system` queues an `account_notice` at once (no Pacer window)
    "system_notice": (0, 0),
    # (iii) worst case: the 1 000 ms default pacing window 23 Sec.6.2 lists for `system`
    "system_notice_1s_window": (1000, 0),
    # (i) a sub-event on `trade_groups` inside its 100 ms pacing window (23 Sec.6.2)
    "trade_groups_100ms": (100, 0),
    # (ii) with no push frame at all: the client re-fetches on a 1 s timer
    "rest_poll_1s": (0, 1000),
}

#: The coverage check only (`--check-table`): ADR-0040 owns the table; this copy proves no
#: `AccountProfile` field is left unclassified and none is classified that does not exist.
DECISION_TABLE: dict[str, str] = {
    **dict.fromkeys(
        (
            "profile_id",
            "account_id",
            "name",
            "is_default",
            "enabled",
            "trading_enabled",
            "version",
            "updated_at",
            "min_leg_notional",
            "qty_rounding",
            "margin_mode",
            "position_mode",
            "require_native_sl",
            "fallback_sl_offset_pct",
            "tp_ladder",
        ),
        "never",
    ),
    **dict.fromkeys(
        (
            "sizing_mode",
            "fixed_qty",
            "fixed_notional",
            "pct_equity",
            "risk_pct_equity",
            "risk_fixed_amount",
            "leverage",
            "sl_offset_value",
            "sl_offset_unit",
            "sl_atr_period",
            "sl_atr_multiple",
            "tp_offset_value",
            "tp_offset_unit",
            "max_position_notional",
            "max_position_pct_equity",
            "max_daily_loss",
            "max_daily_loss_pct",
            "max_open_positions",
            "max_concurrent_orders",
            "max_leverage_cap",
            "max_orders_per_minute",
            "all_symbols",
            "allowed_symbols",
            "denied_symbols",
            "reduce_only_default",
            "time_in_force_default",
            "slippage_tolerance_bps",
        ),
        "narrow_only",
    ),
}


# --------------------------------------------------------------------------- server side


@dataclasses.dataclass(frozen=True)
class ProfilesChangedStandIn:
    """#906's `ProfilesChanged` (rows and versions, never values) plus a local commit stamp."""

    env: str
    account_id: uuid.UUID
    rows: tuple[tuple[str, int], ...]
    binding_version: int | None
    committed_ns: int


def _row(
    raw: dict[str, Any], account: uuid.UUID, pid: uuid.UUID, version: int, cap: Decimal
) -> AccountProfileRow:
    p = AccountProfile.model_validate(
        {
            **raw,
            "account_id": account,
            "profile_id": pid,
            "version": version,
            "max_position_notional": str(cap),
        }
    )
    return AccountProfileRow(
        id=p.profile_id,
        exchange_account_id=account,
        version=version,
        values=profile_values(p),
        created_by=None,
        updated_by=None,
        created_at=AT,
        updated_at=AT,
        deleted_at=None,
    )


class FakeStore:
    """The profile and account reads, scoped as Postgres scopes them; `commit` is the stand-in
    for #906's write (a version bump that narrows `max_position_notional` by 1)."""

    def __init__(self) -> None:
        self.raw = json.loads(FIXTURE.read_text(encoding="utf-8"))
        self.version = {ACCT: 1, FOREIGN: 1}
        self.cap = {ACCT: Decimal(50000), FOREIGN: Decimal(50000)}
        self.rows = {a: (_row(self.raw, a, p, 1, self.cap[a]),) for a, p in self._pids()}

    @staticmethod
    def _pids() -> tuple[tuple[uuid.UUID, uuid.UUID], ...]:
        return ((ACCT, PID), (FOREIGN, FOREIGN_PID))

    @staticmethod
    def _shown(scope: Any, account_id: uuid.UUID) -> bool:
        if isinstance(scope, OwnerScope):
            return True
        return isinstance(scope, GrantScope) and account_id in scope.account_ids

    async def list_profiles(self, scope: Any, account_id: uuid.UUID) -> Any:
        return self.rows.get(account_id, ()) if self._shown(scope, account_id) else ()

    async def get_profile(self, scope: Any, account_id: uuid.UUID, profile_id: uuid.UUID) -> Any:
        rows = self.rows.get(account_id, ()) if self._shown(scope, account_id) else ()
        return next((r for r in rows if r.id == profile_id), None)

    async def get_account(self, scope: Any, account_id: uuid.UUID) -> Any:
        if not self._shown(scope, account_id) or account_id not in self.rows:
            raise AccountNotFoundError("account")
        return _DEMO_ACCOUNT

    def commit(self, account: uuid.UUID) -> tuple[int, int]:
        """The write's commit: returns (version, monotonic ns at commit)."""
        self.version[account] += 1
        self.cap[account] -= 1
        pid = PID if account == ACCT else FOREIGN_PID
        self.rows[account] = (
            _row(self.raw, account, pid, self.version[account], self.cap[account]),
        )
        return self.version[account], time.perf_counter_ns()


_DEMO_ACCOUNT = dataclasses.make_dataclass("Account", [("env", ExchangeEnv)])(ExchangeEnv.DEMO)


class _NoAudit:
    async def emit(self, action: str, **kwargs: Any) -> None:  # a refusal's record: not measured
        return None


class _Resolver:
    def resolve(self, request: Request) -> PrincipalSnapshot:
        return MANAGER  # stand-in for the session: no token, no cookie


INSTRUMENT = {
    "tick": Decimal("0.1"),
    "step": Decimal("0.001"),
    "min_qty": Decimal("0.001"),
    "max_qty": Decimal(100),
    "min_notional": Decimal(5),
}


def size_leg_stand_in(
    p: AccountProfile, equity: Decimal, entry: Decimal, side: str
) -> dict[str, str]:
    """A Decimal copy of 24 Sec.9.3 steps 1-8 for `ticks` stops (the preview's compute)."""
    if not (p.enabled and p.trading_enabled):
        return {"skip": "profile_disabled"}
    tick = INSTRUMENT["tick"]
    dist = p.sl_offset_value * tick
    stop = entry - dist if side == "buy" else entry + dist
    risk_amt = (
        p.risk_fixed_amount
        if p.risk_fixed_amount is not None
        else equity * (p.risk_pct_equity or Decimal(0))
    )
    match p.sizing_mode:
        case "fixed_qty":
            qty = p.fixed_qty or Decimal(0)
        case "fixed_notional":
            qty = (p.fixed_notional or Decimal(0)) / entry
        case "pct_equity":
            qty = equity * (p.pct_equity or Decimal(0)) * p.leverage / entry
        case _:
            qty = risk_amt / (dist + entry * Decimal("0.00055") * 2)
    lev = min(p.leverage, p.max_leverage_cap or p.leverage)
    if p.max_position_pct_equity is not None:
        qty = min(qty, equity * p.max_position_pct_equity * lev / entry)
    if p.max_position_notional is not None:
        qty = min(qty, p.max_position_notional / entry)
    qty = min(qty, INSTRUMENT["max_qty"], equity * lev * Decimal("0.98") / entry)
    qty = (qty / INSTRUMENT["step"]).to_integral_value(ROUND_DOWN) * INSTRUMENT["step"]
    if qty < INSTRUMENT["min_qty"] or qty * entry < max(
        INSTRUMENT["min_notional"], p.min_leg_notional
    ):
        return {"skip": "below_min_notional"}
    return {
        "qty": str(qty),
        "stop": str(stop),
        "notional": str(qty * entry),
        "risk_usd": str(qty * dist),
        "leverage": str(lev),
    }


@dataclasses.dataclass
class Conn:
    ws: WebSocket
    principal: PrincipalSnapshot
    transport: str
    window_ms: int
    queue: asyncio.Queue[str] = dataclasses.field(default_factory=lambda: asyncio.Queue(1024))
    seq: int = 0


class Backend:
    """The server half, run on its own thread and event loop."""

    def __init__(self, transport: str) -> None:
        self.transport = transport
        self.window_ms = TRANSPORTS[transport][0]
        self.store = FakeStore()
        self.repo = ProfilesRepository(self.store, cache=None)  # type: ignore[arg-type]
        self.bus = Bus()
        self.conns: list[Conn] = []
        self.loop: asyncio.AbstractEventLoop | None = None
        self.port = 0
        self.ready = threading.Event()
        self.server: uvicorn.Server | None = None
        self.epoch = time.monotonic()
        self.app = self._app()

    def _app(self) -> FastAPI:
        app = FastAPI()
        app.include_router(make_profiles_router(self.repo, self.store, _NoAudit(), _Resolver()))

        @app.post("/spike/preview")
        async def preview(request: Request) -> JSONResponse:
            body = await request.json()
            stored = await self.repo.read_profiles(
                GrantScope(MANAGER.user_id, frozenset({ACCT})), ACCT
            )
            profile = stored[0].profile
            entry, equity = Decimal(body["entry"]), Decimal(body["equity"])
            legs = [
                size_leg_stand_in(profile, equity + i, entry, "buy") for i in range(body["legs"])
            ]
            return JSONResponse({"version": profile.version, "legs": legs})

        @app.websocket("/ws")
        async def ws(socket: WebSocket) -> None:
            await socket.accept()
            conn = Conn(socket, MANAGER, self.transport, self.window_ms)
            self.conns.append(conn)
            writer = asyncio.create_task(self._writer(conn))
            try:
                while True:
                    await socket.receive_text()
            except WebSocketDisconnect:
                pass
            finally:
                writer.cancel()
                self.conns.remove(conn)

        return app

    async def _writer(self, conn: Conn) -> None:
        if not conn.window_ms:
            while True:
                await conn.ws.send_text(await conn.queue.get())
        w = conn.window_ms / 1000
        while True:  # windows aligned to the server's epoch, as a pacer's are to its clock
            await asyncio.sleep(w - ((time.monotonic() - self.epoch) % w))
            while not conn.queue.empty():
                await conn.ws.send_text(conn.queue.get_nowait())

    def _frame(self, conn: Conn, ev: ProfilesChangedStandIn) -> dict[str, Any] | None:
        if conn.transport.startswith("system_notice"):
            body = {
                "kind": "account_notice",
                "severity": "info",
                "reason": "profiles.changed",
                "message": "An account profile changed.",
                "exchange_account_ids": [str(ev.account_id)],
            }
            view = system_view(body, conn.principal)  # the real per-connection cut
            if view is None:
                return None
            conn.seq += 1
            return {
                "t": "d",
                "ch": "system",
                "s": conn.seq,
                "ts": int(time.time() * 1000),
                "e": "j",
                "p": dict(view),
            }
        if conn.transport == "trade_groups_100ms":
            granted = {g.exchange_account_id for g in conn.principal.account_grants}
            if ev.account_id not in granted:  # stand-in for the topic's granted-account scope
                return None
            conn.seq += 1
            sub_event = {
                "exchange_account_id": str(ev.account_id),
                "profiles": [{"id": i, "version": v} for i, v in ev.rows],
            }
            return {
                "t": "d",
                "ch": "trade_groups",
                "s": conn.seq,
                "ts": int(time.time() * 1000),
                "e": "j",
                "p": {"trade_groups": [], "profiles_changed": [sub_event]},
            }
        return None  # rest_poll_1s: no frame

    async def _bridge(self) -> None:
        sub = self.bus.subscribe(
            "e28k01-bridge", "demo.profiles.*.changed", QueuePolicy.NEVER_DROP, maxsize=1024
        )
        while True:
            ev = await sub.get()
            for conn in list(self.conns):
                frame = self._frame(conn, ev)
                if frame is not None:
                    conn.queue.put_nowait(json.dumps(frame, separators=(",", ":")))

    async def commit(self, account: uuid.UUID) -> tuple[int, int]:
        """The stand-in write, then #906's publish; returns (version, commit ns)."""
        version, committed = self.store.commit(account)
        pid = PID if account == ACCT else FOREIGN_PID
        ev = ProfilesChangedStandIn("demo", account, ((str(pid), version),), None, committed)
        topic = Topic(env="demo", domain="profiles", symbol=str(account), detail="changed")
        await self.bus.publish(topic, ev)
        return version, committed

    def run(self) -> None:
        asyncio.run(self._main())

    async def _main(self) -> None:
        self.loop = asyncio.get_running_loop()
        bridge = asyncio.create_task(self._bridge())
        config = uvicorn.Config(
            self.app,
            host="127.0.0.1",
            port=0,
            log_level="warning",
            lifespan="off",
            access_log=False,
        )
        self.server = uvicorn.Server(config)
        # IPPROTO_TCP named, so asyncio sets TCP_NODELAY on each accepted socket as uvicorn's own
        # listener gets (with proto 0 it does not, and Nagle adds ~40 ms to a split response)
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP)
        sock.bind(("127.0.0.1", 0))  # loopback only, an ephemeral port
        sock.listen(64)  # connections wait in the backlog until uvicorn accepts them
        self.port = sock.getsockname()[1]
        serving = asyncio.create_task(self.server.serve(sockets=[sock]))
        self.ready.set()
        await serving
        bridge.cancel()

    def stop(self) -> None:
        if self.loop is not None and self.server is not None:
            self.loop.call_soon_threadsafe(setattr, self.server, "should_exit", True)


# --------------------------------------------------------------------------- client side


@dataclasses.dataclass
class Sample:
    total_ms: float
    trigger_ms: float  # commit -> the client knows (frame received, or the poll's answer sent)
    fetch_ms: float  # the REST re-fetch round trip (for a poll: the poll that saw the change)
    preview_ms: float  # the stand-in preview round trip and recompute


class Client:
    def __init__(self, backend: Backend, transport: str, legs: int) -> None:
        self.backend, self.transport, self.legs = backend, transport, legs
        self.poll_ms = TRANSPORTS[transport][1]
        self.held = 1
        self.done: dict[int, asyncio.Future[Sample]] = {}
        self.committed: dict[int, int] = {}
        self.frames_for: dict[str, int] = {}
        self.http: httpx.AsyncClient | None = None

    async def refresh(self, t_trigger: int) -> None:
        if self.http is None:
            raise RuntimeError("no HTTP client")
        t_fetch0 = time.perf_counter_ns()
        resp = await self.http.get(f"/exchange-accounts/{ACCT}/profiles")
        resp.raise_for_status()
        item = next(i for i in resp.json()["items"] if i["profile"]["is_default"])
        t_fetch1 = time.perf_counter_ns()
        version = int(item["version"])
        if version <= self.held:
            return
        self.held = version
        pr = await self.http.post(
            "/spike/preview", json={"entry": "64010.0", "equity": "10000", "legs": self.legs}
        )
        pr.raise_for_status()
        t_render = time.perf_counter_ns()
        fut = self.done.get(version)
        committed = self.committed.get(version)
        if fut is None or committed is None or fut.done():
            return
        ms = 1e-6
        fut.set_result(
            Sample(
                round((t_render - committed) * ms, 3),
                round((t_trigger - committed) * ms, 3),
                round((t_fetch1 - t_fetch0) * ms, 3),
                round((t_render - t_fetch1) * ms, 3),
            )
        )

    async def receive(self, ws: Any) -> None:
        async for raw in ws:
            t = time.perf_counter_ns()
            frame = json.loads(raw)
            p = frame.get("p", {})
            ids = p.get("exchange_account_ids") or [
                e["exchange_account_id"] for e in p.get("profiles_changed", [])
            ]
            for acct in ids:
                self.frames_for[acct] = self.frames_for.get(acct, 0) + 1
            if str(ACCT) in ids:
                await self.refresh(t)

    async def poll(self) -> None:
        w = self.poll_ms / 1000
        epoch = time.monotonic()
        while True:
            await asyncio.sleep(w - ((time.monotonic() - epoch) % w))
            await self.refresh(time.perf_counter_ns())

    async def commit(self, account: uuid.UUID) -> tuple[int, int]:
        if self.backend.loop is None:
            raise RuntimeError("the server loop is not running")
        fut = asyncio.run_coroutine_threadsafe(self.backend.commit(account), self.backend.loop)
        return await asyncio.wrap_future(fut)

    async def run(self, iterations: int, seed: int) -> dict[str, Any]:
        base = f"127.0.0.1:{self.backend.port}"
        loop = asyncio.get_running_loop()
        phase_max = max(TRANSPORTS[self.transport]) / 1000 or 0.02
        samples: list[Sample] = []
        async with (
            httpx.AsyncClient(base_url=f"http://{base}") as http,
            websockets.connect(f"ws://{base}/ws") as ws,
        ):
            self.http = http
            receiver = asyncio.create_task(self.receive(ws))
            poller = asyncio.create_task(self.poll()) if self.poll_ms else None
            for i in range(iterations):
                await asyncio.sleep(phase(seed, i) * phase_max)  # a fixed phase vs the windows
                nxt = self.held + 1
                self.done[nxt] = loop.create_future()
                version, committed = await self.commit(ACCT)
                if version != nxt:
                    raise RuntimeError(f"version {version}, expected {nxt}")
                self.committed[version] = committed
                samples.append(await asyncio.wait_for(self.done[version], timeout=10))
            # scope check: a change on an account outside the Manager's grants reaches no frame
            before = self.frames_for.get(str(FOREIGN), 0)
            await self.commit(FOREIGN)
            await asyncio.sleep(max(phase_max, 0.2) + 0.3)
            foreign_frames = self.frames_for.get(str(FOREIGN), 0) - before
            foreign_get = (await http.get(f"/exchange-accounts/{FOREIGN}/profiles")).status_code
            receiver.cancel()
            if poller is not None:
                poller.cancel()
        return {
            "samples": {  # one array per part, in iteration order (columnar: compact on disk)
                k: [getattr(s, k) for s in samples]
                for k in ("total_ms", "trigger_ms", "fetch_ms", "preview_ms")
            },
            "summary": {
                k: stats([getattr(s, k) for s in samples])
                for k in ("total_ms", "trigger_ms", "fetch_ms", "preview_ms")
            },
            "scope_check": {
                "frames_for_foreign_account_change": foreign_frames,
                "foreign_account_get_status": foreign_get,
            },
        }


async def preview_only(backend: Backend, iterations: int, legs: int) -> dict[str, Any]:
    out: list[float] = []
    async with httpx.AsyncClient(base_url=f"http://127.0.0.1:{backend.port}") as http:
        for _ in range(iterations):
            t0 = time.perf_counter_ns()
            r = await http.post(
                "/spike/preview", json={"entry": "64010.0", "equity": "10000", "legs": legs}
            )
            r.raise_for_status()
            out.append(round((time.perf_counter_ns() - t0) * 1e-6, 3))
    return {"samples_ms": out, "summary": stats(out)}


def phase(seed: int, i: int) -> float:
    """A deterministic, evenly spread phase in [0, 1) (a golden-ratio sequence from `seed`)."""
    return ((seed + i) * 0.6180339887498949) % 1.0


def stats(xs: list[float]) -> dict[str, float | int]:
    s = sorted(xs)

    def rank(p: float) -> float:  # nearest-rank percentile
        return s[max(0, math.ceil(p / 100 * len(s)) - 1)]

    return {
        "n": len(s),
        "p50": rank(50),
        "p95": rank(95),
        "p99": rank(99),
        "max": s[-1],
        "min": s[0],
        "mean": round(sum(s) / len(s), 3),
    }


def environment() -> dict[str, Any]:
    return {
        "python": platform.python_version(),
        "system": platform.system(),
        "release": platform.release(),
        "machine": platform.machine(),
        "cpu_count": os.cpu_count(),
        "uvicorn": uvicorn.__version__,
        "websockets": websockets.__version__,
        "httpx": httpx.__version__,
        "measured_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "topology": "one process, two threads (server loop, client loop), loopback TCP "
        "127.0.0.1, uvicorn HTTP + WebSocket; no Postgres, no Tailscale",
    }


def check_table() -> dict[str, Any]:
    fields = set(AccountProfile.model_fields)
    table = set(DECISION_TABLE)
    return {
        "profile_fields": len(fields),
        "classified": len(table),
        "unclassified": sorted(fields - table),
        "unknown": sorted(table - fields),
        "never": sum(v == "never" for v in DECISION_TABLE.values()),
        "narrow_only": sum(v == "narrow_only" for v in DECISION_TABLE.values()),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--transport", choices=[*TRANSPORTS, "preview_only"], required=True)
    ap.add_argument("--iterations", type=int, default=200)
    ap.add_argument("--legs", type=int, default=5)
    ap.add_argument("--seed", type=int, default=968)
    ap.add_argument("--out", type=Path, default=HERE / "results.json")
    args = ap.parse_args()

    backend = Backend("system_notice" if args.transport == "preview_only" else args.transport)
    server = threading.Thread(target=backend.run, name="e28k01-server", daemon=True)
    server.start()
    if not backend.ready.wait(10):
        print("server did not start", file=sys.stderr)
        return 2
    try:
        if args.transport == "preview_only":
            result = {
                f"legs_{n}": asyncio.run(preview_only(backend, args.iterations, n)) for n in (5, 20)
            }
        else:
            result = asyncio.run(
                Client(backend, args.transport, args.legs).run(args.iterations, args.seed)
            )
    finally:
        backend.stop()
        server.join(5)
    record = {
        "config": {
            "transport": args.transport,
            "iterations": args.iterations,
            "legs": args.legs,
            "seed": args.seed,
            "window_ms_poll_ms": TRANSPORTS.get(args.transport),
        },
        "environment": environment(),
        "decision_table_check": check_table(),
        **result,
    }
    existing: dict[str, Any] = {}
    with contextlib.suppress(FileNotFoundError, json.JSONDecodeError):
        existing = json.loads(args.out.read_text(encoding="utf-8"))
    existing[args.transport] = record
    args.out.write_text(json.dumps(existing, indent=1) + "\n", encoding="utf-8")
    summary = {k: v for k, v in record.items() if k not in {"samples"}}
    if "samples" not in record:
        summary = {
            k: (v["summary"] if isinstance(v, dict) and "summary" in v else v)
            for k, v in record.items()
        }
    print(json.dumps(summary, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())

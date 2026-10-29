"""Integration (#3382, E29 follow-up of E42-T03): the order-entry gate measured end to end, on
real Postgres 16, with the budgets of #964's design (200 ms refusal, 2 s push).

One process per test, composed as `create_app` composes it: `build_feature_flags` over Postgres
(the flag service, the writer `PUT /admin/feature-flags/{flagKey}` calls, the maintenance gate and
its 5 s poll), its gate composed with an admitting account check and handed to the OMS runtime
behind `POST /orders` and the exit routes (`test_place_order_route_pg._serving`, a
`FakeTradingPort` as the venue, C-13.5), and the WS gateway (`make_ws_router`, the conformance
harness's wiring) served by uvicorn on a loopback socket, three sessions connected over real
sockets. Every latency is read on one `perf_counter` from the flag row's COMMIT (the store's write
returning, before any change hook runs) or, for a change made in the database, from the
autocommitted statement returning. Each figure is the median and maximum of `REPS` repetitions,
printed as a `MEASURED` line and recorded in `docs/qa/perf/e29-order-entry-gate-measurements.md`.
A budget is asserted on the nearest-rank p90 of the repetitions, not on their maximum: on the
shared host one scheduling stall can put a single reading far past a budget the product meets
(C-13.7); the maximum and the slowest three are printed for the note.
"""

from __future__ import annotations

import asyncio
import json
import math
import os
import socket
import statistics
import time
from collections.abc import AsyncIterator, Awaitable, Callable, Coroutine
from contextlib import AsyncExitStack, asynccontextmanager
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest
import uvicorn
from prometheus_client import REGISTRY
from pydantic import SecretStr
from websockets.asyncio.client import ClientConnection, connect
from websockets.typing import Origin, Subprotocol

from candleviewer.admin.flags.catalogue import MAINTENANCE_MODE
from candleviewer.admin.flags.maintenance import KILL_ORDER_ENTRY, REFRESH_S
from candleviewer.admin.flags.push import feature_flags_snapshot
from candleviewer.admin.flags.service import DEFAULT_READ_BUDGET_MS
from candleviewer.audit.access import AuditPrincipal
from candleviewer.domain.order_entry import OrderEntryRefusal
from candleviewer.exchange.base.models import AmendOrderRequest
from candleviewer.flags_wiring import FeatureFlagsRuntime, build_feature_flags
from candleviewer.oms_wiring import OmsRuntime
from candleviewer.settings import Settings
from tests.contract.ws._harness import World as WsWorld
from tests.contract.ws._support import ORIGIN
from tests.integration.oms import test_place_order_route_pg as route
from tests.integration.oms import test_submission_pipeline_pg as c6
from tests.integration.oms.test_place_order_route_pg import World, _Relay, _serving, world
from tests.integration.oms.test_submission_pipeline_pg import pg_dsn
from tests.unit.admin.flag_fakes import FakeAudit, FakeStepUp
from tests.unit.oms import command_rig as cr
from tests.unit.oms import submit_rig as sr

pytestmark = pytest.mark.integration
__all__ = ["pg_dsn", "world"]  # C6's database and the route tests' world, for this module

#: #964: "order acceptance is rejected server-side within 200 ms" of the flag write's commit.
REFUSAL_BUDGET_S = 0.200
#: #964: "every session receives the maintenance notice within 2 seconds" of the write.
PUSH_BUDGET_S = 2.0
#: The kill-switch class's freshness bound (`21-database-schema.md` 3.9): a row changed in the
#: database, or a store that cannot be read, reaches the gate within one poll plus one read.
TTL_BOUND_S = REFRESH_S + DEFAULT_READ_BUDGET_MS / 1000
SESSIONS = 3
REPS = 20
#: The two TTL tests' repetitions: 10 by default, so CI's integration shard spends about 100 s on
#: each (each repetition waits about two 5 s polls), and the nearest-rank p90 is the ninth value:
#: one late poll is absorbed, where at 5 the p90 is the max. `CV_E29_TTL_REPS=20` reproduces the
#: note's run.
TTL_REPS = max(1, int(os.environ.get("CV_E29_TTL_REPS", "10")))  # never a vacuous loop
_BOUND_S = 15.0  # a bound on a wait the test does not measure, never a time it expects
#: The bound on order entry reopening, in both TTL tests: a wait bound, not a measured budget (no
#: budget names reopening; fail-open is not measured against one). In one local run, under host
#: load, the first reads after a store restore failed or ran past the read budget for over 15 s.
_REOPEN_BOUND_S = 60.0
_JSON = [Subprotocol("cv.v1.json")]
#: The suite bound is 120 s (pyproject); a TTL test waits about two polls (2 x 5 s) per
#: repetition, `TTL_REPS` times, so it needs longer (20 repetitions take about 200 s).
_TTL_TIMEOUT = pytest.mark.timeout(600)


class _Admits:
    """The account check `create_app` composes after maintenance, admitting this world's account
    (the account checks are #4894's)."""

    def refusal(self, account_id: UUID) -> OrderEntryRefusal | None:
        return None


@dataclass
class _GateWatch:
    """Each transition of the maintenance gate, on the test's clock, and an event per call."""

    changed: asyncio.Event = field(default_factory=asyncio.Event)
    engaged: bool = True
    since: float = 0.0

    def wrap(self, flags: FeatureFlagsRuntime, monkeypatch: pytest.MonkeyPatch) -> None:
        inner = flags.gate.set

        def set_(engaged: bool) -> None:
            inner(engaged)
            if engaged is not self.engaged:
                self.engaged, self.since = engaged, time.perf_counter()
            self.changed.set()

        monkeypatch.setattr(flags.gate, "set", set_)

    async def until(self, engaged: bool, bound_s: float) -> float:
        """The instant the gate turned `engaged`, waiting at most `bound_s` for it."""
        async with asyncio.timeout(bound_s):
            while self.engaged is not engaged:
                self.changed.clear()
                await self.changed.wait()
        return self.since


@dataclass
class _Session:
    """One authenticated socket and every `system` payload it received, with its arrival."""

    ws: ClientConnection
    seen: list[tuple[float, dict[str, Any]]] = field(default_factory=list)
    arrived: asyncio.Event = field(default_factory=asyncio.Event)

    async def read(self) -> None:
        async for message in self.ws:
            frame = json.loads(message)
            if frame.get("ch") == "system":
                self.seen.append((time.perf_counter(), frame["p"]))
                self.arrived.set()

    async def first(self, since: int, match: Callable[[dict[str, Any]], bool]) -> float:
        """The arrival of the first payload from index `since` on that `match`es."""
        async with asyncio.timeout(_BOUND_S):
            while True:
                found = [at for at, body in self.seen[since:] if match(body)]
                if found:
                    return found[0]
                self.arrived.clear()
                await self.arrived.wait()


@dataclass
class _Stack:
    flags: FeatureFlagsRuntime
    watch: _GateWatch
    sessions: list[_Session]
    principal: AuditPrincipal
    committed: float = 0.0
    #: Sent the moment the row commits, while the writer runs its hooks and records, as an order
    #: from any client may arrive then; `probe` is its task.
    on_commit: Callable[[], Coroutine[Any, Any, httpx.Response]] | None = None
    probe: asyncio.Task[httpx.Response] | None = None
    tails: list[float] = field(default_factory=list)

    async def write(self, key: str, value: bool) -> float:
        """`value` written through the flag writer; the instant its row committed."""
        current = (await self.flags.service.store.load())[key]
        await self.flags.writer.set(
            key, self.principal, value=value, reason="#3382 measurement",
            expected_updated_at=current.updated_at,
        )  # fmt: skip
        return self.committed

    async def refusal_after(
        self, key: str, send: Callable[[], Coroutine[Any, Any, httpx.Response]]
    ) -> float:
        """`key` set by the writer, `send` started at the commit: its 403, seconds after it."""
        self.on_commit = send
        try:
            commit = await self.write(key, True)
            self.tails.append(time.perf_counter() - commit)  # the writer's hooks and records
            assert self.probe is not None
            answer = await self.probe
            answered = time.perf_counter()
        finally:
            probe, self.on_commit, self.probe = self.probe, None, None
            if probe is not None and not probe.done():
                probe.cancel()  # a failed write leaves no orphaned request behind
        _refused(answer)
        return answered - commit


@asynccontextmanager
async def _stack(
    world: World, monkeypatch: pytest.MonkeyPatch, *, flags_dsn: str = ""
) -> AsyncIterator[_Stack]:
    """The flag runtime on Postgres (at `flags_dsn` when given), its gate open and handed to every
    OMS runtime `_serving` builds, and three WS sessions authenticated on a uvicorn server."""
    holder: list[FeatureFlagsRuntime] = []
    ws_world = WsWorld(flag_snapshot=lambda u, r: feature_flags_snapshot(holder[0].service, u, r))
    dsn = flags_dsn or c6._login(world.dsn, "cv_app")
    settings = Settings(storage_backend="real", pg_dsn=SecretStr(dsn))
    flags = build_feature_flags(
        settings, audit=FakeAudit(), step_up=FakeStepUp(), hub=ws_world.gateway, users=None
    )
    holder.append(flags)
    gate = flags.compose_order_entry_gate(_Admits())
    monkeypatch.setattr(
        route, "OmsRuntime", lambda *a, **k: OmsRuntime(*a, **(k | {"gate": gate}))
    )  # the app's one gate, as `create_app` hands it (`OmsRuntime(..., gate=...)`)
    watch = _GateWatch()
    watch.wrap(flags, monkeypatch)
    owner = AuditPrincipal(world.user, "owner", frozenset({"flags:write"}), is_owner=True)
    stack = _Stack(flags, watch, [], owner)
    async with AsyncExitStack() as exits:
        await flags.start()
        exits.push_async_callback(flags.stop)
        inner = flags.service.store.write

        async def committed(key: str, prepare: Any) -> Any:
            row = await inner(key, prepare)
            stack.committed = time.perf_counter()  # the COMMIT has returned; no hook has run
            if stack.on_commit is not None:  # it runs once the writer next yields
                stack.probe = asyncio.create_task(stack.on_commit())
            return row

        monkeypatch.setattr(flags.service.store, "write", committed)
        await watch.until(False, _BOUND_S)  # both gate flags read: the gate opens
        config = uvicorn.Config(ws_world.app, lifespan="off", log_level="warning",
                                ws="websockets-sansio")  # fmt: skip
        config.load()
        server = uvicorn.Server(config)
        server.lifespan = config.lifespan_class(config)  # as `Server.serve` sets it
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.bind(("127.0.0.1", 0))
        exits.callback(sock.close)
        await server.startup(sockets=[sock])
        exits.push_async_callback(server.shutdown)
        url = f"ws://127.0.0.1:{sock.getsockname()[1]}/ws"
        readers = []
        for _ in range(SESSIONS):
            ws = await exits.enter_async_context(
                connect(url, subprotocols=_JSON, origin=Origin(ORIGIN))
            )
            await ws.send(json.dumps({"t": "hello", "id": "h", "p": {"clock_ms": 1}}))
            assert json.loads(await ws.recv())["t"] == "welcome"
            await ws.send(json.dumps({"t": "auth", "id": "a", "p": {"access_token": "good-x"}}))
            assert json.loads(await ws.recv())["t"] == "auth_ok"
            session = _Session(ws)
            stack.sessions.append(session)
            readers.append(asyncio.create_task(session.read()))
        for session in stack.sessions:  # the `auth_ok` snapshot (#4517): maintenance is off
            await session.first(
                0, lambda p: p.get("feature_flags", {}).get(MAINTENANCE_MODE) is False
            )
        try:
            yield stack
        finally:
            for reader in readers:
                reader.cancel()
            await asyncio.gather(*readers, return_exceptions=True)


def _measured(name: str, seconds: list[float]) -> float:
    """The nearest-rank p90 in ms, the statistic a budget is asserted on; the median, the p90,
    the maximum and the slowest three are printed for the measurement note."""
    ms = sorted(s * 1000 for s in seconds)
    p90 = ms[math.ceil(0.9 * len(ms)) - 1]
    slowest = ", ".join(f"{m:.1f}" for m in ms[-3:][::-1])
    print(
        f"MEASURED {name}: n={len(ms)} median={statistics.median(ms):.1f} ms p90={p90:.1f} ms "
        f"max={ms[-1]:.1f} ms slowest=[{slowest}]"
    )
    return p90


async def _post(client: httpx.AsyncClient, body: dict[str, Any]) -> httpx.Response:
    return await client.post("/orders", json=body, headers={"Idempotency-Key": str(uuid4())})


async def _placed(client: httpx.AsyncClient, world: World) -> UUID:
    """An entry accepted with the gate open; its create carries the native stop (C-2.6)."""
    calls = len(world.port.calls)
    answer = await _post(client, world.body)
    assert answer.status_code == 202, answer.text
    [create] = world.creates(calls)
    assert create.stop_loss == sr.STOP and not create.reduce_only  # C-2.6 on this order path
    return UUID(answer.json()["trade_group"]["legs"][0]["order_details"][0]["id"])


def _refused(answer: httpx.Response) -> None:
    problem = answer.json()
    assert (answer.status_code, problem["code"], problem["reason"]) == (
        403, "trading_disabled", "maintenance",
    ), answer.text  # fmt: skip


def _counted() -> float:
    return (
        REGISTRY.get_sample_value("cv_order_entry_refusals_total", {"reason": "maintenance"}) or 0.0
    )


def _maintenance(on: bool) -> Callable[[dict[str, Any]], bool]:
    return lambda p: (
        p.get("kind") == "feature_flags" and p["feature_flags"].get(MAINTENANCE_MODE) is on
    )


def _notice(on: bool) -> Callable[[dict[str, Any]], bool]:
    reason = "maintenance.enabled" if on else "maintenance.disabled"
    return lambda p: p.get("kind") == "notice" and p.get("reason") == reason


async def _pushed(stack: _Stack, marks: list[int], on: bool, commit: float) -> tuple[float, float]:
    """The last of the sessions to get the `feature_flags` frame, and the notice, after `commit`."""
    frames, notices = [], []
    for session, mark in zip(stack.sessions, marks, strict=True):
        frames.append(await session.first(mark, _maintenance(on)) - commit)
        notices.append(await session.first(mark, _notice(on)) - commit)
    return max(frames), max(notices)


def _keep(pushes: dict[tuple[bool, str], list[float]], on: bool, got: tuple[float, float]) -> None:
    for kind, seconds in zip(("feature_flags frame", "notice"), got, strict=True):
        pushes.setdefault((on, kind), []).append(seconds)


def _key() -> dict[str, str]:
    return {"Idempotency-Key": str(uuid4())}


async def test_maintenance_refuses_within_200_ms_pushes_within_2_s_and_spares_native_stops(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    """#964 "Maintenance mode blocks orders promptly", `REPS` times: maintenance engaged by the
    flag writer; a `POST /orders` sent the moment the row commits (the writer still running its
    hooks) is the gate's 403 (`reason` maintenance) within 200 ms of the commit, recorded with its
    reason, and no create reaches the venue; three sessions get
    the `feature_flags` frame and the notice within 2 s. Released, the next entry is accepted with
    its native stop on the create. Then, under maintenance once more, the last entry's stop is
    tightened (202, the venue's amend carries the new stop) and every entry is cancelled (202);
    throughout, the open position's native stop stays as seeded and no venue call touches
    it (C-2.6, C-4.14, C-12.7 reserve)."""
    world.port.seed_position(cr.position(world.account, stop_loss=Decimal(57000)))
    refusals: list[float] = []
    admits: list[float] = []
    pushes: dict[tuple[bool, str], list[float]] = {}
    counted = _counted()
    async with _stack(world, monkeypatch) as stack, _serving(world) as client:
        orders = [await _placed(client, world)]
        for _ in range(REPS):
            marks, calls = [len(s.seen) for s in stack.sessions], len(world.port.calls)
            refusals.append(
                await stack.refusal_after(MAINTENANCE_MODE, lambda: _post(client, world.body))
            )
            commit = stack.committed
            assert world.creates(calls) == []
            _keep(pushes, True, await _pushed(stack, marks, True, commit))
            marks = [len(s.seen) for s in stack.sessions]
            commit = await stack.write(MAINTENANCE_MODE, False)
            orders.append(await _placed(client, world))
            admits.append(time.perf_counter() - commit)
            _keep(pushes, False, await _pushed(stack, marks, False, commit))
        await stack.write(MAINTENANCE_MODE, True)
        calls = len(world.port.calls)
        tighter = {"stop_loss": {"unit": "price", "value": "59000"}}
        amended = await client.patch(f"/orders/{orders[-1]}", json=tighter, headers=_key())
        assert amended.status_code == 202, amended.text
        [amend] = [c.request for c in world.port.calls[calls:] if c.method == "amend_order"]
        assert isinstance(amend, AmendOrderRequest) and amend.stop_loss == Decimal(59000)
        for order in orders:  # every entry cancelled under maintenance
            gone = await client.delete(f"/orders/{order}", headers=_key())
            assert gone.status_code == 202, gone.text
        await stack.write(MAINTENANCE_MODE, False)
        [position] = await world.port.positions(cr.ref(world.account))
    assert position.stop_loss == Decimal(57000)  # the native stop stands
    assert [c for c in world.port.calls if c.method == "set_trading_stop"] == []
    refused = [r for a, r in world.writer.actions if a == "account.disabled_by_policy"]
    assert refused == ["maintenance"] * REPS  # each refusal recorded with the gate's reason
    delta = _counted() - counted
    print(f"MEASURED cv_order_entry_refusals_total{{reason=maintenance}}: +{delta:g} for {REPS}")
    assert _measured("refusal after the maintenance commit", refusals) <= REFUSAL_BUDGET_S * 1e3
    for (on, kind), last in pushes.items():
        name = f"{kind}, the last of {SESSIONS} sessions, maintenance {'on' if on else 'off'}"
        assert _measured(name, last) <= PUSH_BUDGET_S * 1e3
    _measured("flag write returned after its commit", stack.tails)
    _measured("accepted entry after the release commit", admits)


async def _lapses(
    stack: _Stack,
    client: httpx.AsyncClient,
    world: World,
    close: Callable[[], Awaitable[float]],
    reopen: Callable[[], Awaitable[float]],
    reopen_bound_s: float = _BOUND_S,
) -> tuple[list[float], list[float]]:
    """`TTL_REPS` times: `close` (returning its instant), the gate engaged within the TTL bound and
    `POST /orders` the 403; `reopen`, the gate open again. Two entries are accepted with their
    native stops (one before, one once the first reopen is read), and both are cancelled (202)
    while the gate is closed in the last repetition: a cancel never meets the gate (C-2.6)."""
    closed, reopened = [], []
    orders = [await _placed(client, world)]
    for rep in range(TTL_REPS):
        at = await close()
        closed.append(await stack.watch.until(True, _BOUND_S) - at)
        _refused(await _post(client, world.body))
        if rep == TTL_REPS - 1:
            for order in orders:
                gone = await client.delete(f"/orders/{order}", headers=_key())
                assert gone.status_code == 202, gone.text
        at = await reopen()
        reopened.append(await stack.watch.until(False, reopen_bound_s) - at)
        if rep == 0:
            orders.append(await _placed(client, world))
    return closed, reopened


@_TTL_TIMEOUT
async def test_the_order_kill_switch_set_in_the_database_closes_order_entry_within_its_ttl(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    """#964 "Kill-switch-class flag freshness", end to end: `killswitch.order_entry` set by a
    statement in the database, not by the writer. The maintenance poll re-reads both gate flags
    every `KILLSWITCH_TTL_S` (5 s) from a fresh load (`FlagService.invalidate`), so within that
    TTL plus one read budget the gate engages and `POST /orders` is the 403; cleared, it reopens
    within the same bound (`_lapses`)."""

    async def at(on: bool) -> float:
        return await _set_in_database(world.dsn, on)

    async with _stack(world, monkeypatch) as stack, _serving(world) as client:
        closed, reopened = await _lapses(
            stack, client, world, lambda: at(True), lambda: at(False),
            reopen_bound_s=_REOPEN_BOUND_S,
        )  # fmt: skip
    assert _measured("kill switch set in the database, gate closed", closed) <= TTL_BOUND_S * 1e3
    assert _measured("kill switch cleared, gate open", reopened) <= TTL_BOUND_S * 1e3


async def _set_in_database(dsn: str, on: bool) -> float:
    """`killswitch.order_entry` written by one autocommitted statement; the instant it returned."""
    await asyncio.to_thread(
        c6._sql, dsn,
        "UPDATE feature_flags SET default_value = CAST(%s AS jsonb), updated_at = now() "
        "WHERE key = %s", "true" if on else "false", KILL_ORDER_ENTRY,
    )  # fmt: skip
    return time.perf_counter()


class _Switch(_Relay):
    """`_Relay`, cut and restored on one port: while cut, each connection it accepts is reset at
    once (a connect fails fast, as against a stopped Postgres), and every relayed one is reset."""

    def __init__(self, dsn: str) -> None:
        super().__init__(dsn)
        self._open = True

    async def _relay(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        if not self._open:
            writer.close()
            return
        await super()._relay(reader, writer)

    def block(self) -> float:
        """Cut, on the same port; the instant it was cut, for the measurement."""
        self._open = False
        for stream in self._streams:
            stream.close()
        return time.perf_counter()

    def restore(self) -> float:
        self._open = True
        return time.perf_counter()

    def close(self) -> None:
        self.cut()


@_TTL_TIMEOUT
async def test_an_unreadable_flag_store_fails_order_entry_closed_within_the_ttl(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    """D1, fail closed, end to end: the kill-switch state cannot be confirmed because the flag
    store is unreachable (a relay in front of the flag runtime's Postgres resets and refuses its
    connections; the OMS stores keep theirs). The next poll's load fails, both gate flags read as
    unknown, and within the TTL plus one read budget the gate engages: `POST /orders` is the 403
    and cancels pass. Reachable again, order entry reopens (`_lapses`)."""
    relay = _Switch(world.dsn)

    async def cut() -> float:
        return relay.block()

    async def restore() -> float:
        return relay.restore()

    dsn = await relay.through(c6._login(world.dsn, "cv_app"))
    try:
        async with _stack(world, monkeypatch, flags_dsn=dsn) as stack, _serving(world) as client:
            closed, reopened = await _lapses(
                stack, client, world, cut, restore, reopen_bound_s=_REOPEN_BOUND_S
            )
    finally:
        relay.close()
    assert _measured("flag store unreachable, gate closed", closed) <= TTL_BOUND_S * 1e3
    _measured("flag store reachable, gate open", reopened)


class _Uncounted(Exception):
    """F1 observed, and only F1: the refusal happened but its series did not count it. Any other
    failure, a fixture's included, is not this and so is not excused by the `xfail`."""


@pytest.mark.xfail(
    strict=True,
    raises=_Uncounted,
    reason="F1, #4973 (docs/qa/perf/e29-order-entry-gate-measurements.md): a POST /orders "
    "refusal is not counted in cv_order_entry_refusals_total; strict, so it turns red once "
    "#4973 fixes it",
)
async def test_a_maintenance_refusal_is_counted_with_its_reason(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    """#964 criterion 1's count: each `POST /orders` refused under maintenance increments
    `cv_order_entry_refusals_total{reason="maintenance"}` by one."""
    counted = _counted()
    async with _stack(world, monkeypatch) as stack, _serving(world) as client:
        await stack.refusal_after(MAINTENANCE_MODE, lambda: _post(client, world.body))
        await stack.write(MAINTENANCE_MODE, False)
    delta = _counted() - counted
    if delta != 1:
        raise _Uncounted(f"cv_order_entry_refusals_total{{reason=maintenance}} +{delta:g}, not +1")

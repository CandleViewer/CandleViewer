"""#913 L1d-1 (E29-T04, 29 CV-C13): the order lane signs and sends its own venue calls. The OMS's
trading port is the adapter's lane port (`lane_trading_port`), built on the lane over M2's
`LoopSigning`, which the runtime binds there over the lane's own writer (L2a-2) and closes there,
so no venue call crosses to the serving loop. No timing is asserted: each wait on the lane's
thread is a bound on the test, and a stalled serving loop is one blocked on an event."""

from __future__ import annotations

import asyncio
import inspect
import threading
from collections.abc import Awaitable, Callable
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from uuid import UUID

import pytest
from structlog.testing import capture_logs

from candleviewer import oms_wiring
from candleviewer.admin.wiring import build_lane_audit_writer, secrets_bundle
from candleviewer.exchange.base.ports import TradingPort
from candleviewer.oms.cancel_all_coalescer import CancelAllCoalescer
from candleviewer.oms.commands import OmsCommandPort
from candleviewer.oms.repository import OrderRepository
from candleviewer.oms_lane import OrderLane, Serving
from candleviewer.oms_wiring import AuditAlarm, OmsStores, OwnedAudit
from candleviewer.secrets import KEY_ID_SLOT
from candleviewer.secrets.store import InMemoryCredentialStore
from candleviewer.statechart.bindings import b01_order as b01
from candleviewer.storage.repositories.orders import ORDER_STATE_OF, NewOrderEvent
from tests.unit.audit.audit_fakes import FakeAuditRepository
from tests.unit.credentials_m2._service_fakes import _ctx, _Src, _store_one, _svc
from tests.unit.credentials_m2._vectors import KEK_V1
from tests.unit.oms import command_rig as cr
from tests.unit.oms.test_oms_runtime import (
    SENDING,
    T0,
    Heart,
    Lock,
    Port,
    Transport,
    World,
    Writer,
    crashed,
    failed_phases,
    started,
)
from tests.unit.oms.test_order_lane import BOUND_S, lane_loop

__all__ = ["lane_loop"]  # its lanes on asyncio's loop, then on uvloop (CR-S3L1A-06)

#: Every coroutine member of the trading port, the private stream's included.
VENUE_CALLS = sorted(
    name for name, member in inspect.getmembers(TradingPort) if inspect.iscoroutinefunction(member)
)


#: What each venue member is called with: an account ref that also reads as a request with no
#: `orderLinkId`, so S4-F's fold port passes every call through to the lane's port as it is.
_ANY = SimpleNamespace(account=cr.ref(), order_link_id=None)


def _arguments(name: str) -> list[Any]:
    """As many positional arguments as the trading port's `name` takes, each `_ANY`."""
    taken = list(inspect.signature(getattr(TradingPort, name)).parameters.values())[1:]
    return [_ANY for p in taken if p.default is p.empty and p.kind is p.POSITIONAL_OR_KEYWORD]


async def _thread() -> threading.Thread:
    return threading.current_thread()


def _hopping(real: Callable[..., Any], name: str, hops: list[str]) -> Callable[..., Any]:
    """`Serving.<name>`, noting each hop to the serving loop first."""
    if inspect.iscoroutinefunction(real):

        async def awaited(self: Serving, *args: Any, **kwargs: Any) -> Any:
            hops.append(name)
            return await real(self, *args, **kwargs)

        return awaited

    def called(self: Serving, *args: Any, **kwargs: Any) -> Any:
        hops.append(name)
        return real(self, *args, **kwargs)

    return called


def _ran(name: str, ran: list[tuple[str, threading.Thread]]) -> Callable[..., Any]:
    async def call(self: Port, *_args: Any, **_kwargs: Any) -> None:
        ran.append((name, threading.current_thread()))

    return call


async def test_no_venue_call_hops_to_the_serving_loop(monkeypatch: pytest.MonkeyPatch) -> None:
    """R3: on a real order lane, each coroutine member of the trading port, the private stream's
    included, called through the router's port there (S4-F's fold port), runs on the lane's
    thread, and nothing hops to the serving loop: no `Serving.call` or `notify`, its two hops
    since L4 removed `block` (CR-S3L1B-05's parity, inverted). The hops are read before the stop,
    whose `private_streams` closer then makes the one call, on the serving loop (#913 L1d-2b); the
    adapter's own port opens a private stream across the lane's bridge
    (`test_order_lane_streams.py`)."""
    hops, ran, refused = list[str](), list[tuple[str, threading.Thread]](), list[str]()
    for name in ("call", "notify"):
        monkeypatch.setattr(Serving, name, _hopping(getattr(Serving, name), name, hops))
    for name in VENUE_CALLS:
        monkeypatch.setattr(Port, name, _ran(name, ran))
    world = World()  # its flags unread: the startup waits, and nothing else hops meanwhile
    async with asyncio.timeout(BOUND_S), started(world.runtime(lane=OrderLane)) as runtime:
        parts = runtime._composed()
        port = parts.submission._router.port_for("demo")
        hops.clear()

        async def every_call() -> threading.Thread:
            for name in VENUE_CALLS:
                try:
                    await getattr(port, name)(*_arguments(name))
                except Exception as exc:  # a member refused before it ran
                    refused.append(f"{name}: {type(exc).__name__}")
            return threading.current_thread()

        on_lane = await parts.lane.call(every_call())
        crossed = list(hops)
    assert (crossed, refused) == ([], [])
    assert hops == ["call"]  # the stop's `private_streams` closer
    assert ran == [(name, on_lane) for name in VENUE_CALLS]


class _LaneRows:
    """The lane's own credential store over the rows M2's serving store holds: another object, as
    M2 refuses its own store to the lane (L1d-0), with the two calls the lane's signing makes."""

    def __init__(self, rows: InMemoryCredentialStore) -> None:
        self._rows = rows

    async def get(self, key_id: UUID, env: str) -> dict[str, Any] | None:
        return await self._rows.get(key_id, env)

    async def touch_last_used(self, key_id: UUID) -> None:
        await self._rows.touch_last_used(key_id)


async def _no_pool() -> None:
    """The dispose of the lane store's pool: its rows are in memory, so there is none."""


async def test_a_stalled_serving_loop_holds_neither_a_kill_cancel_nor_a_stop_attach(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """R4, the isolation twin, clock-free: this loop's thread blocks on an event, as the amend test
    blocks it, while B1's KILL cancels the sent order and a stop is attached after an entry's fill,
    each signed first, as the lane's port signs every call; both reach the venue from the lane
    before this loop turns again. Over the lane's real writer (L2a-2's `build_lane_audit_writer`,
    bound to the lane's loop, which refuses any other) and M2's real lane signing, so the OMS's
    write-aheads and M2's `credential_borrowed` ahead of each signing land on the lane."""
    rows, repo = InMemoryCredentialStore(), FakeAuditRepository()
    m2 = _svc(_Src(KEK_V1, 1), store=rows)
    await m2.start(_ctx())
    key_id = (await _store_one(m2)).key_id

    def lane_store(_connections: int) -> tuple[Any, Callable[[], Awaitable[None]]]:
        return _LaneRows(rows), _no_pool  # the two calls M2's lane signing makes, no more

    bundle = secrets_bundle(m2, loop_store=lane_store)
    cancelled, attached = threading.Event(), threading.Event()
    world = World()

    def signed(real: Callable[..., Any], done: threading.Event) -> Callable[..., Any]:
        async def call(self: Port, req: Any) -> Any:
            [built] = world.venue.lane_calls  # the borrower of the lane's `LoopSigning`
            await built.credentials.sign(key_id, (KEY_ID_SLOT,), purpose="sign_rest")
            answer = await real(self, req)
            done.set()
            return answer

        return call

    monkeypatch.setattr(Port, "cancel_order", signed(Port.cancel_order, cancelled))
    monkeypatch.setattr(Port, "set_trading_stop", signed(Port.set_trading_stop, attached))
    wal = str(tmp_path / "oms_lane.audit.wal")

    def lane_writer(alarm: AuditAlarm) -> OwnedAudit:
        return build_lane_audit_writer(repo, wal, on_alarm=alarm)

    def stores() -> OmsStores:  # the lane's writer the real one, over the fake repository
        return replace(world.stores(), audit=lane_writer)

    await crashed(world)
    for flag in world.flags:
        flag.read()
    entry = cr.new_order(seq=9)  # filled: B1's `sl_pending` finds it so
    filled = replace(entry, state=ORDER_STATE_OF["submitted"], lifecycle_state="submitted")
    runtime = world.runtime(lane=OrderLane, lane_signing=bundle.lane_signing, stores=stores)
    try:  # a bound on the test: its two blocking waits' bounds and the rest
        async with asyncio.timeout(3 * BOUND_S), started(runtime):
            await runtime.wait_ready()
            parts = runtime._composed()
            resumed = parts.machines.settled(
                cr.ACCOUNT, SENDING.id, leaving="submitting", timeout_s=BOUND_S
            )
            assert await parts.lane.call(resumed) == "submitted"
            event = NewOrderEvent(kind="submit_attempt", source="local", event_ts=T0)
            await OrderRepository(world.store).create(filled, event)
            world.venue.ports[0].seed_position(cr.position())
            commands = parts.exits._d.commands
            assert isinstance(commands, OmsCommandPort)
            attach = cr.command("attach_stop", entry, {"stop_loss": str(cr.STOP)})
            attaching = parts.lane.call(commands.attach_stop(attach))
            killing = parts.lane.call(parts.machines.kill("kill switch"))
            # this loop's thread blocks: neither venue call may wait for it to turn
            stalled = (cancelled.wait(BOUND_S / 2), attached.wait(BOUND_S / 2))
            answers = await asyncio.gather(killing, attaching, return_exceptions=True)
    finally:
        await m2.stop(1.0)
    assert stalled == (True, True)
    assert answers[0] == () and answers[1] == {"ok": True, "position": answers[1]["position"]}
    borrowed = [row for row in repo.rows if row["action"] == "security.credential_borrowed"]
    assert [row["object_id"] for row in borrowed] == [str(key_id)] * 2  # one ahead of each


@pytest.mark.parametrize("fixture", [False, True], ids=["production", "account-fixture"])
async def test_the_port_is_the_adapters_lane_port_built_on_the_lane_over_its_own_signing(
    fixture: bool,
) -> None:
    """R5: the router's port is S4-F's fold port over the adapter's lane port, built on the lane,
    with no bridge around it, signed by the borrower of the `LoopSigning` bound there first (never
    the serving borrower), which passed its self-check there, and recording through the lane's own
    writer, the one the stores build and the OMS records through (L2a-2), never the serving
    loop's. Its clock offset is the guard's snapshot, never the serving reader with its host-step
    check (CR-S3L1B-09). With the dev-only account fixture, its transport is the lane's own, built
    on the lane and closed there once the port has closed; in production it has none."""
    world = World()
    if fixture:
        world.lane_transport = lambda: Transport(world.binder.log)
    async with asyncio.timeout(BOUND_S), started(world.runtime(lane=OrderLane)) as runtime:
        parts = runtime._composed()
        on_lane = await parts.lane.call(_thread())
        [call] = world.venue.lane_calls
        [signing], [audit] = world.binder.handles, world.binder.audits
        assert (call.env, call.thread, call.credentials) == ("demo", on_lane, signing.borrower)
        assert call.clock_offset_ms is world.ingestion.clock_offset_snapshot_ms
        assert isinstance(call.transport, Transport) is fixture
        folds = parts.submission._router.port_for("demo")
        assert isinstance(folds, CancelAllCoalescer) and folds._inner is world.venue.ports[0]
        assert audit is world.writer and parts.audit._writer is audit
        assert world.binder.log == [("bind", on_lane), ("self_check", on_lane)]
    closed = [step for step in world.binder.log if step[0] == "transport"]
    assert closed == ([("transport", on_lane)] if fixture else [])


async def test_the_stop_closes_the_port_then_the_signing_then_its_writer_each_on_the_lane(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """R6 (#4434 follow-up 10): the closers in order, after the commands and the sink: the lane's
    port, its signing, whose close frees M2's lane pool (L1d-0), then the lane's own writer, which
    a signing refused at the close records through after it (`credential_sign_failed`), then the
    OMS's pool, the heartbeat's cancel and last the environment's lock (SEC-S3N-01); each of those
    six runs on the lane, the port's clients first, so no signing outlives the store it reads or
    the writer it records through, and nothing that signs or sends outlives the lock. The private
    streams the lane's bridge holds close between the sink and the port, on the serving loop
    (#913 L1d-2b)."""
    world = World()
    steps, run = world.binder.log, Heart.run

    async def closes(self: Port) -> None:
        steps.append(("trading_port", threading.current_thread()))

    async def stops(self: Writer, grace_s: float = 5.0) -> None:
        steps.append(("audit", threading.current_thread()))

    async def releases() -> None:
        steps.append(("pool", threading.current_thread()))

    async def beats(self: Heart) -> None:
        try:
            await run(self)
        finally:  # its stop's cancel, waited for there
            steps.append(("heartbeat", threading.current_thread()))

    async def unlocks(self: Lock) -> None:
        steps.append(("environment_lock", threading.current_thread()))

    monkeypatch.setattr(Port, "aclose", closes)
    monkeypatch.setattr(Writer, "stop", stops)
    monkeypatch.setattr(Heart, "run", beats)
    monkeypatch.setattr(Lock, "release", unlocks)
    runtime = world.runtime(
        lane=OrderLane, stores=lambda: replace(world.stores(), release=releases)
    )
    async with asyncio.timeout(BOUND_S), started(runtime):
        parts = runtime._composed()
        names = [name for name, _ in parts.closers]
        on_lane = await parts.lane.call(_thread())
    assert names == [
        "exits", "stop_gate", "machines", "cancel_all_folds", "commands", "sink",
        "private_streams", "trading_port", "loop_signing", "audit", "pool", "heartbeat",
        "environment_lock",
    ]  # fmt: skip
    closing = [step for step in steps if step[0] not in ("bind", "self_check")]
    assert closing == [(name, on_lane) for name in names[7:]]


async def test_each_start_binds_a_new_signing_and_its_stop_closes_it() -> None:
    """R7 (#4434 follow-up 8): a closed `LoopSigning` stays closed, so each start binds a new one,
    over that start's own writer, and its port signs with that one's borrower; each stop closes it,
    which frees its pool (L1d-0)."""
    world = World()
    runtime = world.runtime()
    for _ in range(2):
        async with started(runtime):
            pass
    first, second = world.binder.handles
    assert first is not second and first.closed and second.closed
    assert [call.credentials for call in world.venue.lane_calls] == [
        first.borrower, second.borrower,
    ]  # fmt: skip
    assert [name for name, _ in world.binder.log] == ["bind", "self_check", "loop_signing"] * 2


#: What a compose failing at the signing or the port leaves in the world's log: the lock taken
#: before the lane's writer and its signing (SEC-S3N-01), and given up last, after the pool.
_UNWOUND = ["lock.acquire", "audit.stop", "pool.release", "lock.release"]


@pytest.mark.parametrize(
    ("failing", "phase", "closers", "log", "fixture"),
    [
        ("stores", "stores", [], [], False),
        ("bind", "signing", ["audit", "pool", "environment_lock"], _UNWOUND, False),
        (
            "self_check",
            "signing",
            ["loop_signing", "audit", "pool", "environment_lock"],
            _UNWOUND,
            False,
        ),
        (
            "port",
            "port",
            ["trading_port", "loop_signing", "audit", "pool", "environment_lock"],
            _UNWOUND,
            False,
        ),
        (
            "port",
            "port",
            ["trading_port", "loop_signing", "audit", "pool", "environment_lock"],
            _UNWOUND,
            True,
        ),
    ],
    ids=["stores", "bind", "self_check", "port", "port-account-fixture"],
)
async def test_a_compose_failing_at_or_after_the_binding_fails_closed_by_its_phase(
    failing: str,
    phase: str,
    closers: list[str],
    log: list[str],
    fixture: bool,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """R8: stores that cannot be built (a bad DSN) bind nothing; a binding the binder refuses (the
    serving loop's writer, or no lane store wired, as on a backend that composes no OMS), a
    self-check that fails (a wiring fault, `signing_loop_mismatch` or `store_unavailable`, Q5) or
    a port the adapter refuses (another environment, testnet) fails the start closed, logged and
    paged by its phase; a `LoopSigning` bound before is closed, which frees its pool, then the
    lane's writer, the pool and last the environment's lock, held before any of them: the closers
    the compose unwinds, by name and in order, so nothing that signs or sends outlives the lock;
    and no port is built after a failed signing. With the dev-only
    account fixture, on a real lane, a refused port still closes the lane's transport there, ahead
    of the signing: its closer is registered before the port is built, so the refusal leaks none."""
    world, unwound, close = World(), list[list[str]](), oms_wiring._closed

    async def noted(closing: Any, deadline: float) -> None:
        unwound.append([name for name, _ in closing])
        await close(closing, deadline)

    monkeypatch.setattr(oms_wiring, "_closed", noted)
    over: dict[str, Any] = {"lane": OrderLane} if fixture else {}
    if fixture:
        world.lane_transport = lambda: Transport(world.binder.log)
    if failing == "stores":
        over["stores"] = _refused
    elif failing == "bind":
        world.binder.refuse = RuntimeError("no loop credential store is wired")
    elif failing == "self_check":
        world.binder.fail = RuntimeError("signing_loop_mismatch")
    else:
        world.venue.refuse = RuntimeError("refused")
    with capture_logs() as logs:
        async with asyncio.timeout(BOUND_S), started(world.runtime(**over)) as runtime:
            assert runtime.state == "degraded" and not b01.ports_wired()
    assert failed_phases(logs) == [phase]
    assert world.pager.calls == [f"oms_runtime_failed_closed: {phase}"]
    assert [names for names in unwound if names] == ([closers] if closers else [])
    assert len(world.binder.handles) == (1 if failing in ("self_check", "port") else 0)
    assert all(h.closed for h in world.binder.handles)
    assert len(world.venue.lane_calls) == (1 if failing == "port" else 0)
    assert world.venue.ports == [] and world.log == log
    if fixture:  # the transport the refused build was handed, closed on the lane, then the signing
        on_lane = world.binder.log[0][1]  # where the binding ran: the lane's thread
        assert on_lane is not threading.current_thread()
        assert isinstance(world.venue.lane_calls[0].transport, Transport)
        assert world.binder.log == [
            ("bind", on_lane), ("self_check", on_lane), ("transport", on_lane),
            ("loop_signing", on_lane),
        ]  # fmt: skip


def _refused() -> OmsStores:
    raise RuntimeError("the OMS's pool cannot be built")

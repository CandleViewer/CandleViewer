"""B1 `order` conformance (E29-T03 #847, the remaining implementation): a snapshot round trip at
each quiescence point a real order rests in, on the real binding with the in-memory stores, a
refused restore of a forged or foreign snapshot, and the named family invariants of B1.7 (INV-1,
INV-2 and INV-5), on the library."""

from __future__ import annotations

import copy
import dataclasses
from collections import OrderedDict
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping, Sequence
from contextlib import asynccontextmanager
from decimal import Decimal
from typing import Any

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from structlog.testing import capture_logs
from xstate_statemachine import PluginBase, SimulatedClock

from candleviewer.oms.execution import apply_fields
from candleviewer.statechart import build
from candleviewer.statechart.bindings import b01_order as b01
from candleviewer.statechart.persistence import (
    ChainTripLatch,
    InMemoryDrainJournal,
    MachineKey,
    Persister,
    Restorer,
    RestoreRefusedError,
    SealedSnapshot,
    hmac_sealer,
)
from candleviewer.statechart.registry import Registry
from candleviewer.storage.repositories.orders import NewOrder
from tests.unit.oms.order_rig import ACCOUNT, Rig, build_rig, fill_of, gated, order_of
from tests.xstate_contract._harness import Audit, AuditTap, Charts, Keys, Pager, Repo, exits, settle
from tests.xstate_contract.b01_ports import Commands, Store

REGISTRY = Registry()
CHART = REGISTRY.get("order")
TERMINALS = ("filled", "cancelled", "rejected", "expired", "killed")


# --- Snapshot round trips at each quiescence point, on the real binding --------------------------


async def _validated(rig: Rig) -> NewOrder:
    order = order_of()
    await rig.start(order)
    return order


async def _submitted(rig: Rig) -> NewOrder:
    return await rig.submitted()


async def _triggered(rig: Rig) -> NewOrder:
    order = await rig.submitted()
    await rig.facade.push(ACCOUNT, order.id, "TRIGGERED", {"updated_time": 1})
    return order


async def _protected(rig: Rig) -> NewOrder:
    order = await rig.submitted()
    await rig.facade.push(ACCOUNT, order.id, "EXEC", fill_of(order, "e1", "0.4"))
    await rig.quiet()
    return order


async def _naked(rig: Rig) -> NewOrder:
    order = await _protected(rig)
    lost = {"updated_time": 200, "stop_loss": None, "size": "0.4"}
    await rig.facade.push(ACCOUNT, order.id, "SL_LOST", lost)
    return order


async def _unknown(rig: Rig) -> NewOrder:
    async def ambiguous(_command: b01.Command) -> Mapping[str, Any]:
        raise TimeoutError

    rig.commands.on_place = ambiguous
    order = order_of()
    await rig.start(order)
    await rig.facade.command(ACCOUNT, order.id, "SEND", actor="user")
    await rig.quiet()
    return order


async def _quarantined(rig: Rig) -> NewOrder:
    order = await _protected(rig)
    hostile = fill_of(order, "e9", "0.1", exchange_order_id="x-foreign")
    await rig.facade.push(ACCOUNT, order.id, "EXEC", hostile)
    await rig.quiet()
    return order


async def _held(rig: Rig) -> NewOrder:
    order = await rig.submitted()
    mismatch = {"exchange_order_id": "x9"}
    await rig.facade.command(ACCOUNT, order.id, "MISMATCH", mismatch, actor="system")
    return order


async def _untracked(rig: Rig) -> NewOrder:
    found = order_of(7, order_link_id="ext-" + "ab" * 16, exchange_order_id="x7")
    await rig.facade.discover(found, environment="demo")
    return found


#: Each configuration a real order rests in (no request in flight), and how it gets there.
POINTS: dict[tuple[str, str], Callable[[Rig], Awaitable[NewOrder]]] = {
    ("validated", "not_required"): _validated,
    ("submitted", "not_required"): _submitted,
    ("triggered", "not_required"): _triggered,
    ("partially_filled", "sl_present"): _protected,
    ("partially_filled", "sl_missing"): _naked,
    ("unknown", "not_required"): _unknown,
    ("quarantined", "sl_present"): _quarantined,
    ("held", "not_required"): _held,
    ("untracked", "not_required"): _untracked,
}


@asynccontextmanager
async def _resting(point: tuple[str, str]) -> AsyncIterator[tuple[Rig, NewOrder, Any]]:
    """A real order at *point*, through the OMS facade (the in-memory stores), and its machine."""
    rig = build_rig(registry=REGISTRY)
    try:
        order = await POINTS[point](rig)
        assert rig.facade.state(order.id) == point
        yield rig, order, rig.facade._orders[order.id].interp
    finally:
        await rig.facade.stop()


async def _sealed(interp: Any, key: MachineKey, keys: Keys) -> SealedSnapshot:
    repo, pager = Repo(), Pager()
    seal = hmac_sealer(keys, CHART)
    persister = Persister(
        repo=repo,
        journal=InMemoryDrainJournal(),
        audit=Audit(),
        seal=seal,
        machine_hash_of=REGISTRY.hash,
        pager=pager,
    )
    await persister.persist(interp, key=key)
    assert pager.pages == []  # the persist met no fault to page (24 Sec.17.6)
    envelope: SealedSnapshot = repo.rows[key]
    return envelope


def _restorer(keys: Keys, audit: Audit, pager: Pager) -> Restorer:
    return Restorer(
        registry=REGISTRY,
        keys=keys,
        journal=InMemoryDrainJournal(),
        audit=audit,
        pager=pager,
        latch=ChainTripLatch(),
        plugins=lambda _key: [AuditTap()],
        clock=SimulatedClock(),
        lane="order",
    )


@pytest.mark.parametrize("point", sorted(POINTS), ids=["+".join(p) for p in sorted(POINTS)])
async def test_b01_round_trip_at_each_quiescence_point_is_identical(point: tuple[str, str]) -> None:
    """29 Sec.1.3, E50-T49: a sealed snapshot of a real order at rest (its fills, bound id, staged
    and adopted terms, readings and outbox) restores the same configuration and context, and the
    restore runs no step: it writes nothing and sends nothing."""
    async with _resting(point) as (rig, order, interp):
        before = (set(interp.current_state_ids), copy.deepcopy(dict(interp.context)))
        events, sent = await rig.events.list_for_order(ACCOUNT, order.id), len(rig.commands.sent)
        key, keys = MachineKey("order", str(order.id), "demo"), Keys()
        envelope = await _sealed(interp, key, keys)
        restored = await _restorer(keys, Audit(), Pager()).restore(key, envelope)
        try:
            await settle()
            after = (
                set(restored.interpreter.current_state_ids),
                dict(restored.interpreter.context),
            )
            assert after == before and not restored.degraded
            assert await rig.events.list_for_order(ACCOUNT, order.id) == events
            assert len(rig.commands.sent) == sent
        finally:
            await restored.interpreter.stop()


def _wrong_hash(envelope: SealedSnapshot) -> SealedSnapshot:
    return dataclasses.replace(envelope, machine_hash="0" * 64)


def _bad_hmac(envelope: SealedSnapshot) -> SealedSnapshot:
    context = {**envelope.snapshot["context"], "filled_qty": "0"}  # a forged fill total
    return dataclasses.replace(envelope, snapshot={**envelope.snapshot, "context": context})


def _another_order(envelope: SealedSnapshot) -> SealedSnapshot:
    key = dataclasses.replace(envelope.key, entity_id="00000000-0000-0000-0000-000000000002")
    return dataclasses.replace(envelope, key=key)


@pytest.mark.parametrize("defect", [_wrong_hash, _bad_hmac, _another_order])
async def test_b01_a_forged_or_foreign_snapshot_is_refused(
    defect: Callable[[SealedSnapshot], SealedSnapshot],
) -> None:
    """CV-C52, CV-C53, MUST-12: a snapshot of a filled order under another machine hash, with a
    total edited after the seal, or sealed for another order, is quarantined and pages P1; it is
    never loaded."""
    async with _resting(("partially_filled", "sl_present")) as (_rig, order, interp):
        key, keys, audit, pager = (
            MachineKey("order", str(order.id), "demo"),
            Keys(),
            Audit(),
            Pager(),
        )
        envelope = await _sealed(interp, key, keys)
        with pytest.raises(RestoreRefusedError):
            await _restorer(keys, audit, pager).restore(key, defect(envelope))
        assert (len(audit.quarantined), pager.pages) == (1, ["P1"])


# --- INV-1, INV-2 and INV-5 on the library --------------------------------------------------------


_HYP = settings(
    max_examples=25, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture]
)
_ORDER = {"order_id": str(order_of().id), "order_link_id": order_of().order_link_id}
_ORDER |= {"account_id": str(ACCOUNT), "symbol": "BTCUSDT", "side": "buy", "qty": "1"}
_ORDER |= {"price": "63000", "stop_loss": "62000"}
VALIDATE: dict[str, Any] = {"gates": dict.fromkeys(b01.GATES, b01.PASSED), "order": _ORDER}


def _exec(exec_id: str, qty: str, *, foreign: bool = False) -> dict[str, Any]:
    """An EXEC of the order bound as `x1` (its place ack), or of another exchange order."""
    return fill_of(order_of(), exec_id, qty, exchange_order_id="x-foreign" if foreign else "x1")


class _Bounded(PluginBase[Any]):
    """INV-1's observer: `0 <= filled_qty <= qty` at every committed step."""

    def __init__(self) -> None:
        self.broken: list[tuple[str, str]] = []

    def on_transition(self, interpreter: Any, *_args: Any) -> None:
        ctx = interpreter.context
        if not Decimal(0) <= Decimal(ctx["filled_qty"]) <= Decimal(ctx["qty"]):
            self.broken.append((ctx["filled_qty"], ctx["qty"]))


@asynccontextmanager
async def _order_machine(
    *plugins: Any,
    place: Callable[..., Awaitable[object]] | None = None,
    start: str = "submitting",
) -> AsyncIterator[tuple[Any, list[tuple[str, dict[str, Any]]]]]:
    """B1 from `draft` on its real binding, the command port answering at once (or *place*), the
    step writer a recording double, and every audit record collected; sent (VALIDATE and SEND),
    or discovered on the exchange (`untracked`) when *start* says so."""
    records: list[tuple[str, dict[str, Any]]] = []

    async def hook(name: str, context: dict[str, Any]) -> None:
        records.append((name, dict(context.get("denied") or context.get("anomaly") or {})))

    commands = Commands(on_place=place) if place is not None else Commands()
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(b01, "_ATTEMPTS", OrderedDict())
        mp.setattr(b01, "_ports", b01.OrderPorts(persist=Store(), commands=commands))
        mp.setattr(b01, "_core", apply_fields)
        mp.setattr(b01, "_hook", hook)
        built = await build(
            "order", clock=SimulatedClock(), lane="order", registry=REGISTRY, plugins=plugins
        )
        try:
            if start == "untracked":
                found = {"order": _ORDER | {"exchange_order_id": "x1"}}
                await built.interpreter.send("DISCOVERED", wait=True, **found)
            else:
                await built.interpreter.send("VALIDATE", wait=True, **VALIDATE)
                await built.interpreter.send("SEND", wait=True)
            yield built.interpreter, records
        finally:
            await built.interpreter.stop()


_FILLS = st.lists(
    st.tuples(st.sampled_from(("e1", "e2", "e3", "e4")), st.sampled_from(("0.1", "0.4", "0.7"))),
    min_size=1,
    max_size=8,
)


@_HYP
@given(fills=_FILLS, early=st.integers(min_value=0, max_value=3))
async def test_inv_1_filled_qty_never_exceeds_qty_property(
    fills: list[tuple[str, str]], early: int
) -> None:
    """INV-1 (OM-T04): whatever executions arrive, some while the place is in flight (deferred,
    then drained), repeats and fills past `qty` included, `0 <= filled_qty <= qty` holds at every
    committed step: a fill the order cannot absorb is refused, never clamped."""
    gate, held = gated({"ok": True, "exchange_order_id": "x1"})
    bounded = _Bounded()
    async with _order_machine(bounded, place=held) as (interp, _records):
        for exec_id, qty in fills[:early]:  # deferred by `submitting`, drained after the ack
            await interp.send("EXEC", wait=True, **_exec(exec_id, qty))
        gate.set()
        await settle()
        for exec_id, qty in fills[early:]:
            await interp.send("EXEC", wait=True, **_exec(exec_id, qty))
        await settle()
        assert bounded.broken == []
        assert Decimal(interp.context["filled_qty"]) <= Decimal(interp.context["qty"])


#: An event of every kind B1 takes, with a payload its closed schema accepts.
SAMPLES: dict[str, dict[str, Any]] = {
    "VALIDATE": VALIDATE, "SEND": {}, "CANCEL": {}, "AMEND": {"price": "64000"},
    "EXEC": _exec("e9", "0.1"), "TRIGGERED": {"updated_time": 9}, "EXPIRE": {"updated_time": 9},
    "REMOTE_CANCELLED": {"updated_time": 9}, "AMEND_REJECTED": {"error_code": "REFUSED"},
    "MISMATCH": {"exchange_order_id": "x9"}, "TRANSPORT_FAULT": {"reason": "socket closed"},
    "FAULT": {"reason": "OM-T04"}, "RECON_FOUND_LIVE": {"exchange_order_id": "x1"},
    "RECON_FOUND_PARTIAL": {"exchange_order_id": "x1"}, "RECON_FOUND_FILLED": {},
    "RECON_FOUND_CANCELLED": {}, "RECON_MISS": {"pass_id": "p1"}, "ADOPT": {},
    "OPERATOR_RESOLVED": {"decided_by": "owner"}, "DISCOVERED": {}, "KILL": {"reason": "kill"},
    "MATERIALISED": {"pass_id": "p1", "source": "reconcile"},
    "FIRST_FILL": {}, "SL_DEADLINE": {}, "SL_OBSERVED": {"updated_time": 9, "size": "1"},
    "SL_LOST": {"updated_time": 9, "size": "1"},
}  # fmt: skip


def test_b01_samples_cover_every_event() -> None:
    assert set(SAMPLES) == set(b01.SCHEMAS)


@_HYP
@given(
    final=st.sampled_from(TERMINALS), events=st.lists(st.sampled_from(sorted(SAMPLES)), max_size=6)
)
async def test_inv_2_a_terminal_state_is_never_left_property(
    final: str, events: list[str], charts: Charts
) -> None:
    """INV-2 (24 Sec.8.2 S6): no arm leaves a final state, and whatever is sent to an order there,
    on its real binding, its `lifecycle` state stays: a fill is an audited anomaly, a KILL is
    audited, the rest is consumed or deferred, never a step."""
    assert exits(CHART, f"lifecycle.{final}") == []
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(b01, "_ATTEMPTS", OrderedDict())
        mp.setattr(b01, "_ports", b01.OrderPorts(persist=Store(), commands=Commands()))
        mp.setattr(b01, "_core", apply_fields)
        source = f"lifecycle.{final}"
        built = await build(
            "order",
            clock=SimulatedClock(),
            lane="order",
            registry=charts.registry("order", CHART, source),
            plugins=(AuditTap(),),
        )
        interp = built.interpreter
        try:
            for event in events:
                await interp.send(event, wait=True, **SAMPLES[event])
                await settle()
                assert f"order.{source}" in interp.current_state_ids
        finally:
            await interp.stop()


_DELIVERIES = st.lists(
    st.tuples(
        st.sampled_from(("e1", "e2", "e3")),
        st.sampled_from(("0.2", "0.5", "1.5")),
        st.booleans(),  # foreign: of another exchange order
        st.sampled_from(("", "TRIGGERED", "CANCEL", "FAULT", "REMOTE_CANCELLED", "KILL")),
    ),
    min_size=1,
    max_size=6,
)


@_HYP
@given(
    deliveries=_DELIVERIES,
    early=st.integers(min_value=0, max_value=2),
    start=st.sampled_from(("submitting", "untracked")),
)
async def test_inv_5_no_delivered_exec_is_unaccounted_for_property(
    deliveries: list[tuple[str, str, bool, str]], early: int, start: str
) -> None:
    """INV-5 (LC-03, 24 Sec.8.2 S10): every `exec_id` sent to the machine, whatever its state, is
    in `seen_exec_ids`, still deferred, or in the record of the arm that consumed it (a repeat, a
    fill of another order or past `qty`: `guard_denied`; a fill of a held or final order:
    `reconcile_anomaly`; one `untracked` heard of: `record_remote_state`'s), never
    dropped silently. Orders that were sent and orders discovered on the exchange alike."""
    gate, held = gated({"ok": True, "exchange_order_id": "x1"})
    with capture_logs() as logs:
        await _deliver(deliveries, early, start, gate, held, logs)


async def _deliver(
    deliveries: list[tuple[str, str, bool, str]],
    early: int,
    start: str,
    gate: Any,
    held: Callable[..., Awaitable[object]],
    logs: Sequence[Mapping[str, Any]],
) -> None:
    async with _order_machine(place=held, start=start) as (interp, records):
        delivered: list[str] = []
        for index, (exec_id, qty, foreign, then) in enumerate(deliveries):
            if index == early:
                gate.set()
                await settle()
            await interp.send("EXEC", wait=True, **_exec(exec_id, qty, foreign=foreign))
            delivered.append(exec_id)
            if then:
                await interp.send(then, wait=True, **SAMPLES[then])
            await settle()
        gate.set()
        await settle()
        deferred = {e.payload.get("exec_id") for e in interp._deferred_events}
        audited = {
            r.get("exec_id") for n, r in records if n in ("guard_denied", "reconcile_anomaly")
        }
        seen = {e["exec_id"] for e in logs if e["event"] == "b01_untracked_order_seen"}
        accounted = set(interp.context["seen_exec_ids"]) | deferred | audited | seen
        assert set(delivered) <= accounted

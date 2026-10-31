"""B1 `order` conformance (E29-T03 #847, the remaining implementation): a snapshot round trip at
each quiescence point a real order rests in, on the real binding with the in-memory stores, a
refused restore of a forged or foreign snapshot, and the named family invariants of B1.7 (INV-1,
INV-2 and INV-5), on the library. Chart version 5 (#848): a recorded stop's terms step round trips
and is refused forged, and a golden version-4 snapshot is refused on restore, its order rebuilt
from its `order_events` (28 B1.8, the snapshot migration). Chart version 6 (#4808) is version 5
with its exit refusals alone, and a version-5 snapshot is refused on restore. Chart version 7 (#914)
is version 6 with its `missing_remote` arms alone, and a golden version-6 snapshot is refused on
restore, its order rebuilt from its `order_events`. Chart version 8 (#914) is version 7 with its
`untracked` fill arms alone, an `untracked` row that holds a fill round trips, and a golden
version-7 snapshot is refused on restore, its order rebuilt from its `order_events`."""

from __future__ import annotations

import copy
import dataclasses
import json
from collections import OrderedDict
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping, Sequence
from contextlib import asynccontextmanager
from decimal import Decimal
from pathlib import Path
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
    Seal,
    SealedSnapshot,
    hmac_sealer,
    open_sealed,
)
from candleviewer.statechart.registry import Registry, machine_hash
from candleviewer.statechart.upcasters import has_upcaster
from candleviewer.storage.repositories.orders import NewOrder
from tests.unit.oms.order_rig import ACCOUNT, Rig, build_rig, fill_of, gated, order_of
from tests.xstate_contract._harness import Audit, AuditTap, Charts, Keys, Pager, Repo, exits, settle
from tests.xstate_contract.b01_ports import Commands, Store

REGISTRY = Registry()
CHART = REGISTRY.get("order")
TERMINALS = ("filled", "cancelled", "rejected", "expired", "killed")
#: Chart version 4's `machine_hash` (28 B1.8): version 5's restore refuses a snapshot sealed at it.
V4_HASH = "18d4f519f032b9394245f00f18b0c6fce9145d22969ef2eb3854f2695190c3dc"
#: Chart version 5's `machine_hash` (28 B1.8): version 6's restore refuses a snapshot sealed at it.
V5_HASH = "627c93f770bcff5d39dce0bed60d2a666c730860998327c6449b4e9e961ee019"
#: Chart version 6's `machine_hash` (28 B1.8): version 7's restore refuses a snapshot sealed at it.
V6_HASH = "e75583007285bcb73dfa511d71ec92bdee74054827864668a41f5f8e638fc15e"
#: Chart version 7's `machine_hash` (28 B1.8): version 8's restore refuses a snapshot sealed at it.
V7_HASH = "f6289b9e6d7738bc6574c8cc5a6985e4e1be98a647deeb1514b4b5421ed13c54"
#: Version 6's arm in each `lifecycle` state for an exit it does not take (INV-B1-r).
_EXIT_REFUSAL = {"actions": ["audit_operator_command_refused"]}
#: Version 7's arm in each live state a reconciliation pass finds nowhere (INV-B1-s).
_MISSING_REMOTE = {"target": "#order.lifecycle.unknown", "actions": ["record_missing_remote"]}
#: The settled live states that take it, in chart order (24 Sec.8.5 step 3b); a state with a
#: request in flight takes none.
_MISSED_LIVE = ("submitted", "triggered", "partially_filled", "quarantined")
#: `untracked`'s `EXEC` arm before version 8, and version 8's three in its place (INV-B1-l).
_V7_UNTRACKED_EXEC = {"actions": ["record_remote_state"]}
_UNTRACKED_FILLS = [
    {
        "target": "#order.lifecycle.filled",
        "guard": "exec_new_and_closes",
        "actions": ["apply_untracked_exec"],
    },
    {
        "target": "#order.lifecycle.untracked",
        "guard": "exec_new_and_partial",
        "reenter": True,
        "actions": ["apply_untracked_exec"],
    },
    {"actions": ["record_remote_state"]},
]
_GOLDEN = Path(__file__).resolve().parent / "golden"


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


def _version_5_hash(envelope: SealedSnapshot) -> SealedSnapshot:
    return dataclasses.replace(envelope, machine_hash=V5_HASH)


def _version_6_hash(envelope: SealedSnapshot) -> SealedSnapshot:
    return dataclasses.replace(envelope, machine_hash=V6_HASH)


def _version_7_hash(envelope: SealedSnapshot) -> SealedSnapshot:
    return dataclasses.replace(envelope, machine_hash=V7_HASH)


@pytest.mark.parametrize(
    "defect",
    [_wrong_hash, _version_5_hash, _version_6_hash, _version_7_hash, _bad_hmac, _another_order],
)
async def test_b01_a_forged_or_foreign_snapshot_is_refused(
    defect: Callable[[SealedSnapshot], SealedSnapshot],
) -> None:
    """CV-C52, CV-C53, MUST-12: a snapshot of a filled order under another machine hash, version
    5's, version 6's and version 7's included, with a total edited after the seal, or sealed for
    another order, is quarantined and pages P1; it is never loaded."""
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


# --- Version 5: the terms step's snapshots, and version 4's refused (28 B1.8) -------------------


async def _recorded_stop(rig: Rig) -> NewOrder:
    """A recorded stop's row (24 Sec.8.3 rule 7), materialised by the private stream."""
    stop = order_of(
        5, order_link_id="ext-" + "ef" * 16, intent="stop_loss", order_type="Market", price=None,
        trigger_price=Decimal(62000), stop_loss=None, reduce_only=True, close_on_trigger=True,
        exchange_order_id="x-sl5",
    )  # fmt: skip
    assert await rig.facade.materialise(stop, environment="demo") == "submitted"
    await rig.quiet()
    return stop


async def _recorded_stop_with_new_terms(rig: Rig) -> NewOrder:
    """The row once its order's trigger price and quantity changed in place (INV-B1-q)."""
    stop = await _recorded_stop(rig)
    terms = {"exchange_order_id": "x-sl5", "trigger_price": "61000", "qty": "2", "updated_time": 9}
    await rig.facade.push(ACCOUNT, stop.id, "TERMS_CHANGED", terms)
    await rig.quiet()
    return stop


async def test_b01_terms_step_snapshot_round_trip_identical() -> None:
    """29 Sec.1.3 on version 5: a sealed snapshot of a recorded stop's row whose terms step was
    written restores the same configuration and context, its new terms included, and the restore
    runs no step: it writes nothing and sends nothing."""
    rig = build_rig(registry=REGISTRY)
    try:
        stop = await _recorded_stop_with_new_terms(rig)
        interp = rig.facade._orders[stop.id].interp
        before = (set(interp.current_state_ids), copy.deepcopy(dict(interp.context)))
        assert (before[1]["qty"], before[1]["trigger_price"]) == ("2", "61000")
        events = await rig.events.list_for_order(ACCOUNT, stop.id)
        key, keys = MachineKey("order", str(stop.id), "demo"), Keys()
        envelope = await _sealed(interp, key, keys)
        restored = await _restorer(keys, Audit(), Pager()).restore(key, envelope)
        try:
            await settle()
            after = (
                set(restored.interpreter.current_state_ids),
                dict(restored.interpreter.context),
            )
            assert after == before and not restored.degraded
            assert await rig.events.list_for_order(ACCOUNT, stop.id) == events
            assert rig.commands.sent == []
        finally:
            await restored.interpreter.stop()
    finally:
        await rig.facade.stop()


def _version_4_hash(envelope: SealedSnapshot) -> SealedSnapshot:
    return dataclasses.replace(envelope, machine_hash=V4_HASH)


def _forged_terms(envelope: SealedSnapshot) -> SealedSnapshot:
    context = {**envelope.snapshot["context"], "trigger_price": "60000"}  # moved after the seal
    return dataclasses.replace(envelope, snapshot={**envelope.snapshot, "context": context})


@pytest.mark.parametrize("defect", [_wrong_hash, _version_4_hash, _forged_terms])
async def test_b01_terms_step_snapshot_forged_or_version_4_refused(
    defect: Callable[[SealedSnapshot], SealedSnapshot],
) -> None:
    """CV-C52, CV-C53, MUST-12: a recorded stop's snapshot under another machine hash, under
    version 4's, or with its trigger price edited after the seal is quarantined and pages P1; it
    is never loaded."""
    rig = build_rig(registry=REGISTRY)
    try:
        stop = await _recorded_stop_with_new_terms(rig)
        key, keys, audit, pager = (
            MachineKey("order", str(stop.id), "demo"),
            Keys(),
            Audit(),
            Pager(),
        )
        envelope = await _sealed(rig.facade._orders[stop.id].interp, key, keys)
        with pytest.raises(RestoreRefusedError):
            await _restorer(keys, audit, pager).restore(key, defect(envelope))
        assert (len(audit.quarantined), pager.pages) == (1, ["P1"])
    finally:
        await rig.facade.stop()


def _version_7(chart: Mapping[str, Any]) -> dict[str, Any]:
    """Chart version 7: version 8 with `untracked`'s one `EXEC` arm, `record_remote_state`, in
    place of version 8's three (28 B1.8, INV-B1-l)."""
    out = copy.deepcopy(dict(chart)) | {"version": 7}
    on = out["states"]["lifecycle"]["states"]["untracked"]["on"]
    if on["EXEC"] == _UNTRACKED_FILLS:
        on["EXEC"] = dict(_V7_UNTRACKED_EXEC)
    return out


def _version_6(chart: Mapping[str, Any]) -> dict[str, Any]:
    """Chart version 6: version 7 without its `missing_remote` arms (28 B1.8), each the one arm
    that takes a live row a pass finds nowhere into `unknown` (INV-B1-s)."""
    out = _version_7(chart) | {"version": 6}
    for node in out["states"]["lifecycle"]["states"].values():
        on = node.get("on") or {}
        if on.get("RECON_MISS") == _MISSING_REMOTE:
            del on["RECON_MISS"]
    return out


def _version_5(chart: Mapping[str, Any]) -> dict[str, Any]:
    """Chart version 5: version 6 without its exit refusals (28 B1.8), each the one arm that
    records an exit its state does not take (INV-B1-r)."""
    out = _version_6(chart) | {"version": 5}
    for node in out["states"]["lifecycle"]["states"].values():
        on = node.get("on") or {}
        for event in ("CANCEL", "AMEND"):
            if on.get(event) == _EXIT_REFUSAL:
                del on[event]
    return out


def _version_4(chart: Mapping[str, Any]) -> dict[str, Any]:
    """Chart version 4: version 5 without its `TERMS_CHANGED` groups (28 B1.8)."""
    out = _version_5(chart) | {"version": 4}
    for node in out["states"]["lifecycle"]["states"].values():
        (node.get("on") or {}).pop("TERMS_CHANGED", None)
    return out


def test_b01_version_6_is_version_5_with_the_exit_refusals_alone() -> None:
    """28 B1.8 version 6: the chart is version 5 with one refusal arm for each exit a non-final
    state does not take (INV-B1-r), and nothing else. Its hash moved from version 5's, so the
    restore refuses a snapshot sealed at version 5 (MUST-12), and no upcaster carries one: B1
    recovers from its `order_events`. Version 7 derives it first (`_version_6`)."""
    assert machine_hash(_version_6(CHART)) == V6_HASH != V5_HASH
    assert machine_hash(_version_5(CHART)) == V5_HASH
    assert not has_upcaster("order", V5_HASH, REGISTRY.hash("order"))


def test_b01_version_7_is_version_6_with_the_missing_remote_arms_alone() -> None:
    """28 B1.8 version 7: the chart is version 6 with one `RECON_MISS` arm into `unknown` in each
    settled live state a pass finds nowhere (INV-B1-s), and nothing else. Its hash moved from
    version 6's, so the restore refuses a snapshot sealed at version 6 (MUST-12), and no upcaster
    carries one: B1 recovers from its `order_events`. Version 8 derives it first (`_version_7`)."""
    assert machine_hash(_version_7(CHART)) == V7_HASH != V6_HASH
    assert machine_hash(_version_6(CHART)) == V6_HASH
    states = CHART["states"]["lifecycle"]["states"]
    arms = [
        s
        for s, node in states.items()
        if (node.get("on") or {}).get("RECON_MISS") == _MISSING_REMOTE
    ]
    assert arms == list(_MISSED_LIVE)
    assert not has_upcaster("order", V6_HASH, REGISTRY.hash("order"))


def test_b01_version_8_is_version_7_with_the_untracked_fill_arms_alone() -> None:
    """28 B1.8 version 8: the chart is version 7 with `untracked`'s three `EXEC` arms in place of
    its one, `record_remote_state` (INV-B1-l), and nothing else: no other state's `EXEC` group
    moved. Its hash moved from version 7's, so the restore refuses a snapshot sealed at version 7
    (MUST-12), and no upcaster carries one: B1 recovers from its `order_events`."""
    assert CHART["version"] == 8 and REGISTRY.hash("order") != V7_HASH
    assert machine_hash(_version_7(CHART)) == V7_HASH
    states = CHART["states"]["lifecycle"]["states"]
    assert states["untracked"]["on"]["EXEC"] == _UNTRACKED_FILLS
    users = {s for s, node in states.items() if "apply_untracked_exec" in json.dumps(node)}
    assert users == {"untracked"}
    assert not has_upcaster("order", V7_HASH, REGISTRY.hash("order"))


async def test_b01_version_4_golden_snapshot_refused_then_rebuilt_from_order_events() -> None:
    """28 B1.8 version 5, the snapshot migration, on a golden snapshot: a recorded stop's row
    sealed at version 4 (`golden/order.v4_to_v5.before.json`, its seal genuine under version 4's
    chart) is refused by version 5's restore for its machine hash, quarantined and paged P1, and
    never loaded; no upcaster carries it, as B1 recovers from `order_events`: the row's history
    hydrates to the configuration `.after.json` names and to every context value the snapshot
    held."""
    before = json.loads((_GOLDEN / "order.v4_to_v5.before.json").read_text(encoding="utf-8"))
    after = json.loads((_GOLDEN / "order.v4_to_v5.after.json").read_text(encoding="utf-8"))
    key, seal = MachineKey(**before["key"]), Seal(**before["seal"])
    envelope = SealedSnapshot(
        key, before["version"], before["machine_hash"], before["snapshot"], seal
    )
    v4, keys, audit, pager = _version_4(CHART), Keys(), Audit(), Pager()
    assert machine_hash(v4) == before["machine_hash"] == V4_HASH != REGISTRY.hash("order")
    open_sealed(keys, v4, envelope, key=key, expected_machine_hash=V4_HASH)  # a genuine seal
    with pytest.raises(RestoreRefusedError) as refused:
        await _restorer(keys, audit, pager).restore(key, envelope)
    assert (refused.value.reason, len(audit.quarantined), pager.pages) == (
        after["refused"],
        1,
        ["P1"],
    )
    assert not has_upcaster("order", V4_HASH, REGISTRY.hash("order"))
    rig = build_rig(registry=REGISTRY)
    try:
        stop = await _recorded_stop(rig)
    except BaseException:
        await rig.facade.stop()  # B1's ports are process-wide: never left wired (C-2.11)
        raise
    again = await rig.restart()
    try:
        assert str(stop.id) == key.entity_id
        lifecycle = await again.facade.hydrate(ACCOUNT, stop.id, environment="demo")
        await again.quiet()
        assert again.facade.state(stop.id) == (lifecycle, after["protection"])
        assert lifecycle == after["lifecycle"]
        held = before["snapshot"]["context"]
        assert {name: again.context(stop)[name] for name in held} == held
    finally:
        await again.facade.stop()


async def test_b01_version_6_golden_snapshot_refused_then_rebuilt_from_order_events() -> None:
    """28 B1.8 version 7, the snapshot migration, on a golden snapshot: a recorded stop's row at
    rest in `submitted`, a state version 7 gives a `RECON_MISS` arm, sealed at version 6
    (`golden/order.v6_to_v7.before.json`, its seal genuine under version 6's chart) is refused by
    version 7's restore for its machine hash, quarantined and paged P1, and never loaded; no
    upcaster carries it, as B1 recovers from `order_events`: the row's history hydrates to the
    configuration `.after.json` names and to every context value the snapshot held."""
    before = json.loads((_GOLDEN / "order.v6_to_v7.before.json").read_text(encoding="utf-8"))
    after = json.loads((_GOLDEN / "order.v6_to_v7.after.json").read_text(encoding="utf-8"))
    key, seal = MachineKey(**before["key"]), Seal(**before["seal"])
    envelope = SealedSnapshot(
        key, before["version"], before["machine_hash"], before["snapshot"], seal
    )
    v6, keys, audit, pager = _version_6(CHART), Keys(), Audit(), Pager()
    assert machine_hash(v6) == before["machine_hash"] == V6_HASH != REGISTRY.hash("order")
    open_sealed(keys, v6, envelope, key=key, expected_machine_hash=V6_HASH)  # a genuine seal
    with pytest.raises(RestoreRefusedError) as refused:
        await _restorer(keys, audit, pager).restore(key, envelope)
    assert (refused.value.reason, len(audit.quarantined), pager.pages) == (
        after["refused"],
        1,
        ["P1"],
    )
    assert not has_upcaster("order", V6_HASH, REGISTRY.hash("order"))
    rig = build_rig(registry=REGISTRY)
    try:
        stop = await _recorded_stop(rig)
    except BaseException:
        await rig.facade.stop()  # B1's ports are process-wide: never left wired (C-2.11)
        raise
    again = await rig.restart()
    try:
        assert str(stop.id) == key.entity_id
        lifecycle = await again.facade.hydrate(ACCOUNT, stop.id, environment="demo")
        await again.quiet()
        assert again.facade.state(stop.id) == (lifecycle, after["protection"])
        assert lifecycle == after["lifecycle"]
        held = before["snapshot"]["context"]
        assert {name: again.context(stop)[name] for name in held} == held
    finally:
        await again.facade.stop()


async def test_b01_version_7_golden_snapshot_refused_then_rebuilt_from_order_events() -> None:
    """28 B1.8 version 8, the snapshot migration, on a golden snapshot: an order reconciliation
    discovered, at rest in `untracked`, the state version 8 gives its `EXEC` arms, sealed at
    version 7 (`golden/order.v7_to_v8.before.json`, its seal genuine under version 7's chart) is
    refused by version 8's restore for its machine hash, quarantined and paged P1, and never
    loaded; no upcaster carries it, as B1 recovers from `order_events`: the row's history
    hydrates to the configuration `.after.json` names and to every context value the snapshot
    held."""
    before = json.loads((_GOLDEN / "order.v7_to_v8.before.json").read_text(encoding="utf-8"))
    after = json.loads((_GOLDEN / "order.v7_to_v8.after.json").read_text(encoding="utf-8"))
    key, seal = MachineKey(**before["key"]), Seal(**before["seal"])
    envelope = SealedSnapshot(
        key, before["version"], before["machine_hash"], before["snapshot"], seal
    )
    v7, keys, audit, pager = _version_7(CHART), Keys(), Audit(), Pager()
    assert machine_hash(v7) == before["machine_hash"] == V7_HASH != REGISTRY.hash("order")
    open_sealed(keys, v7, envelope, key=key, expected_machine_hash=V7_HASH)  # a genuine seal
    with pytest.raises(RestoreRefusedError) as refused:
        await _restorer(keys, audit, pager).restore(key, envelope)
    assert (refused.value.reason, len(audit.quarantined), pager.pages) == (
        after["refused"],
        1,
        ["P1"],
    )
    assert not has_upcaster("order", V7_HASH, REGISTRY.hash("order"))
    rig = build_rig(registry=REGISTRY)
    try:
        found = await _untracked(rig)
    except BaseException:
        await rig.facade.stop()  # B1's ports are process-wide: never left wired (C-2.11)
        raise
    again = await rig.restart()
    try:
        assert str(found.id) == key.entity_id
        lifecycle = await again.facade.hydrate(ACCOUNT, found.id, environment="demo")
        await again.quiet()
        assert again.facade.state(found.id) == (lifecycle, after["protection"])
        assert lifecycle == after["lifecycle"]
        held = before["snapshot"]["context"]
        assert {name: again.context(found)[name] for name in held} == held
    finally:
        await again.facade.stop()


async def test_b01_untracked_row_with_a_fill_snapshot_round_trip_identical() -> None:
    """29 Sec.1.3 on version 8: a sealed snapshot of an `untracked` row that holds a partial fill
    (applied through the facade, written as an `untracked` to `untracked` step) restores the same
    configuration and context, its totals included, and the restore runs no step: it writes
    nothing and sends nothing."""
    rig = build_rig(registry=REGISTRY)
    try:
        found = await _untracked(rig)
        await rig.facade.push(ACCOUNT, found.id, "EXEC", fill_of(found, "e1", "0.4"))
        await rig.quiet()
        assert rig.facade.state(found.id) == ("untracked", "not_required")
        interp = rig.facade._orders[found.id].interp
        before = (set(interp.current_state_ids), copy.deepcopy(dict(interp.context)))
        assert (before[1]["filled_qty"], before[1]["seen_exec_ids"]) == ("0.4", ["e1"])
        events = await rig.events.list_for_order(ACCOUNT, found.id)
        key, keys = MachineKey("order", str(found.id), "demo"), Keys()
        envelope = await _sealed(interp, key, keys)
        restored = await _restorer(keys, Audit(), Pager()).restore(key, envelope)
        try:
            await settle()
            after = (
                set(restored.interpreter.current_state_ids),
                dict(restored.interpreter.context),
            )
            assert after == before and not restored.degraded
            assert await rig.events.list_for_order(ACCOUNT, found.id) == events
            assert rig.commands.sent == []
        finally:
            await restored.interpreter.stop()
    finally:
        await rig.facade.stop()


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
    "TERMS_CHANGED": {
        "exchange_order_id": "x1", "trigger_price": "61000", "qty": "1", "updated_time": 9
    },
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

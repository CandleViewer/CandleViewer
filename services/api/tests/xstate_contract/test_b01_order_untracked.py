"""tests/xstate_contract/test_b01_order_untracked.py: B1 chart version 8 (#914, E29-T06).

Membership module of the blocking gate for an `untracked` row's own fills (28 B1.8 version 8,
INV-B1-l, INV-B1-o, INV-5). An order reconciliation adopted takes `EXEC` on three ordered arms:
one that fills it goes to `filled`, one that leaves quantity open re-enters `untracked`, both
through `apply_untracked_exec`, and every other `EXEC` is consumed by `record_remote_state`. The
row is never managed: nothing is sent, no notice is posted and its protection region never starts
while it stays `untracked`. Each trace runs on the real binding with the recording step writer and
command port (`b01_ports`), on the library.
"""

from __future__ import annotations

import contextlib
from collections import OrderedDict
from collections.abc import AsyncIterator, Mapping
from decimal import Decimal
from typing import Any, Final

import pytest
from hypothesis import HealthCheck, example, given, settings
from hypothesis import strategies as st
from structlog.testing import capture_logs
from xstate_statemachine import SimulatedClock

from candleviewer.oms.execution import apply_fields
from candleviewer.oms.order_machine import Legality
from candleviewer.statechart import build
from candleviewer.statechart.bindings import b01_order as b01
from candleviewer.statechart.registry import Registry
from tests.unit.oms.order_rig import ACCOUNT, build_rig, fill_of, order_of
from tests.xstate_contract._harness import AuditTap, settle
from tests.xstate_contract.b01_ports import Commands, Store

REGISTRY = Registry()
CHART = REGISTRY.get("order")
#: Version 8's `EXEC` arms in `untracked`, in their order (28 B1.3).
ARMS: Final = [
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
_IDENTITY: Final = ("order_id", "order_link_id", "account_id", "symbol", "side")
_FOUND = {"order_id": str(order_of().id), "order_link_id": order_of().order_link_id}
_FOUND |= {"account_id": str(ACCOUNT), "symbol": "BTCUSDT", "side": "buy", "qty": "1"}
_FOUND |= {"price": "63000", "stop_loss": "62000", "exchange_order_id": "x1"}
#: The steps an `untracked` row writes: its first row, a miss or a partial fill back into it, and
#: the two ends a fill or a miss may take it to (INV-B1-l).
_WRITTEN: Final = {
    (None, "untracked"),
    ("untracked", "untracked"),
    ("untracked", "filled"),
    ("untracked", "cancelled"),
}
_HYP = settings(
    max_examples=40, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture]
)


def _exec(exec_id: str, qty: str, **over: Any) -> dict[str, Any]:
    """An `EXEC` of the discovered order, on its exchange order `x1` (or as *over* says)."""
    return fill_of(order_of(), exec_id, qty, exchange_order_id="x1") | over


def _leaf(interp: Any, region: str = "lifecycle") -> str:
    head = f"order.{region}."
    return str(next(s for s in interp.current_state_ids if s.startswith(head)))[len(head) :]


class _Event:
    """An event as an action reads it: its name and its payload."""

    def __init__(self, kind: str, payload: Mapping[str, Any]) -> None:
        self.type, self.payload = kind, dict(payload)


@contextlib.asynccontextmanager
async def _discovered() -> AsyncIterator[tuple[Any, Store, Commands]]:
    """An order reconciliation found on the exchange (`DISCOVERED`, bound to `x1`), on B1's real
    binding with the OMS's fill arithmetic, at rest in `untracked`."""
    store, commands = Store(), Commands()
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(b01, "_ATTEMPTS", OrderedDict())
        mp.setattr(b01, "_REPLAYS", {})
        mp.setattr(b01, "_ports", b01.OrderPorts(persist=store, commands=commands))
        mp.setattr(b01, "_core", apply_fields)
        built = await build(
            "order", clock=SimulatedClock(), lane="order", registry=REGISTRY, plugins=(AuditTap(),)
        )
        interp = built.interpreter
        try:
            await interp.send("DISCOVERED", wait=True, order=_FOUND)
            await settle()
            assert (_leaf(interp), interp.context["discovered"]) == ("untracked", True)
            yield interp, store, commands
        finally:
            await interp.stop()


async def _send(interp: Any, event: str, payload: Mapping[str, Any]) -> None:
    await interp.send(event, wait=True, **payload)
    await settle()


# --- The chart and its static table ------------------------------------------------------------


def test_inv_b1_l_untracked_takes_exec_on_three_ordered_arms() -> None:
    """28 B1.3 version 8: `untracked`'s `EXEC` group is the live states' two guards, each through
    `apply_untracked_exec`, the partial one re-entering `untracked`, then the unguarded
    `record_remote_state`; the OMS facade's static table, read from the chart, admits `EXEC` on
    both edges, so a recorded partial fill replays as an `EXEC` (24 Sec.8.2)."""
    untracked = CHART["states"]["lifecycle"]["states"]["untracked"]
    assert untracked["on"]["EXEC"] == ARMS and untracked["entry"] == ["persist_event"]
    legality = Legality.of(CHART)
    assert "EXEC" in legality.triggers[("untracked", "untracked")]
    assert legality.triggers[("untracked", "filled")] == {"EXEC", "RECON_FOUND_FILLED"}
    assert "EXEC" in legality.handled["untracked"]
    assert "untracked" not in legality.in_flight  # no invoke: nothing is ever sent from it


# --- The arms, on the real binding -------------------------------------------------------------


async def test_inv_b1_l_a_partial_exec_reenters_untracked_and_writes_the_fill() -> None:
    """`exec_new_and_partial` (an `EXEC` that leaves quantity open): the row re-enters
    `untracked`, so `persist_event` writes the fill as an `untracked` to `untracked` step with
    its execution, and the totals and `seen_exec_ids` move (S4); nothing is sent, no notice is
    posted and the protection region stays `not_required`."""
    async with _discovered() as (interp, store, commands):
        await _send(interp, "EXEC", _exec("e1", "0.4"))
        context = interp.context
        assert (_leaf(interp), _leaf(interp, "protection")) == ("untracked", "not_required")
        assert (context["filled_qty"], context["leaves_qty"]) == ("0.4", "0.6")
        assert (context["seen_exec_ids"], context["outbox"]) == (["e1"], [])
        step = store.steps[-1]
        assert (step.from_state, step.to_state, step.event) == ("untracked", "untracked", "EXEC")
        assert (dict(step.payload), step.context["filled_qty"]) == (_exec("e1", "0.4"), "0.4")
        assert commands.sent == []


@pytest.mark.parametrize(
    "fills",
    [
        [("e1", "1")],
        [("e1", "0.4"), ("e2", "0.6")],
        [("e1", "0.2"), ("e2", "0.3"), ("e3", "0.5")],
    ],
    ids=["one", "two", "three"],
)
async def test_inv_b1_l_the_exec_that_fills_the_order_takes_it_to_filled(
    fills: list[tuple[str, str]],
) -> None:
    """`exec_new_and_closes`: the `EXEC` that fills `qty`, alone or after partial fills, takes the
    row to `filled`, whose entry writes the `fill` step and posts the first fill and the end as
    for any order; nothing is sent from `untracked`."""
    async with _discovered() as (interp, store, commands):
        for exec_id, qty in fills:
            await _send(interp, "EXEC", _exec(exec_id, qty))
        assert (_leaf(interp), interp.context["filled_qty"]) == ("filled", "1")
        assert interp.context["seen_exec_ids"] == [exec_id for exec_id, _qty in fills]
        steps = [(s.from_state, s.to_state, s.event) for s in store.steps[1:]]
        partial = [("untracked", "untracked", "EXEC")] * (len(fills) - 1)
        assert steps == [*partial, ("untracked", "filled", "EXEC")]
        assert [n["kind"] for n in interp.context["outbox"]] == ["first_fill", "terminal"]
        assert commands.sent == []


@pytest.mark.parametrize(
    "then",
    [
        _exec("e1", "0.4"),  # a repeat (S4)
        _exec("e2", "0.4", exchange_order_id="x-other"),  # another exchange order's
        _exec("e2", "0.7"),  # past `qty` (INV-1)
        _exec("e2", "0.4", exec_type="funding"),  # not a trade
    ],
    ids=["repeat", "another_order", "past_qty", "not_a_trade"],
)
async def test_inv_5_an_exec_untracked_does_not_apply_is_recorded_never_deferred(
    then: dict[str, Any],
) -> None:
    """Both guards deny: the unguarded `record_remote_state` consumes the `EXEC`, logs it with
    its `exec_id` and restarts the miss count, never deferred (INV-5); no step is written, the
    totals stay as they were, and nothing is sent."""
    async with _discovered() as (interp, store, commands):
        await _send(interp, "EXEC", _exec("e1", "0.4"))
        await _send(interp, "RECON_MISS", {"pass_id": "p1"})
        assert interp.context["recon_misses"] == 1
        written, before = len(store.steps), dict(interp.context)
        with capture_logs() as logs:
            await _send(interp, "EXEC", then)
        seen = [e for e in logs if e["event"] == "b01_untracked_order_seen"]
        assert [(e["trigger"], e["exec_id"]) for e in seen] == [("EXEC", then["exec_id"])]
        assert (_leaf(interp), interp.deferred_count, len(store.steps)) == ("untracked", 0, written)
        assert dict(interp.context) == before | {"recon_misses": 0}
        assert commands.sent == []


async def test_inv_b1_l_an_applied_fill_restarts_the_miss_count() -> None:
    """An `EXEC` the row applies proves the order exists, as `record_remote_state` did for it in
    version 7: `apply_untracked_exec` restarts `recon_misses`, so a miss after it is a first one
    again and the row is not ended (24 Sec.8.5)."""
    async with _discovered() as (interp, _store, _commands):
        await _send(interp, "RECON_MISS", {"pass_id": "p1"})
        assert interp.context["recon_misses"] == 1
        await _send(interp, "EXEC", _exec("e1", "0.4"))
        assert (_leaf(interp), interp.context["recon_misses"]) == ("untracked", 0)
        await _send(interp, "RECON_MISS", {"pass_id": "p2"})
        assert (_leaf(interp), interp.context["recon_misses"]) == ("untracked", 1)


async def test_an_untracked_row_holding_a_fill_ends_cancelled_with_its_protection_handed_on() -> (
    None
):
    """Newly reachable in version 8 (#5157's code look): an `untracked` row that applied a partial
    fill and then misses twice ends `cancelled`, which `starts_protection` answers yes for, as it
    holds a fill (`_filled`): `cancelled`'s entry posts `first_fill`, then `terminal`, and nothing
    is ever sent (INV-B1-l, INV-B1-o)."""
    async with _discovered() as (interp, store, commands):
        await _send(interp, "EXEC", _exec("e1", "0.4"))
        await _send(interp, "RECON_MISS", {"pass_id": "p1"})
        await _send(interp, "RECON_MISS", {"pass_id": "p2"})
        assert (_leaf(interp), interp.context["filled_qty"]) == ("cancelled", "0.4")
        assert [n["kind"] for n in interp.context["outbox"]] == ["first_fill", "terminal"]
        steps = [(s.from_state, s.to_state) for s in store.steps[1:]]
        assert steps == [("untracked", "untracked")] * 2 + [("untracked", "cancelled")]
        assert commands.sent == []


async def test_the_facade_hands_a_cancelled_untracked_rows_position_to_b8() -> None:
    """The same trace through the facade (`OrderMachines`): the discovered order's `first_fill`
    starts no attach, as it is not the OMS's (`discovered`), so B1's region lands in `sl_missing`
    and the facade asks B8 for its fallback (`request_fallback_sl`), only as 24 Sec.8.8 rule 3's
    watchdog acts; nothing is sent to the venue (C-2.6)."""
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(b01, "_ATTEMPTS", OrderedDict())
        rig = build_rig()
        try:
            found = order_of(7, order_link_id="ext-" + "ab" * 16, exchange_order_id="x7")
            assert await rig.facade.discover(found, environment="demo") == "untracked"
            await rig.facade.push(ACCOUNT, found.id, "EXEC", fill_of(found, "e1", "0.4"))
            for pass_id in ("p1", "p2"):
                miss = {"pass_id": pass_id}
                await rig.facade.command(ACCOUNT, found.id, "RECON_MISS", miss, actor="system")
                await rig.quiet()
            row = await rig.orders.get(ACCOUNT, found.id)
            assert row is not None
            assert (row.state, row.cum_exec_qty) == ("cancelled", Decimal("0.4"))
            assert rig.commands.sent == []
            assert [(n.kind, dict(n.detail)) for n in rig.notices.got] == [
                ("alert", {"alert": "SL_ATTACH_FAILED"}),
                ("request_fallback_sl", {}),
            ]
        finally:
            await rig.facade.stop()


async def test_a_hydrated_untracked_row_keeps_the_fill_that_restarted_its_miss_count() -> None:
    """#5157's code look (its optional item): a row whose history is `RECON_MISS` then `EXEC`,
    each an `untracked` to `untracked` step, hydrates from `order_events` (24 Sec.8.2 Recovery) to
    the context the live machine held: the fill applied and `recon_misses` back to 0, so the next
    miss after the restart is a first one and the row is not ended (INV-B1-l)."""
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(b01, "_ATTEMPTS", OrderedDict())
        rig = build_rig()
        found = order_of(7, order_link_id="ext-" + "ab" * 16, exchange_order_id="x7")
        try:
            assert await rig.facade.discover(found, environment="demo") == "untracked"
            await rig.facade.command(
                ACCOUNT, found.id, "RECON_MISS", {"pass_id": "p1"}, actor="system"
            )
            await rig.facade.push(ACCOUNT, found.id, "EXEC", fill_of(found, "e1", "0.4"))
            await rig.quiet()
            held = ("recon_misses", "filled_qty", "seen_exec_ids", "discovered")
            live = {name: rig.context(found)[name] for name in held}
            assert live == {
                "recon_misses": 0, "filled_qty": "0.4", "seen_exec_ids": ["e1"], "discovered": True,
            }  # fmt: skip
        except BaseException:
            await rig.facade.stop()
            raise
        again = await rig.restart()
        try:
            events = await again.events.list_for_order(ACCOUNT, found.id)
            assert [(e.from_state, e.to_state) for e in events] == [
                (None, "untracked"), ("untracked", "untracked"), ("untracked", "untracked"),
            ]  # fmt: skip
            assert await again.facade.hydrate(ACCOUNT, found.id, environment="demo") == "untracked"
            await again.quiet()
            assert {name: again.context(found)[name] for name in held} == live
            await again.facade.command(
                ACCOUNT, found.id, "RECON_MISS", {"pass_id": "p2"}, actor="system"
            )
            await again.quiet()
            states = again.facade.state(found.id)
            assert states is not None and states[0] == "untracked"
            assert again.context(found)["recon_misses"] == 1
            assert again.commands.sent == []
        finally:
            await again.facade.stop()


async def test_a_findings_execution_is_still_only_recorded_in_untracked() -> None:
    """28 B1.8 version 8 (d): `RECON_FOUND_PARTIAL` keeps version 7's arm, so an execution it
    carries is recorded, never applied: an `untracked` row's fills reach it as `EXEC`."""
    async with _discovered() as (interp, store, _commands):
        found = {"exchange_order_id": "x1", "execution": _exec("e1", "0.4"), "pass_id": "p1"}
        await _send(interp, "RECON_FOUND_PARTIAL", found)
        assert (_leaf(interp), interp.context["filled_qty"]) == ("untracked", "0")
        assert (interp.context["seen_exec_ids"], len(store.steps)) == ([], 1)


# --- The action and the protection question ----------------------------------------------------


async def test_apply_untracked_exec_applies_the_fill_and_posts_nothing() -> None:
    """S4 as `apply_fill` applies it (the totals, `seen_exec_ids`), the miss count restarted, no
    notice posted (the row is never managed), and the applied fill logged by its `exec_id`."""
    context = dict(CHART["context"]) | {key: _FOUND[key] for key in _IDENTITY}
    context |= {"qty": "1", "leaves_qty": "1", "exchange_order_id": "x1", "recon_misses": 2}
    with pytest.MonkeyPatch.context() as mp, capture_logs() as logs:
        mp.setattr(b01, "_core", apply_fields)
        await b01.apply_untracked_exec(None, context, _Event("EXEC", _exec("e1", "0.4")), None)
    assert (context["filled_qty"], context["leaves_qty"]) == ("0.4", "0.6")
    assert (context["seen_exec_ids"], context["recon_misses"], context["outbox"]) == (["e1"], 0, [])
    [entry] = [e for e in logs if e["event"] == "b01_untracked_fill_applied"]
    assert (entry["exec_id"], entry["order_link_id"]) == ("e1", _FOUND["order_link_id"])


def test_inv_b1_o_starts_protection_answers_no_while_untracked() -> None:
    """INV-B1-o, version 8: an `untracked` row's fills start nothing while it stays `untracked`,
    after a hydration too, as it held none in version 7; the same row in `filled` starts the
    region, as any order's fill does."""
    held = {"filled_qty": "0.4", "reduce_only": False}
    assert not b01.starts_protection(held, "untracked")
    assert not b01.starts_protection(held, "untracked", "EXEC")
    assert b01.starts_protection(held, "filled") and b01.starts_protection(held, "cancelled")


# --- INV-B1-l: never managed, whatever reaches it ----------------------------------------------

_EXECS = st.tuples(
    st.just("EXEC"),
    st.sampled_from(("e1", "e2", "e3", "e4")),
    st.sampled_from(("0.2", "0.3", "0.5", "1.5")),
    st.booleans(),  # another exchange order's
)
_OTHERS = st.tuples(
    st.sampled_from(
        (
            "RECON_FOUND_LIVE",
            "RECON_FOUND_PARTIAL",
            "RECON_MISS",
            "CANCEL",
            "AMEND",
            "SEND",
            "VALIDATE",
            "KILL",
            "ADOPT",
        )
    ),
    st.just(""),
    st.just(""),
    st.just(False),
)
_PAYLOADS: Final[dict[str, dict[str, Any]]] = {
    "RECON_FOUND_LIVE": {"exchange_order_id": "x1", "pass_id": "p1"},
    "RECON_FOUND_PARTIAL": {
        "exchange_order_id": "x1",
        "execution": _exec("e9", "0.1"),
        "pass_id": "p1",
    },
    "RECON_MISS": {"pass_id": "p1"},
    "CANCEL": {},
    "AMEND": {"price": "64000"},
    "SEND": {},
    "VALIDATE": {},
    "KILL": {"reason": "kill"},
    "ADOPT": {},
}


@_HYP
@given(events=st.lists(st.one_of(_EXECS, _OTHERS), max_size=10))
@example(events=[("EXEC", "e1", "0.5", False), ("EXEC", "e2", "0.5", False)])
@example(events=[("EXEC", "e1", "0.5", False), ("EXEC", "e1", "0.5", False)])
@example(events=[("RECON_MISS", "", "", False), ("EXEC", "e1", "0.2", False)] * 2)
async def test_inv_b1_l_an_untracked_row_is_never_managed_property(
    events: list[tuple[str, str, str, bool]],
) -> None:
    """Whatever reaches an `untracked` row (its own fills, repeats, another order's, fills past
    `qty`, findings, misses, commands, a KILL, an ADOPT), on the real binding: nothing is ever
    sent; while it stays `untracked` no notice is posted and its protection region never starts;
    it applies exactly its own new fills, which `filled_qty` sums; it leaves only for `filled`,
    once its fills reach `qty`, or for `cancelled`, on a second consecutive miss; and every step
    it writes is one of those (INV-B1-l, INV-B1-o, SR-E29-12)."""
    async with _discovered() as (interp, store, commands):
        leaf, applied, misses = "untracked", dict[str, Decimal](), 0
        for kind, exec_id, qty, foreign in events:
            if kind == "EXEC":
                over = {"exchange_order_id": "x-other"} if foreign else {}
                await _send(interp, "EXEC", _exec(exec_id, qty, **over))
                total = sum(applied.values(), Decimal(0)) + Decimal(qty)
                if not foreign and exec_id not in applied and total <= 1:
                    applied[exec_id] = Decimal(qty)
                    leaf = "filled" if total == 1 else leaf
                misses = 0
            else:
                await _send(interp, kind, _PAYLOADS[kind])
                if kind == "RECON_MISS":
                    leaf, misses = ("cancelled", misses) if misses else (leaf, 1)
                elif kind.startswith("RECON_FOUND"):
                    misses = 0
            assert _leaf(interp) == leaf and commands.sent == []
            assert Decimal(interp.context["filled_qty"]) == sum(applied.values(), Decimal(0))
            assert interp.context["seen_exec_ids"] == list(applied)
            assert {(s.from_state, s.to_state) for s in store.steps} <= _WRITTEN
            if leaf != "untracked":
                break
            assert (_leaf(interp, "protection"), interp.context["outbox"]) == ("not_required", [])
            assert interp.context["recon_misses"] == misses
        if leaf == "filled":
            assert interp.context["filled_qty"] == "1"

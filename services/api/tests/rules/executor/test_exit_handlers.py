"""E35-T12 slice 3e: a rule's cancels and amends, check 8 bound, and the circuit breaker's cancels
(24 §11.5 "Exits", check 8, §11.7, §15.5; the rulings of record on #5004, BQ-2, BQ-3, BQ-7 to
BQ-10).

The executor runs as a dispatch worker runs it (`ActionExecutor`), its checks' ports and records in
memory; the handlers, check 8's port and the breaker's cancels are the composition root's
(`rules_oms_exits`), over the real exit service (`OrderExits`: B1's facade, the command port, a
demo `FakeTradingPort`, C-13.5) and a read of the rule's resting entries that selects, from the
rig's store, what `rule_entries_statement` selects on Postgres (its own Postgres row is in the
integration suite). The rule's entries are the pipeline's, placed with the rule's origin. Every
cancel and amend test holds C-2.6: a stop is never removed or loosened
(`assert_position_stop_untouched`). No sleeps.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass, field, replace
from decimal import Decimal
from typing import Any

import pytest

from candleviewer.oms.ports import RequestRecord, RuleOrigin
from candleviewer.rules.executor import gates as gates_module
from candleviewer.rules.executor.budget import CircuitBreaker, OrderBudget
from candleviewer.rules.executor.dispatch import Fire
from candleviewer.rules.executor.engine import ActionExecutor, RowVerdict
from candleviewer.rules.executor.gates import Gates, Halts
from candleviewer.rules.executor.handlers import HANDLERS, BoundHandler, bind_handlers
from candleviewer.rules.executor.ports import STOP_ADMITTED, StopVerdict
from candleviewer.rules.executor.results import BLOCKED_DETAIL, NODE_ID, OMS_DETAIL, POSITION_STOP
from candleviewer.rules.ir.models import RuleLimits
from candleviewer.rules.scope import ActionRequest
from candleviewer.rules_oms_exits import (
    AMEND_TYPES,
    CANCEL_TYPES,
    RuleBreakerCancels,
    RuleStopCheck,
    rule_exit_handlers,
    rule_reduce_handlers,
)
from candleviewer.storage.repositories.orders import OPEN_STATES, OrderRow
from candleviewer.storage.repositories.orders_sqlalchemy import RULE_ENTRY_STATES
from candleviewer.storage.repositories.trade_groups import TradeGroupRecord
from tests.rules.executor.native_sl import assert_position_stop_untouched
from tests.rules.executor.request_builders import Facts, Principals, Records, Switches
from tests.rules.executor.test_order_handlers import GUARD_S, OWNER, RULE, RUN, RUN_2, NoHistory
from tests.rules.executor.test_reduce_only_handlers import Held, exit_request, stored
from tests.unit.oms import command_rig as cr
from tests.unit.oms import submit_rig as sr
from tests.unit.oms.submit_rig import SubmitRig
from tests.unit.oms.test_exits import exits_of
from tests.unit.oms.test_submit_rule_origin import rule_context

OTHER_RULE = uuid.UUID("4c3d2e1f-0a9b-4c8d-8e7f-6a5b4c3d2e1f")
RULE_ID = uuid.UUID(RULE)
STOP, TAKE_PROFIT = sr.STOP, sr.TAKE_PROFIT
TIGHTER, LOOSER = Decimal("59000"), Decimal("57000")


@dataclass
class Entries:
    """`RuleEntries` over the rig's store: what `rule_entries_statement` selects (its groups'
    orders through `origin_rule_id`, `placed`, open, not reduce-only, no parent, a group whose
    algo is `none`), oldest first; a read can fail."""

    rig: SubmitRig
    fails: bool = False
    asked: list[tuple[uuid.UUID, uuid.UUID | None, str | None]] = field(default_factory=list)

    async def rule_resting_entries(
        self,
        rule_id: uuid.UUID,
        environment: Any,
        *,
        account_id: uuid.UUID | None = None,
        symbol: str | None = None,
        limit: int,
    ) -> tuple[OrderRow, ...]:
        self.asked.append((rule_id, account_id, symbol))
        if self.fails:
            raise ConnectionError("the entries read failed")
        groups: dict[uuid.UUID, TradeGroupRecord] = self.rig.store._groups
        legs = {
            leg.id: record.group
            for record in groups.values()
            for leg in record.legs
            if record.group.origin_rule_id == rule_id and record.group.algo == "none"
            and record.group.env == environment
        }  # fmt: skip
        rows = [
            row for row in self.rig.store._orders.values()
            if row.trade_group_leg_id in legs and row.provenance == "placed"
            and not row.reduce_only and row.parent_order_id is None
            and row.state in OPEN_STATES and row.lifecycle_state in RULE_ENTRY_STATES
            and account_id in (None, row.exchange_account_id) and symbol in (None, row.symbol)
        ]  # fmt: skip
        return tuple(sorted(rows, key=lambda row: (row.created_ts, row.id))[:limit])


class Runtime:
    """`ExitRuntime` over the rig's exit service."""

    def __init__(self, exits: Any) -> None:
        self.exits = exits


@dataclass
class Rig:
    """One executor over the rig's exit service (module docstring), the exits bound."""

    rig: SubmitRig
    records: Records
    principals: Principals
    entries: Entries
    held: Held
    stops: Any
    halts: Halts = field(default_factory=Halts)
    tasks: list[asyncio.Task[None]] = field(default_factory=list)
    executor: ActionExecutor = field(init=False)

    async def check_one(self, req: ActionRequest) -> RowVerdict:
        return "armed"

    async def emit(self, req: ActionRequest) -> str | None:
        await self.executor.hand_over(req)
        return None

    async def run(self, *reqs: ActionRequest) -> None:
        fire = Fire(
            RULE, reqs[0].run_id, reqs, self.emit, version_id=str(uuid.UUID(int=0xC0)),
            trigger_type="on_bar_close", limits=RuleLimits(),
        )  # fmt: skip
        async with asyncio.timeout(GUARD_S):
            await self.executor.execute(fire)
            if self.tasks:
                await asyncio.gather(*self.tasks)
            await self.rig.quiet()

    def outcomes(self) -> list[tuple[str, str, str | None]]:
        """`(node, outcome, blocked_by or error_code)` of each result, in order."""
        return [
            (p["node_id"], p["outcome"], p["blocked_by"] or p["error_code"])
            for p in (dict(e.payload) for _, e in self.records.events)
            if "outcome" in p
        ]

    def detail(self) -> list[str | None]:
        return [dict(e.payload).get("blocked_detail") for _, e in self.records.events]

    def calls(self, method: str) -> list[Any]:
        return [c for c in self.rig.port.demo.calls if c.method == method]

    async def state(self, order: uuid.UUID) -> OrderRow:
        row = await self.rig.port.orders.get(cr.ACCOUNT, order)
        assert row is not None
        return row


def build(rig: SubmitRig, *, stops: Any = None, budget: OrderBudget | None = None) -> Rig:
    principals, records, held = Principals(frozenset({cr.ACCOUNT})), Records(), Held()
    entries = Entries(rig)

    def runtime() -> Runtime:
        return Runtime(exits_of(rig))

    port = (
        RuleStopCheck(principals, entries, held, "demo") if stops is None else stops
    )  # check 8's port: the composition root's unless a test hands its own
    built = Rig(rig, records, principals, entries, held, port)
    breaker = RuleBreakerCancels(runtime, principals, entries, "demo", None)

    def cancels(req: ActionRequest) -> None:
        built.tasks.append(asyncio.ensure_future(breaker.cancel_resting(req)))

    async def moved(_rule_id: str) -> bool:
        return True

    handlers: dict[str, BoundHandler] = dict(
        rule_exit_handlers(runtime, principals=principals, entries=entries, environment="demo")
    )
    handlers |= rule_reduce_handlers(
        lambda: None, oms_enabled=lambda: True, principals=principals, positions=held
    )
    built.executor = ActionExecutor(
        check_one=built.check_one, scope_check=lambda req: None,
        gates=Gates(switches=Switches(), principal=principals, stop=port), records=records,
        audit=records, handlers=bind_handlers(HANDLERS, handlers), halts=built.halts,
        budget=budget or OrderBudget(rebuild=NoHistory()),
        breaker=CircuitBreaker(built.halts, move=moved, cancels=cancels),
    )  # fmt: skip
    return built


def origin(rule: uuid.UUID = RULE_ID) -> RuleOrigin:
    return RuleOrigin(
        rule_id=rule, version=3, run_id=uuid.uuid4(), node_id="a1", armed_by=None,
        armed_by_role=None,
    )  # fmt: skip


async def resting(rig: SubmitRig, rule: uuid.UUID | None = RULE_ID, **over: Any) -> OrderRow:
    """A limit buy entry resting at the venue (`submitted`), with its native stop and take-profit:
    the rule's (its group's `origin_rule_id`), another rule's, or a user's (`rule` None)."""
    context = (
        sr.context(client_ref=uuid.uuid4())
        if rule is None
        else rule_context(origin=origin(rule), client_ref=uuid.uuid4())
    )
    outcome = await rig.submit(sr.entry(**over), context)
    await rig.quiet()
    assert outcome.order_id is not None
    row = await rig.port.orders.get(cr.ACCOUNT, outcome.order_id)
    assert row is not None and rig.machines.state(row.id) == ("submitted", "not_required")
    return row


async def rule_close(rig: SubmitRig) -> OrderRow:
    """The rule's own reduce-only limit close, resting: a reduce-only exit (C-2.6)."""
    rig.port.demo.seed_position(cr.position(qty="0.050", stop_loss=STOP))
    close = sr.flatten(order_type="limit", price=Decimal("61000"))
    outcome = await rig.submit(close, rule_context(origin=origin(), client_ref=uuid.uuid4()))
    await rig.quiet()
    assert outcome.order_id is not None
    row = await rig.port.orders.get(cr.ACCOUNT, outcome.order_id)
    assert row is not None and row.reduce_only
    return row


def requests(rig: SubmitRig, action: str) -> list[RequestRecord]:
    """The exit service's own records of `action`, in order."""
    return [r for r in rig.records(action) if isinstance(r, RequestRecord)]


@pytest.fixture
async def rig() -> AsyncIterator[SubmitRig]:
    async with sr.rigged() as built:
        built.store.seed_owner(OWNER)
        yield built


async def test_no_rule_can_remove_or_loosen_a_native_stop(rig: SubmitRig) -> None:
    """G "No rule can remove or loosen a native stop (parent Gherkin 4, failure case)": a rule of
    an Owner holding every permission moves its resting entry's stop away from the market; check 8
    refuses it, never clamped: `blocked` (`native_sl`) before the OMS, `sl.loosen_refused` written
    ahead with the stop before and after, then `rules.blocked`, never `rules.fired`; nothing is
    sent and the stop stays. `only_tighten: false` is a loosening too. The OMS's own ratchet stays
    last: past a check that admits all, the exit service refuses the loosening itself."""
    entry = await resting(rig)
    owner = build(rig)
    assert owner.principals.principal(OWNER) is not None
    loosen = {"mode": "absolute", "value": str(LOOSER)}
    await owner.run(
        exit_request("modify_stop_loss", loosen, node="s1", on_error="continue"),
        exit_request("tighten_stop", {"mode": "absolute", "value": str(TIGHTER),
                                      "only_tighten": False}, node="s2"),
    )  # fmt: skip
    assert owner.outcomes() == [("s1", "blocked", "native_sl"), ("s2", "blocked", "native_sl")]
    assert [v for v, _ in owner.records.audits] == [
        "sl.loosen_refused", "rules.blocked", "sl.loosen_refused", "rules.blocked",
    ]  # fmt: skip
    first, second = owner.records.loosened
    assert (first.order_id, first.before, first.after) == (entry.id, STOP, LOOSER)
    assert (second.order_id, second.before, second.after) == (None, None, None)
    assert owner.calls("amend_order") == [] and set(owner.detail()) == {BLOCKED_DETAIL["native_sl"]}
    after = await owner.state(entry.id)
    assert_position_stop_untouched("Buy", before=STOP, after=after.stop_loss)

    class Admits:
        async def judge(self, req: ActionRequest, account_id: Any) -> StopVerdict:
            return STOP_ADMITTED

    last = build(rig, stops=Admits())
    await last.run(exit_request("modify_stop_loss", loosen, run=RUN_2))
    assert last.outcomes() == [("x1", "blocked", "native_sl")]
    assert last.calls("amend_order") == []
    denied = [r for r in requests(rig, "orders.amend") if r.outcome == "denied"]
    assert [r.reason for r in denied] == ["risk_limit_breached"]
    assert_position_stop_untouched("Buy", before=STOP, after=(await last.state(entry.id)).stop_loss)


async def test_a_failed_stop_read_refuses_as_native_sl(
    rig: SubmitRig, monkeypatch: pytest.MonkeyPatch
) -> None:
    """BQ-2: check 8's read that fails, or that does not answer within its bound, refuses the
    action `native_sl` (fail closed), with no loosen record as no loosening is known, and nothing
    is sent."""
    entry = await resting(rig)
    failed = build(rig)
    failed.entries.fails = True
    await failed.run(exit_request("tighten_stop", {"mode": "absolute", "value": str(TIGHTER)}))
    assert failed.outcomes() == [("x1", "blocked", "native_sl")]
    assert [v for v, _ in failed.records.audits] == ["rules.blocked"]

    class Hangs:
        async def judge(self, req: ActionRequest, account_id: Any) -> StopVerdict:
            await asyncio.Event().wait()
            return STOP_ADMITTED

    monkeypatch.setattr(gates_module, "STOP_CHECK_TIMEOUT_S", 0.0)
    late = build(rig, stops=Hangs())
    await late.run(
        exit_request("modify_stop_loss", {"mode": "absolute", "value": "59000"}, run=RUN_2)
    )
    assert late.outcomes() == [("x1", "blocked", "native_sl")]
    assert failed.calls("amend_order") == []
    assert_position_stop_untouched(
        "Buy", before=STOP, after=(await failed.state(entry.id)).stop_loss
    )


async def test_tighten_on_a_resting_order_is_sent_and_recorded(rig: SubmitRig) -> None:
    """G "A tightening of a resting order is sent and recorded": `modify_stop_loss`,
    `tighten_stop` and `modify_take_profit` on the rule's resting entry each go through the amend
    path, on `entry` (a rule's send), recorded as the rule's (`orders.amend`, reason `rule`) and
    `ok`; the stop only ever tightens."""
    entry = await resting(rig)
    exits = build(rig)
    await exits.run(
        exit_request("modify_stop_loss", {"mode": "absolute", "value": "58500"}, node="m1"),
        exit_request("tighten_stop", {"mode": "offset_from_entry", "value": "1000"}, node="m2"),
        exit_request("modify_take_profit", {"mode": "absolute", "value": "63000"}, node="m3"),
    )
    assert exits.outcomes() == [("m1", "ok", None), ("m2", "ok", None), ("m3", "ok", None)]
    sent = exits.calls("amend_order")
    assert [c.lane for c in sent] == ["entry"] * 3
    assert [(c.request.stop_loss, c.request.take_profit) for c in sent] == [
        (Decimal("58500"), TAKE_PROFIT), (Decimal("59000"), TAKE_PROFIT),
        (Decimal("59000"), Decimal("63000")),
    ]  # fmt: skip
    amended = [r for r in requests(rig, "orders.amend") if r.outcome == "success"]
    assert {r.reason for r in amended} >= {"rule"}
    assert all(r.origin is not None for r in amended if r.reason == "rule")
    assert [v for v, _ in exits.records.audits] == ["rules.fired"] * 3
    after = await exits.state(entry.id)
    assert_position_stop_untouched("Buy", before=STOP, after=after.stop_loss)
    assert after.stop_loss == Decimal("59000")


async def test_cancel_all_orders_never_cancels_a_stop_or_take_profit(rig: SubmitRig) -> None:
    """G "cancel_all_orders never cancels a protective order (failure case)": on an account
    holding the rule's resting entry with its stop and take-profit, and the rule's own resting
    reduce-only close, `cancel_all_orders` cancels the entry alone, through the exit service with
    the reason `rule` on `entry`; the reduce-only close stays, as does the position's stop. A
    `purpose` naming a stop-loss is refused at check 8 (`native_sl`), nothing sent; one naming a
    take-profit selects nothing (C-2.6)."""
    close = await rule_close(rig)
    entry = await resting(rig)
    exits = build(rig)
    exits.held.rows[cr.ACCOUNT] = [stored(qty="0.050")]
    await exits.run(exit_request("cancel_all_orders"))
    assert exits.outcomes() == [("x1", "ok", None)]
    assert [c.lane for c in exits.calls("cancel_order")] == ["entry"]
    assert (await exits.state(entry.id)).lifecycle_state == "cancelled"
    assert (await exits.state(close.id)).lifecycle_state == "submitted"
    rule = [r for r in requests(rig, "orders.cancel") if r.reason == "rule"]
    assert [r.object_id for r in rule] == [entry.id]
    guarded = build(rig)
    await guarded.run(
        exit_request("cancel_all_orders", {"purpose": "stop_loss"}, node="c1", on_error="continue"),
        exit_request("cancel_all_orders", {"purpose": "take_profit"}, node="c2", run=RUN),
    )
    assert guarded.outcomes() == [("c1", "blocked", "native_sl"), ("c2", "ok", None)]
    assert len(guarded.calls("cancel_order")) == 1 and guarded.records.loosened == []
    [venue] = await rig.port.demo.positions(cr.ref(cr.ACCOUNT))
    assert_position_stop_untouched("Buy", before=STOP, after=venue.stop_loss)


async def test_cancel_order_never_touches_another_rules_children(rig: SubmitRig) -> None:
    """G "A rule never touches another rule's or algo's orders (E11)": `cancel_order` cancels the
    rule's own resting entry on the instance's symbol, under its `purpose`; another rule's entry,
    a user's manual entry and an algo's child (a group whose algo is not `none`) stay resting,
    whatever `exclude_algo_children` reads (BQ-7, BQ-8)."""
    own = await resting(rig)
    theirs = await resting(rig, OTHER_RULE)
    manual = await resting(rig, None)
    child = await resting(rig, price=Decimal("59500"))
    group = next(r for r in rig.store._groups.values() if child.trade_group_leg_id in
                 {leg.id for leg in r.legs})  # fmt: skip
    rig.store._groups[group.group.id] = replace(group, group=replace(group.group, algo="twap"))
    exits = build(rig)
    scope = {"exclude_algo_children": False}
    await exits.run(exit_request("cancel_order", {"purpose": "entry"}, scope=scope))
    assert exits.outcomes() == [("x1", "ok", None)]
    assert (await exits.state(own.id)).lifecycle_state == "cancelled"
    for kept in (theirs, manual, child):
        assert rig.machines.state(kept.id) == ("submitted", "not_required"), kept.id
    assert [c.lane for c in exits.calls("cancel_order")] == ["entry"]
    assert exits.entries.asked == [(uuid.UUID(RULE), cr.ACCOUNT, cr.SYMBOL)]
    assert_position_stop_untouched(
        "Buy", before=STOP, after=(await exits.state(theirs.id)).stop_loss
    )


async def test_breaker_cancels_the_rules_resting_entries_only(rig: SubmitRig) -> None:
    """G "The breaker cancels only the tripped rule's resting entries": the order budget spent,
    the rule's next order trips its breaker; after the B9 move its resting entries, found through
    their groups, are cancelled through the exit service with the reason `rule_circuit_breaker`
    on the `critical` lane (E35-T11's lane rule), each record naming the tripped rule; its
    reduce-only close and another rule's entry are never cancelled, nor is any stop."""
    close = await rule_close(rig)
    own = await resting(rig)
    theirs = await resting(rig, OTHER_RULE)

    class Spent:
        async def order_ages(self, rule_id: str, *, limit: int) -> tuple[float, ...]:
            return (1.0,) * 10

    exits = build(rig, budget=OrderBudget(rebuild=Spent()))
    exits.held.rows[cr.ACCOUNT] = [stored(qty="0.050")]
    await exits.run(exit_request("scale_out", {"order_type": "market", "qty_pct": "10"}))
    assert exits.outcomes() == [("x1", "blocked", "order_budget")]
    assert exits.halts.tripped.get(RULE) is not None and len(exits.tasks) == 1
    assert (await exits.state(own.id)).lifecycle_state == "cancelled"
    assert [c.lane for c in exits.calls("cancel_order")] == ["critical"]
    for kept in (close, theirs):
        assert rig.machines.state(kept.id) == ("submitted", "not_required")
    tripped = [r for r in requests(rig, "orders.cancel") if r.reason == "rule_circuit_breaker"]
    assert [r.object_id for r in tripped] == [own.id]
    assert {(r.detail["rule_id"], r.detail["rule_version"]) for r in tripped} == {(RULE, "1")}
    [venue] = await rig.port.demo.positions(cr.ref(cr.ACCOUNT))
    assert_position_stop_untouched("Buy", before=STOP, after=venue.stop_loss)


async def test_position_level_stop_moves_block_as_unavailable(rig: SubmitRig) -> None:
    """G "Position-level stop moves block as unavailable (edge case)": with no resting order of
    the rule to move, each stop or take-profit move is a move of the open position's stop, which
    waits for `setPositionTpSl` (#915): blocked `unavailable` at check 8, its detail saying so,
    nothing sent; `move_to_breakeven` is `unavailable` at check 2, its handler table row naming
    what it waits for. The position's stop is untouched."""
    rig.port.demo.seed_position(cr.position(qty="0.050", stop_loss=STOP))
    exits = build(rig)
    exits.held.rows[cr.ACCOUNT] = [stored(qty="0.050")]
    moves = [
        exit_request(t, {"mode": "absolute", "value": str(TIGHTER)}, node=f"p{n}",
                     on_error="continue")
        for n, t in enumerate(AMEND_TYPES)
    ] + [exit_request("move_to_breakeven", {}, node="p9")]  # fmt: skip
    await exits.run(*moves)
    assert [(o, r) for _, o, r in exits.outcomes()] == [("blocked", "unavailable")] * 4
    # decided before the records written ahead: `rules.blocked` alone, never `rules.fired`
    assert [v for v, _ in exits.records.audits] == ["rules.blocked"] * 4
    assert exits.detail()[-4:] == [BLOCKED_DETAIL[POSITION_STOP]] * 3 + [
        BLOCKED_DETAIL["unavailable"]
    ]
    assert "setPositionTpSl" in str(HANDLERS["move_to_breakeven"].waits_for)
    assert exits.calls("amend_order") == [] and exits.calls("set_trading_stop") == []
    [venue] = await rig.port.demo.positions(cr.ref(cr.ACCOUNT))
    assert_position_stop_untouched("Buy", before=STOP, after=venue.stop_loss)


async def test_an_amend_whose_level_the_snapshot_cannot_give_fails_with_nothing_sent(
    rig: SubmitRig,
) -> None:
    """BQ-9: `atr`, `structure` and `offset_from_price` read the fire's snapshot; one that does
    not hold the value fails the amend (`metric_unavailable`), nothing sent; one that holds it
    sets the level from it."""
    entry = await resting(rig)
    exits = build(rig)
    await exits.run(exit_request("tighten_stop", {"mode": "atr", "value": "2"}))
    assert exits.outcomes() == [("x1", "failed", "metric_unavailable")]
    assert exits.calls("amend_order") == []
    snapshot = {"atr": Decimal("400"), "price": Decimal("60100")}
    held = replace(
        exit_request("tighten_stop", {"mode": "atr", "value": "2"}, run=RUN_2),
        metric_values=snapshot,
    )
    await exits.run(held)
    [sent] = exits.calls("amend_order")
    assert sent.request.stop_loss == Decimal("59200")  # 60000 - 2 x 400
    assert_position_stop_untouched(
        "Buy", before=STOP, after=(await exits.state(entry.id)).stop_loss
    )


@pytest.mark.parametrize("action_type", CANCEL_TYPES + AMEND_TYPES)
async def test_a_refused_rule_origin_fails_each_cancel_and_amend_as_invalid_params(
    rig: SubmitRig, action_type: str
) -> None:
    """A node id the OMS's rule origin refuses (24 §11.5 "Exits"): each cancel and amend is
    `failed` (`invalid_params`), never a raise, its detail the generic sentence, which never
    holds the id; nothing is sent."""
    entry = await resting(rig)
    exits = build(rig)
    odd = "n" * 65
    params = {} if action_type in CANCEL_TYPES else {"mode": "absolute", "value": "58500"}
    await exits.run(exit_request(action_type, params, node=odd))
    [result] = [dict(e.payload) for _, e in exits.records.events if e.kind == "action_fail"]
    assert (result["outcome"], result["error_code"]) == ("failed", "invalid_params")
    assert result["blocked_detail"] == OMS_DETAIL[NODE_ID]
    assert exits.calls("amend_order") == [] and exits.calls("cancel_order") == []
    assert_position_stop_untouched(
        "Buy", before=STOP, after=(await exits.state(entry.id)).stop_loss
    )


async def test_a_cancel_or_amend_outside_the_intersection_or_by_a_view_only_armer_is_blocked(
    rig: SubmitRig,
) -> None:
    """The cross-account and forbidden-role cases: an action on an account the armer's grants do
    not reach, or by an armer whose grant is view-only, is blocked at check 5 (`permission`),
    nothing read and nothing sent; the entry's stop is untouched (C-2.6)."""
    entry = await resting(rig)
    narrowed: list[Facts] = [
        (True, "manager", False, frozenset()), (True, "viewer", False, frozenset()),
    ]  # fmt: skip
    for facts in narrowed:
        exits = build(rig)
        exits.principals.facts[uuid.UUID(exits_armer())] = facts
        await exits.run(
            exit_request("cancel_order", node="c1", on_error="continue"),
            exit_request("modify_stop_loss", {"mode": "absolute", "value": "58500"}, node="c2"),
        )
        assert {(o, r) for _, o, r in exits.outcomes()} == {("blocked", "permission")}
        assert exits.entries.asked == [] and exits.calls("cancel_order") == []
        assert exits.calls("amend_order") == []
        assert_position_stop_untouched(
            "Buy", before=STOP, after=(await exits.state(entry.id)).stop_loss
        )


def exits_armer() -> str:
    """The armer `exit_request` names."""
    return str(exit_request("cancel_order").armed_by)

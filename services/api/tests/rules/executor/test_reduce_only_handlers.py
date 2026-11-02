"""E35-T12 slice 3d: the reduce-only exits, `scale_out`, `flatten_position` and
`flatten_all_positions`, bound through the rules service's seam and handed to the real OMS
pipeline (24 §11.5 "Exits", §11.6, §11.9; the rulings of record on #5004, BQ-5, BQ-6 and BQ-8).

The executor runs as a dispatch worker runs it (`ActionExecutor`), its checks' ports and records in
memory; the handlers are the composition root's (`rules_oms_exits`), their order port the entries'
over an OMS runtime double whose pipeline is the real one (`submit_rig`: B1's facade, the command
port, a demo `FakeTradingPort`, C-13.5: no venue is reached). Every exit is held to C-2.6: each
order is reduce-only and the position's native stop at the venue is never removed or loosened
(`assert_position_stop_untouched`). No sleeps.
"""

from __future__ import annotations

import asyncio
import re
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, Literal

import pytest

import candleviewer.rules_oms_exits as exits_module
from candleviewer.domain.primitives import AccountId
from candleviewer.exchange.base.models import PlaceOrderRequest, RateHeadroom
from candleviewer.rules.executor.budget import OrderBudget
from candleviewer.rules.executor.dispatch import Fire
from candleviewer.rules.executor.engine import ActionExecutor, RowVerdict
from candleviewer.rules.executor.gates import Gates
from candleviewer.rules.executor.handlers import HANDLERS, BoundHandler, bind_handlers
from candleviewer.rules.executor.ports import PrincipalView
from candleviewer.rules.executor.results import NODE_ID, OMS_DETAIL
from candleviewer.rules.ir.models import Action, RuleLimits, RuleScope
from candleviewer.rules.scope import ActionRequest, ScopeInstanceRef
from candleviewer.rules_oms_exits import REDUCE_TYPES, rule_reduce_handlers
from candleviewer.storage.repositories.positions import PositionRow
from tests.rules.executor.native_sl import assert_position_stop_untouched
from tests.rules.executor.request_builders import Principals, Records, Switches, action_request
from tests.rules.executor.test_order_handlers import (
    ARMER,
    GUARD_S,
    OTHER,
    OWNER,
    RULE,
    RUN,
    RUN_2,
    Lookups,
    NoHistory,
    Recorded,
    Runtime,
    seed_other,
)
from tests.unit.oms import command_rig as cr
from tests.unit.oms import submit_rig as sr
from tests.unit.oms.submit_rig import SubmitRig

STOP = cr.STOP
_SHORT = re.compile(r"[A-Za-z0-9_-]{1,64}")
T0 = datetime(2026, 11, 2, 12, 0, tzinfo=UTC)


def stored(
    account: uuid.UUID = cr.ACCOUNT,
    *,
    qty: str = "0.050",
    side: Literal["Buy", "Sell"] = "Buy",
    symbol: str = cr.SYMBOL,
    idx: Literal[0, 1, 2] = 0,
    stop: Decimal | None = STOP,
) -> PositionRow:
    """An open position as the private stream stores it, its native stop in force (Full)."""
    return PositionRow(
        exchange_account_id=account, symbol=symbol, size=Decimal(qty), position_idx=idx,
        side=side, avg_price=Decimal("60000"), stop_loss=stop, tpsl_mode="Full",
        id=uuid.uuid5(uuid.UUID(int=0x505), f"{account}:{symbol}:{idx}"), recv_ts=T0,
        updated_at=T0,
    )  # fmt: skip


@dataclass
class Held:
    """`OpenPositions` in memory: each account's stored open positions; a read can fail or hang."""

    rows: dict[uuid.UUID, list[PositionRow]] = field(default_factory=dict)
    fails: bool = False
    hangs: asyncio.Event | None = None
    asked: list[tuple[uuid.UUID, uuid.UUID]] = field(default_factory=list)

    async def open_positions(self, owner: PrincipalView, account_id: uuid.UUID) -> Any:
        self.asked.append((owner.user_id, account_id))
        if self.hangs is not None:
            await self.hangs.wait()
        if self.fails:
            raise ConnectionError("the position read failed")
        return tuple(self.rows.get(account_id, ()))


@dataclass
class Exits:
    """One executor over the rig's pipeline (module docstring), the exits bound."""

    rig: SubmitRig
    runtime: Runtime
    records: Records
    principals: Principals
    held: Held
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
            await self.rig.quiet()

    def outcomes(self) -> list[tuple[str, str | None, str, str | None]]:
        """`(node, account, outcome, blocked_by or error_code)` of each result, in order."""
        return [
            (p["node_id"], p["account_id"], p["outcome"], p["blocked_by"] or p["error_code"])
            for p in (dict(e.payload) for _, e in self.records.events)
            if "outcome" in p
        ]

    def creates(self) -> list[PlaceOrderRequest]:
        calls = self.rig.port.demo.calls
        return [c.request for c in calls if isinstance(c.request, PlaceOrderRequest)]

    def hold(self, row: PositionRow) -> None:
        """`row` stored, and the same position at the venue, its native stop set there."""
        self.held.rows.setdefault(row.exchange_account_id, []).append(row)
        side: Literal["buy", "sell"] = "buy" if row.side == "Buy" else "sell"
        venue = cr.position(
            AccountId(row.exchange_account_id), side=side, qty=str(row.size),
            stop_loss=row.stop_loss, position_idx=row.position_idx,
        )  # fmt: skip
        self.rig.port.demo.seed_position(venue)

    async def assert_stops_untouched(self) -> None:
        """C-2.6: no stop was set or cancelled, and each held position's stop at the venue is
        its stop before the action or tighter, never removed."""
        methods = {c.method for c in self.rig.port.demo.calls}
        assert not methods & {"set_trading_stop", "cancel_order", "cancel_all", "amend_order"}
        for account, rows in self.held.rows.items():
            venue = await self.rig.port.demo.positions(cr.ref(AccountId(account)))
            for row in rows:
                [now] = [p for p in venue if p.position_idx == row.position_idx]
                side: Literal["Buy", "Sell"] = "Sell" if row.side == "Sell" else "Buy"
                assert_position_stop_untouched(side, before=row.stop_loss, after=now.stop_loss)


def build(rig: SubmitRig, *, switches: Switches | None = None) -> Exits:
    runtime = Runtime(None, None)
    runtime.submission, runtime.anchors = (
        Recorded(rig.pipeline, runtime),
        Lookups(rig.pipeline._anchors),
    )
    principals, held, records = Principals(frozenset({cr.ACCOUNT, OTHER})), Held(), Records()
    handlers: dict[str, BoundHandler] = dict(
        rule_reduce_handlers(
            lambda: runtime, oms_enabled=lambda: True, principals=principals, positions=held
        )
    )
    exits = Exits(rig, runtime, records, principals, held)
    exits.executor = ActionExecutor(
        check_one=exits.check_one, scope_check=lambda req: None,
        gates=Gates(switches=switches or Switches(), principal=principals), records=records,
        audit=records, handlers=bind_handlers(HANDLERS, handlers),
        budget=OrderBudget(rebuild=NoHistory()),
    )  # fmt: skip
    return exits


def exit_request(
    action_type: str,
    params: dict[str, Any] | None = None,
    *,
    node: str = "x1",
    account: uuid.UUID | None = cr.ACCOUNT,
    run: uuid.UUID = RUN,
    scope: dict[str, Any] | None = None,
    **action: Any,
) -> ActionRequest:
    """An armed fire's exit of `OWNER`'s rule, armed by `ARMER`, on `account`'s instance."""
    fields = {"node_id": node, "type": action_type, "params": params or {}} | action
    payload = Action.model_validate(fields) if _SHORT.fullmatch(node) else odd_action(fields)
    instance = ScopeInstanceRef(f"{cr.SYMBOL}@{account}", cr.SYMBOL, account)
    rule_scope = RuleScope.model_validate({"level": "account"} | (scope or {}))
    over = {
        "action_type": action_type, "payload": payload, "rule_id": RULE, "run_id": run,
        "armed_by": str(ARMER),
    }  # fmt: skip
    return action_request(rule_scope, OWNER, instance, **over)


def odd_action(fields: dict[str, Any]) -> Action:
    """An action whose node id is no short identifier, built past the IR's own checks, as a
    version stored before a bound on it would hold it: the handler's refusal is the last fence."""
    base = Action.model_validate(fields | {"node_id": "x1"})
    return Action.model_construct(**(base.model_dump() | {"node_id": fields["node_id"]}))


@pytest.fixture
async def rig() -> AsyncIterator[SubmitRig]:
    async with sr.rigged() as built:
        yield built


async def test_scale_out_is_reduce_only_and_never_opens_a_position(rig: SubmitRig) -> None:
    """G "A reduce-only exit never opens a position", `scale_out`: half of a long goes out as one
    reduce-only market sell of the closing side, intent `flatten`, through the pipeline as the
    rule's (its owner the principal, its origin the rule, never `protective`), with no stop or
    take-profit of its own; a quantity above the position is refused, nothing sent."""
    exits = build(rig)
    exits.hold(stored(qty="0.050"))
    await exits.run(exit_request("scale_out", {"order_type": "market", "qty_pct": "50"}))
    assert exits.outcomes() == [("x1", str(cr.ACCOUNT), "ok", None)]
    [(sent, context)] = exits.runtime.requests
    assert (sent.side, sent.reduce_only, sent.intent, sent.order_type) == (
        "sell", True, "flatten", "market",
    )  # fmt: skip
    assert (sent.sizing.mode, sent.sizing.qty) == ("fixed_qty", Decimal("0.025"))
    assert (sent.stop_loss, sent.take_profit) == (None, None)
    assert context.protective is False and context.origin is not None
    assert (context.actor.user_id, context.origin.armed_by) == (OWNER, ARMER)
    [create] = exits.creates()
    assert (create.reduce_only, create.side, create.stop_loss, create.take_profit) == (
        True, "sell", None, None,
    )  # fmt: skip
    await exits.assert_stops_untouched()
    over = build(rig)
    over.hold(stored(qty="0.050"))
    await over.run(exit_request("scale_out", {"order_type": "market", "qty": "0.060"}, run=RUN_2))
    assert over.outcomes() == [("x1", str(cr.ACCOUNT), "failed", "exceeds_position")]
    assert over.runtime.requests == [] and len(over.creates()) == 1  # the first test's only


async def test_flatten_position_leaves_the_native_stop_in_place(rig: SubmitRig) -> None:
    """G "A reduce-only exit never opens a position", the flatten: the whole long is closed by
    one reduce-only market order, which attaches no stop or take-profit; no stop is set, moved
    or cancelled, so the position's native stop at the venue stays as it was (C-2.6), and the
    close routes' Partial-mode sweep is not run (the order is never `protective`)."""
    exits = build(rig)
    exits.hold(stored(qty="0.050", stop=Decimal("58500")))
    await exits.run(exit_request("flatten_position"))
    assert exits.outcomes() == [("x1", str(cr.ACCOUNT), "ok", None)]
    [(sent, context)] = exits.runtime.requests
    assert (sent.reduce_only, sent.side, sent.sizing.qty, context.protective) == (
        True, "sell", Decimal("0.050"), False,
    )  # fmt: skip
    [create] = exits.creates()
    assert (create.stop_loss, create.take_profit, create.reduce_only) == (None, None, True)
    await exits.assert_stops_untouched()


@pytest.mark.parametrize("pct", ["100.01", "150", "0"])
async def test_a_percentage_above_100_is_refused(rig: SubmitRig, pct: str) -> None:
    """G "A reduce-only exit never opens a position": a `scale_out` percent above 100 (or not
    above 0) is refused at the parameters, `failed` (`invalid_params`), nothing sent, the stop
    untouched; 100 itself closes the whole position."""
    exits = build(rig)
    exits.hold(stored(qty="0.050"))
    await exits.run(exit_request("scale_out", {"order_type": "market", "qty_pct": pct}))
    assert exits.outcomes() == [("x1", str(cr.ACCOUNT), "failed", "invalid_params")]
    assert exits.runtime.requests == [] and exits.creates() == []
    await exits.assert_stops_untouched()
    whole = build(rig)
    whole.hold(stored(qty="0.050"))
    await whole.run(exit_request("scale_out", {"order_type": "market", "qty_pct": 100}, run=RUN_2))
    [(sent, _)] = whole.runtime.requests
    assert (sent.reduce_only, sent.sizing.qty) == (True, Decimal("0.050"))


async def test_scale_out_by_quantity_closes_that_quantity(rig: SubmitRig) -> None:
    """G "A reduce-only exit never opens a position", `scale_out` by `qty`: a quantity within the
    position goes out as one reduce-only market order of that quantity on the closing side, with
    no stop or take-profit of its own, never `protective`; the position's stop is untouched."""
    exits = build(rig)
    exits.hold(stored(qty="0.050"))
    await exits.run(exit_request("scale_out", {"order_type": "market", "qty": "0.020"}))
    assert exits.outcomes() == [("x1", str(cr.ACCOUNT), "ok", None)]
    [(sent, context)] = exits.runtime.requests
    assert (sent.side, sent.reduce_only, sent.sizing.mode, sent.sizing.qty) == (
        "sell", True, "fixed_qty", Decimal("0.020"),
    )  # fmt: skip
    assert (sent.stop_loss, sent.take_profit, context.protective) == (None, None, False)
    [create] = exits.creates()
    assert (create.reduce_only, create.side, Decimal(str(create.qty))) == (
        True, "sell", Decimal("0.020"),
    )  # fmt: skip
    await exits.assert_stops_untouched()


async def test_reduce_only_rule_orders_never_draw_the_reserve(rig: SubmitRig) -> None:
    """G "Rule exits ride the entry lane (RE-D6)": with the `critical` reserve spent, a rule's
    reduce-only closes still pass the pipeline's headroom step and leave on `entry`; none is
    sent on `critical`, so a rule never spends the reserve a stop or a cancel needs."""
    rig.port.demo.set_headroom(cr.ACCOUNT, RateHeadroom(lane="critical", tokens=0.0, wait_s=60.0))
    exits = build(rig)
    exits.hold(stored(qty="0.050"))
    await exits.run(
        exit_request("scale_out", {"order_type": "market", "qty_pct": "40"}),
        exit_request("flatten_position", node="x2"),
    )
    assert [o for _, _, o, _ in exits.outcomes()] == ["ok", "ok"]
    lanes = [c.lane for c in rig.port.demo.calls if c.method == "place_order"]
    assert lanes == ["entry", "entry"]
    await exits.assert_stops_untouched()


async def test_flatten_all_positions_runs_per_account_in_resolved_order(rig: SubmitRig) -> None:
    """G "flatten_all_positions runs per account in the resolved order": `all_accounts` resolves
    to the owner's and the armer's intersection, sorted, and each account's open positions are
    closed in turn, one OMS call each through the pipeline and its rate headroom (`entry`); an
    algo's child order resting on an account is never cancelled (E11)."""
    seed_other(rig)
    exits = build(rig)
    exits.hold(stored(cr.ACCOUNT, qty="0.050"))
    exits.hold(stored(OTHER, qty="0.020", side="Sell", stop=Decimal("61500")))
    await exits.run(exit_request("flatten_all_positions", targets="all_accounts"))
    order = sorted([str(cr.ACCOUNT), str(OTHER)])
    assert [a for _, a, _, _ in exits.outcomes()] == order
    assert {o for _, _, o, _ in exits.outcomes()} == {"ok"}
    sent = [(str(r.account_id), r.side, r.reduce_only) for r, _ in exits.runtime.requests]
    sides = {str(cr.ACCOUNT): "sell", str(OTHER): "buy"}
    assert sent == [(a, sides[a], True) for a in order]
    assert [c.lane for c in rig.port.demo.calls if c.method == "place_order"] == ["entry"] * 2
    assert [a for _, a in exits.held.asked] == [uuid.UUID(a) for a in order]
    await exits.assert_stops_untouched()


async def test_flatten_never_acts_on_another_rules_or_algos_children(rig: SubmitRig) -> None:
    """G "A rule never touches another rule's or algo's orders (E11)", a flatten: it closes
    positions only, with reduce-only orders, and never cancels or amends an order: another
    rule's resting entry and an order resting on the account stay as they were."""
    resting = await rig.submit()  # a user's (or another rule's) resting limit entry
    await rig.quiet()
    assert resting.order_id is not None
    before = await rig.port.orders.get(cr.ACCOUNT, resting.order_id)
    exits = build(rig)
    exits.hold(stored(qty="0.050"))
    await exits.run(exit_request("flatten_position"))
    assert exits.outcomes() == [("x1", str(cr.ACCOUNT), "ok", None)]
    after = await rig.port.orders.get(cr.ACCOUNT, resting.order_id)
    assert after == before and rig.machines.state(resting.order_id) == (
        "submitted", "not_required",
    )  # fmt: skip
    assert all(r.reduce_only for r, _ in exits.runtime.requests)
    await exits.assert_stops_untouched()


async def test_a_flat_position_is_ok_with_no_order(rig: SubmitRig) -> None:
    """BQ-6 (a): the exit's end state holds, so a flat account is `ok` for each of the three,
    with no order and nothing sent, and no stop is touched (C-2.6)."""
    exits = build(rig)
    exits.hold(stored(qty="0", stop=None))
    reqs = [
        exit_request("scale_out", {"order_type": "market", "qty_pct": "50"}),
        exit_request("flatten_position", node="x2"),
        exit_request("flatten_all_positions", node="x3"),
    ]
    await exits.run(*reqs)
    assert exits.outcomes() == [(n, str(cr.ACCOUNT), "ok", None) for n in ("x1", "x2", "x3")]
    assert exits.runtime.requests == [] and exits.creates() == []
    await exits.assert_stops_untouched()


async def test_a_rule_exit_on_an_account_outside_the_intersection_is_blocked(
    rig: SubmitRig,
) -> None:
    """The cross-account case: an exit on an account the armer's grants do not reach is blocked
    at check 5 (`permission`) before anything is read or sent; the account's stop is untouched."""
    seed_other(rig)
    exits = build(rig)
    exits.principals.facts[ARMER] = (True, "manager", False, frozenset({cr.ACCOUNT}))
    exits.hold(stored(OTHER, qty="0.020"))
    await exits.run(exit_request("flatten_position", account=OTHER))
    assert exits.outcomes() == [("x1", str(OTHER), "blocked", "permission")]
    assert exits.held.asked == [] and exits.runtime.requests == []
    await exits.assert_stops_untouched()


async def test_a_view_only_armer_blocks_an_exit(rig: SubmitRig) -> None:
    """The forbidden-role case: an armer whose grant on the account is view-only admits no trade
    there, so each exit is blocked (`permission`), nothing read and nothing sent."""
    exits = build(rig)
    exits.principals.facts[ARMER] = (True, "viewer", False, frozenset())
    exits.hold(stored(qty="0.050"))
    await exits.run(
        *(
            exit_request(t, _PARAMS[t], node=f"x{n}", on_error="continue")
            for n, t in enumerate(REDUCE_TYPES)
        )
    )
    assert {(o, r) for _, _, o, r in exits.outcomes()} == {("blocked", "permission")}
    assert exits.held.asked == [] and exits.runtime.requests == []
    await exits.assert_stops_untouched()


_PARAMS: dict[str, dict[str, Any]] = {
    "scale_out": {"order_type": "market", "qty_pct": "50"},
    "flatten_position": {},
    "flatten_all_positions": {},
}


@pytest.mark.parametrize("action_type", REDUCE_TYPES)
async def test_a_refused_rule_origin_fails_each_reduce_exit_as_invalid_params(
    rig: SubmitRig, action_type: str
) -> None:
    """A node id that is no short identifier, which the OMS's rule origin refuses (24 §11.5
    "Exits"): the exit is `failed` (`invalid_params`), never a raise, its detail the generic
    sentence, which never holds the id; nothing is read or sent, and the position's stop is
    untouched (C-2.6)."""
    exits = build(rig)
    exits.hold(stored(qty="0.050"))
    odd = "a" * 65
    await exits.run(exit_request(action_type, _PARAMS[action_type], node=odd))
    [result] = [dict(e.payload) for _, e in exits.records.events if e.kind == "action_fail"]
    assert (result["outcome"], result["error_code"]) == ("failed", "invalid_params")
    assert result["blocked_detail"] == OMS_DETAIL[NODE_ID] and odd not in str(
        result["blocked_detail"]
    )
    assert exits.held.asked == [] and exits.runtime.requests == []
    await exits.assert_stops_untouched()


async def test_a_failed_or_late_position_read_fails_the_exit_with_nothing_sent(
    rig: SubmitRig, monkeypatch: pytest.MonkeyPatch
) -> None:
    """BQ-6 (a): a position read that fails, or does not answer within its bound, is `failed`
    (`position_unavailable`), never retried as no answer; nothing is sent, and the position's
    stop is untouched (C-2.6)."""
    exits = build(rig)
    exits.hold(stored(qty="0.050"))
    exits.held.fails = True
    await exits.run(exit_request("flatten_position"))
    assert exits.outcomes() == [("x1", str(cr.ACCOUNT), "failed", "position_unavailable")]
    monkeypatch.setattr(exits_module, "POSITION_READ_TIMEOUT_S", 0.0)
    late = build(rig)
    late.held.hangs = asyncio.Event()
    await late.run(exit_request("flatten_all_positions", run=RUN_2))
    assert late.outcomes() == [("x1", str(cr.ACCOUNT), "failed", "position_unavailable")]
    assert exits.runtime.requests == [] and late.runtime.requests == []
    await exits.assert_stops_untouched()


async def test_positions_outside_the_rules_symbols_are_never_closed(rig: SubmitRig) -> None:
    """A flatten closes only what the rule's scope reaches: a symbol its `scope.symbols` does
    not name is left open, and a flatten that names it in `symbols` sends nothing; its stop is
    untouched (C-2.6)."""
    exits = build(rig)
    exits.hold(stored(qty="0.050"))
    scope = {"level": "symbol", "symbols": ["ETHUSDT"]}
    await exits.run(exit_request("flatten_all_positions", scope=scope))
    await exits.run(
        exit_request("flatten_position", {"symbols": [cr.SYMBOL]}, scope=scope, run=RUN_2)
    )
    assert [o for _, _, o, _ in exits.outcomes()] == ["ok", "ok"]
    assert exits.runtime.requests == [] and exits.creates() == []
    await exits.assert_stops_untouched()

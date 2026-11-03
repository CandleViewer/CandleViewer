"""E35-T11 slice 3c: the `place_order` and `scale_in` handlers, bound through the rules service's
seam and handed to the real OMS pipeline (24 §11.5, §11.7, §11.9; the rulings of #863 BQ-2 to
BQ-5, BQ-9, BQ-17, and of #5003 BQ-4, BQ-5 and BQ-7).

The executor runs as a dispatch worker runs it (`ActionExecutor`), its checks' ports and its
records in memory; the handlers are the composition root's (`rules_oms_orders`), their order port
over an OMS runtime double whose pipeline is the real one (`submit_rig`: B1's facade, the command
port, a demo `FakeTradingPort`, C-13.5: no venue is reached). Every entry is held to C-2.6 at
every layer it crosses (`assert_entry_carries_native_stop`). No sleeps: a create held at the
venue's door waits on an event the test sets, under a bound the test sets to 0.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from collections.abc import AsyncIterator, Coroutine
from dataclasses import asdict, dataclass, field, replace
from decimal import Decimal
from types import SimpleNamespace
from typing import Any, cast

import pytest
from structlog.testing import capture_logs

from candleviewer.domain.primitives import AccountId
from candleviewer.exchange.base.models import PlaceOrderRequest
from candleviewer.oms import submit as oms_submit
from candleviewer.oms.errors import OmsNotReady
from candleviewer.oms.idempotency import Fresh
from candleviewer.oms.submit import OrderRequest, SubmitContext, SubmitOutcome
from candleviewer.oms_wiring import InterimKillSwitch, TradingSwitchesBinding
from candleviewer.risk.models import RiskDecision
from candleviewer.rules.executor import dispatch
from candleviewer.rules.executor.budget import OrderBudget
from candleviewer.rules.executor.dispatch import Fire
from candleviewer.rules.executor.engine import ActionExecutor, RowVerdict
from candleviewer.rules.executor.gates import Gates
from candleviewer.rules.executor.handlers import HANDLERS, bind_handlers
from candleviewer.rules.executor.metrics import ExecutorMetrics
from candleviewer.rules.executor.ports import PrincipalView
from candleviewer.rules.executor.results import BLOCKED_DETAIL, NODE_ID, OMS_DETAIL
from candleviewer.rules.ir.models import Action, RuleLimits, RuleScope
from candleviewer.rules.scope import ActionRequest, ScopeInstanceRef
from candleviewer.rules_oms_orders import RuleEntryHandler, SubmitCutShort, rule_order_handlers
from candleviewer.rules_oms_wiring import rule_switches
from candleviewer.storage.repositories.orders import OrderRow
from tests.rules.executor.native_sl import assert_entry_carries_native_stop
from tests.rules.executor.request_builders import (
    Counted,
    Principals,
    Records,
    Switches,
    action_request,
)
from tests.unit.oms import command_rig as cr
from tests.unit.oms import submit_rig as sr
from tests.unit.oms.submit_rig import SubmitRig
from tests.unit.oms.test_submit_rule_origin import RefusingGate

GUARD_S = 10.0
OWNER, ARMER = sr.USER, uuid.UUID("2b3c4d5e-6f70-4182-93a4-b5c6d7e8f901")
RULE, RUN = "3f2b8c1e-5d4a-4e6f-9a0b-1c2d3e4f5a6b", uuid.UUID(int=0xF1)
#: Later fires of one test, each its own run, so each action its own fire key.
RUN_2, RUN_3 = uuid.UUID(int=0xF2), uuid.UUID(int=0xF3)
#: A second demo account, after `cr.ACCOUNT` in `all_accounts`' sorted order.
OTHER = AccountId(uuid.UUID("9e1d2c3b-4a59-4e68-8f7a-9b0c1d2e3f40"))
MARKET: dict[str, Any] = {"side": "buy", "order_type": "market", "qty_mode": "profile"}


@dataclass
class Runtime:
    """`OrderRuntime` over the rig's pipeline, as `OmsRuntime` serves it: ready, its anchors'
    lookup (recorded), and each submit a task it tracks (`run`)."""

    submission: Any
    anchors: Any
    readiness: str = "ok"
    tasks: list[asyncio.Task[SubmitOutcome]] = field(default_factory=list)
    requests: list[tuple[OrderRequest, SubmitContext]] = field(default_factory=list)
    stopping: bool = False  # its stop has begun: `run` refuses, as `OmsRuntime.run` does

    def run(self, coro: Coroutine[Any, Any, SubmitOutcome]) -> asyncio.Task[SubmitOutcome]:
        if self.stopping:
            coro.close()
            raise OmsNotReady
        task = asyncio.ensure_future(coro)
        self.tasks.append(task)
        return task


class Lookups:
    """The anchor service's lookup, each call's key and fingerprint recorded."""

    def __init__(self, inner: Any) -> None:
        self.inner, self.asked = inner, list[tuple[uuid.UUID, uuid.UUID, str]]()

    async def lookup(self, created_by: uuid.UUID, client_ref: uuid.UUID, sha: str) -> Any:
        self.asked.append((created_by, client_ref, sha))
        return await self.inner.lookup(created_by, client_ref, sha)


class Recorded:
    """The pipeline, each request it is handed recorded."""

    def __init__(self, pipeline: Any, runtime: Runtime) -> None:
        self.pipeline, self.runtime = pipeline, runtime

    async def submit(self, request: OrderRequest, context: SubmitContext) -> SubmitOutcome:
        self.runtime.requests.append((request, context))
        outcome: SubmitOutcome = await self.pipeline.submit(request, context)
        return outcome

    async def answer_replay(self, account_id: Any, replay: Any) -> SubmitOutcome:
        outcome: SubmitOutcome = await self.pipeline.answer_replay(account_id, replay)
        return outcome


@dataclass
class Sides:
    """`PositionSides`: the side of the open position each account holds, if any."""

    held: dict[uuid.UUID, str] = field(default_factory=dict)
    fails: bool = False

    async def side(self, owner: PrincipalView, account_id: uuid.UUID, symbol: str) -> Any:
        if self.fails:
            raise ConnectionError("the position read failed")
        return self.held.get(account_id)


class NoHistory:
    """The order budget's rebuild with no counted order in the last 24 h."""

    async def order_ages(self, rule_id: str, *, limit: int) -> tuple[float, ...]:
        return ()


@dataclass
class DayNotional:
    """The day's rebuild (`NotionalRebuild`), answering a prior sum."""

    prior: Decimal = Decimal(0)
    asked: list[str] = field(default_factory=list)

    async def day_notional(self, rule_id: str, day: Any) -> Decimal:
        self.asked.append(rule_id)
        return self.prior


@dataclass
class Orders:
    """One executor over the rig's pipeline (module docstring)."""

    rig: SubmitRig
    runtime: Runtime
    lookups: Lookups
    records: Records
    switches: Switches
    principals: Principals
    sides: Sides
    handlers: dict[str, RuleEntryHandler]
    scope_refusals: dict[uuid.UUID | None, str] = field(default_factory=dict)
    executor: ActionExecutor = field(init=False)

    async def check_one(self, req: ActionRequest) -> RowVerdict:
        return "armed"

    async def emit(self, req: ActionRequest) -> str | None:
        """The routing emitter: check 4's refusal for the account, else the hand-over."""
        refusal = self.scope_refusals.get(req.instance.account_id)
        if refusal is not None:
            return refusal
        await self.executor.hand_over(req)
        return None

    async def run(
        self, *reqs: ActionRequest, limits: RuleLimits | None = None, quiet: bool = True
    ) -> None:
        """One fire of `reqs` (their run's), then, unless a create is held, B1 settled."""
        fire = Fire(
            RULE, reqs[0].run_id, reqs, self.emit, version_id=str(uuid.UUID(int=0xC0)),
            trigger_type="on_bar_close", limits=limits or RuleLimits(),
        )  # fmt: skip
        async with asyncio.timeout(GUARD_S):
            await self.executor.execute(fire)
            if quiet:
                await self.rig.quiet()
                await self.assert_native_stops()  # C-2.6 on every entry a fire placed (R1C2-03)

    def results(self) -> list[dict[str, Any]]:
        return [
            dict(e.payload)
            for _, e in self.records.events
            if e.kind in ("action_ok", "action_fail")
        ]

    def outcomes(self) -> list[tuple[str, str | None, str, str | None]]:
        """`(node, account, outcome, blocked_by or error_code)` of each result, in order."""
        return [
            (r["node_id"], r["account_id"], r["outcome"], r["blocked_by"] or r["error_code"])
            for r in self.results()
        ]

    def creates(self, port: Any = None) -> list[PlaceOrderRequest]:
        calls = (port or self.rig.port.demo).calls
        sent = [c.request for c in calls if c.method == "place_order"]
        return [create for create in sent if isinstance(create, PlaceOrderRequest)]

    async def row(self, result: dict[str, Any]) -> OrderRow:
        order = await self.rig.port.orders.get(
            uuid.UUID(result["account_id"]), uuid.UUID(result["order_id"])
        )
        assert order is not None
        return order

    async def assert_native_stops(self) -> int:
        """C-2.6 for every entry the fire placed, at every layer; how many."""
        placed = [r for r in self.results() if r["outcome"] == "ok" and r["order_id"]]
        for result in placed:
            assert_entry_carries_native_stop(
                await self.row(result), reference_price=self.rig.prices.price or sr.REFERENCE,
                stops=self.rig.store._stops.values(), records=self.rig.records(),
                calls=self.rig.port.demo.calls,
            )  # fmt: skip
        return len(placed)


def build(
    rig: SubmitRig,
    *,
    switches: Any = None,
    notional: DayNotional | None = None,
    bound: bool = True,
    anchors: Any = None,
    metrics: ExecutorMetrics | None = None,
) -> Orders:
    runtime = Runtime(None, None)
    lookups = Lookups(rig.pipeline._anchors if anchors is None else anchors)
    runtime.submission, runtime.anchors = Recorded(rig.pipeline, runtime), lookups
    principals, sides, records = Principals(frozenset({cr.ACCOUNT, OTHER})), Sides(), Records()
    handlers = rule_order_handlers(
        lambda: runtime, oms_enabled=lambda: True, principals=principals, positions=sides
    )
    table = bind_handlers(HANDLERS, handlers) if bound else HANDLERS
    chosen = Switches() if switches is None else switches
    orders = Orders(rig, runtime, lookups, records, chosen, principals, sides, handlers)
    orders.executor = ActionExecutor(
        check_one=orders.check_one, scope_check=lambda req: None,
        gates=Gates(switches=chosen, principal=principals, notional=notional),
        records=records, audit=records, handlers=table,
        budget=OrderBudget(rebuild=NoHistory()), metrics=metrics,
    )  # fmt: skip
    return orders


def seed_other(rig: SubmitRig, **profile: Any) -> None:
    """`OTHER` as a demo account the rig trades, with a default profile of its own."""
    rig.port.accounts.seed(cr.ref(OTHER))
    rig.submissions.seed_account(cr.ref(OTHER))
    rig.profiles.held[(OTHER, None)] = sr.profile(OTHER, **profile)


def request(
    node: str = "a1",
    action_type: str = "place_order",
    params: dict[str, Any] | None = None,
    *,
    account: uuid.UUID | None = cr.ACCOUNT,
    run: uuid.UUID = RUN,
    **action: Any,
) -> ActionRequest:
    """An armed fire's action of `OWNER`'s rule, armed by `ARMER`, on `account`'s instance, in
    the fire `run` (each fire its own, so each its own fire keys)."""
    payload = Action.model_validate(
        {"node_id": node, "type": action_type, "params": MARKET if params is None else params}
        | action
    )
    instance = ScopeInstanceRef(f"BTCUSDT@{account}", "BTCUSDT", account)
    scope = RuleScope.model_validate({"level": "account"})
    over = {
        "action_type": action_type, "payload": payload, "rule_id": RULE, "run_id": run,
        "armed_by": str(ARMER),
    }  # fmt: skip
    return action_request(scope, OWNER, instance, **over)


@pytest.fixture
async def rig() -> AsyncIterator[SubmitRig]:
    async with sr.rigged() as built:
        yield built


async def test_place_order_entry_carries_a_native_stop(rig: SubmitRig) -> None:
    """G "Every rule entry carries a native stop (C-2.6)", `place_order`: a profile-sized market
    entry reaches the OMS as the rule's (its owner the principal, its origin the rule), rides the
    `entry` lane, and carries a finite stop on the protective side at every layer."""
    orders = build(rig)
    await orders.run(request())
    assert orders.outcomes() == [("a1", str(cr.ACCOUNT), "ok", None)]
    assert await orders.assert_native_stops() == 1
    [(sent, context)] = orders.runtime.requests
    assert (sent.sizing.mode, sent.sizing.qty, sent.intent) == ("profile", None, "entry")
    assert (context.actor.user_id, context.origin and context.origin.armed_by) == (OWNER, ARMER)
    assert [c.lane for c in rig.port.demo.calls if c.method == "place_order"] == ["entry"]
    assert [verb for verb, _ in orders.records.audits] == ["rules.fired"]


async def test_scale_in_entry_carries_a_native_stop_and_profile_caps_apply(rig: SubmitRig) -> None:
    """G same, `scale_in`: it adds to the open position, on its side, the OMS's `scale_in` intent,
    and carries its own native stop; a size past the profile's caps is refused whole by the OMS
    (`cap`, naming the cap), nothing sent; with no position open it sends nothing."""
    orders = build(rig)
    orders.sides.held[cr.ACCOUNT] = "buy"
    await orders.run(request(action_type="scale_in", params={"qty": "0.010"}))
    assert orders.outcomes() == [("a1", str(cr.ACCOUNT), "ok", None)]
    assert await orders.assert_native_stops() == 1
    [(sent, _)] = orders.runtime.requests
    assert (sent.side, sent.intent, sent.sizing.mode, sent.sizing.qty) == (
        "buy", "scale_in", "fixed_qty", Decimal("0.01"),
    )  # fmt: skip
    rig.profiles.held[(cr.ACCOUNT, None)] = sr.profile(max_position_notional="50")
    capped = build(rig)
    capped.sides.held[cr.ACCOUNT] = "buy"
    await capped.run(request(action_type="scale_in", params={"qty": "0.010"}, run=RUN_2))
    [result] = capped.results()
    assert (result["outcome"], result["blocked_by"]) == ("blocked", "cap")
    assert result["blocked_detail"] == (
        "Not done — the account's cap max_position_notional refused it."
    )
    flat = build(rig)
    await flat.run(request(action_type="scale_in", params={"qty": "0.010"}, run=RUN_3))
    assert flat.outcomes() == [("a1", str(cr.ACCOUNT), "failed", "no_position")]
    assert flat.runtime.requests == [] and len(orders.creates()) == 1


@pytest.mark.parametrize("side", ["buy", "sell"])
async def test_a_scale_in_takes_the_side_of_the_open_position(rig: SubmitRig, side: str) -> None:
    """A `scale_in` names no side of its own (24 §11.6): it adds to the open position on that
    position's side, a long's or a short's, with its own native stop on the protective side."""
    orders = build(rig)
    orders.sides.held[cr.ACCOUNT] = side
    await orders.run(request(action_type="scale_in", params={"qty": "0.010"}))
    assert orders.outcomes() == [("a1", str(cr.ACCOUNT), "ok", None)]
    [(sent, _)] = orders.runtime.requests
    assert (sent.side, sent.intent) == (side, "scale_in")
    assert await orders.assert_native_stops() == 1


async def test_a_rule_can_never_exceed_the_accounts_risk_caps() -> None:
    """G "A rule can never exceed the account's risk caps (parent Gherkin 2, failure case)": the
    OMS rejects the order after the engine has planned it (its records written ahead), the
    rejection is recorded on the action with `blocked_by` naming the cap, and nothing reaches the
    exchange fake: a refusing risk-gate double, and the profile-cap path that is real today."""
    async with sr.rigged(risk=RefusingGate("max_open_positions")) as gated_rig:
        gated = build(gated_rig)
        await gated.run(request())
        [result] = gated.results()
        assert (result["outcome"], result["blocked_by"]) == ("blocked", "cap")
        assert "max_open_positions" in result["blocked_detail"]
        assert gated.creates() == [] and len(gated.runtime.requests) == 1
        assert [(v, f.blocked_by) for v, f in gated.records.audits] == [
            ("rules.fired", None), ("rules.blocked", "cap"),
        ]  # fmt: skip
    async with sr.rigged() as sized_rig:
        sized_rig.profiles.held[(cr.ACCOUNT, None)] = sr.profile(max_position_notional="50")
        sized = build(sized_rig)
        await sized.run(request())
        [result] = sized.results()
        assert (result["outcome"], result["blocked_by"]) == ("blocked", "cap")
        assert "max_position_notional" in result["blocked_detail"]
        assert sized.creates() == []


class LostAnswer:
    """The pipeline whose first answer is lost in transit (`TimeoutError`) while its submit goes
    on: `held` keeps the create at the venue's door, so the order is in flight when the retry
    meets its anchor; else the submit ends first, so the retry meets a decided anchor."""

    def __init__(self, pipeline: Any, door: asyncio.Event | None) -> None:
        self.pipeline, self.door, self.calls = pipeline, door, 0
        self.first: asyncio.Task[SubmitOutcome] | None = None
        self.at_door = asyncio.Event()

    async def submit(self, request: OrderRequest, context: SubmitContext) -> SubmitOutcome:
        self.calls += 1
        self.first = asyncio.ensure_future(self.pipeline.submit(request, context))
        if self.door is not None:
            await self.at_door.wait()
        else:
            await self.first
        raise TimeoutError

    async def answer_replay(self, account_id: Any, replay: Any) -> SubmitOutcome:
        outcome: SubmitOutcome = await self.pipeline.answer_replay(account_id, replay)
        return outcome


def held_at_the_door(rig: SubmitRig, door: asyncio.Event, at_door: asyncio.Event) -> None:
    """Every create waits at the venue's door until `door` is set, then lands."""
    land = rig.port.demo.place_order

    async def held(create: PlaceOrderRequest) -> Any:
        at_door.set()
        await door.wait()
        return await land(create)

    rig.port.demo.place_order = held  # type: ignore[method-assign, assignment]  # the door wraps the venue


@pytest.mark.parametrize(
    ("held", "outcome", "code"),
    [(False, "ok", None), (True, "unknown", "idempotency_in_flight")],
    ids=["replayed", "in-flight"],
)
async def test_a_retried_fire_does_not_double_place(
    rig: SubmitRig, held: bool, outcome: str, code: str | None
) -> None:
    """G "A retried fire does not double-place (parent Gherkin 6, edge case)": a `place_order`
    whose OMS call got no answer is retried once under `retry_once`, after checks 1 to 8 again,
    with the same `client_ref` and the fingerprint built once; the OMS answers it as a replay of
    the decided anchor (`ok`), or as in flight (`unknown`, never sent again); one order exists."""
    door = asyncio.Event() if held else None
    orders = build(rig)
    lost = LostAnswer(rig.pipeline, door)
    orders.runtime.submission = lost
    if door is not None:
        held_at_the_door(rig, door, lost.at_door)
    prepared: list[Any] = []
    handler = orders.handlers["place_order"]
    real_prepare = handler.prepare

    def spied(req: ActionRequest, account_id: Any, *, max_notional_usd: Any) -> Any:
        prepared.append(real_prepare(req, account_id, max_notional_usd=max_notional_usd))
        return prepared[-1]

    handler.prepare = spied  # type: ignore[method-assign]  # the spy records the one build
    await orders.run(request(on_error="retry_once"), quiet=False)
    if door is not None:
        door.set()
    assert lost.first is not None
    async with asyncio.timeout(GUARD_S):
        first = await lost.first
        await rig.quiet()
    assert first.status == 202 and lost.calls == 1  # the retry sent nothing new
    assert orders.outcomes() == [("a1", str(cr.ACCOUNT), outcome, code)]
    [(owner, ref, sha), again] = orders.lookups.asked  # the first call, then its retry
    assert again == (owner, ref, sha) == (OWNER, ref, prepared[0].request_sha256)
    assert len(prepared) == 1 and len(orders.creates()) == 1 and len(rig.store._orders) == 1
    fired = [f.dedupe_key for verb, f in orders.records.audits if verb == "rules.fired"]
    assert len(fired) == 2 and len(set(fired)) == 1  # one key: the keyed record lands once


async def test_multi_account_action_runs_abort_on_first_across_accounts(rig: SubmitRig) -> None:
    """G "A multi-account action runs one single-leg entry per account (BQ-4)": `all_accounts`
    resolves to two accounts, each its own single-leg entry sized by its own profile, with its
    own native stop and key; and `abort_on_first` holds across them, whatever `on_error` says:
    once one account's result is not `ok`, the next is `skipped`, nothing sent for it, every
    result recorded, and under `continue` the fire's next action still runs."""
    seed_other(rig, fixed_qty="0.02")
    orders = build(rig)
    await orders.run(request(targets="all_accounts"))
    assert [(a, o) for _, a, o, _ in orders.outcomes()] == [
        (str(cr.ACCOUNT), "ok"), (str(OTHER), "ok"),
    ]  # fmt: skip
    assert await orders.assert_native_stops() == 2
    keys = {r["dedupe_key"] for r in orders.results()}
    refs = {context.client_ref for _, context in orders.runtime.requests}
    groups = {r["group_id"] for r in orders.results()}
    assert len(keys) == len(refs) == len(groups) == 2
    assert sorted(c.qty for c in orders.creates()) == [Decimal("0.01"), Decimal("0.02")]
    rig.profiles.held[(cr.ACCOUNT, None)] = sr.profile(max_position_notional="50")
    first_refused = build(rig)
    await first_refused.run(
        request(targets="all_accounts", run=RUN_2, on_error="continue"),
        request("a2", account=OTHER, run=RUN_2),
    )
    assert first_refused.outcomes() == [
        ("a1", str(cr.ACCOUNT), "blocked", "cap"), ("a1", str(OTHER), "skipped", None),
        ("a2", str(OTHER), "ok", None),
    ]  # fmt: skip
    assert len(first_refused.runtime.requests) == 2 and len(first_refused.creates()) == 3


@pytest.mark.parametrize(
    "closed",
    ["rollout-off", "rollout-unread", "master-switch-off", "sink-unbound", "live-account"],
)
async def test_live_stays_closed_while_the_rollout_flag_or_master_switch_is_off_or_the_account_is_live(  # noqa: E501 -- the ticket's test name (#5003)
    rig: SubmitRig, closed: str
) -> None:
    """G "Live stays closed (BQ-9, BQ-17, failure case)": while `rules.oms_actions` is off (or
    unread: its view is off until the store answers), while the master switch is off, while no
    handler is bound (the fake backend binds none), or when the account is live (check 4's live
    gate), the action is blocked before anything is written ahead: no `rules.fired`, nothing
    sent."""
    expected = {
        "rollout-off": "unavailable", "rollout-unread": "unavailable",
        "master-switch-off": "rules_disabled", "sink-unbound": "unavailable",
        "live-account": "live_gate",
    }[closed]  # fmt: skip
    switches: Any = Switches()
    if closed == "rollout-off":
        switches.rollout = False
    elif closed == "master-switch-off":
        switches.enabled = False
    elif closed == "rollout-unread":
        views = SimpleNamespace(
            rules_enabled=lambda: True, order_entry_killed=lambda: False,
            rules_oms_actions=lambda: None,  # a view the store has not answered yet
        )  # fmt: skip
        switches = rule_switches(cast(Any, views), lambda account: None)
    orders = build(rig, switches=switches, bound=closed != "sink-unbound")
    account: uuid.UUID = cr.LIVE_ACCOUNT if closed == "live-account" else cr.ACCOUNT
    if closed == "live-account":
        orders.scope_refusals[cr.LIVE_ACCOUNT] = "live_gate"
    await orders.run(request(account=account))
    assert orders.outcomes() == [("a1", str(account), "blocked", expected)]
    assert orders.runtime.requests == [] and orders.lookups.asked == []
    assert [verb for verb, _ in orders.records.audits] == ["rules.blocked"]
    assert orders.creates() == [] and orders.creates(rig.port.live) == []


class AdmitAll:
    """A risk gate that admits every order: past it, the live gate is the fence left."""

    def check(self, order: Any, *, profile: Any) -> RiskDecision:
        return RiskDecision(allowed=True, evaluated_at=cr.EPOCH)


@pytest.mark.parametrize(("risk", "blocked_by"), [(None, "cap"), (AdmitAll(), "kill_switch")],
                         ids=["interim-risk-gate", "live-gate"])  # fmt: skip
async def test_a_live_account_meets_the_oms_fences_even_past_the_engine(
    risk: Any, blocked_by: str
) -> None:
    """The OMS's own fences stay the last word (C-2.11): a rule entry for a live account, handed
    straight to the handler, is refused by the interim risk gate (no evaluation for `live` yet,
    `cap`) and, past it, by the live gate (`trading_disabled`, live trading not enabled,
    `kill_switch`); nothing reaches either venue."""
    async with sr.rigged(risk=risk) as rig:
        rig.profiles.held[(cr.LIVE_ACCOUNT, None)] = sr.profile(cr.LIVE_ACCOUNT)
        live_gate = TradingSwitchesBinding(
            live_enabled=False, live_flag=lambda: False, kill_switch=InterimKillSwitch(),
            gate=cast(Any, SimpleNamespace(refusal=lambda account_id: None)), fenced=lambda: False,
        )  # fmt: skip
        rig.pipeline._deps = replace(rig.pipeline._deps, switches=live_gate)
        orders = build(rig)
        orders.principals.accounts = frozenset({cr.LIVE_ACCOUNT})
        handler = orders.handlers["place_order"]
        req = request(account=cr.LIVE_ACCOUNT)
        built = handler.prepare(req, cr.LIVE_ACCOUNT, max_notional_usd=None)
        answer = await handler.send(built, client_ref=str(uuid.UUID(int=0xD1)))
        assert (answer.answer, answer.blocked_by) == ("refused", blocked_by)
        assert orders.creates(rig.port.live) == [] and orders.creates() == []


async def test_a_submit_running_at_the_action_bound_is_unknown_and_never_sent_again(
    rig: SubmitRig, monkeypatch: pytest.MonkeyPatch
) -> None:
    """BQ-7 as ruled: the submit is a task the OMS runtime tracks, shielded, so the action's bound
    (0 s here) never cancels it; the action is `unknown` and, under `retry_once` too, never sent
    again; the submit goes on and lands once the venue answers."""
    monkeypatch.setattr(dispatch, "ACTION_TIMEOUT_S", 0.0)
    orders = build(rig, anchors=FreshAnchors())
    door, at_door = asyncio.Event(), asyncio.Event()
    held_at_the_door(rig, door, at_door)
    await orders.run(request(on_error="retry_once"), quiet=False)
    assert orders.outcomes() == [("a1", str(cr.ACCOUNT), "unknown", "timeout")]
    [task] = orders.runtime.tasks
    assert not task.done() and len(orders.lookups.asked) == 1
    door.set()
    async with asyncio.timeout(GUARD_S):
        outcome = await task
        await rig.quiet()
    assert (outcome.status, task.cancelled(), len(orders.creates())) == (202, False, 1)
    assert len(orders.runtime.tasks) == 1 and len(orders.lookups.asked) == 1
    assert outcome.order_id is not None  # the late landing carries its native stop (C-2.6)
    landed = await rig.port.orders.get(cr.ACCOUNT, outcome.order_id)
    assert landed is not None
    assert_entry_carries_native_stop(
        landed, reference_price=rig.prices.price or sr.REFERENCE, stops=rig.store._stops.values(),
        records=rig.records(), calls=rig.port.demo.calls,
    )  # fmt: skip


class FreshAnchors:
    """An anchor lookup that answers `Fresh` at once, never yielding to the loop."""

    async def lookup(self, created_by: uuid.UUID, client_ref: uuid.UUID, sha: str) -> Fresh:
        return Fresh()


async def test_a_submit_the_runtimes_stop_cut_short_is_in_flight_and_never_sent_again(
    rig: SubmitRig,
) -> None:
    """The OMS runtime's stop cancels the submits it did not drain in time: the action awaiting
    one is answered in flight (`unknown`, `submit_cut_short`), never re-sent, never a cancelled
    worker."""
    orders = build(rig, anchors=FreshAnchors())
    door, at_door = asyncio.Event(), asyncio.Event()
    held_at_the_door(rig, door, at_door)

    async def stop_runtime() -> None:
        await at_door.wait()
        orders.runtime.tasks[0].cancel()

    stopper = asyncio.ensure_future(stop_runtime())
    await orders.run(request(on_error="retry_once"), quiet=False)
    await stopper
    assert orders.outcomes() == [("a1", str(cr.ACCOUNT), "unknown", "submit_cut_short")]
    assert len(orders.lookups.asked) == 1 and len(orders.runtime.tasks) == 1
    door.set()  # the venue answers the create B1 had sent; nothing more is sent
    async with asyncio.timeout(GUARD_S):
        await rig.quiet()
    assert len(orders.creates()) == 1


async def test_an_oms_not_ready_is_a_refusal_before_the_anchor(rig: SubmitRig) -> None:
    """A runtime not ready refuses before the anchor's lookup: `pre_anchor`, which `retry_once`
    retries once, never more; nothing sent (one not composed: the handler test below)."""
    orders = build(rig)
    orders.runtime.readiness = "starting"
    await orders.run(request(on_error="retry_once"))
    assert orders.outcomes() == [("a1", str(cr.ACCOUNT), "failed", "oms_not_ready")]
    assert orders.lookups.asked == [] and orders.creates() == []
    fired = [verb for verb, _ in orders.records.audits]
    assert fired == ["rules.fired", "rules.fired"]  # the first call and its one retry


async def test_a_runtime_whose_stop_has_begun_refuses_the_submit_before_its_anchor(
    rig: SubmitRig,
) -> None:
    """R1C2-09: `OmsRuntime.run` refuses a submit once its stop has begun (`OmsNotReady`, the
    coroutine closed), past the lookup and before any anchor is written: `pre_anchor`, which
    `retry_once` retries once, never more; nothing sent."""
    orders = build(rig)
    orders.runtime.stopping = True
    await orders.run(request(on_error="retry_once"))
    assert orders.outcomes() == [("a1", str(cr.ACCOUNT), "failed", "oms_not_ready")]
    assert len(orders.lookups.asked) == 2 and orders.runtime.tasks == []
    assert orders.creates() == [] and rig.store._orders == {}


async def test_the_oms_admission_flag_off_refuses_an_entry_after_its_replay_lookup(
    rig: SubmitRig,
) -> None:
    """`trading.oms_enabled` gates a rule's entry as it gates `placeOrder`'s, after the anchor's
    lookup (a repeat is answered whatever it reads): off is `trading_disabled`, `kill_switch`."""
    orders = build(rig)
    for handler in orders.handlers.values():
        handler._orders._oms_enabled = lambda: False
    await orders.run(request())
    assert orders.outcomes() == [("a1", str(cr.ACCOUNT), "blocked", "kill_switch")]
    assert len(orders.lookups.asked) == 1 and orders.runtime.requests == []


async def test_the_day_notional_rebuild_sums_the_rules_action_ok_notionals(rig: SubmitRig) -> None:
    """24 §11.7 and BQ-5 as ruled: an accepted entry's `action_ok` row records its sized notional
    (the size step's quantity times its reference price, never the request's ceiling), which the
    day's rebuild sums; the ledger counts it, so the next entry's ceiling is what the day leaves,
    and an allowance spent is refused at check 6 (`cap`, the rule's limit) before the OMS."""
    day = DayNotional(prior=Decimal("100"))
    orders = build(rig, notional=day)
    limits = RuleLimits(max_daily_notional=Decimal("1300"))
    await orders.run(request(), limits=limits)
    [ok] = orders.results()
    assert (ok["outcome"], ok["notional_usd"]) == ("ok", "600")  # 0.01 x 60000, at submit
    assert orders.runtime.requests[0][0].sizing.max_notional_usd == Decimal("1200")
    assert day.asked == [RULE]  # rebuilt once, at the rule's first entry of the day
    orders.records.events.clear()
    await orders.run(request(run=RUN_2), limits=limits)
    assert orders.runtime.requests[1][0].sizing.max_notional_usd == Decimal("600")
    assert orders.outcomes() == [("a1", str(cr.ACCOUNT), "ok", None)]
    orders.records.events.clear()
    await orders.run(request(run=RUN_3), limits=limits)
    [spent] = orders.results()
    assert (spent["outcome"], spent["blocked_by"]) == ("blocked", "cap")
    assert spent["blocked_detail"] == BLOCKED_DETAIL["max_daily_notional"]
    assert len(orders.runtime.requests) == 2 and "notional_usd" not in spent


@pytest.mark.parametrize(
    ("params", "code"),
    [
        ({"side": "buy", "order_type": "market", "qty_mode": "profile", "qty": 0.5},
         "invalid_params"),
        ({**MARKET, "leverage": 10}, "invalid_params"),
    ],
    ids=["two-sizes", "undeclared"],
)  # fmt: skip
async def test_an_entry_whose_params_do_not_parse_sends_nothing(
    rig: SubmitRig, params: dict[str, Any], code: str
) -> None:
    orders = build(rig)
    await orders.run(request(params=params))
    assert orders.outcomes() == [("a1", str(cr.ACCOUNT), "failed", code)]
    assert orders.runtime.requests == [] and orders.lookups.asked == []


async def test_a_principal_gone_since_check_five_refuses_permission_at_prepare(
    rig: SubmitRig,
) -> None:
    """The roles the request names are the views check 5 read: one gone before the request is
    built (aged out, or never read) refuses it `permission`, nothing sent."""
    orders = build(rig)
    handler = orders.handlers["place_order"]
    orders.principals.missing.add(ARMER)
    built = handler.prepare(request(), cr.ACCOUNT, max_notional_usd=None)
    answer = await handler.send(built, client_ref=str(uuid.UUID(int=0xD2)))
    assert (answer.answer, answer.blocked_by) == ("refused", "permission")
    assert orders.runtime.requests == [] and orders.lookups.asked == []


async def test_a_scale_in_whose_position_read_fails_gets_no_answer(rig: SubmitRig) -> None:
    orders = build(rig)
    orders.sides.fails = True
    await orders.run(request(action_type="scale_in", params={}))
    assert orders.outcomes() == [("a1", str(cr.ACCOUNT), "unknown", "position_unread")]
    assert orders.runtime.requests == []


def test_the_handlers_bind_through_the_seam_with_the_entry_capability() -> None:
    """The seam E35-T13 opened: each handler carries its type's capability, so the table admits
    it, and a handler of another type is refused at the composition root."""
    handlers = rule_order_handlers(
        lambda: None, oms_enabled=lambda: True, principals=Principals(), positions=None
    )
    table = bind_handlers(HANDLERS, handlers)
    assert sorted(t for t, s in table.items() if s.handler is not None) == [
        "place_order", "scale_in",
    ]  # fmt: skip
    with pytest.raises(ValueError):
        RuleEntryHandler("scale_out", handlers["place_order"]._orders, Principals())
    assert issubclass(SubmitCutShort, Exception)


async def test_a_handler_with_no_runtime_composed_refuses_before_the_anchor() -> None:
    """No OMS composed: each entry refuses before the anchor's lookup (`pre_anchor`), a
    `scale_in` before any position read too, as the side is read for a fresh key only."""
    handlers = rule_order_handlers(
        lambda: None, oms_enabled=lambda: True,
        principals=Principals(frozenset({cr.ACCOUNT})), positions=None,
    )  # fmt: skip
    built = handlers["place_order"].prepare(request(), cr.ACCOUNT, max_notional_usd=None)
    answer = await handlers["place_order"].send(built, client_ref=str(uuid.UUID(int=0xD3)))
    assert (answer.answer, answer.error_code) == ("pre_anchor", "oms_not_ready")
    no_reads = handlers["scale_in"].prepare(
        request(action_type="scale_in", params={}), cr.ACCOUNT, max_notional_usd=None
    )
    gone = await handlers["scale_in"].send(no_reads, client_ref=str(uuid.UUID(int=0xD4)))
    assert (gone.answer, gone.error_code) == ("pre_anchor", "oms_not_ready")


#: Node ids the IR refuses at save (`NodeId`, E35-T11) that a rule stored before that bound may
#: still hold, and which the OMS's rule origin refuses (K4a's bound): such a request is built here
#: with its payload copied unvalidated, as a stored document is read.
ODD_NODE_IDS: tuple[str, ...] = ("a.1", "a 1", "n" * 65)


def odd(req: ActionRequest, node: str) -> ActionRequest:
    """`req` naming `node`, an id outside the IR's bound (a document stored before it)."""
    return replace(req, payload=req.payload.model_copy(update={"node_id": node}))


def held_only_as_key(node: str, records: Records) -> bool:
    """Whether the rule's own records hold `node` only as their node's key (24 §15.5): the
    events' `node_ref` and `node_id`, and the audit records' `node_id`, never in another field."""

    def other_fields(fields: Any) -> list[Any]:
        return [v for k, v in dict(fields).items() if k not in ("node_id", "node_ref")]

    held = [v for _, e in records.events for v in other_fields(e.payload)]
    held += [v for _, f in records.audits for v in other_fields(asdict(f))]
    return not any(node in json.dumps(v, default=str) for v in held)


@pytest.mark.parametrize("node", ODD_NODE_IDS, ids=["dot", "space", "too-long"])
async def test_a_rule_action_whose_node_id_is_not_a_short_identifier_fails_with_nothing_sent(
    rig: SubmitRig, node: str
) -> None:
    """Fail closed (K4a's node-id bound; the orchestrator's carry 2): an action whose node id the
    OMS's rule origin refuses reaches the handler and is `failed` (`invalid_params`), its detail
    the register's generic sentence. Nothing reaches the OMS and nothing raises. It is recorded
    and counted as a failed action is; the action's next account is `skipped` (`abort_on_first`),
    and so is the fire's next action (`abort_remaining`). No log line holds the node id, and the
    rule's own records hold it only as their node's key."""
    seed_other(rig)
    counted = Counted()
    orders = build(rig, metrics=counted.metrics)
    with capture_logs() as logs:
        await orders.run(odd(request(targets="all_accounts"), node), request("a2"))
    assert orders.outcomes() == [
        (node, str(cr.ACCOUNT), "failed", "invalid_params"), (node, str(OTHER), "skipped", None),
        ("a2", str(cr.ACCOUNT), "skipped", None),
    ]  # fmt: skip
    assert orders.results()[0]["blocked_detail"] == OMS_DETAIL[NODE_ID]
    assert [verb for verb, _ in orders.records.audits] == ["rules.fired"]
    assert counted.blocked() == {} and counted.of("rule_actions_total")
    assert orders.runtime.requests == [] and orders.creates() == [] and rig.records() == []
    assert not [e for e in logs if e["event"] == "rules.action_failed"]
    assert held_only_as_key(node, orders.records)
    assert not [e for e in logs if node in json.dumps(e, default=str)]


@pytest.mark.parametrize("refusal", ["principal-gone", "origin-refused"])
async def test_a_refusal_decided_at_prepare_records_the_hand_over_then_the_refusal(
    rig: SubmitRig, refusal: str
) -> None:
    """24 §11.5 (the lenses' R1S-01 and R1C2-05): a refusal the handler decides as it builds the
    request (a principal gone since check 5 read it, an origin the OMS refuses) writes as the OMS's
    mapped refusals do: `action_start` and `rules.fired`, then the refusal's `action_fail` (with
    `rules.blocked` for a `permission` block), in that order, and nothing reaches the OMS."""
    orders = build(rig)
    req = request()
    if refusal == "principal-gone":  # check 5 read both views; the handler finds the armer's gone
        gone = Principals(frozenset({cr.ACCOUNT, OTHER}), missing={ARMER})
        orders.handlers["place_order"]._principals = gone
        expected, verbs = ("blocked", "permission"), ["rules.fired", "rules.blocked"]
    else:
        req, expected, verbs = odd(req, "a.1"), ("failed", "invalid_params"), ["rules.fired"]
    await orders.run(req)
    [(_, _, outcome, code)] = orders.outcomes()
    assert (outcome, code) == expected
    assert [e.kind for _, e in orders.records.events] == ["action_start", "action_fail"]
    assert [verb for verb, _ in orders.records.audits] == verbs
    assert orders.lookups.asked == [] and orders.runtime.requests == [] and orders.creates() == []


async def test_a_scale_in_retry_is_answered_from_its_anchor_though_the_position_closed(
    rig: SubmitRig,
) -> None:
    """R1C2-01: the order port consults the anchor before the position. A `scale_in` whose first
    answer was lost after the OMS decided its anchor is answered on its `retry_once` retry from
    that anchor (`ok`), though the position closed in between: the position is read once, by the
    first call, and one order exists."""
    orders = build(rig)
    orders.sides.held[cr.ACCOUNT] = "buy"
    lost = LostAnswer(rig.pipeline, None)
    orders.runtime.submission = lost
    read_for: list[uuid.UUID] = []
    held_side = orders.sides.side

    async def closing(owner: PrincipalView, account_id: uuid.UUID, symbol: str) -> Any:
        read_for.append(account_id)
        side = await held_side(owner, account_id, symbol)
        orders.sides.held.clear()  # the position closes once the first call has read it
        return side

    orders.sides.side = closing  # type: ignore[method-assign]  # the read closes the position
    scale_in = request(action_type="scale_in", params={"qty": "0.01"}, on_error="retry_once")
    await orders.run(scale_in, quiet=False)
    assert lost.first is not None
    async with asyncio.timeout(GUARD_S):
        await lost.first
        await rig.quiet()
    assert orders.outcomes() == [("a1", str(cr.ACCOUNT), "ok", None)]
    assert read_for == [cr.ACCOUNT] and lost.calls == 1 and len(orders.lookups.asked) == 2
    assert len(orders.creates()) == 1 and len(rig.store._orders) == 1
    assert await orders.assert_native_stops() == 1


class NoAnswer:
    """A pipeline whose every call gets no answer (a transport failure), nothing placed."""

    async def submit(self, request: OrderRequest, context: SubmitContext) -> SubmitOutcome:
        raise TimeoutError

    async def answer_replay(self, account_id: Any, replay: Any) -> SubmitOutcome:
        raise AssertionError("no anchor was decided")


async def test_an_entry_left_unknown_counts_at_the_allowance_it_was_sent_under(
    rig: SubmitRig,
) -> None:
    """The ledger ruling (BQ-5 of #5003, the cautious side): an entry whose outcome is left
    `unknown` counts against the day at the allowance its request was sent under, as the order may
    stand; its `action_fail` row names that figure for the day's rebuild, and the next entry finds
    the allowance spent (`cap`) before the OMS."""
    orders = build(rig, notional=DayNotional(prior=Decimal("100")))
    orders.runtime.submission = NoAnswer()
    limits = RuleLimits(max_daily_notional=Decimal("1300"))
    await orders.run(request(), limits=limits)
    [unknown] = orders.results()
    assert (unknown["outcome"], unknown["error_code"]) == ("unknown", "timeout")
    assert unknown["notional_usd"] == "1200"  # the allowance it was sent under: 1300 - 100
    orders.records.events.clear()
    orders.runtime.submission = Recorded(rig.pipeline, orders.runtime)
    await orders.run(request(run=RUN_2), limits=limits)
    assert orders.outcomes() == [("a1", str(cr.ACCOUNT), "blocked", "cap")]
    assert orders.runtime.requests == [] and orders.creates() == []


async def test_a_retry_answered_as_a_replay_counts_the_entry_once(rig: SubmitRig) -> None:
    """The ledger ruling: an entry counts once, whatever its retry answers. A first call whose
    answer is lost, retried once and answered as a replay (at the allowance it was sent under),
    takes that allowance from the day once, never twice: the next fire's ceiling is what the day
    leaves after one count."""
    orders = build(rig, notional=DayNotional(prior=Decimal(0)))
    lost = LostAnswer(rig.pipeline, None)
    orders.runtime.submission = lost
    limits = RuleLimits(max_notional_per_fire=Decimal("1000"), max_daily_notional=Decimal("2500"))
    await orders.run(request(on_error="retry_once"), limits=limits, quiet=False)
    assert lost.first is not None
    async with asyncio.timeout(GUARD_S):
        await lost.first
        await rig.quiet()
    [replayed] = orders.results()
    assert (replayed["outcome"], replayed["notional_usd"]) == ("ok", "1000")
    orders.records.events.clear()
    orders.runtime.submission = Recorded(rig.pipeline, orders.runtime)
    await orders.run(request(run=RUN_2), limits=limits)
    [(sent, _)] = orders.runtime.requests
    assert sent.sizing.max_notional_usd == Decimal("1000")  # 2500 - 1000 leaves the fire's 1000
    assert orders.outcomes() == [("a1", str(cr.ACCOUNT), "ok", None)]


def test_the_action_bound_stands_above_the_pipelines_bounds_after_its_anchor() -> None:
    """BQ-7 (R1C2-02): the action's bound is above every bound the pipeline holds once its anchor
    exists (`OrderSubmission`'s defaults), so the action never gives up first on a submit the
    pipeline still runs on its own bounds."""
    after_anchor = oms_submit._after_anchor_s(
        store_timeout_s=oms_submit.STORE_TIMEOUT_S, place_wait_s=oms_submit.PLACE_WAIT_S,
        result_wait_s=oms_submit.RESULT_WAIT_S,
    )  # fmt: skip
    assert dispatch.ACTION_TIMEOUT_S > after_anchor

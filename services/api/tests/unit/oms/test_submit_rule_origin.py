"""A rule-originated submit through the OMS pipeline (E35-T11 slice 3a; 24 Sec.8.4
"Rule-originated orders" items 1 to 6, Sec.9.5, Sec.15.5; 21 Sec.3.3.4 "Origin").

The pipeline runs over the real B1 facade and the command port's rig (`submit_rig`), with a demo
`FakeTradingPort` (C-13.5). A rule's request is the composition root's: `SubmitContext.origin`,
which no route sets and no body can carry. Its entry writes its group as the rule's
(`abort_on_first`), its rows name the rule, its records are the rule's, a risk refusal names its
cap in process, and its first answer carries the sized notional; a route's request keeps every
one of those as it was.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass, replace
from decimal import Decimal
from pathlib import Path
from typing import Any, cast
from uuid import UUID, uuid4

import pytest

from candleviewer.audit.writer import AuditWriter
from candleviewer.oms.errors import RiskRefused, problem_for
from candleviewer.oms.ports import (
    KeyedRecord,
    RequestRecord,
    RuleOrigin,
    SizedOrder,
    SizingRequest,
    SubmitActor,
)
from candleviewer.oms.submit import SubmitContext, SubmitOutcome
from candleviewer.oms_wiring import OmsAudit, _actor
from candleviewer.risk.models import RiskDecision
from candleviewer.storage.repositories.orders import OrderRow
from tests.rules.executor.native_sl import assert_entry_carries_native_stop
from tests.unit.api.test_orders_route import BODY, World, post
from tests.unit.oms import command_rig as cr
from tests.unit.oms import submit_rig as sr
from tests.unit.oms.submit_rig import SubmitRig
from tests.unit.risk.test_risk_models import _refusal as refusal

RULE = UUID("3f2b8c1e-5d4a-4e6f-9a0b-1c2d3e4f5a6b")
RUN = UUID("7c1d2e3f-4a5b-4c6d-8e9f-0a1b2c3d4e5f")
ARMER = UUID("2b3c4d5e-6f70-4182-93a4-b5c6d7e8f901")
#: The rule's owner, the OMS principal: the rig's user, with no session and no address (24
#: Sec.8.4: the adapter reads no HTTP session).
OWNER_ACTOR = SubmitActor(user_id=sr.USER, role="owner")
ORIGIN = RuleOrigin(
    rule_id=RULE, version=3, run_id=RUN, node_id="a1", armed_by=ARMER, armed_by_role="manager"
)
#: What a rule's request's records add to `after_state` through the runtime's adapter (24
#: Sec.15.5, the E35 threat model's RE-S1).
RULE_FIELDS: dict[str, str] = {
    "decision_source": "rule", "actor_type": "rule", "rule_id": str(RULE), "rule_version": "3",
    "run_id": str(RUN), "node_id": "a1", "owner_user_id": str(sr.USER), "owner_role": "owner",
    "armed_by_user_id": str(ARMER), "armed_by_role": "manager",
}  # fmt: skip
_BY_PROFILE = SizingRequest(mode="profile")


def rule_context(**over: Any) -> SubmitContext:
    """A rule action's context as the composition root's adapter builds it: the owner, the fire's
    key and fingerprint, no correlation id (a job) and the origin."""
    base = SubmitContext(actor=OWNER_ACTOR, client_ref=sr.KEY, request_sha256=sr.SHA, origin=ORIGIN)
    return replace(base, **over)


class RecordingWriter:
    """`AuditWriterPort` that checks each append with the real writer's `build`, then keeps it."""

    def __init__(self, tmp_path: Path) -> None:
        self.real = AuditWriter(cast(Any, object()), str(tmp_path / "audit.wal"))
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def emit(self, action: str, **fields: Any) -> None:
        self.real.build(action, **fields)
        self.calls.append((action, fields))

    async def emit_keyed(self, action: str, name: str, **fields: Any) -> None:
        self.real.build(action, **fields)
        self.calls.append((action, fields))


async def through_the_adapter(records: list[Any], tmp_path: Path) -> list[tuple[str, Any]]:
    """`records` as the runtime's `OmsAudit` writes them: each append's action and fields."""
    writer = RecordingWriter(tmp_path)
    for record in records:
        await OmsAudit(writer, environment="demo").write(record)
    return writer.calls


@pytest.fixture
async def rig() -> AsyncIterator[SubmitRig]:
    async with sr.rigged() as built:
        yield built


async def _row(rig: SubmitRig, outcome: SubmitOutcome) -> OrderRow:
    assert outcome.order_id is not None
    row = await rig.port.orders.get(cr.ACCOUNT, outcome.order_id)
    assert row is not None
    return row


async def test_a_rule_origin_entry_writes_its_group_with_origin_rule_and_ids(
    rig: SubmitRig,
) -> None:
    """G "The origin is set server-side only" (the rule's half) and the OMS half of G "Every rule
    entry carries a native stop (C-2.6)": the group is the rule's, naming the rule and the fire's
    run, keyed by the action's `client_ref` and created by the owner; the order's row names the
    rule; and the entry carries its native stop at every layer it crosses."""
    outcome = await rig.submit(sr.entry(), rule_context())
    await rig.quiet()
    assert outcome.status == 202 and outcome.trade_group_id is not None
    group = rig.store._groups[outcome.trade_group_id].group
    assert (group.origin, group.origin_rule_id, group.origin_rule_run_id) == ("rule", RULE, RUN)
    assert (group.client_group_ref, group.created_by) == (str(sr.KEY), sr.USER)
    row = await _row(rig, outcome)
    assert (row.origin, row.origin_ref, row.reduce_only) == ("rule", str(RULE), False)
    assert_entry_carries_native_stop(
        row, reference_price=sr.REFERENCE, stops=rig.store._stops.values(),
        records=rig.records(), calls=rig.port.demo.calls,
    )  # fmt: skip


@pytest.mark.parametrize(
    ("origin", "policy", "kind"),
    [(ORIGIN, "abort_on_first", "rule"), (None, "best_effort", "manual")],
    ids=["a-rule", "a-route"],
)
async def test_rule_origin_group_policy_is_abort_on_first(
    rig: SubmitRig, origin: RuleOrigin | None, policy: str, kind: str
) -> None:
    """24 Sec.9.5: a rule-originated group's policy is `abort_on_first`, never the column's
    `best_effort` taken by omission; a route's stays `best_effort`, `manual`."""
    ctx = rule_context() if origin is not None else sr.context()
    outcome = await rig.submit(sr.entry(), ctx)
    assert outcome.trade_group_id is not None
    group = rig.store._groups[outcome.trade_group_id].group
    assert (group.leg_failure_policy, group.origin) == (policy, kind)


async def test_the_route_never_sets_an_origin(rig: SubmitRig) -> None:
    """G "The origin is set server-side only": the `placeOrder` route hands the pipeline a context
    with no origin; a body naming an origin, its ref or a lane is refused before the pipeline, as
    the strict body model forbids extras; and a route's order keeps both columns NULL (the
    forbidden case)."""
    world = World()
    answer = await post(world, body=BODY)
    assert answer.status_code == 202
    [(_order, context)] = world.oms.submission.submitted
    assert context.origin is None
    for forged in ({"origin": "rule"}, {"origin_ref": str(RULE)}, {"lane": "entry"},
                   {"origin": {"rule_id": str(RULE), "version": 3}}):  # fmt: skip
        world = World()
        refused = await post(world, body=BODY | forged)
        assert (refused.status_code, world.oms.submission.submitted) == (400, [])
        assert {e["rule"] for e in refused.json()["errors"]} == {"extra_forbidden"}
    row = await _row(rig, await rig.submit(sr.entry(), sr.context()))
    assert (row.origin, row.origin_ref) == (None, None)


async def test_a_route_order_keeps_its_lane_and_a_null_origin(rig: SubmitRig) -> None:
    """A route's reduce-only close keeps the `critical` lane of SR-E29-01, its row names no origin
    and its answer carries no notional: only a rule's request changes any of them."""
    rig.port.demo.seed_position(cr.position(qty="0.050"))
    outcome = await rig.submit(sr.flatten(), sr.context())
    await rig.quiet()
    row = await _row(rig, outcome)
    assert (row.origin, row.origin_ref, row.reduce_only) == (None, None, True)
    assert [c.lane for c in rig.port.demo.calls if c.method == "place_order"] == ["critical"]
    assert outcome.notional_usd is None


async def test_a_rule_reduce_only_order_row_carries_origin_and_origin_ref(rig: SubmitRig) -> None:
    """24 Sec.8.4 item 2: a rule's reduce-only order, which joins no group, names its rule on its
    own row, so a resumed send finds its origin there; it carries no notional (item 6)."""
    rig.port.demo.seed_position(cr.position(qty="0.050"))
    outcome = await rig.submit(sr.flatten(), rule_context())
    row = await _row(rig, outcome)
    assert (row.origin, row.origin_ref, row.reduce_only) == ("rule", str(RULE), True)
    assert (outcome.trade_group_id, outcome.notional_usd) == (None, None)


async def test_rule_origin_request_records_carry_the_decision_source(
    rig: SubmitRig, tmp_path: Path
) -> None:
    """24 Sec.15.5, RE-S1: `orders.submit`, `trade_group.submit` and the entry's `sl.attached`
    each carry the origin, and the runtime's adapter writes each as the rule's: the actor
    `rule:<rule_id>@v<n>` with no user, session or address, the decision source, the rule, its
    run and node, and both users' ids and roles."""
    await rig.submit(sr.entry(), rule_context())
    await rig.quiet()
    written = [r for r in rig.records() if isinstance(r, RequestRecord | KeyedRecord)]
    actions = {"orders.submit", "trade_group.submit", "sl.attached"}
    ours = [r for r in written if r.action in actions]
    assert {r.action for r in ours} == actions and all(r.origin == ORIGIN for r in ours)
    for action, fields in await through_the_adapter(ours, tmp_path):
        assert (fields["actor_label"], fields["actor_user_id"]) == (f"rule:{RULE}@v3", None), action
        assert "session_id" not in fields and "actor_ip" not in fields
        assert fields["after_state"].items() >= RULE_FIELDS.items(), action


@dataclass
class RefusingGate:
    """A risk gate that refuses every order, naming `cap` (the risk models suite's refusal)."""

    cap: str | None

    def check(self, order: SizedOrder, *, profile: object) -> RiskDecision:
        return refusal(cap=self.cap)


async def test_risk_refusal_names_the_cap() -> None:
    """24 Sec.8.4 item 5: a rule's refused order names the cap that refused it, the risk gate's
    `RiskDecision.cap` (step 5) or the field the size step judged (step 3), in process; the
    route's `403 risk_limit_breached` body is the same with or without it, and the refusal is
    the rule's record."""
    async with sr.rigged(risk=RefusingGate("max_open_positions")) as rig:
        with pytest.raises(RiskRefused) as gated:
            await rig.submit(sr.entry(), rule_context())
        [denied] = [r for r in rig.records("orders.submit") if isinstance(r, RequestRecord)]
        assert (denied.outcome, denied.reason, denied.origin) == (
            "denied",
            "risk_limit_breached",
            ORIGIN,
        )
    async with sr.rigged() as rig:
        rig.profiles.held[(cr.ACCOUNT, None)] = sr.profile(max_position_notional="50")
        with pytest.raises(RiskRefused) as sized:
            await rig.submit(
                sr.entry(sizing=_BY_PROFILE, stop_loss=None, take_profit=None), rule_context()
            )
    assert (gated.value.cap, sized.value.cap) == ("max_open_positions", "max_position_notional")
    assert problem_for(gated.value) == problem_for(RiskRefused())
    assert gated.value.errors == () and "max_open_positions" not in str(gated.value)


#: (sizing, type, limit price, market mid): by profile at a limit and at the market, and a fixed
#: quantity off the lot step, which the size step floors (0.0105 to 0.010).
_SIZED: list[tuple[SizingRequest, str, Decimal | None, Decimal]] = [
    (_BY_PROFILE, "limit", Decimal("60000"), Decimal("60000")),
    (_BY_PROFILE, "market", None, Decimal("61000")),
    (SizingRequest(mode="fixed_qty", qty=Decimal("0.0105")), "limit", Decimal("60000"),
     Decimal("60000")),
]  # fmt: skip


@pytest.mark.parametrize(("sizing", "order_type", "price", "mid"), _SIZED)
async def test_a_rule_entry_answer_carries_its_sized_notional(
    rig: SubmitRig, sizing: SizingRequest, order_type: str, price: Decimal | None, mid: Decimal
) -> None:
    """24 Sec.8.4 item 6: a rule's entry answers the sized order's notional, its sized quantity
    times the reference price it sized at (the limit's price, else the market's), never the
    request's figures, and never in its repr (C-12.6); a route's answer carries none."""
    rig.prices.price = mid
    request = sr.entry(
        sizing=sizing, stop_loss=None, take_profit=None, order_type=order_type, price=price
    )
    outcome = await rig.submit(request, rule_context())
    await rig.quiet()
    row = await _row(rig, outcome)
    assert outcome.notional_usd == row.qty * (price if price is not None else mid)
    assert sizing.qty is None or row.qty < sizing.qty  # the size step's quantity, not the request's
    assert outcome.notional_usd is not None and str(outcome.notional_usd) not in repr(outcome)
    route = await rig.submit(request, sr.context(client_ref=uuid4()))
    assert route.notional_usd is None


@pytest.mark.parametrize(
    "over",
    [{"version": 0}, {"version": True}, {"node_id": ""}, {"armed_by_role": None}],
    ids=["version-0", "version-bool", "no-node", "armer-without-role"],
)
def test_a_rule_origin_names_its_version_its_node_and_its_armer(over: dict[str, Any]) -> None:
    """`RuleOrigin` is built by the server from the fire it serves: a version from 1, a node, and
    an armer with its role or neither; anything else is a defect, refused at construction."""
    with pytest.raises(ValueError):
        replace(ORIGIN, **over)
    assert replace(ORIGIN, armed_by=None, armed_by_role=None).armed_by is None


#: The rule origin's node id is bounded to a short identifier: `[A-Za-z0-9_-]{1,64}`, whole.
_NODE_REFUSED: list[Any] = [
    "x" * 65, "a1\nb2", "a1\n", "n\u0153ud", "", "a 1", 7,
]  # fmt: skip
_NODE_REFUSED_IDS = [
    "65-characters", "embedded-newline", "trailing-newline", "non-ascii", "empty", "space",
    "not-text",
]  # fmt: skip


@pytest.mark.parametrize("node", _NODE_REFUSED, ids=_NODE_REFUSED_IDS)
def test_a_rule_origins_node_id_is_bounded_to_a_short_identifier(node: Any) -> None:
    """The rule origin's node id is bounded to a short identifier, matched whole: 65 characters, a
    newline inside, a newline at the end, a character outside ASCII, no character, a space and a
    value that is not text are each refused at construction, with one fixed message that holds
    none of the input."""
    with pytest.raises(ValueError) as refused:
        replace(ORIGIN, node_id=node)
    assert str(refused.value) == "a rule origin's node id is not a short identifier"
    assert node == "" or str(node) not in str(refused.value)  # "" is in every text


@pytest.mark.parametrize(
    "node",
    ["a1", "c0", "n" * 64, "node_1-b"],
    ids=["a1", "c0", "64-characters", "underscore-hyphen"],
)
def test_a_rule_origin_admits_a_short_identifier_as_its_node(node: str) -> None:
    """The contract's node ids (`a1`, `c0`), the longest id the bound admits, and one with `_`
    and `-`."""
    assert replace(ORIGIN, node_id=node).node_id == node


def test_a_rules_request_never_takes_the_protective_carve_out() -> None:
    """The close routes' C-2.6 carve-out (`protective`) is theirs alone: a context naming both it
    and a rule origin is refused, so no rule's request passes the switches at step 6."""
    with pytest.raises(ValueError, match="protective close"):
        rule_context(protective=True)


@pytest.mark.parametrize(
    "over",
    [{"replayed": True}, {"trade_group_id": None}, {"notional_usd": Decimal(0)},
     {"notional_usd": Decimal("NaN")}],
    ids=["a-replay", "no-group", "zero", "nan"],
)  # fmt: skip
def test_only_an_entrys_first_answer_carries_a_notional_above_zero(over: dict[str, Any]) -> None:
    """24 Sec.8.4 item 6: a replay and a reduce-only order (no group) carry no notional, and one
    carried is a finite figure above zero."""
    base: dict[str, Any] = {
        "status": 202, "anchor_id": uuid4(), "order_id": uuid4(), "trade_group_id": uuid4(),
        "lifecycle": "submitted", "notional_usd": Decimal("600"),
    }  # fmt: skip
    assert SubmitOutcome(**base).notional_usd == Decimal("600")
    with pytest.raises(ValueError, match="notional"):
        SubmitOutcome(**(base | over))


def test_a_rules_record_names_the_owner_it_acts_for() -> None:
    """A rule's record has no user of its own (`rule:<rule_id>@v<n>`), so it names the owner it
    acts for: a keyed record and the adapter both refuse one that names none (RE-S1)."""
    with pytest.raises(ValueError, match="names the owner"):
        KeyedRecord(
            "sl.attached", "x", cr.ACCOUNT, "recorded_stop", uuid4(), "success", "info",
            "entry_attach", None, {}, None, None, ORIGIN,
        )  # fmt: skip
    with pytest.raises(ValueError, match="names the owner"):
        _actor(None, None, ORIGIN)
    assert _actor(OWNER_ACTOR, sr.USER, ORIGIN) == {
        "actor_label": ORIGIN.actor_label, "actor_user_id": None,
    }  # fmt: skip

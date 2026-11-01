"""The rate lanes of what a rule sends (E35-T11 slice 3a; 24 Sec.8.4 "Rule-originated orders"
item 3, Sec.8.7, Sec.14.2 rule 12; the E35 threat model's RE-D6; C-12.7, C-2.6).

A rule never draws on the `critical` reserve but in the restart case: its orders and its own
cancels ride `entry`, a reduce-only close included, a create resumed from its stored row too; a
cancel's reason sets its lane, every protective one `critical`, the circuit breaker's among them;
a cancel B1 sends with no registration (a KILL's, a rebuilt machine's resumed call) rides
`critical`; and the native stop of a rule's entry is the OMS's protection, `critical`. No route
names an origin, a rule's reason or a lane: the server builds them. The exchange is a demo
`FakeTradingPort` (C-13.5) and, for the stop's lane at the venue, the Bybit port over the
transcribed reply.
"""

from __future__ import annotations

import ast
from collections.abc import AsyncIterator
from dataclasses import replace
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest

import candleviewer
from candleviewer.exchange.base.models import RateHeadroom, TradingStopRequest
from candleviewer.exchange.bybit.config import EndpointClass
from candleviewer.oms.commands import place_request
from candleviewer.oms.errors import RateBudgetExceeded
from candleviewer.oms.exits import CANCEL_LANES, AmendTerms, CancelReason, ExitCaller
from candleviewer.oms.ports import RequestRecord, RuleOrigin
from candleviewer.storage.repositories.accounts import OwnerScope
from candleviewer.storage.repositories.orders import NewOrder, OrderRow, ScopedOrder
from tests._corpus import rest
from tests.unit.api.test_orders_route import BODY, World, post
from tests.unit.exchange.bybit._trading import RecordingGovernor, Venue, account, make_port
from tests.unit.oms import command_rig as cr
from tests.unit.oms import submit_rig as sr
from tests.unit.oms.submit_rig import SubmitRig
from tests.unit.oms.test_exits import exits_of
from tests.unit.oms.test_submit_rule_origin import (
    ORIGIN,
    OWNER_ACTOR,
    RULE,
    rule_context,
    through_the_adapter,
)

#: What a rule, a user and the breaker send, its reason, and the lane it rides (24 Sec.8.4 item
#: 3). The row `("cancel", "rule", "entry")` is the ruled lane of a rule's own cancel.
SENDS: list[tuple[str, CancelReason, str]] = [
    ("cancel", "rule", "entry"),
    ("cancel", "rule_circuit_breaker", "critical"),
    ("cancel", "user", "critical"),
    ("cancel", "cancel_all", "critical"),
    ("amend", "rule", "entry"),
    ("amend", "user", "critical"),
]
_PKG = Path(candleviewer.__file__).resolve().parent


@pytest.fixture
async def rig() -> AsyncIterator[SubmitRig]:
    async with sr.rigged() as built:
        yield built


def _lanes(calls: Any, method: str) -> list[str]:
    return [c.lane for c in calls if c.method == method]


async def _resting_close(rig: SubmitRig) -> OrderRow:
    """A route's reduce-only limit close of a long, resting at the venue: `submitted`."""
    rig.port.demo.seed_position(cr.position(qty="0.050"))
    close = sr.flatten(order_type="limit", price=Decimal("61000"))
    outcome = await rig.submit(close, sr.context(client_ref=uuid4()))
    await rig.quiet()
    assert outcome.order_id is not None
    row = await rig.port.orders.get(cr.ACCOUNT, outcome.order_id)
    assert row is not None and rig.machines.state(row.id) == ("submitted", "not_required")
    return row


def _rule_close() -> NewOrder:
    """A rule's reduce-only market close as its first persist stores it (21 Sec.3.3.4)."""
    return cr.new_order(
        intent="flatten", reduce_only=True, side="Sell", order_type="Market", price=None,
        stop_loss=None, take_profit=None, origin="rule", origin_ref=str(RULE),
    )  # fmt: skip


async def test_rule_cannot_consume_rate_reserve(rig: SubmitRig) -> None:
    """G "A rule never spends the rate reserve, but the circuit breaker's own cancels may (RE-D6,
    C-12.7)": with the `critical` reserve spent, a rule's entry and its reduce-only close each
    pass step 7's headroom and leave in `entry`, where a route's close meets the spent reserve
    and is refused, nothing sent; and a create a restart resumes from the rule's stored row,
    which has no request, keeps `entry` from the row's origin."""
    spent = RateHeadroom(lane="critical", tokens=0.0, wait_s=60.0)
    rig.port.demo.set_headroom(cr.ACCOUNT, spent)
    rig.port.demo.seed_position(cr.position(qty="0.050"))
    await rig.submit(sr.entry(), rule_context())
    await rig.quiet()
    await rig.submit(sr.flatten(), rule_context(client_ref=uuid4()))
    await rig.quiet()
    assert _lanes(rig.port.demo.calls, "place_order") == ["entry", "entry"]
    with pytest.raises(RateBudgetExceeded):
        await rig.submit(sr.flatten(), sr.context(client_ref=uuid4()))
    assert _lanes(rig.port.demo.calls, "place_order") == ["entry", "entry"]
    resumed, stored = cr.build_rig(), _rule_close()
    await resumed.stored(stored)
    resumed.now.us = cr.T0_US + 1_000_000
    answer = await resumed.port.place(cr.command("place", stored))
    assert answer["ok"] is True
    assert _lanes(resumed.demo.calls, "place_order") == ["entry"]
    route_row = replace(stored, origin=None, origin_ref=None)
    assert (place_request(stored, cr.ref()).lane, place_request(route_row, cr.ref()).lane) == (
        "entry", "critical",
    )  # fmt: skip


@pytest.mark.parametrize(("send", "reason", "lane"), SENDS)
async def test_breaker_cancels_ride_the_critical_lane_while_every_other_rule_send_rides_entry(
    rig: SubmitRig, send: str, reason: CancelReason, lane: str
) -> None:
    """G "A rule never spends the rate reserve, but the circuit breaker's own cancels may (RE-D6,
    C-12.7)": through the exit service, B1 and the command port, a rule's own cancel rides
    `entry`; the breaker's, a user's and a cancel-all's ride `critical`; a rule's amend of a
    reduce-only close rides `entry` where a user's of the same order rides `critical` (its own
    lane, SR-E29-01)."""
    row = await _resting_close(rig)
    origin = ORIGIN if reason in ("rule", "rule_circuit_breaker") else None
    exits = exits_of(rig)
    if send == "cancel":
        assert CANCEL_LANES[reason] == lane
        got = await exits.cancel_admitted(
            row, actor=OWNER_ACTOR, reason=reason, request_id=None, origin=origin
        )
    else:
        scoped = ScopedOrder(row, None, None, sr.USER, True)
        caller = ExitCaller(OwnerScope(sr.USER), OWNER_ACTOR, origin=origin)
        terms = AmendTerms(price=Decimal("61500"))
        got = await exits.amend(scoped, terms, caller=caller, expected_seq=None)
    assert (got.kind, got.status) == ("accepted", 202), got
    method = "cancel_order" if send == "cancel" else "amend_order"
    assert _lanes(rig.port.demo.calls, method) == [lane]


async def test_breaker_cancel_reason_is_recorded(rig: SubmitRig, tmp_path: Path) -> None:
    """24 Sec.15.5: the breaker's cancel is `orders.cancel` with reason `rule_circuit_breaker`,
    its detail naming the tripped rule; it carries no rule origin (it protects the account, it is
    no rule's send), so its actor is the principal its caller names. A breaker's cancel naming no
    rule, or a user's naming one, is a defect, refused before anything is recorded."""
    row = await _resting_close(rig)
    exits = exits_of(rig)
    defects: list[tuple[CancelReason, RuleOrigin | None]] = [
        ("rule_circuit_breaker", None), ("user", ORIGIN), ("rule", None),
    ]  # fmt: skip
    for reason, origin in defects:
        with pytest.raises(ValueError, match="names its rule"):
            await exits.cancel_admitted(
                row, actor=OWNER_ACTOR, reason=reason, request_id=None, origin=origin
            )
    assert rig.records("orders.cancel") == []
    await exits.cancel_admitted(
        row, actor=OWNER_ACTOR, reason="rule_circuit_breaker", request_id=None, origin=ORIGIN
    )
    records = [r for r in rig.records("orders.cancel") if isinstance(r, RequestRecord)]
    assert [(r.outcome, r.reason, r.origin) for r in records] == [
        ("success", "rule_circuit_breaker", None), ("success", "cancelled", None),
    ]  # fmt: skip
    assert (records[0].detail["rule_id"], records[0].detail["rule_version"]) == (str(RULE), "3")
    [(_, intent), _outcome] = await through_the_adapter(records, tmp_path)
    assert (intent["actor_label"], intent["actor_user_id"]) == ("user:owner", sr.USER)
    assert intent["after_state"]["rule_id"] == str(RULE)


async def test_a_rule_cancel_is_recorded_with_its_reason(rig: SubmitRig, tmp_path: Path) -> None:
    """24 Sec.15.5: a rule's own cancel is `orders.cancel` with reason `rule`, its intent and its
    outcome the rule's records, as the runtime's adapter writes them (RE-S1)."""
    row = await _resting_close(rig)
    await exits_of(rig).cancel_admitted(
        row, actor=OWNER_ACTOR, reason="rule", request_id=None, origin=ORIGIN
    )
    records = [r for r in rig.records("orders.cancel") if isinstance(r, RequestRecord)]
    assert [(r.outcome, r.reason, r.origin) for r in records] == [
        ("success", "rule", ORIGIN), ("success", "cancelled", ORIGIN),
    ]  # fmt: skip
    for _action, fields in await through_the_adapter(records, tmp_path):
        assert (fields["actor_label"], fields["actor_user_id"]) == (ORIGIN.actor_label, None)
        assert fields["after_state"]["decision_source"] == "rule"


async def _resting(port_rig: cr.Rig, order: NewOrder) -> OrderRow:
    """`order` resting at the venue, stored `submitted` and bound to the venue's id for it."""
    resting = cr.exchange_order(order)
    port_rig.demo.seed_order(resting, uid=cr.UIDS["demo"])
    bound = replace(order, exchange_order_id=resting.exchange_order_id)
    return await port_rig.stored(bound, lifecycle="submitted")


@pytest.mark.parametrize("kind", ["kill_cancel", "cancel"], ids=["a-kill", "a-resumed-call"])
async def test_an_unregistered_cancel_keeps_the_critical_lane(kind: Any) -> None:
    """The restart case (24 Sec.8.4 item 3): B1's `CANCEL` carries no origin, so a cancel of a
    rule's order that finds no registration rides `critical`, the protective direction: a KILL's,
    which spends none even while a rule's registration in `entry` waits, and a rebuilt machine's
    call resumed after a restart, which has lost its reason."""
    port_rig = cr.build_rig()
    row = await _resting(port_rig, cr.new_order(origin="rule", origin_ref=str(RULE)))
    if kind == "kill_cancel":
        cr.taken(port_rig.port, row.id, "cancel", lane="entry")
    await port_rig.port.cancel(cr.command(kind, row))
    assert [(c.method, c.lane) for c in port_rig.demo.calls] == [("cancel_order", "critical")]


async def test_a_rule_entrys_native_stop_attach_keeps_the_critical_lane() -> None:
    """C-2.6: the native stop B1 attaches for a rule's entry is the OMS's protection, not a rule's
    send: the `trading-stop` call rides `critical`, at the exchange fake and at the Bybit port,
    where it takes its token on the position class."""
    port_rig = cr.build_rig()
    order = cr.new_order(origin="rule", origin_ref=str(RULE))
    await port_rig.stored(order, lifecycle="submitted")
    port_rig.demo.seed_position(cr.position())
    port_rig.now.us = cr.T0_US + 7_000_000
    await port_rig.port.attach_stop(cr.command("attach_stop", order, {"stop_loss": "58000"}))
    assert _lanes(port_rig.demo.calls, "set_trading_stop") == ["critical"]
    venue = Venue().on("/v5/position/trading-stop", rest("rest/trading-trading-stop-reply.json"))
    governor = RecordingGovernor()
    stop = TradingStopRequest(account=account(), symbol="BTCUSDT", stop_loss=Decimal("58000"))
    await make_port(venue, governor=governor).set_trading_stop(stop)
    assert [(cls, lane) for _, cls, lane, _ in governor.acquired] == [
        (EndpointClass.POSITION, "critical")
    ]


def _calls(tree: ast.AST, name: str) -> list[ast.Call]:
    return [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and (getattr(node.func, "id", None) == name or getattr(node.func, "attr", None) == name)
    ]


async def test_a_rule_lane_comes_from_the_server_never_from_the_request() -> None:
    """The forged-origin and cross-account case: no route or WS module builds an origin, names a
    rule's cancel reason or a lane, and only the OMS's command port builds a cancel's request; a
    `placeOrder` body that forges an origin or a lane is refused before the pipeline, the
    owner's and a manager's naming an account outside its grants alike."""
    for path in sorted([*(_PKG / "api").rglob("*.py"), *(_PKG / "ws").rglob("*.py")]):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        named = [k.arg for c in _calls(tree, "SubmitContext") for k in c.keywords]
        named += [k.arg for c in _calls(tree, "ExitCaller") for k in c.keywords]
        assert "origin" not in named, path.name
        assert not _calls(tree, "RuleOrigin") and not _calls(tree, "CancelOrderRequest"), path.name
        for call in _calls(tree, "cancel_admitted"):
            keywords = {k.arg: k.value for k in call.keywords}
            assert "origin" not in keywords, path.name
            reason = keywords.get("reason")
            assert not (isinstance(reason, ast.Constant) and str(reason.value).startswith("rule"))
    forged = {"origin": "rule", "origin_ref": str(RULE), "lane": "entry", "reason": "rule"}
    for who, body in (("owner", BODY), ("manager", BODY | {"exchange_account_id": str(uuid4())})):
        world = World()
        refused = await post(world, who, body=body | forged)
        assert refused.status_code in (400, 403, 404) and world.oms.submission.submitted == []


def test_the_lane_table_names_every_reason_once() -> None:
    """Every `CancelReason` has its lane, and only a rule's own cancel rides `entry`."""
    assert set(CANCEL_LANES) == {"user", "cancel_all", "rule", "rule_circuit_breaker"}
    assert [r for r, lane in CANCEL_LANES.items() if lane == "entry"] == ["rule"]
    assert UUID(int=0) != RULE  # the rule's id is a canonical UUID, not a placeholder

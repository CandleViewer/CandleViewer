"""E35-T11 slice 3b: a rule entry's OMS request, its context and the OMS's answer, built at the
composition root (24 §8.4 "Rule-originated orders", §11.5, §11.6, §11.9; BQ-2 to BQ-5 and BQ-8
of #863; RE-S1).

The request carries what the rule asked for and never a figure the engine sized; the context names
the owner as the OMS principal and the rule as the origin, with no session; and every OMS answer
maps onto one handler answer of 24 §11.9, a refusal onto the closed `blocked_by` set. The records
of a request built here are run through the real pipeline (`submit_rig`) and the runtime's audit
adapter, so the attribution checked is the one the OMS writes.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from candleviewer.domain.order_entry import OrderEntryRefusal
from candleviewer.oms.errors import (
    AuditNotDurable,
    ClockDriftBlocked,
    ExchangeUnavailable,
    IdempotencyInFlight,
    IdempotencyKeyReuse,
    OmsError,
    OmsNotReady,
    OrderEntryRefused,
    OrderInvalid,
    RateBudgetExceeded,
    RiskRefused,
    SizingUnavailable,
    StopRequestPending,
    StoreUnavailable,
    TradingDisabled,
)
from candleviewer.oms.ports import KeyedRecord, RequestRecord
from candleviewer.oms.submit import RECONCILING, SubmitOutcome, entry_order_id
from candleviewer.oms.validator import OrderPlacementRefused
from candleviewer.rules.executor.handlers import HandlerAnswer, prepared
from candleviewer.rules.executor.params import PlaceOrderParams, ScaleInParams, entry_params
from candleviewer.rules.executor.results import BLOCKED_BY, BLOCKED_DETAIL, OMS_DETAIL, READ_ONLY
from candleviewer.rules.ir.models import Action, RuleScope
from candleviewer.rules.scope import ScopeInstanceRef
from candleviewer.rules_oms_requests import (
    answer_of,
    canonical_request,
    order_request,
    refusal_answer,
    rule_origin,
    submit_context,
    system_role,
)
from tests.rules.executor.request_builders import action_request
from tests.unit.oms import command_rig as cr
from tests.unit.oms import submit_rig as sr
from tests.unit.oms.test_submit_rule_origin import through_the_adapter

RULE = uuid.UUID("3f2b8c1e-5d4a-4e6f-9a0b-1c2d3e4f5a6b")
RUN = uuid.UUID("7c1d2e3f-4a5b-4c6d-8e9f-0a1b2c3d4e5f")
ARMER = uuid.UUID("2b3c4d5e-6f70-4182-93a4-b5c6d7e8f901")
GROUP, ORDER, ANCHOR = (uuid.UUID(int=i) for i in (0x61, 0x62, 0x63))
CEILING = Decimal("2500")


def place(**params: Any) -> PlaceOrderParams:
    parsed = entry_params(
        "place_order", {"side": "buy", "order_type": "market", "qty_mode": "profile"} | params
    )
    assert isinstance(parsed, PlaceOrderParams)
    return parsed


def scale(**params: Any) -> ScaleInParams:
    parsed = entry_params("scale_in", params)
    assert isinstance(parsed, ScaleInParams)
    return parsed


def rule_request(**over: Any) -> Any:
    action = Action.model_validate({"node_id": "n7", "type": "place_order", "params": {}})
    instance = ScopeInstanceRef(f"BTCUSDT@{cr.ACCOUNT}", "BTCUSDT", cr.ACCOUNT)
    scope = RuleScope.model_validate({"level": "account"})
    base: dict[str, Any] = {
        "action_type": "place_order", "payload": action, "rule_id": str(RULE), "version": 3,
        "run_id": RUN, "armed_by": str(ARMER),
    }  # fmt: skip
    return action_request(scope, sr.USER, instance, **(base | over))


async def test_rule_order_audit_actor_is_rule_with_armer(tmp_path: Path) -> None:
    """G "The owner is the OMS principal and the armer is recorded (RE-S1, E35-FR-01)": the
    context names the owner as the OMS principal, by id and role, with no session, address or
    correlation id, and the rule as the origin with its armer; through the real pipeline and the
    runtime's audit adapter every record of the request is the rule's, `rule:<rule_id>@v<n>`,
    with no user id and both users' ids and roles."""
    req = rule_request()
    context = submit_context(
        owner=req.owner, owner_role="manager", origin=rule_origin(req, "owner"),
        client_ref=str(sr.KEY), request_sha256=sr.SHA,
    )  # fmt: skip
    assert (context.actor.user_id, context.actor.role, context.client_ref) == (
        sr.USER, "manager", sr.KEY,
    )  # fmt: skip
    assert (context.actor.session_id, context.actor.ip, context.request_id) == (None, None, None)
    assert not context.protective and context.operation == "placeOrder"
    entry = order_request(
        place(stop_loss={"unit": "price", "value": str(sr.STOP)}), account_id=cr.ACCOUNT,
        symbol=sr.SYMBOL, side="buy", max_notional_usd=None,
    )  # fmt: skip
    async with sr.rigged() as rig:
        outcome = await rig.submit(entry, context)
        await rig.quiet()
        written = [r for r in rig.records() if isinstance(r, RequestRecord | KeyedRecord)]
    assert outcome.status == 202
    ours = [r for r in written if r.action in {"orders.submit", "trade_group.submit"}]
    assert {r.action for r in ours} == {"orders.submit", "trade_group.submit"}
    for action, fields in await through_the_adapter(ours, tmp_path):
        assert (fields["actor_label"], fields["actor_user_id"]) == (f"rule:{RULE}@v3", None), action
        after = fields["after_state"]
        assert (after["owner_user_id"], after["owner_role"]) == (str(sr.USER), "manager"), action
        assert (after["armed_by_user_id"], after["armed_by_role"]) == (str(ARMER), "owner")
        assert (after["run_id"], after["node_id"]) == (str(RUN), "n7")


def test_the_armers_role_is_one_of_the_closed_role_set() -> None:
    """The orchestrator's carry 3: the origin's `armed_by_role` is one of the closed role set
    (`Role`, the `role_name` enum), never a free string: `system_role` reads a view's role into it
    (a name outside it is none), and the origin refuses one outside it."""
    names = ("owner", "manager", "viewer", "admin", "Owner", None)
    assert [system_role(n) for n in names] == ["owner", "manager", "viewer", None, None, None]
    with pytest.raises(ValueError):
        rule_origin(rule_request(), "admin")  # type: ignore[arg-type]  # outside the closed set


def test_the_origin_names_its_armer_with_the_armers_role_or_neither() -> None:
    assert rule_origin(rule_request(armed_by=None), "owner").armed_by_role is None
    with pytest.raises(ValueError):  # an armer read with no role is no origin
        rule_origin(rule_request(), None)
    with pytest.raises(ValueError):
        rule_origin(rule_request(rule_id="not-a-uuid"), "owner")


@pytest.mark.parametrize(
    ("params", "mode", "qty", "pct"),
    [
        (place(), "profile", None, None),
        (place(qty_mode="explicit", qty="0.010"), "fixed_qty", Decimal("0.01"), None),
        (scale(), "profile", None, None),
        (scale(qty="0.5"), "fixed_qty", Decimal("0.5"), None),
        (scale(qty_pct="25"), "pct_position", None, Decimal("25")),
    ],
    ids=["profile", "explicit", "scale-in-profile", "scale-in-qty", "scale-in-pct"],
)
def test_profile_qty_mode_is_never_sized_by_the_engine(
    params: PlaceOrderParams | ScaleInParams, mode: str, qty: Decimal | None, pct: Decimal | None
) -> None:
    """24 §11.6: the engine never sizes. `qty_mode: profile` is the OMS's `profile` sizing with no
    quantity, an explicit one its own `qty`, a scale-in's percent `pct_position`; the allowance
    rides as `max_notional_usd`, the one figure the engine passes, a ceiling (C-12.5)."""
    request = order_request(
        params, account_id=cr.ACCOUNT, symbol="ETHUSDT", side="sell", max_notional_usd=CEILING
    )
    sizing = request.sizing
    assert (sizing.mode, sizing.qty, sizing.pct, sizing.max_notional_usd) == (
        mode, qty, pct, CEILING,
    )  # fmt: skip
    assert (sizing.notional_usd, sizing.risk_per_trade_usd, sizing.risk_per_trade_pct) == (
        None, None, None,
    )  # fmt: skip
    assert (request.account_id, request.symbol, request.side) == (cr.ACCOUNT, "ETHUSDT", "sell")
    assert not request.reduce_only
    expected_intent = "entry" if isinstance(params, PlaceOrderParams) else "scale_in"
    assert request.intent == expected_intent


def test_the_stop_and_take_profit_ride_as_offsets_and_a_limit_keeps_its_price() -> None:
    params = place(
        order_type="limit", price="61000.5", profile="00000000-0000-4000-8000-0000000000aa",
        stop_loss={"unit": "percent", "value": "1.5"},
        take_profits=[{"unit": "price", "value": "64000"}],
    )  # fmt: skip
    request = order_request(
        params, account_id=cr.ACCOUNT, symbol="BTCUSDT", side="buy", max_notional_usd=None
    )
    assert (request.order_type, request.price) == ("limit", Decimal("61000.5"))
    assert request.stop_loss is not None and request.take_profit is not None
    assert (request.stop_loss.unit, request.stop_loss.value) == ("percent", Decimal("1.5"))
    assert (request.take_profit.unit, request.take_profit.value) == ("price", Decimal("64000"))
    assert str(request.profile_id) == "00000000-0000-4000-8000-0000000000aa"
    bare = order_request(
        scale(qty="1"), account_id=cr.ACCOUNT, symbol="BTCUSDT", side="sell", max_notional_usd=None
    )
    assert (bare.order_type, bare.price, bare.stop_loss, bare.take_profit) == (
        "market", None, None, None,
    )  # fmt: skip


def test_the_canonical_request_is_one_fingerprint_for_one_ask() -> None:
    """24 §11.9: the fingerprint is the canonical request's, decimals as their plain text, so two
    spellings of one figure are one request, and another account or allowance another."""

    def sha(params: PlaceOrderParams, **over: Any) -> str:
        fields: dict[str, Any] = {
            "account_id": cr.ACCOUNT, "symbol": "BTCUSDT", "max_notional_usd": CEILING,
        } | over  # fmt: skip
        return prepared(canonical_request("place_order", params, **fields)).request_sha256

    one = place(qty_mode="explicit", qty="0.010")
    assert sha(one) == sha(place(qty_mode="explicit", qty=0.01))
    assert sha(one) != sha(one, account_id=cr.LIVE_ACCOUNT)
    assert sha(one) != sha(one, max_notional_usd=Decimal("2499"))
    assert sha(one) != sha(place(qty_mode="explicit", qty="0.011"))


def _outcome(status: int, **over: Any) -> SubmitOutcome:
    codes = {202: None, 429: "exchange_rate_limited", 502: "exchange_error"}
    base: dict[str, Any] = {
        "status": status, "anchor_id": ANCHOR, "order_id": ORDER, "trade_group_id": GROUP,
        "code": codes[status], "lifecycle": "submitted" if status == 202 else None,
    }  # fmt: skip
    return SubmitOutcome(**(base | over))


_GATE = OrderEntryRefusal(reason="maintenance", detail="Order entry is paused for maintenance.")
#: (what the OMS raised, the answer, its `blocked_by`, its `error_code`)
_REFUSALS: list[tuple[Exception, str, str | None, str | None]] = [
    (RiskRefused(cap="max_open_positions"), "refused", "cap", "risk_limit_breached"),
    (OrderEntryRefused(_GATE), "refused", "order_entry", "trading_disabled"),
    (TradingDisabled(), "refused", "kill_switch", "trading_disabled"),
    (
        OrderPlacementRefused(reason_code=None, reason_text=None),
        "refused", "kill_switch", "trading_disabled",
    ),
    (RateBudgetExceeded(retry_after_s=2), "refused", "rate_limited", "exchange_rate_limited"),
    (IdempotencyInFlight(retry_after_s=1), "in_flight", None, "idempotency_in_flight"),
    (OmsNotReady(), "pre_anchor", None, "oms_not_ready"),
    (StoreUnavailable(), "pre_anchor", None, "store_unavailable"),
    (ExchangeUnavailable(retry_after_s=1), "pre_anchor", None, "exchange_unavailable"),
    (ClockDriftBlocked(retry_after_s=1), "pre_anchor", None, "clock_drift"),
    (SizingUnavailable(retry_after_s=1), "refused", None, "sizing_unavailable"),
    (AuditNotDurable(), "refused", None, "audit_unavailable"),
    (OrderInvalid(), "refused", None, "validation_failed"),
    (IdempotencyKeyReuse(), "refused", None, "idempotency_key_reuse"),
    (StopRequestPending(retry_after_s=1), "refused", None, "stop_request_in_flight"),
    (OmsError("not recorded as validated"), "refused", None, "internal_error"),
    (TimeoutError(), "no_answer", None, "timeout"),
    (ConnectionError("the lane went away"), "no_answer", None, "internal_error"),
]  # fmt: skip


@pytest.mark.parametrize(
    ("error", "answer", "blocked_by", "code"), _REFUSALS, ids=lambda v: type(v).__name__
)
def test_problem_codes_map_to_the_closed_blocked_by_set(
    error: Exception, answer: str, blocked_by: str | None, code: str | None
) -> None:
    """24 §11.5's map: `risk_limit_breached` to `cap`, `trading_disabled` to `order_entry` with
    the gate's reason else `kill_switch`, `exchange_rate_limited` to `rate_limited`; §11.9's
    classes: `idempotency_in_flight` in flight, a `503` before the anchor existed `pre_anchor`,
    no answer `no_answer`, and every other refusal `refused` with its problem code alone."""
    mapped = refusal_answer(error)
    assert (mapped.answer, mapped.blocked_by, mapped.error_code) == (answer, blocked_by, code)
    assert mapped.blocked_by is None or mapped.blocked_by in BLOCKED_BY
    assert "the lane" not in repr(mapped) and "not recorded" not in repr(mapped)


def test_a_mapped_refusal_names_its_cause_in_its_detail() -> None:
    """24 §11.9: `cap` names the cap the refusal carries, and a read-only system is never
    reported as an engaged kill switch; a cap no sentence may quote keeps `cap`'s own."""
    assert refusal_answer(RiskRefused(cap="max_open_positions")).detail == (
        "Not done — the account's cap max_open_positions refused it."
    )
    assert refusal_answer(RiskRefused()).detail == BLOCKED_DETAIL["cap"]
    assert refusal_answer(RiskRefused(cap="cap_9")).detail == BLOCKED_DETAIL["cap"]  # a digit
    read_only = refusal_answer(OrderPlacementRefused(reason_code=None, reason_text=None))
    assert read_only.detail == OMS_DETAIL[READ_ONLY] != BLOCKED_DETAIL["kill_switch"]
    assert refusal_answer(TradingDisabled()).detail is None  # the kill switch's own sentence


def test_the_longest_cap_name_quoted_keeps_the_sentence_within_80_characters() -> None:
    """The register's form (R1C1-04): the longest name the cap pattern admits, 39 characters,
    makes an 80-character sentence; a 40-character name falls back to `cap`'s own; a computed
    sentence holds no digit and is one sentence, as the register's are."""
    longest = refusal_answer(RiskRefused(cap="a" * 39)).detail
    assert longest is not None and len(longest) == 80
    assert refusal_answer(RiskRefused(cap="a" * 40)).detail == BLOCKED_DETAIL["cap"]
    named = refusal_answer(RiskRefused(cap="max_position_notional")).detail
    for sentence in (longest, named):
        assert sentence is not None and sentence.startswith("Not done — ")
        assert sentence.endswith(".") and sentence.count(".") == 1
        assert not any(ch.isdigit() for ch in sentence)


@pytest.mark.parametrize(
    ("outcome", "expected"),
    [
        (_outcome(202, notional_usd=Decimal("612.5")),
         HandlerAnswer("accepted", order_id=ORDER, group_id=GROUP,
                       notional_usd=Decimal("612.5"))),
        (_outcome(202, lifecycle="held"),
         HandlerAnswer("accepted", order_id=ORDER, group_id=GROUP)),
        (_outcome(202, lifecycle="unknown"),
         HandlerAnswer("in_flight", error_code="unknown", order_id=ORDER, group_id=GROUP)),
        (_outcome(202, lifecycle=RECONCILING, replayed=True),
         HandlerAnswer("in_flight", error_code=RECONCILING, order_id=ORDER, group_id=GROUP)),
        (_outcome(202, lifecycle="filled", replayed=True, order_id=None),
         HandlerAnswer("accepted", order_id=entry_order_id(GROUP), group_id=GROUP,
                       notional_usd=CEILING)),
        (_outcome(429, lifecycle=None, retry_after_s=3),
         HandlerAnswer("refused", error_code="exchange_rate_limited", blocked_by="rate_limited",
                       order_id=ORDER, group_id=GROUP)),
        (_outcome(502, ret_code=10001),
         HandlerAnswer("refused", error_code="exchange_error", order_id=ORDER, group_id=GROUP)),
    ],
    ids=["accepted", "held", "unknown", "reconciling-replay", "replay", "429", "502"],
)  # fmt: skip
def test_an_outcome_maps_to_its_answer(outcome: SubmitOutcome, expected: HandlerAnswer) -> None:
    """A `202` is `accepted` with the sized notional the OMS answered, unless its order's outcome
    is not known (`in_flight`: never re-sent, no success assumed); a replay counts at the ceiling
    it was sent under, the cautious side; a `429` is `rate_limited`, a `502` `exchange_error`."""
    assert answer_of(outcome, ceiling=CEILING) == expected


def test_a_replay_with_no_allowance_counts_nothing() -> None:
    replay = _outcome(202, lifecycle="filled", replayed=True)
    assert answer_of(replay).notional_usd is None
    reduce_only = _outcome(202, trade_group_id=None)
    assert answer_of(reduce_only, ceiling=CEILING).notional_usd is None

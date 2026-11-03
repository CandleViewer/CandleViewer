"""A rule entry's OMS request, its context and the OMS's answer, at the composition root (E35-T11
slice 3b; 24 §8.4 "Rule-originated orders", §11.5, §11.9; the rulings of #863: BQ-2 to BQ-5,
BQ-8).

`rules` may not import `oms` or `accounts` (the adapter lives here, beside `rules_oms_wiring`),
so the order handlers' three translations are here, each pure:

- **The request** (`order_request`): the typed parameters (`rules.executor.params`) as the
  pipeline's `OrderRequest`. The engine never sizes (24 §11.6): `qty_mode: profile` is
  `SizingRequest(mode="profile")`, an explicit `qty` is `fixed_qty`, a `scale_in`'s `qty_pct` is
  `pct_position` (which the OMS refuses until its sizer reads a position, never this module); the
  notional allowance rides as `max_notional_usd`, refused by the size step and never clamped
  (C-12.5); the stop and take-profit offsets are 22 `Offset`s, which the size step and
  `NativeStopGuard` judge (C-2.6). A `place_order` is an `entry` on its side; a `scale_in` is the
  OMS's `scale_in` intent, a market order on the side of the position it adds to.
- **The context** (`submit_context`): the owner as the OMS principal (`SubmitActor`, with no
  session, address or correlation id: a job's, never an HTTP session, E35-FR-01), the action's
  `client_ref` and `request_sha256` as the fire key gave them (24 §11.9), and the rule's
  `RuleOrigin` (its id, version, fire, node and armer, with the armer's role), which no route
  sets.
- **The answer** (`answer_of`, `refusal_answer`): the OMS's outcome or refusal as a
  `HandlerAnswer`, by 24 §11.5's map and §11.9's classes: a `202` is `accepted` with its order,
  group and sized notional, unless the order is `unknown` or still reconciling (`in_flight`,
  never re-sent); `risk_limit_breached` is `cap` naming the cap; `trading_disabled` is
  `order_entry` with the gate's `reason`, else `kill_switch` (the read-only gate's own detail);
  `exchange_rate_limited` is `rate_limited`; `idempotency_in_flight` is `in_flight`; a `503`
  before the anchor existed is `pre_anchor`; no answer (a timeout, a transport failure) is
  `no_answer`; every other refusal is `refused` with its problem code.
"""

from __future__ import annotations

from collections.abc import Mapping
from decimal import Decimal
from typing import Any, Final
from uuid import UUID

from candleviewer.accounts.override_comparator import Role
from candleviewer.domain.primitives import AccountId, Side, Symbol
from candleviewer.oms.errors import (
    IdempotencyInFlight,
    OmsError,
    OrderEntryRefused,
    RateBudgetExceeded,
    RiskRefused,
    TradingDisabled,
    problem_for,
)
from candleviewer.oms.ports import RuleOrigin, SizingRequest, StopOffset, SubmitActor
from candleviewer.oms.submit import (
    RECONCILING,
    OrderRequest,
    SubmitContext,
    SubmitOutcome,
    entry_order_id,
)
from candleviewer.oms.validator import OrderPlacementRefused
from candleviewer.rules.executor.handlers import HandlerAnswer
from candleviewer.rules.executor.params import EntryParams, Offset, PlaceOrderParams
from candleviewer.rules.executor.results import OMS_DETAIL, READ_ONLY, oms_cap_detail
from candleviewer.rules.scope import ActionRequest

#: 24 §11.9: the refusals before the anchor existed that `retry_once` may retry, by problem code.
PRE_ANCHOR_CODES: Final = frozenset(
    {"oms_not_ready", "store_unavailable", "exchange_unavailable", "clock_drift"}
)
#: The B1 states of a `202` whose create has no known outcome: `unknown` (an ambiguous send the
#: OMS never re-sends, 24 §8.2 S1) and a repeat's `reconciling`. Each is `in_flight`, never
#: `accepted`: no success is assumed (C-2.10).
UNRESOLVED_STATES: Final = frozenset({"unknown", RECONCILING})
#: The closed role set (`Role`, the `role_name` enum) by name: the armer's role the origin carries.
_ROLES: Final[Mapping[str, Role]] = {"owner": "owner", "manager": "manager", "viewer": "viewer"}


def system_role(name: str | None) -> Role | None:
    """`name` as one of the closed role set, `None` for no role or a name outside it."""
    return None if name is None else _ROLES.get(name)


def _offset(offset: Offset | None) -> StopOffset | None:
    return None if offset is None else StopOffset(unit=offset.unit, value=offset.value)


def _sizing(params: EntryParams, ceiling: Decimal | None) -> SizingRequest:
    """What the rule asked for, never a figure the engine sized (24 §11.6), with its allowance."""
    if isinstance(params, PlaceOrderParams):
        if params.qty_mode == "profile":
            return SizingRequest(mode="profile", max_notional_usd=ceiling)
        return SizingRequest(mode="fixed_qty", qty=params.qty, max_notional_usd=ceiling)
    if params.qty is not None:
        return SizingRequest(mode="fixed_qty", qty=params.qty, max_notional_usd=ceiling)
    if params.qty_pct is not None:
        return SizingRequest(mode="pct_position", pct=params.qty_pct, max_notional_usd=ceiling)
    return SizingRequest(mode="profile", max_notional_usd=ceiling)


def order_request(
    params: EntryParams,
    *,
    account_id: UUID,
    symbol: str,
    side: Side,
    max_notional_usd: Decimal | None,
) -> OrderRequest:
    """The pipeline's request for one account (module docstring): `side` is a `place_order`'s
    own, or the side of the position a `scale_in` adds to."""
    sizing = _sizing(params, max_notional_usd)
    account, market = AccountId(account_id), Symbol(symbol)
    if isinstance(params, PlaceOrderParams):
        take_profit = _offset(params.take_profits[0]) if params.take_profits else None
        return OrderRequest(
            account_id=account, symbol=market, side=side, order_type=params.order_type,
            sizing=sizing, intent="entry", price=params.price,
            stop_loss=_offset(params.stop_loss), take_profit=take_profit,
            profile_id=params.profile,
        )  # fmt: skip
    return OrderRequest(
        account_id=account, symbol=market, side=side, order_type="market", sizing=sizing,
        intent="scale_in",
    )  # fmt: skip


def canonical_request(
    action_type: str,
    params: EntryParams,
    *,
    account_id: UUID,
    symbol: str,
    max_notional_usd: Decimal | None,
) -> Mapping[str, Any]:
    """What the action's fingerprint covers (24 §11.9 `request_sha256`), built once at prepare:
    the type, the account, the symbol, the allowance and the typed parameters, decimals as
    decimals. A `scale_in`'s side is the position's, read when it is sent."""
    return {
        "action_type": action_type, "account_id": account_id, "symbol": symbol,
        "max_notional_usd": max_notional_usd, "params": params.model_dump(),
    }  # fmt: skip


def rule_origin(req: ActionRequest, armed_by_role: Role | None) -> RuleOrigin:
    """The rule a request comes from (24 §8.4 "Rule-originated orders"): its id, version, fire,
    node, and its armer with the armer's role (`RuleOrigin` refuses one without the other).
    `ValueError` for a rule id or an armer that is no UUID, and for a node id the origin refuses
    (not a short identifier)."""
    armer = None if req.armed_by is None else UUID(str(req.armed_by))
    return RuleOrigin(
        rule_id=UUID(req.rule_id), version=req.version, run_id=req.run_id,
        node_id=req.payload.node_id, armed_by=armer,
        armed_by_role=None if armer is None else armed_by_role,
    )  # fmt: skip


def submit_context(
    *,
    owner: UUID,
    owner_role: str,
    origin: RuleOrigin,
    client_ref: str,
    request_sha256: str,
) -> SubmitContext:
    """The context a rule's request carries (module docstring): the owner as the principal, the
    fire key's `client_ref` and fingerprint unchanged, and the origin; no session, no address and
    no correlation id, as a job's."""
    return SubmitContext(
        actor=SubmitActor(user_id=owner, role=owner_role), client_ref=UUID(client_ref),
        request_sha256=request_sha256, origin=origin,
    )  # fmt: skip


def answer_of(outcome: SubmitOutcome, *, ceiling: Decimal | None = None) -> HandlerAnswer:
    """A recorded request's outcome (module docstring). An accepted entry's notional is the sized
    one the OMS answered (`SubmitOutcome.notional_usd`); a replay names none, so it counts at the
    allowance it was sent under, the cautious side (24 §11.7: what a rule sent is counted at
    submit), else nothing."""
    group = outcome.trade_group_id
    order = outcome.order_id
    if order is None and group is not None:  # an entry's replay names its group alone
        order = entry_order_id(group)
    ids: dict[str, Any] = {"order_id": order, "group_id": group}
    if outcome.status == 429:
        return HandlerAnswer("refused", error_code=outcome.code, blocked_by="rate_limited", **ids)
    if outcome.status == 502:
        return HandlerAnswer("refused", error_code=outcome.code, **ids)
    if outcome.lifecycle in UNRESOLVED_STATES:
        return HandlerAnswer("in_flight", error_code=outcome.lifecycle, **ids)
    notional = outcome.notional_usd
    if notional is None and outcome.replayed and group is not None:
        notional = ceiling
    return HandlerAnswer("accepted", notional_usd=notional, **ids)


def refusal_answer(error: Exception) -> HandlerAnswer:
    """A refusal or a failure of the call (module docstring), named by its problem code alone,
    never its text (SR-E29-09, C-12.6)."""
    if isinstance(error, TimeoutError):
        return HandlerAnswer("no_answer", error_code="timeout")
    if not isinstance(error, OmsError):  # a transport failure or a defect: no definite answer
        return HandlerAnswer("no_answer", error_code="internal_error")
    code = problem_for(error).code
    if isinstance(error, RiskRefused):
        return HandlerAnswer(
            "refused", error_code=code, blocked_by="cap", detail=oms_cap_detail(error.cap)
        )
    if isinstance(error, OrderEntryRefused):
        return HandlerAnswer("refused", error_code=code, blocked_by="order_entry")
    if isinstance(error, OrderPlacementRefused):
        return HandlerAnswer(
            "refused", error_code=code, blocked_by="kill_switch", detail=OMS_DETAIL[READ_ONLY]
        )
    if isinstance(error, TradingDisabled):
        return HandlerAnswer("refused", error_code=code, blocked_by="kill_switch")
    if isinstance(error, RateBudgetExceeded):
        return HandlerAnswer("refused", error_code=code, blocked_by="rate_limited")
    if isinstance(error, IdempotencyInFlight):
        return HandlerAnswer("in_flight", error_code=code)
    if code in PRE_ANCHOR_CODES:
        return HandlerAnswer("pre_anchor", error_code=code)
    return HandlerAnswer("refused", error_code=code)

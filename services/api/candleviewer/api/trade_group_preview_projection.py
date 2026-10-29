"""The trade-group preview's REST document and its audit row (E28-T05 S3b, #909).

`preview_document` renders the planner's `GroupPlan` as 22's `TradeGroupPreview`, in the shape S0
gave it. Each leg states its `status` as text and `would_submit`, true exactly for `ready` and
`warn`, its `warnings` and, skipped or blocked, its `rejection`: 22's code with CandleViewer's own
sentence for it (`MESSAGES`), never another text (SR-E29-09). A `figure_unknown` one says the
account's figures are not available yet: the preview reads cached figures only (SR-E28-22), and
#881 (E39-T01) supplies them. A leg the comparator admitted shows `resolved`, what it would send
(its take-profit the one sent: the ladder's last rung, unless the request named one), and
`take_profits`, the sizer's rungs; a leg the sizer priced shows `estimated_margin_usd` and
`estimated_risk_usd`. A risk is 1R and both taker fees, rounded up to the 18 places a leg's
`risk_usd` column keeps, as `EntrySize` stores it; `estimated_fee_usd` is those fees exactly, the
share the planner's totals sum. A figure the sizer never reached is left out, never 0. Decimals are
`plain`: every digit, no exponent, no trailing zero.

`previewed_entry` is ruling 2's `trade_group.previewed` row for an answered preview, `200` or a
refusal: the request's symbol, side and account ids, the actor's role and its legs' outcome counts,
never a figure. The route writes it ahead of its answer (S3c, C-2.9).
"""

from __future__ import annotations

from collections.abc import Mapping
from decimal import ROUND_CEILING, Context, Decimal
from types import MappingProxyType
from typing import Final, TypedDict
from uuid import UUID

from candleviewer.accounts.override_comparator import RefusalActor, Refused
from candleviewer.accounts.sizer import LegSizing
from candleviewer.api.profile_projection import plain
from candleviewer.audit.models import AuditOutcome, ExchangeEnv, Severity
from candleviewer.oms.fanout.guard import RejectionCode
from candleviewer.oms.fanout.plan import GroupPlan, GroupRefused, GroupRequest, LegPlan

__all__ = ["MESSAGES", "PREVIEWED_ACTION", "PreviewedRow", "preview_document", "previewed_entry"]

type Body = dict[str, object]

PREVIEWED_ACTION: Final = "trade_group.previewed"
_EXACT: Final = Context(prec=100)
_STORED: Final = Decimal("1e-18")  # `numeric(38,18)`: a leg's risk, rounded up, never down
_STATUSES: Final = ("ready", "warn", "skipped", "blocked")

#: CandleViewer's own sentence for each of 22's codes: the only `rejection.message` there is.
MESSAGES: Final[Mapping[RejectionCode, str]] = MappingProxyType(
    {
        "cap_breached": "A risk cap blocks this leg.",
        "symbol_not_allowed": "The account's profile does not allow this symbol.",
        "insufficient_margin": "The account does not have the margin for this leg.",
        "rate_budget_exhausted": "The account's order rate budget is spent.",
        "account_locked": "The account is locked out of trading.",
        "key_invalid": "The account's API key failed its check.",
        "leverage_unavailable": "The leverage is not available on this symbol.",
        "kill_switch_engaged": "The kill switch is engaged.",
        "profile_disabled": "The account's profile is disabled or does not trade.",
        "symbol_denied": "The account's profile blocks this symbol.",
        "below_min_notional": "The leg sizes under the minimum quantity or notional.",
        "skipped": "The request leaves this leg out.",
        "no_reference_price": "No market price is available to size this leg.",
        "invalid_stop_distance": "The stop cannot protect this leg.",
        "figure_unknown": "The account's figures are not available yet.",
        "stop_beyond_liquidation": "The stop would not fire before liquidation.",
        "account_disabled": "The account is disabled.",
        "account_unhealthy": "The account fails its health check.",
        "trading_disabled": "Order entry is closed for this account.",
        "risk_state_unavailable": "No risk state is available to judge this leg.",
    }
)


def _stored(value: Decimal | None) -> Decimal | None:
    return None if value is None else value.quantize(_STORED, ROUND_CEILING, _EXACT)


def _fee(sized: LegSizing) -> Decimal | None:
    """Both taker fees: the risk with fees less 1R, the planner's totals' own share."""
    gross, flat = sized.risk_with_fees_usdt, sized.risk_usdt
    return None if gross is None or flat is None else _EXACT.subtract(gross, flat)


def _leg(leg: LegPlan, labels: Mapping[UUID, str]) -> Body:
    code, sized, admitted = leg.reason, leg.sizing, leg.admitted
    doc: Body = {
        "exchange_account_id": str(leg.account_id),
        "account_profile_id": None if leg.profile is None else str(leg.profile.profile_id),
        "would_submit": leg.status in ("ready", "warn"),
        "status": leg.status,
        "warnings": list(leg.warnings),
        "rejection": None if code is None else {"code": code, "message": MESSAGES[code]},
    }
    if (label := labels.get(leg.account_id)) is not None:
        doc["account_label"] = label
    if sized is None:
        return doc
    priced = {"estimated_margin_usd": sized.initial_margin}
    priced["estimated_risk_usd"] = _stored(sized.risk_with_fees_usdt)
    doc |= {name: plain(value) for name, value in priced.items() if value is not None}
    if admitted is not None:  # an `ok` leg: only a market `price` or no take-profit is null
        sent = admitted.leg
        resolved = {
            "qty": sent.qty, "price": sized.limit_price, "leverage": sent.leverage,
            "stop_loss_price": sent.stop_price, "take_profit_price": sent.take_profit_price,
            "notional_usd": sized.notional, "risk_usd": _stored(sized.risk_with_fees_usdt),
            "estimated_fee_usd": _fee(sized),
        }  # fmt: skip
        doc["resolved"] = {k: None if v is None else plain(v) for k, v in resolved.items()} | {
            "sizing_explanation": sized.render()
        }
        doc["take_profits"] = [{"price": plain(tp.price), "qty": plain(tp.qty)} for tp in sized.tps]
    return doc


def preview_document(plan: GroupPlan, labels: Mapping[UUID, str]) -> Body:
    """22's `TradeGroupPreview` of `plan`; `labels` holds the legs' account labels by id."""
    totals = plan.totals
    return {
        "legs": [_leg(leg, labels) for leg in plan.legs],
        "totals": {
            "accounts_targeted": totals.accounts_targeted,
            "accounts_submittable": totals.accounts_submittable,
            "total_qty": plain(totals.qty), "total_notional_usd": plain(totals.notional_usd),
            "total_risk_usd": plain(totals.risk_usd),
            "total_estimated_fee_usd": plain(totals.fee_usd),
        },
    }  # fmt: skip


class PreviewedRow(TypedDict):
    """`AuditWriter.emit`'s keyword arguments for the row, all but `action`."""

    actor_label: str
    actor_user_id: UUID
    actor_ip: str | None
    object_kind: str
    outcome: AuditOutcome
    severity: Severity
    reason: str | None
    after_state: dict[str, object]
    request_id: UUID | None
    env: ExchangeEnv


def previewed_entry(
    request: GroupRequest | None, answer: GroupPlan | GroupRefused | str, *, actor: RefusalActor
) -> PreviewedRow:
    """The row for `answer` to `request` (module docstring): `emit(PREVIEWED_ACTION, **row)`. A
    refusal the route answers before planning (S3c) is its rule or code, with no leg counted; one
    answered before the body was read names no request."""
    if isinstance(answer, GroupPlan):
        counts = {status: sum(leg.status == status for leg in answer.legs) for status in _STATUSES}
    else:
        counts = {"refused": len(answer.legs)} if isinstance(answer, GroupRefused) else {}
    refused = not isinstance(answer, GroupPlan)
    reason = answer if isinstance(answer, str) else Refused.problem if refused else None
    named = {} if request is None else {
        "symbol": request.symbol, "side": request.side,
        "exchange_account_ids": [str(leg.account_id) for leg in request.legs],
    }  # fmt: skip
    return PreviewedRow(
        actor_label=str(actor.user_id), actor_user_id=actor.user_id, actor_ip=actor.ip,
        object_kind="trade_group_preview",
        outcome=AuditOutcome.DENIED if refused else AuditOutcome.SUCCESS,
        severity=Severity.WARNING if refused else Severity.INFO, reason=reason,
        after_state=named | {"role": actor.role, "outcomes": counts},
        request_id=actor.request_id, env=ExchangeEnv(actor.env),
    )  # fmt: skip

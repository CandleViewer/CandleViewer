"""A stored group's REST document, 22's `TradeGroup` (E28-T05 #909, slice S2e).

`group_document` renders a group `TradeGroupReader` served, with its legs' order ids, as the
members 22 declares and no others (SEC-S3D-03): never `profile_snapshot`, the request fingerprint
or `algo_params`. `created_by`, `note` and `client_group_ref` follow `shows_private_fields`, which
the read sets for an Owner or the group's creator (SR-E28-21). A decimal has every digit and no
exponent (C6), a time is RFC 3339 (C7). `atomicity` is the policy 22's two values can name:
`abort_on_first` has none, so the member is left out (E34 owns that gap). A leg's `resolved` is
null for a leg with no stop, which only a rejected, cancelled or error leg can be (`tgl_sl_px`).
`placeOrder`'s `202` renders a group from the rows its pipeline just wrote, with `order_details`,
so it shares no code with this read of stored rows.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from uuid import UUID

from candleviewer.accounts.trade_groups import ScopedTradeGroup, TradeGroupLeg, group_totals
from candleviewer.api.profile_projection import plain, plain_or_none, rfc3339
from candleviewer.domain.primitives import TsUs

__all__ = ["group_document"]

type Body = dict[str, object]


def _time(us: TsUs | None) -> str | None:
    return None if us is None else rfc3339(us)


def _id(value: UUID | None) -> str | None:
    return None if value is None else str(value)


def _leg_document(leg: TradeGroupLeg, orders: Sequence[UUID]) -> Body:
    """22 `TradeGroupLeg`: the leg's columns and its order ids, never `order_details`."""
    resolved: Body | None = None
    if leg.resolved_sl_price is not None:
        resolved = {
            "qty": plain(leg.target_qty), "leverage": plain(leg.resolved_leverage),
            "stop_loss_price": plain(leg.resolved_sl_price),
            "take_profit_price": plain_or_none(leg.resolved_tp_price),
        }  # fmt: skip
        if leg.risk_usd is not None:
            resolved["risk_usd"] = plain(leg.risk_usd)
    rejection = (("code", leg.rejection_code), ("message", leg.rejection_message))
    return {
        "id": str(leg.leg_id), "trade_group_id": str(leg.group_id),
        "exchange_account_id": str(leg.account_id),
        "account_profile_id": _id(leg.account_profile_id), "status": leg.status,
        "sequence_no": leg.sequence_no, "resolved": resolved,
        "orders": [str(order_id) for order_id in orders], "target_qty": plain(leg.target_qty),
        "filled_qty": plain(leg.filled_qty), "avg_entry_price": plain_or_none(leg.avg_entry_price),
        "avg_exit_price": plain_or_none(leg.avg_exit_price),
        "risk_usd": plain_or_none(leg.risk_usd),
        "native_sl_confirmed": leg.native_sl_confirmed, "fees_paid": plain(leg.fees_paid),
        "native_sl_confirmed_at": _time(leg.native_sl_confirmed_at),
        "realised_pnl": plain(leg.realised_pnl),
        "error": {name: text for name, text in rejection if text is not None} or None,
        "submitted_at": _time(leg.submitted_at), "closed_at": _time(leg.closed_at),
        "created_at": rfc3339(leg.created_at), "updated_at": rfc3339(leg.updated_at),
    }  # fmt: skip


def group_document(scoped: ScopedTradeGroup, order_ids: Mapping[UUID, Sequence[UUID]]) -> Body:
    """22's `TradeGroup` of `scoped`; `order_ids` holds each leg's order ids by leg id."""
    group, legs = scoped.record.group, scoped.record.legs
    totals = group_totals(legs)
    doc: Body = {
        "id": str(group.group_id), "symbol": group.symbol, "side": group.side,
        "status": group.status, "algo": {"kind": group.algo}, "rule_id": _id(group.rule_id),
        "is_paper": group.is_paper, "created_at": rfc3339(group.created_at),
        "updated_at": rfc3339(group.updated_at), "closed_at": _time(group.closed_at),
        "legs": [_leg_document(leg, order_ids.get(leg.leg_id, ())) for leg in legs],
        "totals": {
            "requested_legs": totals.requested_legs, "submitted_legs": totals.submitted_legs,
            "rejected_legs": totals.rejected_legs, "filled_qty": plain(totals.filled_qty),
            "target_qty": plain(totals.target_qty), "realised_pnl": plain(totals.realised_pnl),
        },
    }  # fmt: skip
    if group.leg_failure_policy != "abort_on_first":
        doc["atomicity"] = group.leg_failure_policy
    if scoped.shows_private_fields:
        doc |= {
            "created_by": str(group.created_by), "note": group.note,
            "client_group_ref": str(group.client_group_ref),
        }  # fmt: skip
    return doc

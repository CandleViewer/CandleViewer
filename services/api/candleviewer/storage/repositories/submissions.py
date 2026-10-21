"""Driver-free port for an order's first persist (E29-T04 #913; 21-database-schema.md Sec.3.3.10
"Writes", 24-internal-schemas.md Sec.8.4, M10).

B1's `VALIDATE` step writes an order's first rows in one transaction (24 Sec.8.4 step 5): for an
entry its one-leg trade group and the leg; the order's `validated` row with its first event; the
entry's recorded stops (21 Sec.3.3.11), `pending` and in flight; and last the request's replay
anchor (21 Sec.3.3.10). The caller's write-ahead audit hook runs before the commit (C-2.9). A
transaction that does not commit leaves nothing, so its repeat is a first submission, and nothing
has been sent: the send follows the persist. `submissions_sqlalchemy.py` is the Postgres
implementation; stdlib only, so M14 (`oms`) types against it with no storage driver (ADR-0003).

`FirstPersist.check` refuses, before any statement, parts that do not belong together: an anchor
that does not name the group of an entry or the order of a reduce-only order (`ia_target`, which
the group's `client_group_ref` and `client_body_sha256` mirror, 21 Sec.3.3.2); a group without
exactly one leg, the order's, on the order's account, with the order's stop; and recorded stops
that are not the entry's own attach (its stop-loss always, C-2.6, and its take-profit when it has
one). A reduce-only order persists no group and records no stop. No message names a value.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Final, Literal, Protocol
from uuid import UUID

from candleviewer.storage.repositories.idempotency_anchors import NewAnchor
from candleviewer.storage.repositories.orders import (
    NewOrder,
    NewOrderEvent,
    OrderRow,
    OrderStoreError,
)
from candleviewer.storage.repositories.recorded_stops import NewRecordedStop, RecordedStopRow
from candleviewer.storage.repositories.trade_groups import (
    NewTradeGroup,
    NewTradeGroupLeg,
    TradeGroupRecord,
)

__all__ = [
    "UX_TG_CREATOR_REF", "AnchorConstraint", "AnchorTakenError", "FirstPersist",
    "FirstPersistWriteAhead", "FirstPersisted", "SubmissionRefusal", "SubmissionStore",
]  # fmt: skip

#: The group-level twin of the anchor's key (21 Sec.3.3.2): an entry's group holds it too.
UX_TG_CREATOR_REF: Final = "ux_tg_creator_ref"
AnchorConstraint = Literal["ux_ia_principal_ref", "ux_tg_creator_ref"]
#: Why the first persist's share-locked re-check refused (SR-E28-15): the trade-group store's
#: refusals a first persist can meet; it locks no definition, so never `definition_not_live`.
SubmissionRefusal = Literal["account_not_live", "profile_changed"]


@dataclass(frozen=True, slots=True)
class FirstPersisted:
    """What the first persist stored, as the database returned it: the order row, the anchor's
    id, the entry's group with its leg (`None` for a reduce-only order) and the recorded stops."""

    order: OrderRow
    anchor_id: UUID
    group: TradeGroupRecord | None
    recorded_stops: tuple[RecordedStopRow, ...]


#: Awaited once in the persist's transaction, after the anchor's insert and before the commit, with
#: the rows as stored: the caller's write-ahead audit (`orders.submit`, `trade_group.submit`,
#: `sl.attached`, 24 Sec.15.5). A hook that raises, or outlasts the store's audit bound
#: (`WriteAheadTimeout`), leaves nothing written (C-2.9).
FirstPersistWriteAhead = Callable[[FirstPersisted], Awaitable[None]]


@dataclass(frozen=True, slots=True, kw_only=True)
class FirstPersist:
    """The rows written with an order's `validated` row (module docstring). `write_ahead` is the
    caller's audit of them; the OMS's `SubmissionRepository` refuses a persist without one (C-2.9,
    CR-2A-02)."""

    anchor: NewAnchor
    group: NewTradeGroup | None = None
    legs: tuple[NewTradeGroupLeg, ...] = ()
    recorded_stops: tuple[NewRecordedStop, ...] = ()
    write_ahead: FirstPersistWriteAhead | None = field(default=None, compare=False, repr=False)

    def check(self, order: NewOrder) -> None:
        """`ValueError`, before any statement, unless these rows belong to `order`."""
        if order.lifecycle_state != "validated" or order.provenance != "placed":
            raise ValueError("a first persist writes the OMS's own validated row (24 Sec.8.4)")
        if (self.group is None) is not order.reduce_only:
            raise ValueError("an entry persists its one-leg group, a reduce-only order none")
        if self.group is None:
            self._check_groupless(order)
        else:
            self._check_group(self.group, order)
        self._check_stops(order)

    def _check_groupless(self, order: NewOrder) -> None:
        anchor = self.anchor
        if self.legs or order.trade_group_leg_id is not None:
            raise ValueError("an order without a group writes no leg and names none")
        if anchor.order_id != order.id or anchor.trade_group_id is not None:
            raise ValueError("the anchor of an order without a group names the order (ia_target)")

    def _check_group(self, group: NewTradeGroup, order: NewOrder) -> None:
        anchor = self.anchor
        if anchor.trade_group_id != group.id or anchor.order_id is not None:
            raise ValueError("the anchor of an entry names its group (ia_target)")
        twin = (group.created_by, group.client_group_ref, group.client_body_sha256)
        if twin != (anchor.created_by, anchor.client_ref, anchor.request_sha256):
            raise ValueError("an entry's group holds its anchor's principal, key and fingerprint")
        if (group.symbol, group.side) != (order.symbol, order.side):
            raise ValueError("an entry's group is for the order's symbol and side")
        if len(self.legs) != 1:
            raise ValueError("an entry's group has exactly one leg")
        (leg,) = self.legs
        if order.trade_group_leg_id != leg.id:
            raise ValueError("the order belongs to its group's leg")
        if leg.exchange_account_id != order.exchange_account_id:
            raise ValueError("the leg is on the order's account")
        if leg.resolved_sl_price != order.stop_loss:
            raise ValueError("the leg's resolved stop is the order's stop (C-2.6)")

    def _check_stops(self, order: NewOrder) -> None:
        stops = self.recorded_stops
        if order.reduce_only:
            if stops:
                raise ValueError("a reduce-only order records no stop of its own")
            return
        wanted = {"stop_loss": order.stop_loss, "take_profit": order.take_profit}
        if wanted["stop_loss"] is None:
            raise ValueError("an entry carries its native stop (C-2.6)")
        place = (order.exchange_account_id, order.symbol, order.position_idx, order.side)
        for stop in stops:
            if (stop.source, stop.order_id) != ("entry_attach", order.id):
                raise ValueError("an entry records its own attach (rs_entry)")
            if (stop.exchange_account_id, stop.symbol, stop.position_idx, stop.position_side) != (
                place
            ):
                raise ValueError("an entry's stop protects the position the entry opens")
            if stop.tpsl_mode != order.tpsl_mode or stop.actor_user_id != self.anchor.created_by:
                raise ValueError("an entry's stop has the order's mode and the request's actor")
        kinds = [stop.kind for stop in stops]
        expected = [kind for kind, price in wanted.items() if price is not None]
        if sorted(kinds) != expected:
            raise ValueError("an entry records its stop-loss, and its take-profit when it has one")
        if any(stop.trigger_price != wanted[stop.kind] for stop in stops):
            raise ValueError("each recorded stop is the order's attached price")


class AnchorTakenError(OrderStoreError):
    """The request's key is held already, by an earlier request of the principal or a concurrent
    first persist: the insert of the anchor (`ux_ia_principal_ref`) or of an entry's group
    (`ux_tg_creator_ref`) wrote nothing, and the transaction rolled back with nothing written.
    The caller answers it as a repeat (21 Sec.3.3.10). Names the constraint only."""

    def __init__(self, constraint: AnchorConstraint) -> None:
        super().__init__(f"the request's key is held already ({constraint}): nothing was written")
        self.constraint: AnchorConstraint = constraint


class SubmissionStore(Protocol):
    """The first persist; no route reaches it (C-12.4)."""

    async def create_first(
        self, first: FirstPersist, order: NewOrder, event: NewOrderEvent
    ) -> FirstPersisted:
        """Write `first` with `order` and its first `event` in one transaction (module
        docstring), or raise with nothing written: `ValueError` (`FirstPersist.check`) before any
        statement; `AnchorTakenError` when the key is held; `TradeGroupStoreRefusedError` when the
        order's account is not live or the leg's profile moved on (SR-E28-15);
        `OrderConstraintError` for a refused row (`ux_orders_link`, `ux_rs_in_flight`, ...);
        `WriteAheadTimeout` when the hook outlasts its bound."""
        ...

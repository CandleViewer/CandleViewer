"""`order_link_id` allocation: the §8.3 rule 5 collision check and rule 4 replacement.

E29-T02 (#846). Allocation runs once per logical order, before its first send;
the caller persists the id at once (rule 1). A retry re-sends the persisted id
and never allocates again, because the persisted row would count as a
collision and yield a second id.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final, Protocol, cast

import structlog

from candleviewer.domain.primitives import OrderId, OrderLinkId

from .errors import OrderLinkIdExhausted
from .order_link import SEQ_MAX, OrderLinkIdParts

__all__ = ["MAX_SEQ_INCREMENTS", "AllocatedOrderLinkId", "OrderLinkIdAllocator", "OrderLinkLookup"]

MAX_SEQ_INCREMENTS: Final = 16
"""Collisions tolerated before `OrderLinkIdExhausted` (#846 ruling Q6)."""


def _log() -> structlog.stdlib.BoundLogger:
    """Resolve per call: a module-level logger pins a stale processor chain (#2008)."""
    return cast(structlog.stdlib.BoundLogger, structlog.get_logger(__name__))


class OrderLinkLookup(Protocol):
    """Whether any `orders` row, in any state, holds an id (#846 rulings B1, Q1).

    One indexed lookup on `ux_orders_link`. E29-T01's order repository
    implements it; `oms.fakes.InMemoryOrderLinkLookup` stands in until then.
    It is a check, not a reservation: the unique index stays the final guard.
    """

    async def exists(self, order_link_id: OrderLinkId) -> bool: ...


@dataclass(frozen=True, slots=True)
class AllocatedOrderLinkId:
    """A free id; the caller persists it, with `replaces_order_id`, before sending."""

    parts: OrderLinkIdParts
    replaces_order_id: OrderId | None = None

    @property
    def order_link_id(self) -> OrderLinkId:
        return self.parts.value


class OrderLinkIdAllocator:
    """Turns a candidate id into a free one against an `OrderLinkLookup`."""

    def __init__(self, lookup: OrderLinkLookup) -> None:
        self._lookup = lookup

    async def allocate(
        self, candidate: OrderLinkIdParts, *, replaces_order_id: OrderId | None = None
    ) -> AllocatedOrderLinkId:
        """Rule 5: while the id is taken, log both ids at warning and increment `seq2`;
        raise `OrderLinkIdExhausted` after 16 increments or at `seq2` = 3843."""
        parts = candidate
        increments = 0
        while await self._lookup.exists(parts.value):
            if increments == MAX_SEQ_INCREMENTS or parts.seq == SEQ_MAX:
                raise OrderLinkIdExhausted(first=candidate.value, last=parts.value)
            following = parts.with_seq(parts.seq + 1)
            _log().warning(
                "order_link_id_collision",
                order_link_id=parts.value,
                next_order_link_id=following.value,
            )
            parts = following
            increments += 1
        return AllocatedOrderLinkId(parts=parts, replaces_order_id=replaces_order_id)

    async def allocate_replacement(
        self, replaced: OrderLinkId, *, replaces_order_id: OrderId
    ) -> AllocatedOrderLinkId:
        """Rule 4: a cancel-and-replace order takes the replaced id's next `seq2`
        and records the order it replaces (#846 ruling Q3; E29-T04 persists it)."""
        parts = OrderLinkIdParts.parse(replaced)
        if parts.seq == SEQ_MAX:
            raise OrderLinkIdExhausted(first=replaced, last=replaced)
        return await self.allocate(
            parts.with_seq(parts.seq + 1), replaces_order_id=replaces_order_id
        )

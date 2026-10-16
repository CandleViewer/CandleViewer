"""In-memory stand-ins for M14 ports, for unit tests (#846 ruling B1)."""

from __future__ import annotations

from collections.abc import Iterable

from candleviewer.domain.primitives import OrderLinkId

__all__ = ["InMemoryOrderLinkLookup"]


class InMemoryOrderLinkLookup:
    """An `OrderLinkLookup` over a set of taken ids, whatever their row's state;
    `lookups` records every id asked about, in order (one lookup per candidate)."""

    def __init__(self, taken: Iterable[OrderLinkId] = ()) -> None:
        self._taken = set(taken)
        self.lookups: list[OrderLinkId] = []

    def add(self, order_link_id: OrderLinkId) -> None:
        """Record a persisted row, as the order INSERT does."""
        self._taken.add(order_link_id)

    async def exists(self, order_link_id: OrderLinkId) -> bool:
        self.lookups.append(order_link_id)
        return order_link_id in self._taken

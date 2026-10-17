"""Domain errors for the oms module (M14)."""

from __future__ import annotations


class OmsError(Exception):
    """Base exception for the M14 `oms` module."""


class InvalidOrderLinkId(OmsError):
    """A string the §8.3 generator cannot produce, or parts that cannot render one."""


class UnsupportedExecutionMode(OmsError):
    """`replay` has no §8.3 environment letter, so generation fails closed (#846 Q4)."""


class OrderLinkIdExhausted(OmsError):
    """§8.3 rule 5: still colliding after 16 `seq2` increments, or at `seq2` = 3843."""

    def __init__(self, *, first: str, last: str) -> None:
        super().__init__(f"no free order_link_id from {first} to {last}")
        self.first = first
        self.last = last


class InvalidHistoryRetention(OmsError, ValueError):
    """An exchange order retention under 2 days: §8.3 rule 6 expires an id after the
    retention less one day, so 1 day or less would expire every id on creation."""


class DuplicateOrderLinkId(OmsError):
    """`ux_orders_link` already holds this id, so the order was not stored (#845 Gherkin).

    The rule 5 collision check runs before the insert; this is the race it cannot see. The id is
    taken: the caller never sends under it, and allocates again (24 Sec.8.3 rule 5)."""

    def __init__(self, order_link_id: str) -> None:
        super().__init__(f"order_link_id {order_link_id} is already stored")
        self.order_link_id = order_link_id

"""A recorded stop's terms on the private stream (E29-T05 #848, S7a; 24-internal-schemas.md
Sec.8.12 "Terms, at most one a second", Sec.8.3 rule 7's sixth item). Pure bookkeeping on the
hot-path contract (C-2.20): no I/O, no clock of its own, no interpreter; `StreamPushes` sends.

`terms_payload` is B1's `TERMS_CHANGED` for a recorded stop's row from its order as a push or a
read shows it: the order's trigger price and quantity, each named only when above zero, under the
row's own `order_link_id`, stamped with the venue's own time (`push_time_ms`). A Full-mode order
showing a quantity of 0 names no quantity: its row takes the position's size (S6b), so that 0 is
never a change of terms. `differs` says whether a term it names is another than the row's, as money
by value.

`PendingTerms` is the coalescing (the orchestrator's 2026-10-25 ruling Q2): one pending slot per
row, the latest terms winning, at most one send per row each `TERMS_MIN_INTERVAL_S` on the
monotonic clock. The caller sends a slot before any other push of that order (`take`), and at the
account's next row or `heartbeat` status once the row's interval has passed (`due`), so a row's
terms pushes never send more than one a second and no timer runs. At most `MAX_PENDING_TERMS`
slots wait: a slot the cap evicts is answered to be sent, never dropped. The terms are the row's
record of what the exchange holds; the exchange holds the stop (C-2.6).
"""

from __future__ import annotations

from collections import OrderedDict
from decimal import Decimal
from typing import Final
from uuid import UUID

from candleviewer.domain.primitives import AccountId, TsUs
from candleviewer.exchange.base.models import Order
from candleviewer.storage.repositories.orders import OrderRow

from .push_mapping import money_text, push_time_ms

TERMS_MIN_INTERVAL_S: Final = 1.0  # 24 Sec.8.12: at most one TERMS_CHANGED a second per row
MAX_PENDING_TERMS: Final = 1024  # pending slots (C-2.18); an evicted one is sent, never dropped
#: Rows whose last send is remembered (C-2.18), past the interval's own forgetting: one forgotten
#: may send its next terms early, never drop them.
MAX_SENT_TERMS: Final = 4096

type TermsKey = tuple[AccountId, UUID]  # the account and the row's id


def _named(order: Order) -> dict[str, Decimal]:
    """The terms `order` shows, each above zero: a quantity of 0 or no trigger price names none."""
    out = {"qty": order.qty} if order.qty > 0 else {}
    trigger = order.trigger_price
    return out | ({"trigger_price": trigger} if trigger is not None and trigger > 0 else {})


def differs(order: Order, row: OrderRow) -> bool:
    """A term `order` names is another than the row's, by value."""
    held = {"qty": row.qty, "trigger_price": row.trigger_price}
    return any(held[key] != value for key, value in _named(order).items())


def terms_payload(order: Order, row: OrderRow, ts_event: TsUs) -> dict[str, object] | None:
    """B1's `TERMS_CHANGED` for `row` from `order` (module docstring), or None when the order
    names no term."""
    named = _named(order)
    if not named:
        return None
    return {
        "exchange_order_id": order.exchange_order_id,
        "order_link_id": row.order_link_id,  # the row's own (24 Sec.8.3 rule 7)
        **{key: money_text(value) for key, value in named.items()},
        "updated_time": push_time_ms(order, ts_event),
        "source": "ws_private",
    }


class PendingTerms[T]:
    """The rows' pending terms slots and their last sends (module docstring)."""

    def __init__(
        self, *, interval_s: float = TERMS_MIN_INTERVAL_S, cap: int = MAX_PENDING_TERMS,
        sent_cap: int = MAX_SENT_TERMS,
    ) -> None:  # fmt: skip
        self._interval, self._cap, self._sent_cap = interval_s, cap, sent_cap
        self._slots: OrderedDict[TermsKey, T] = OrderedDict()
        self._sent: OrderedDict[TermsKey, float] = OrderedDict()  # in send order

    def __len__(self) -> int:
        return len(self._slots)

    def offer(self, key: TermsKey, slot: T, now: float) -> tuple[T | None, T | None]:
        """`(send now, evicted)`. `slot` is sent at once when its row sent no terms within the
        interval, and it replaces the row's pending slot; else it waits as that slot, the latest
        winning, and a slot the cap evicts (the oldest waiting) is answered to be sent."""
        if not self._recent(key, now):
            self._slots.pop(key, None)
            return slot, None
        self._slots[key] = slot
        self._slots.move_to_end(key)
        if len(self._slots) <= self._cap:
            return None, None
        return None, self._slots.popitem(last=False)[1]

    def take(self, key: TermsKey) -> T | None:
        """The row's pending slot, removed: sent before another push of its order, or dropped
        when a later push shows the row's own terms (the latest win)."""
        return self._slots.pop(key, None)

    def due(self, account_id: AccountId, now: float) -> list[T]:
        """The account's pending slots whose row sent no terms within the interval, removed, in
        the order they started waiting."""
        keys = [k for k in self._slots if k[0] == account_id and not self._recent(k, now)]
        return [self._slots.pop(k) for k in keys]

    def sent(self, key: TermsKey, now: float) -> None:
        """The row's terms were sent at `now`. Sends older than the interval are forgotten (they
        hold nothing back), and past the cap the oldest is (it may then send early, never drop)."""
        self._sent.pop(key, None)
        self._sent[key] = now
        while self._sent:
            first, at = next(iter(self._sent.items()))
            if now - at < self._interval and len(self._sent) <= self._sent_cap:
                break
            del self._sent[first]

    def _recent(self, key: TermsKey, now: float) -> bool:
        at = self._sent.get(key)
        return at is not None and now - at < self._interval

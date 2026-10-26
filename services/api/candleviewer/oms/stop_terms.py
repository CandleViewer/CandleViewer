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
row, the latest terms (by the venue's time, `older_than`) winning, at most one send per row each
`TERMS_MIN_INTERVAL_S` on the monotonic clock. The caller sends a slot before any other push of that
order (`take`), and at the account's next row or `heartbeat` status once the row's interval has
passed (`next_due`, one at a time, at most `MAX_FLUSH_TERMS` a flush), so a row's terms pushes never
send more than one a second and no timer runs. The slots are kept by account, so finding one
account's due slots never walks another's (C-2.20). At most `MAX_PENDING_TERMS` slots wait: a slot
the cap evicts is answered to be sent, never dropped. A slot a later push names only some terms of
keeps the terms that push does not name (`carried`). The terms are the row's record of what the
exchange holds; the exchange holds the stop (C-2.6).
"""

from __future__ import annotations

from collections import OrderedDict
from collections.abc import Mapping
from decimal import Decimal
from typing import Final
from uuid import UUID

from candleviewer.domain.primitives import AccountId, TsUs
from candleviewer.exchange.base.models import Order
from candleviewer.storage.repositories.orders import OrderRow

from .push_mapping import money_text, push_time_ms

TERMS_MIN_INTERVAL_S: Final = 1.0  # 24 Sec.8.12: at most one TERMS_CHANGED a second per row
MAX_PENDING_TERMS: Final = 1024  # pending slots (C-2.18); an evicted one is sent, never dropped
#: The due slots one flush sends (C-2.18): the rest wait for the account's next row or heartbeat, so
#: a backlog against a slow facade holds its consumer loop for at most this many sends.
MAX_FLUSH_TERMS: Final = 4
TERMS: Final = ("qty", "trigger_price")  # the terms a recorded stop's row follows (24 Sec.8.3 r.7)
#: Rows whose last send is remembered (C-2.18), past the interval's own forgetting: one forgotten
#: may send its next terms early, never drop them.
MAX_SENT_TERMS: Final = 4096

type TermsKey = tuple[AccountId, UUID]  # the account and the row's id


def _named(order: Order) -> dict[str, Decimal]:
    """The terms `order` shows, each above zero: a quantity of 0 or no trigger price names none."""
    out = {"qty": order.qty} if order.qty > 0 else {}
    trigger = order.trigger_price
    return out | ({"trigger_price": trigger} if trigger is not None and trigger > 0 else {})


def held(row: OrderRow) -> dict[str, Decimal | None]:
    """The terms `row` holds."""
    return {"qty": row.qty, "trigger_price": row.trigger_price}


def terms_of(payload: Mapping[str, object]) -> dict[str, Decimal]:
    """The terms a `terms_payload` names, as money (they are money text)."""
    return {key: Decimal(raw) for key in TERMS if isinstance(raw := payload.get(key), str)}


def carried(
    pending: Mapping[str, object] | None, order: Order, row: OrderRow
) -> dict[str, Decimal]:
    """A pending payload's terms that `order` does not name and that are still another than the
    row's: a later push naming only some terms (a Full-mode quantity of 0, no trigger price) keeps
    them, the latest winning only for the terms it names."""
    if pending is None:
        return {}
    named, now = _named(order), held(row)
    return {k: v for k, v in terms_of(pending).items() if k not in named and now[k] != v}


def differs(
    order: Order, row: OrderRow, kept: Mapping[str, Decimal] | None = None,
    terms: Mapping[str, Decimal | None] | None = None,
) -> bool:  # fmt: skip
    """A term `order` names, or `kept`, is another than `terms` (the row's by default), by
    value."""
    now = held(row) if terms is None else terms
    return any(now.get(key) != value for key, value in ({**(kept or {}), **_named(order)}).items())


def older_than(order: Order, ts_event: TsUs, pending: Mapping[str, object]) -> bool:
    """`order` changed, by the venue's own time (`push_time_ms`), before the terms the `pending`
    payload waits to send: the latest terms win by that time, never by arrival (the S7a review's
    1), so an out-of-order older push neither drops nor replaces them."""
    stamp = pending.get("updated_time")
    return isinstance(stamp, int) and push_time_ms(order, ts_event) < stamp


def terms_payload(
    order: Order, row: OrderRow, ts_event: TsUs, kept: Mapping[str, Decimal] | None = None
) -> dict[str, object] | None:
    """B1's `TERMS_CHANGED` for `row` from `order` (module docstring), with `kept` (`carried`)
    under the terms the order names, or None when they name no term."""
    named = {**(kept or {}), **_named(order)}
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
    """The rows' pending terms slots, kept by account, and their last sends (module docstring)."""

    def __init__(
        self, *, interval_s: float = TERMS_MIN_INTERVAL_S, cap: int = MAX_PENDING_TERMS,
        sent_cap: int = MAX_SENT_TERMS,
    ) -> None:  # fmt: skip
        self._interval, self._cap, self._sent_cap = interval_s, cap, sent_cap
        self._slots: dict[AccountId, OrderedDict[UUID, T]] = {}  # each account's, oldest first
        self._waiting: OrderedDict[TermsKey, None] = OrderedDict()  # every slot: the cap's order
        self._sent: OrderedDict[TermsKey, float] = OrderedDict()  # in send order

    def __len__(self) -> int:
        return len(self._waiting)

    def offer(self, key: TermsKey, slot: T, now: float) -> tuple[T | None, T | None]:
        """`(send now, evicted)`. `slot` is sent at once when its row sent no terms within the
        interval, and it replaces the row's pending slot; else it waits as that slot, the latest
        winning, and a slot the cap evicts (the oldest waiting) is answered to be sent."""
        if not self._recent(key, now):
            self.take(key)
            return slot, None
        rows = self._slots.setdefault(key[0], OrderedDict())
        rows[key[1]] = slot
        rows.move_to_end(key[1])
        self._waiting[key] = None
        self._waiting.move_to_end(key)
        if len(self._waiting) <= self._cap:
            return None, None
        return None, self._pop(self._waiting.popitem(last=False)[0])

    def peek(self, key: TermsKey) -> T | None:
        """The row's pending slot, left waiting."""
        rows = self._slots.get(key[0])
        return None if rows is None else rows.get(key[1])

    def take(self, key: TermsKey) -> T | None:
        """The row's pending slot, removed: sent before another push of its order, or dropped
        when a later push shows the row's own terms (the latest win)."""
        self._waiting.pop(key, None)
        return self._pop(key)

    def next_due(self, account_id: AccountId, now: float) -> T | None:
        """The account's oldest pending slot whose row sent no terms within the interval, removed;
        only that account's slots are looked at. One at a time, so a cancelled flush loses none
        it has not started to send."""
        for row_id in self._slots.get(account_id, ()):
            if not self._recent((account_id, row_id), now):
                return self.take((account_id, row_id))
        return None

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

    def _pop(self, key: TermsKey) -> T | None:
        rows = self._slots.get(key[0])
        if rows is None:
            return None
        out = rows.pop(key[1], None)
        if not rows:
            del self._slots[key[0]]
        return out

    def _recent(self, key: TermsKey, now: float) -> bool:
        at = self._sent.get(key)
        return at is not None and now - at < self._interval

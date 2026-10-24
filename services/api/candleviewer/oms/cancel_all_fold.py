"""The venue cancel-all fold's two rules that stand alone (E29-T04 #913 slice 4, S4-F; 24 Sec.8.7
"Cancel-all", ruling Q1): when one symbol's cancels may fold into the venue's `cancel-all`, and
how often one may leave.

- **Coverage.** Only an unrestricted request folds, per account and symbol, and only when a
  `poll`-lane open-orders read shows every plain order resting there among the request's selected
  orders. A plain order is the kind the venue's `cancel-all` with `orderFilter=Order` cancels
  (`order_kind` "order"; never a TP/SL or a conditional order, SR-E29-06). Any other plain order
  resting there (another client's, or one the request left out) keeps that symbol on per-order
  cancels: the fail-safe, as a venue `cancel-all` would take it too.
- **Spacing.** At most one venue `cancel-all` per UID per second (`order.cancel_all`, 1/s for
  linear; the exchange counts it per UID, shared by its keys), on a monotonic clock the OMS owns
  until E34-T02's governor takes it over (#859). A caller takes the UID's next free slot before
  it waits, so callers that arrive together leave in turn, a second apart; one whose slot falls
  past its deadline takes none, and its symbol stays on per-order cancels.
"""

from __future__ import annotations

import asyncio
import math
from collections.abc import Awaitable, Callable, Collection, Iterable
from typing import Final

from candleviewer.exchange.base.models import Order

__all__ = ["CANCEL_ALL_INTERVAL_S", "FOLDED_KIND", "MAX_UIDS", "CancelAllSpacer", "covers"]

#: The order kind the venue's `cancel-all` cancels (`orderFilter=Order`, 24 Sec.14.2 rule 12).
FOLDED_KIND: Final = "order"
#: One venue `cancel-all` per UID per second (24 Sec.8.7, `order.cancel_all`).
CANCEL_ALL_INTERVAL_S: Final = 1.0
#: UIDs the spacer remembers before it forgets those whose next slot has passed (C-2.18).
MAX_UIDS: Final = 4096


def covers(resting: Iterable[Order], selected: Collection[str]) -> bool:
    """Whether one symbol's cancels may fold: at least one plain order rests there, as the read
    shows it, and every one of them is among the `selected` order link ids."""
    plain = {order.order_link_id for order in resting if order.order_kind == FOLDED_KIND}
    return bool(plain) and plain <= set(selected)


class CancelAllSpacer:
    """The per-UID spacing of the venue's `cancel-all` (module docstring). `turn(uid, deadline=)`
    answers True once the UID's next free slot has come and the call may leave, or False at once,
    with no slot taken, when that slot falls past `deadline` (a time on `monotonic`). A caller
    cancelled while it waits leaves its slot spent: the next waits the full second all the same.
    One event loop's, as the order lanes are."""

    def __init__(
        self,
        *,
        monotonic: Callable[[], float],
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        interval_s: float = CANCEL_ALL_INTERVAL_S,
        max_uids: int = MAX_UIDS,
    ) -> None:
        if isinstance(interval_s, bool) or not (math.isfinite(interval_s) and interval_s > 0):
            raise ValueError("interval_s must be a finite number of seconds above zero")
        if isinstance(max_uids, bool) or max_uids < 1:
            raise ValueError("max_uids must be at least 1")
        self._monotonic, self._sleep = monotonic, sleep
        self._interval, self._max_uids = float(interval_s), max_uids
        self._free_at: dict[str, float] = {}

    async def turn(self, uid: str, *, deadline: float) -> bool:
        now = self._monotonic()
        slot = max(now, self._free_at.get(uid, now))
        if slot > deadline:
            return False
        self._free_at[uid] = slot + self._interval  # taken before the wait: callers leave in turn
        if len(self._free_at) > self._max_uids:
            self._forget(now)
        if slot > now:
            await self._sleep(slot - now)
        return True

    def _forget(self, now: float) -> None:
        """The UIDs whose next slot has passed: remembering them changes no answer. One still to
        come stays, as forgetting it could let a second call leave inside its second."""
        for uid in [uid for uid, free_at in self._free_at.items() if free_at <= now]:
            del self._free_at[uid]

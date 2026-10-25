"""The venue cancel-all fold's parts that stand alone (E29-T04 #913 slice 4, S4-F; 24 Sec.8.7
"Cancel-all", ruling Q1): when one symbol's cancels may fold into the venue's `cancel-all`, how
often one may leave, and how its members meet it.

- **Coverage.** Only an unrestricted request folds, per account and symbol, and only when a
  `poll`-lane open-orders read shows every plain order resting there among the request's selected
  orders. A plain order is the kind the venue's `cancel-all` cancels under the venue's plain-order
  filter (24 Sec.14.2 rule 12, SR-E29-06): `order_kind` "order", never a TP/SL or a conditional
  order. Any other plain order resting there (another client's, or one the request left out)
  keeps that symbol on per-order cancels: the fail-safe, as a venue `cancel-all` would take it too.
- **Spacing.** At most one venue `cancel-all` per UID per second (`order.cancel_all`, 1/s for
  linear; the exchange counts it per UID, shared by its keys), on a monotonic clock the OMS owns
  until E34-T02's governor takes it over (#859). A caller takes the UID's next free slot before
  it waits, so callers that arrive together leave in turn, a second apart; one whose slot falls
  past its deadline takes none, and its symbol stays on per-order cancels.
- **The join.** The members of one account-and-symbol fold each arrive once their B1 `CANCEL` is
  written ahead (C-2.9), so the venue's call only ever takes orders the OMS already cancels. Once
  every member has arrived, one venue call leaves and each member is answered by its own ack; one
  the acks do not name (the venue's 500-order cap, a race) or a refused call sends its own cancel.
  A member that leaves, or a gather that runs past its bound, abandons the fold before anything is
  sent, and every member sends its own cancel: the fail-safe. A call that raises reaches every
  member as its own call's would: its outcome is not known, and nothing is sent again.
"""

from __future__ import annotations

import asyncio
import math
from collections.abc import Awaitable, Callable, Collection, Iterable, Sequence
from typing import Final

from candleviewer.exchange.base.errors import UnknownStateError
from candleviewer.exchange.base.models import Order, OrderAck
from candleviewer.observability.context import spawn

__all__ = [
    "CANCEL_ALL_INTERVAL_S", "FOLDED_KIND", "GATHER_S", "MAX_UIDS", "CancelAllJoin",
    "CancelAllSpacer", "covers",
]  # fmt: skip

#: The order kind the venue's `cancel-all` cancels: the venue's plain-order filter (24 Sec.14.2
#: rule 12, SR-E29-06).
FOLDED_KIND: Final = "order"
#: One venue `cancel-all` per UID per second (24 Sec.8.7, `order.cancel_all`).
CANCEL_ALL_INTERVAL_S: Final = 1.0
#: UIDs the spacer remembers before it forgets those whose next slot has passed (C-2.18).
MAX_UIDS: Final = 4096
#: How long a fold's members may take to arrive, from the join's opening, before it is abandoned:
#: well inside a cancel's own 9 s (24 Sec.8.7), so its fallback still has its time.
GATHER_S: Final = 1.0


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


class CancelAllJoin:
    """One account-and-symbol fold's meeting point (module docstring). `members` are the order
    link ids it folds. `send` makes the one venue call, behind the spacer, and answers its acks, or
    None when the spacer refused it a slot in time. `arrive(link)` answers that member's ack, or
    None when it must send its own cancel; `leave` abandons the fold for a member that will not
    arrive. The gather's bound runs on `monotonic` and `sleep` from the join's opening. One event
    loop's, as the order lanes are."""

    def __init__(
        self,
        members: Collection[str],
        send: Callable[[], Awaitable[Sequence[OrderAck] | None]],
        *,
        monotonic: Callable[[], float],
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        gather_s: float = GATHER_S,
    ) -> None:
        if not members:
            raise ValueError("a fold has at least one member")
        if isinstance(gather_s, bool) or not (math.isfinite(gather_s) and gather_s > 0):
            raise ValueError("gather_s must be a finite number of seconds above zero")
        self._members, self._send = frozenset(members), send
        self._monotonic, self._sleep = monotonic, sleep
        self._deadline = monotonic() + float(gather_s)
        self._arrived: set[str] = set()
        self._answer: asyncio.Future[dict[str, OrderAck] | None] = (
            asyncio.get_running_loop().create_future()
        )
        self._sent = False
        self._expiry: asyncio.Task[None] | None = None

    @property
    def members(self) -> frozenset[str]:
        return self._members

    async def arrive(self, link: str) -> OrderAck | None:
        if link not in self._members:
            raise ValueError("only a member arrives at its fold")
        if self._answer.done() or link in self._arrived:
            return self._own(link)
        self._arrived.add(link)
        if self._arrived == self._members:
            if self._monotonic() > self._deadline:  # gathered too late: nothing is sent
                self._abandon()
            else:
                await self._call()
            return self._own(link)
        if self._expiry is None:
            self._expiry = spawn(self._expire(), name="oms-cancel-all-gather")
        try:
            await asyncio.shield(self._answer)
        except asyncio.CancelledError:
            if not self._sent:
                self._abandon()
            raise
        return self._own(link)

    def leave(self, link: str) -> None:
        """A member that will not arrive (refused before its send): the fold is abandoned unless
        its call has left already."""
        if link in self._members and not self._sent:
            self._abandon()

    async def _expire(self) -> None:
        """The gather's bound: past it, a fold whose call has not left is abandoned."""
        await self._sleep(max(self._deadline - self._monotonic(), 0.0))
        if not self._sent:
            self._abandon()

    async def _call(self) -> None:
        """The last member's: the one venue call. A refused call, or none, answers no member."""
        self._sent = True
        self._stop_expiry()
        try:
            acks = await self._send()
        except Exception as exc:  # the call's error, as each member's own call would raise it
            self._fail(exc)
            raise
        except BaseException:  # cut short (cancelled): the call may have left
            self._fail(UnknownStateError("a fold's cancel-all was cut short", retryable=False))
            raise
        if acks is None or not any(ack.ok for ack in acks):
            self._abandon()
        elif not self._answer.done():
            self._answer.set_result(
                {ack.order_link_id: ack for ack in acks if ack.ok and ack.order_link_id}
            )

    def _fail(self, error: Exception) -> None:
        if not self._answer.done():
            self._answer.set_exception(error)
            self._answer.exception()  # retrieved here; each member re-raises it

    def _abandon(self) -> None:
        if not self._answer.done():
            self._answer.set_result(None)
        self._stop_expiry()

    def _stop_expiry(self) -> None:
        expiry = self._expiry
        if expiry is not None and expiry is not asyncio.current_task():
            expiry.cancel()

    def _own(self, link: str) -> OrderAck | None:
        """This member's ack, or None (send your own cancel); the call's error, re-raised."""
        answer = self._answer.result() if self._answer.done() else None
        return None if answer is None else answer.get(link)

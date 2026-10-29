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
  written ahead (C-2.9), so every member the venue's call takes is an order the OMS has already
  commanded cancelled; the call may take one more, an order placed on the symbol after the
  coverage read (the residual `cancel_all_coalescer` names). Once every member has arrived, a task
  of the join's own waits for the UID's spacer slot and makes the one venue call, and each member
  is answered by its own ack; one the acks do not name (the venue's 500-order cap, a race) sends
  its own cancel, as every member does when the call names none or no slot comes in time. Until
  the call leaves, a member that leaves or is cut short, or a gather past its bound, abandons the
  fold: nothing is sent, and every member sends its own cancel, the fail-safe. Once it has left,
  no member's cancellation cuts it short: its acks answer every member, and a call that raises
  reaches each as its own call's would, its outcome not known and nothing sent again.
"""

from __future__ import annotations

import asyncio
import math
from collections.abc import Awaitable, Callable, Collection, Coroutine, Iterable, Sequence
from typing import Any, Final, Protocol

from candleviewer.exchange.base.errors import UnknownStateError
from candleviewer.exchange.base.models import Order, OrderAck
from candleviewer.observability import spawn

__all__ = [
    "CANCEL_ALL_INTERVAL_S", "FOLDED_KIND", "GATHER_S", "MAX_UIDS", "CancelAllJoin",
    "CancelAllSpacer", "FoldRefused", "Spawn", "covers",
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


class FoldRefused(Exception):
    """A fold not opened: one of its orders is already a member of another open fold (one order
    meets one fold). Its orders are cancelled one at a time instead."""


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


class Spawn(Protocol):
    """How a join starts its own tasks, its call and its gather's watchdog: its owner's spawn,
    which tracks each one until it ends (`CancelAllCoalescer`), or `spawn` itself."""

    def __call__(self, coro: Coroutine[Any, Any, None], *, name: str) -> asyncio.Task[None]: ...


class CancelAllJoin:
    """One account-and-symbol fold's meeting point (module docstring). `members` are the order
    link ids it folds. Once every member has arrived, a task of the join's own (`spawn`) awaits
    `slot`, the UID's spacer slot (False: none in time), then `call`, the one venue call.
    `arrive(link)` answers that member's ack, or None when it must send its own cancel; `leave`
    abandons the fold for a member that will not arrive or no longer waits. Until the call leaves,
    any member's departure, a leave or its cancellation, abandons the fold and ends the slot's
    wait: nothing was sent. Once it has left, no member's cancellation cuts it short; only its
    owner's teardown cancels it, leaving the members still waiting an unknown outcome, and
    `close`, the teardown's last word, abandons a fold whose call has not left. The gather's bound
    runs on `monotonic` and `sleep` from the join's opening. One event loop's, as the order lanes
    are."""

    def __init__(
        self,
        members: Collection[str],
        slot: Callable[[], Awaitable[bool]],
        call: Callable[[], Awaitable[Sequence[OrderAck]]],
        *,
        monotonic: Callable[[], float],
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        spawn: Spawn = spawn,
        gather_s: float = GATHER_S,
    ) -> None:
        if not members:
            raise ValueError("a fold has at least one member")
        if isinstance(gather_s, bool) or not (math.isfinite(gather_s) and gather_s > 0):
            raise ValueError("gather_s must be a finite number of seconds above zero")
        self._members, self._slot, self._call = frozenset(members), slot, call
        self._monotonic, self._sleep, self._spawn = monotonic, sleep, spawn
        self._deadline = monotonic() + float(gather_s)
        self._arrived: set[str] = set()
        self._answer: asyncio.Future[dict[str, OrderAck] | None] = (
            asyncio.get_running_loop().create_future()
        )
        self._left = False
        self._why: str | None = None
        self._expiry: asyncio.Task[None] | None = None
        self._sending: asyncio.Task[None] | None = None

    @property
    def left(self) -> bool:
        """Whether its venue call has left: it is never abandoned after."""
        return self._left

    @property
    def abandoned(self) -> str | None:
        """Why it was abandoned before anything was sent (`left`, a member left or was cut
        short; `gather`, the gather's bound; `slot`, no spacer slot in time; `closed`, its owner's
        teardown), or None."""
        return self._why

    async def arrive(self, link: str) -> OrderAck | None:
        if link not in self._members:
            raise ValueError("only a member arrives at its fold")
        if self._answer.done() or link in self._arrived:
            return self._own(link)  # answered, or arriving twice while it gathers: its own
        self._arrived.add(link)
        if self._arrived == self._members:
            if self._monotonic() > self._deadline:  # gathered too late: nothing is sent
                self._abandon("gather")
                return self._own(link)
            self._stop_expiry()
            self._sending = self._spawn(self._send(), name="oms-cancel-all-call")
        elif self._expiry is None:
            self._expiry = self._spawn(self._expire(), name="oms-cancel-all-gather")
        try:
            await asyncio.shield(self._answer)
        except asyncio.CancelledError:
            self._abandon("left")  # before the call leaves; once it has left, nothing changes
            raise
        return self._own(link)

    def leave(self, link: str) -> None:
        """A member that will not arrive, or no longer waits: the fold is abandoned unless its
        call has left."""
        if link in self._members:
            self._abandon("left")

    def close(self) -> None:
        """Its owner's teardown, once the join's own tasks have ended (`CancelAllCoalescer.aclose`):
        a fold whose call has not left is abandoned (`closed`), so each member still waiting sends
        its own cancel, never left waiting on a watchdog or a call that the teardown cut short
        before it ran. One whose call has left keeps its answer: nothing is sent again."""
        self._abandon("closed")

    async def _expire(self) -> None:
        """The gather's bound: past it, a fold still gathering is abandoned."""
        await self._sleep(max(self._deadline - self._monotonic(), 0.0))
        self._abandon("gather")

    async def _send(self) -> None:
        """The join's own task, once every member has arrived (class docstring)."""
        try:
            slot = await self._slot()
        except BaseException:  # cut short (teardown) or a defect before anything left: nothing
            self._abandon("slot")  # was sent, so each member sends its own cancel
            raise
        if not slot:
            self._abandon("slot")
            return
        self._left = True
        try:
            acks = await self._call()
        except Exception as exc:  # the call's error, as each member's own call would raise it
            self._fail(exc)
            return
        except BaseException:  # cut short at teardown: the call may have left
            self._fail(UnknownStateError("a fold's cancel-all was cut short", retryable=False))
            raise
        if not self._answer.done():  # a call that names no member leaves each to its own
            self._answer.set_result({a.order_link_id: a for a in acks if a.ok and a.order_link_id})

    def _fail(self, error: Exception) -> None:
        if not self._answer.done():
            self._answer.set_exception(error)
            self._answer.exception()  # retrieved here; each member re-raises it

    def _abandon(self, why: str) -> None:
        """Nothing is sent: each member sends its own cancel. A no-op once the call has left."""
        if self._left:
            return
        if not self._answer.done():
            self._why = why
            self._answer.set_result(None)
        self._stop_expiry()
        sending = self._sending
        if sending is not None and sending is not asyncio.current_task():
            sending.cancel()  # in the slot's wait: nothing has left

    def _stop_expiry(self) -> None:
        expiry = self._expiry
        if expiry is not None and expiry is not asyncio.current_task():
            expiry.cancel()

    def _own(self, link: str) -> OrderAck | None:
        """This member's ack, or None (send your own cancel); the call's error, re-raised."""
        answer = self._answer.result() if self._answer.done() else None
        return None if answer is None else answer.get(link)

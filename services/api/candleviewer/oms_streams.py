"""The order lane's private streams (#913 L1d-2b; 20-architecture.md Sec.6.2, ruling Q2 (b)).

The adapter's one stream registry stays on the serving loop, which opens, dials, signs (through its
M2 binding) and reads each private stream as B13's `platform` chart; the order lane's trading port
opens through `LaneStreams`, the stream source the composition root gives it, and its consumer
reads a `_LaneStream`. The bridge crosses only by `oms_lane.Serving`'s awaited call and its notice.

**Open.** One awaited hop runs the adapter's `open_private_stream` on the serving loop; its
refusals are raised on the lane. An open the lane stops waiting for sends a discard notice, which
the serving loop takes after the open's hop: a stream that opens all the same, then or later, is
closed there at once, so no account stays held.

**Read.** The lane pops its batch; with none left it takes, by one awaited hop, the stream's next
item and every item already queued behind it (`ready()`), at most `HOP_BATCH`, in arrival order,
those behind the first in the turn its await returns, so a batch never runs past a `down` into the
next epoch, whose dial needs awaits. It asks again only once the consumer has taken the whole
batch: the hop holds one batch at most and never drops, sheds or re-delivers an item, so the
adapter's queue stays the stream's only buffer and its policy the only shedding (`slow_consumer`,
24 Sec.14.2 rule 13). A read cancelled closes the stream as on one loop: its read on the serving
loop is cancelled, and a close notice covers one the serving loop had not begun. A hop that fails
(`STREAM_READ_BOUND_S`, or a closed serving loop) ends the stream on the lane, logged, and closes
it there.

**Close.** The consumer's close crosses as a notice, never cut short or discarded unrun; the lane
waits at most `STREAM_CLOSE_BOUND_S` for the serving loop to report the socket closed and the
account freed, so its own resubscribe is not refused, and past that logs
`oms_private_stream_close_overran` while the close runs on. The runtime's stop closes, on the
serving loop, any stream a consumer left open (`aclose`), the lane playing no part.

The lane's batch and flags are the lane's; the registry's stream and the bridge's books are the
serving loop's, which the lane holds by reference only. Only frozen events and statuses, the
`AccountRef` and the open's refusals cross; logs carry ids only (C-12.6). Plain code on C-2.20's
hot-path contract: it imports neither the statechart package nor `oms_lane`, whose `Serving` it
types by `Hop`.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
from collections import deque
from collections.abc import Awaitable, Callable, Coroutine
from typing import Any, Protocol, runtime_checkable

import structlog

from candleviewer.exchange.base.models import AccountRef, PrivateEvent, PrivateStreamStatus
from candleviewer.exchange.base.ports import PrivateStream
from candleviewer.observability import spawn
from candleviewer.oms.config import HOP_BATCH, STREAM_CLOSE_BOUND_S, STREAM_READ_BOUND_S

__all__ = ["LaneStreams"]

type Item = PrivateEvent | PrivateStreamStatus
type OffsetReader = Callable[[], int | None]
#: `LaneStreams._close`: on the serving loop, a stream's close, its waiter answered once done.
type _Close = Callable[[_Held, concurrent.futures.Future[None] | None], None]


def _log() -> Any:
    """Resolve per call: a module-level logger pins a stale processor chain (#2008)."""
    return structlog.get_logger(__name__)


class Hop(Protocol):
    """`oms_lane.Serving` as the bridge crosses it: an awaited call on the serving loop, cut at its
    bound, and a notice there that nothing cuts short."""

    async def call[T](self, coro: Coroutine[Any, Any, T], *, timeout_s: float = ...) -> T: ...

    def notify(self, fn: Callable[..., object], /, *args: Any, **kwargs: Any) -> None: ...


class OpenStream(Protocol):
    """The adapter's `open_private_stream`, which the bridge runs on the serving loop."""

    def __call__(
        self, account: AccountRef, *, clock_offset_ms: OffsetReader | None = None
    ) -> Awaitable[PrivateStream]: ...


@runtime_checkable
class Batched(Protocol):
    """The registry's stream as a hop reads it: `ready()`, the items its `__anext__` returns now,
    each with no wait, in arrival order. A stream without it crosses one item a hop."""

    def ready(self) -> int: ...


def _none() -> int:
    return 0


class _Held:
    """A stream the bridge holds on the serving loop: the registry's stream, its `ready`, and its
    close once begun, read and changed there only; the lane holds it by reference."""

    __slots__ = ("closing", "ready", "stream")

    def __init__(self, stream: PrivateStream) -> None:
        self.stream = stream
        self.ready: Callable[[], int] = stream.ready if isinstance(stream, Batched) else _none
        self.closing: asyncio.Task[None] | None = None


class _Opening:
    """One open, on the serving loop only: the stream it opened, and whether the lane stopped
    waiting for it."""

    __slots__ = ("discarded", "held")

    def __init__(self) -> None:
        self.held: _Held | None = None
        self.discarded = False


class LaneStreams:
    """The order lane's stream source (the adapter's `StreamOpener`), built with no I/O over the
    adapter's `open_private_stream` and the way back to the serving loop (module docstring)."""

    def __init__(self, open_stream: OpenStream, serving: Hop) -> None:
        self._open, self._serving = open_stream, serving
        #: The streams held and the closes begun, the serving loop's only.
        self._held: set[_Held] = set()
        self._tasks: set[asyncio.Task[None]] = set()

    async def open(
        self, account: AccountRef, *, clock_offset_ms: OffsetReader | None = None
    ) -> PrivateStream:
        """On the lane: the account's stream, opened on the serving loop by one awaited hop, its
        refusals raised here. `clock_offset_ms`, the lane port's snapshot of the exchange clock's
        offset, is read on the serving loop at each dial's `auth`, so it must be a read that
        changes nothing and is safe from that thread. A stream that opens once this stops
        waiting is closed there (`_discard`)."""
        opening = _Opening()
        try:
            held = await self._serving.call(self._opened(account, clock_offset_ms, opening))
        except BaseException:  # refused there, or no longer waited for: nothing is held
            self._serving.notify(self._discard, opening)
            raise
        return _LaneStream(self._serving, self._close, held, account)

    async def aclose(self) -> None:
        """On the serving loop, the runtime's stop: every stream still held closes, concurrently,
        and every close begun is awaited; the lane plays no part, so a dead lane's streams close
        too."""
        for held in list(self._held):
            self._close(held, None)
        while self._tasks:
            await asyncio.wait(set(self._tasks))

    async def _opened(
        self, account: AccountRef, clock_offset_ms: OffsetReader | None, opening: _Opening
    ) -> _Held:
        held = _Held(await self._open(account, clock_offset_ms=clock_offset_ms))
        if opening.discarded:  # the lane stopped waiting meanwhile: closed at once, never held
            self._close(held, None)
            return held
        opening.held = held
        self._held.add(held)
        return held

    def _discard(self, opening: _Opening) -> None:
        """The notice of an open the lane stopped waiting for: its stream, should it open, is
        closed."""
        opening.discarded = True
        if opening.held is not None:
            self._close(opening.held, None)

    def _close(self, held: _Held, done: concurrent.futures.Future[None] | None) -> None:
        """On the serving loop: `held` closes once, in a task the bridge owns that nothing cuts
        short, which frees the account once its socket is closed; `done` is answered then."""
        self._held.discard(held)
        closing = held.closing
        if closing is None:
            closing = held.closing = self._spawn(held.stream.aclose())
        if done is not None:
            closing.add_done_callback(lambda _: _answered(done))

    def _spawn(self, close: Coroutine[Any, Any, None]) -> asyncio.Task[None]:
        task = spawn(close, name="oms-private-stream-close")
        self._tasks.add(task)
        task.add_done_callback(self._ended)
        return task

    def _ended(self, task: asyncio.Task[None]) -> None:
        self._tasks.discard(task)
        if not task.cancelled() and (error := task.exception()) is not None:
            _log().error("oms_private_stream_close_failed", error=type(error).__name__)


def _answered(done: concurrent.futures.Future[None]) -> None:
    if done.set_running_or_notify_cancel():  # else the lane stopped waiting
        done.set_result(None)


async def _take(held: _Held) -> tuple[Item, ...]:
    """On the serving loop, one read: the stream's next item, awaited, then every item already
    queued behind it, at most `HOP_BATCH` in all, each with no wait, so those behind the first are
    taken in the turn its await returns; none once the stream has ended."""
    try:
        first = await anext(held.stream)
    except StopAsyncIteration:  # closed meanwhile, by the bridge's close
        return ()
    batch = [first]
    while len(batch) < HOP_BATCH and held.ready() > 0:
        batch.append(await anext(held.stream))
    return tuple(batch)


class _LaneStream:
    """The account's stream on the lane (`PrivateStream`), for one reader: the items the hops
    bring, in arrival order, ending after its `closed` status (module docstring)."""

    def __init__(self, serving: Hop, close: _Close, held: _Held, account: AccountRef) -> None:
        self._serving, self._close, self._held, self._account = serving, close, held, account
        self._batch: deque[Item] = deque()
        self._last = False  # its last item is in the batch: nothing more is asked
        self._ended = False  # ended on the lane: nothing more is yielded
        self._closed = False

    def __aiter__(self) -> _LaneStream:
        return self

    async def __anext__(self) -> Item:
        if not self._batch and not self._last:
            await self._fetch()
        if not self._batch:
            raise StopAsyncIteration
        return self._batch.popleft()

    async def aclose(self) -> None:
        """Close the stream; idempotent. The close is a notice to the serving loop, and this
        returns once the socket is closed and the account freed there, or past
        `STREAM_CLOSE_BOUND_S`, logged, while the close runs on."""
        if self._closed:
            return
        self._closed = True
        self._end(notice=False)
        done: concurrent.futures.Future[None] = concurrent.futures.Future()
        self._serving.notify(self._close, self._held, done)
        try:
            async with asyncio.timeout(STREAM_CLOSE_BOUND_S):
                await asyncio.wrap_future(done)
        except TimeoutError:
            _log().error(
                "oms_private_stream_close_overran",
                account_id=str(self._account.account_id),
                bound_s=STREAM_CLOSE_BOUND_S,
            )

    async def _fetch(self) -> None:
        try:
            batch = await self._serving.call(_take(self._held), timeout_s=STREAM_READ_BOUND_S)
        except asyncio.CancelledError:  # the consumer's bound or cancel: closed as on one loop
            self._end(notice=True)
            raise
        except Exception as exc:  # past the bound, or a closed serving loop: it ends here
            _log().error(
                "oms_private_stream_hop_failed",
                account_id=str(self._account.account_id),
                error=type(exc).__name__,
            )
            self._end(notice=True)
            return
        if self._ended:  # closed meanwhile: nothing more is yielded
            return
        self._batch.extend(batch)
        last = batch[-1] if batch else None
        if last is None or (isinstance(last, PrivateStreamStatus) and last.state == "closed"):
            self._last = True

    def _end(self, *, notice: bool) -> None:
        """Nothing more is yielded or asked; with `notice`, the close crosses, once."""
        first = not self._ended
        self._ended = self._last = True
        self._batch.clear()
        if notice and first:
            self._serving.notify(self._close, self._held, None)

"""Per-UID token bucket for the Bybit REST client (E08-T02 "Rate budget is
shared per UID" scenario; `docs/plan/24-internal-schemas.md` §14.3/§8.7).

One bucket is keyed by `(uid, endpoint_class)` because Bybit's budgets
differ per endpoint family (technical notes: "`ExchangeCapabilities.
order_rate_per_uid_per_s` is a dict"). All callers sharing a UID — even
across different API keys — draw from the same bucket, which is what makes
the per-UID limit enforceable at all (ticket Context paragraph).

The process builds one governor (`ExchangeBybitService`, OM-D08, #2877 ruling R5): every
REST client is given it, so the 600-per-5 s IP bucket and the `10018` hold cover every UID and
the public clients. Key verification draws through a `capped` view that shares that IP bucket,
hold and per-UID buckets and adds its own 50-per-5 s cap (SR-E27-05). Every acquisition names
its lane (`critical`, `entry`, `poll`; 20 §4.3): the buckets accept it and serve every lane
alike until E34-T02 builds the reserve behind it (#2877 ruling R3).

Both of the process's event loops draw on that one budget per UID: the serving loop and the
order lane's own (20 §4.4, CV-C13; #913 ruling Q11). Each bucket, a view's cap and the hold
exist once per process, and one `threading.Lock` guards every read and change of them, held
for the arithmetic only. A taker waits on its own loop, behind that loop's other takers of a
bucket, then in the bucket's `heads`, at most one per loop. A loop that dies or stalls with
a taker waiting, uncancelled, keeps at most the one token it was handed per (bucket, loop),
and any its acquisitions in flight took at earlier buckets (a cap or a UID bucket): spent,
never sent, an underspend and never an overspend; the collector's end of it takes no lock.
"""

from __future__ import annotations

import asyncio
import contextlib
import copy
import math
import threading
import time
import weakref
from collections import deque
from collections.abc import Awaitable, Callable

from candleviewer.exchange.base.errors import RateBudgetExceededError
from candleviewer.exchange.base.models import RateLane
from candleviewer.exchange.bybit.config import EndpointClass
from candleviewer.exchange.bybit.metrics import bybit_ip_hold_remaining_seconds

#: Hard ceiling on one IP hold (defence in depth vs a hostile/garbled reset header).
MAX_IP_HOLD_S = 900.0
#: The longest single sleep while a token refills, so a hold set meanwhile is seen promptly.
_MAX_POLL_S = 1.0
#: The poll interval of a bucket that does not refill.
_NO_REFILL_POLL_S = 0.05


class _Turn:
    """One loop's queue of takers of one bucket, first come first served, on public asyncio
    only (#913 ruling 3); one loop per instance, as `_Bucket._turns` keys them. A free turn is
    taken without yielding. `release` hands the turn to the first waiter, never freeing it
    while one waits; a waiter cut after that hand-off passes it on. It takes no lock and
    refers to its loop only through waiting takers' futures, so a closed loop is collected."""

    __slots__ = ("_held", "_waiters")

    def __init__(self) -> None:
        self._held = False
        self._waiters: deque[asyncio.Future[None]] = deque()

    def locked(self) -> bool:
        return self._held

    async def acquire(self) -> None:
        if not self._held:
            self._held = True
            return
        waiter = asyncio.get_running_loop().create_future()
        self._waiters.append(waiter)
        try:
            await waiter  # `release` hands the turn over, held throughout
        except BaseException:
            if waiter.done() and not waiter.cancelled():
                self.release()  # handed the turn, then cut before it ran: pass it on
            else:
                with contextlib.suppress(ValueError):
                    self._waiters.remove(waiter)
            raise

    def release(self) -> None:
        if not self._held:
            raise RuntimeError("release of a turn that is not held")
        while self._waiters:
            waiter = self._waiters.popleft()
            # A closed loop's waiter is skipped, not resolved: it would pass on a turn not its.
            if not waiter.done() and not waiter.get_loop().is_closed():
                waiter.set_result(None)
                return
        self._held = False


class _Head:
    """The first of one loop's takers of a bucket, waiting for a token; `granted` once it has it."""

    __slots__ = ("granted",)

    def __init__(self) -> None:
        self.granted = False


class _Bucket:
    """A single leaky/token bucket, one per process, read and changed only under `guard`. Its
    takers queue on their loop's `lock`; the first of each loop waits in `heads`, in order."""

    __slots__ = ("_turns", "capacity", "guard", "heads", "refill_per_s", "tokens", "updated_at")

    def __init__(
        self, capacity: float, refill_per_s: float, *, now: float, guard: threading.Lock
    ) -> None:
        self.capacity = capacity
        self.tokens = capacity
        self.refill_per_s = refill_per_s
        self.updated_at = now
        self.guard = guard
        self.heads: deque[_Head] = deque()
        self._turns: weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, _Turn] = (
            weakref.WeakKeyDictionary()
        )

    @property
    def lock(self) -> _Turn:
        """The running loop's queue of takers of this bucket, made at its first use."""
        loop = asyncio.get_running_loop()
        with self.guard:
            turn = self._turns.get(loop)
            if turn is None:
                turn = self._turns[loop] = _Turn()
            return turn

    def _refill(self, now: float) -> None:
        elapsed = max(0.0, now - self.updated_at)
        self.tokens = min(self.capacity, self.tokens + elapsed * self.refill_per_s)
        self.updated_at = now

    def serve(self, head: _Head, now: float) -> bool:
        """Refill, hand each whole token to the waiting heads in the order they came (`head`
        joins them at its first look), and say whether `head` holds one."""
        if not head.granted and head not in self.heads:
            self.heads.append(head)
        self._refill(now)
        while self.heads and self.tokens >= 1.0:
            self.tokens -= 1.0
            self.heads.popleft().granted = True
        return head.granted

    def wait_for(self, head: _Head) -> float:
        """Seconds until a token is spare for `head`, after one for each head before it (a short
        poll when the bucket never refills, so only a header or a drain can change it)."""
        deficit = self.heads.index(head) + 1.0 - self.tokens
        return deficit / self.refill_per_s if self.refill_per_s > 0 else _NO_REFILL_POLL_S

    def leave(self, head: _Head) -> None:
        """`head` stops waiting: a token handed to it goes back, or it leaves the queue."""
        if head.granted:
            head.granted = False
            self.tokens = min(self.capacity, self.tokens + 1.0)
        elif head in self.heads:
            self.heads.remove(head)

    def level(self, now: float) -> float:
        """The tokens it holds at `now`, refilled, read without changing it."""
        elapsed = max(0.0, now - self.updated_at)
        return min(self.capacity, self.tokens + elapsed * self.refill_per_s)

    def wait_at(self, now: float) -> float:
        """Seconds from `now` until one token is spare, read without changing it (never, for a
        bucket that does not refill: only a header or a drain can change it)."""
        deficit = 1.0 - self.level(now)
        if deficit <= 0.0:
            return 0.0
        return deficit / self.refill_per_s if self.refill_per_s > 0 else math.inf


class _IpGate:
    """The IP-wide bucket and the `10018` hold: one per process, shared by every view and loop."""

    __slots__ = ("bucket", "hold_until")

    def __init__(self, bucket: _Bucket) -> None:
        self.bucket = bucket
        self.hold_until = 0.0


class TokenBucketGovernor:
    """Owns one bucket per `(uid, endpoint_class)` and one IP-wide bucket.

    `acquire` waits (cooperatively, on the injected sleep) until a token is
    available — the budget is *shaped*, never silently exceeded (acceptance
    criterion 2) — or, given `deadline_s`, refuses with `RateBudgetExceededError`
    as soon as the wait would run past it, before any request is signed or sent
    (24 §8.7). `drain` is called by the client after a `10018`/rate-limited
    response to account for exchange-side budget consumption the client did not
    itself schedule (acceptance criterion 3).

    It is safe to call from several event loops over one budget (#913 ruling Q11): `_guard`,
    shared by every view, is held for the arithmetic only. Across loops a token that comes due
    is handed, by whichever taker sees it first, to the loop's first taker that has waited
    longest. So a busy or parked loop costs another its turn at most, never its lag, and a
    taker first on its loop waits for at most one token per other loop.
    """

    def __init__(
        self,
        *,
        default_capacity: float = 10.0,
        default_refill_per_s: float = 5.0,
        ip_budget_per_5s: int = 600,
        clock: Callable[[], float] | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        """`clock` is read under the governor's lock: one that calls back into the governor
        would deadlock."""
        self._guard = threading.Lock()
        self._sleep = sleep
        self._default_capacity = default_capacity
        self._default_refill_per_s = default_refill_per_s
        self._buckets: dict[tuple[str, EndpointClass], _Bucket] = {}
        self._now: Callable[[], float] = clock if clock is not None else time.monotonic
        ip_refill = ip_budget_per_5s / 5.0
        ip_bucket = _Bucket(float(ip_budget_per_5s), ip_refill, now=self._now(), guard=self._guard)
        self._ip = _IpGate(ip_bucket)
        self._cap: _Bucket | None = None
        #: Read, never changed, by `headroom` for a bucket not made yet: it is made full.
        self._full = _Bucket(default_capacity, default_refill_per_s, now=0.0, guard=self._guard)

    def capped(self, per_5s: int) -> TokenBucketGovernor:
        """A view that shares this governor's IP bucket, hold and per-UID buckets and adds a
        cap of its own: `per_5s` acquisitions per five seconds across every UID it serves. A
        shallow copy, so a view holds every attribute the governor holds, shared, its lock too."""
        view = copy.copy(self)
        view._cap = _Bucket(float(per_5s), per_5s / 5.0, now=self._now(), guard=self._guard)
        return view

    def _get_bucket(self, uid: str, endpoint_class: EndpointClass) -> _Bucket:
        with self._guard:
            return self._bucket(uid, endpoint_class)

    def _bucket(self, uid: str, endpoint_class: EndpointClass) -> _Bucket:
        """The bucket of `(uid, endpoint_class)`, made full at its first use; under `_guard`."""
        key = (uid, endpoint_class)
        bucket = self._buckets.get(key)
        if bucket is None:
            bucket = _Bucket(
                self._default_capacity,
                self._default_refill_per_s,
                now=self._now(),
                guard=self._guard,
            )
            self._buckets[key] = bucket
        return bucket

    async def acquire(
        self,
        uid: str,
        endpoint_class: EndpointClass,
        *,
        lane: RateLane,
        deadline_s: float | None = None,
    ) -> None:
        """Wait until the view's cap (if any), the per-UID/endpoint-class bucket and the
        IP-wide bucket each have a spare token, then consume one from each. `lane` is
        accepted and served like any other until E34-T02. With `deadline_s`, a wait (a hold,
        and the queue behind other takers of a bucket, included) that would end later raises
        `RateBudgetExceededError`; a token taken before the refusal, or before the caller
        cancels the wait, cuts it with a timeout or anything else ends it, is given back, so
        nothing is spent on a request that is never sent."""
        limit = None if deadline_s is None else self._now() + max(0.0, deadline_s)
        await self._wait_ip_hold(limit)
        targets = [b for b in (self._cap, self._get_bucket(uid, endpoint_class)) if b is not None]
        taken: list[_Bucket] = []
        try:
            for target in (*targets, self._ip.bucket):
                await self._take(target, limit)
                taken.append(target)
        except GeneratorExit:
            raise  # ended by the collector, maybe inside a critical section: no lock (M-1)
        except BaseException:
            with self._guard:
                for bucket in taken:
                    bucket.tokens = min(bucket.capacity, bucket.tokens + 1.0)
            raise

    async def _take(self, target: _Bucket, limit: float | None) -> None:
        turn = target.lock
        await self._queue(turn, limit)
        head = _Head()
        try:
            while True:
                # A hold set while we queued on this lock must not be missed.
                await self._wait_ip_hold(limit)
                with self._guard:
                    now = self._now()
                    if self._ip.hold_until > now:
                        continue  # another loop set one since: wait it out first
                    if target.serve(head, now):
                        return
                    wait_s = target.wait_for(head)
                if limit is not None and now + wait_s > limit:
                    raise RateBudgetExceededError(
                        "no rate token within the lane's wait; nothing was sent",
                        retry_after_s=wait_s,
                    )
                await self._sleep(min(wait_s, _MAX_POLL_S))
        except GeneratorExit:
            raise  # as in `acquire`: its head and a handed token stay, an underspend
        except BaseException:
            with self._guard:  # a token handed to us meanwhile goes back too
                target.leave(head)
            raise
        finally:
            turn.release()

    async def _queue(self, turn: _Turn, limit: float | None) -> None:
        """Hold the bucket's lock, queued behind other takers for no longer than the deadline
        leaves (24 §8.7: the queue counts against the lane's wait). The bound runs on the event
        loop's clock, which is the monotonic clock this governor reads in production."""
        if limit is None:
            await turn.acquire()
            return
        try:
            async with asyncio.timeout(max(0.0, limit - self._now())):
                await turn.acquire()
        except TimeoutError:
            raise RateBudgetExceededError(
                "the rate bucket was busy past the lane's wait; nothing was sent"
            ) from None

    async def acquire_ip_only(self) -> None:
        """Wait for a spare token on the IP-wide bucket only, without
        touching any per-UID/endpoint-class bucket. Used by unauthenticated,
        unbudgeted-by-endpoint-class calls (e.g. the startup reachability
        probe) that must still respect the IP-wide ceiling (C-12.7)."""
        await self._wait_ip_hold(None)
        await self._take(self._ip.bucket, None)

    def hold_ip(self, duration_s: float) -> None:
        """Throttle every caller (all UIDs, all endpoint classes) for at least
        `duration_s` from now (`24-internal-schemas.md` §8.6, `10018`: IP-level
        backoff, all accounts throttled). Holds only ever extend, never shorten."""
        with self._guard:
            now = self._now()
            capped = min(max(0.0, duration_s), MAX_IP_HOLD_S)
            self._ip.hold_until = max(self._ip.hold_until, min(now + capped, now + MAX_IP_HOLD_S))
            bybit_ip_hold_remaining_seconds.set(self._ip.hold_until - now)

    def ip_hold_remaining_s(self) -> float:
        with self._guard:
            return max(0.0, self._ip.hold_until - self._now())

    async def _wait_ip_hold(self, limit: float | None) -> None:
        while (remaining := self.ip_hold_remaining_s()) > 0.0:
            if limit is not None and self._now() + remaining > limit:
                raise RateBudgetExceededError(
                    "an IP-level hold outlasts the lane's wait; nothing was sent",
                    retry_after_s=remaining,
                )
            await self._sleep(remaining)
        with self._guard:  # ended, unless another loop has set a new one since
            if 0.0 < self._ip.hold_until <= self._now():
                self._ip.hold_until = 0.0
                bybit_ip_hold_remaining_seconds.set(0.0)

    def headroom(
        self, uid: str, endpoint_class: EndpointClass, *, lane: RateLane
    ) -> tuple[float, float]:
        """`(tokens, wait_s)` for the next acquisition of `uid` on `endpoint_class` in `lane`:
        the spare tokens of the buckets it draws (the view's cap, the per-UID class bucket, the
        IP bucket), the fewest of them, and the seconds until it would hold a token of each, an
        IP hold included; `acquire` refuses it when that wait passes its deadline. Read without
        taking a token or changing a bucket (#2877 ruling 4); `lane` is served like any other
        until E34-T02, as in `acquire`."""
        with self._guard:
            now = self._now()
            bucket = self._buckets.get((uid, endpoint_class), self._full)
            draws = [b for b in (self._cap, bucket, self._ip.bucket) if b is not None]
            tokens = min(b.level(now) for b in draws)
            held_s = max(0.0, self._ip.hold_until - now)
            wait_s = max(held_s, *(b.wait_at(now) for b in draws))
        return tokens, wait_s

    def remaining(self, uid: str, endpoint_class: EndpointClass) -> float:
        with self._guard:
            bucket = self._bucket(uid, endpoint_class)
            bucket._refill(self._now())
            return bucket.tokens

    def observe_header(self, uid: str, endpoint_class: EndpointClass, remaining: int) -> None:
        """Feed `X-Bapi-Limit-Status` back into the local bucket so a
        server-side view of the budget wins over our own accounting drift
        (technical notes: "fed back from `X-Bapi-Limit-Status` / `X-Bapi-
        Limit` response headers"). The header is untrusted input: a figure
        below zero empties the bucket and no more, so one malformed answer
        cannot hold a UID's order class for longer than a refill."""
        with self._guard:
            bucket = self._bucket(uid, endpoint_class)
            bucket._refill(self._now())
            bucket.tokens = max(0.0, min(bucket.capacity, float(remaining)))

    def drain(self, uid: str, endpoint_class: EndpointClass, amount: float) -> None:
        """Account for budget consumed server-side that a `RateLimitError`
        response reports (acceptance criterion 3: "the bucket is drained by
        the advertised amount")."""
        with self._guard:
            bucket = self._bucket(uid, endpoint_class)
            bucket._refill(self._now())
            bucket.tokens = max(0.0, bucket.tokens - amount)

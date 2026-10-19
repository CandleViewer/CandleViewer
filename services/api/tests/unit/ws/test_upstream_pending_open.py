"""#2227: the acquirers of one upstream key share its open (`ws/upstream.py`, `UpstreamRefs`).

Every `acquire` returns only once the key's upstream is open. A failed open fails every acquire
that joined it and leaves no consumer; a joined acquire's cancellation leaves the open to the
others, and the opening acquire's cancels it. Pure asyncio: the sink's `open` is held on an event
and released or failed by the test, time is passed to `release` and `sweep`, and nothing waits on
a clock (`sleep(0)` is one scheduling turn)."""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Awaitable, Iterator
from typing import Any

import pytest

from candleviewer.auth.generated_permissions import Permission
from candleviewer.auth.scopes import PrincipalSnapshot
from candleviewer.observability.metrics_catalogue import CATALOGUE
from candleviewer.ws.errors import WsError
from candleviewer.ws.permissions import ConnectionAuthz, SubscriptionServices, handle_sub
from candleviewer.ws.topics import FAMILIES
from candleviewer.ws.upstream import (
    MAX_SYMBOL_LABELS,
    UpstreamKey,
    UpstreamOpenFailed,
    UpstreamRefs,
    cv_ws_upstream_consumers_in_use,
)

KEY: UpstreamKey = ("ZZPENDUSDT", "trades", ())
SERIES = ("ZZPENDUSDT", "trades")
PRINCIPAL = PrincipalSnapshot(
    uuid.UUID(int=0x2227), frozenset({"manager"}), frozenset({Permission.MARKETDATA_READ})
)


class _HeldSink:
    """An upstream whose `open` waits for `go`, then returns, or raises `fail` if it is set."""

    def __init__(self) -> None:
        self.entered, self.go = asyncio.Event(), asyncio.Event()
        self.fail: Exception | None = None
        self.opened: list[UpstreamKey] = []
        self.dropped: list[UpstreamKey] = []
        self.cancelled = 0

    async def open(self, key: UpstreamKey) -> None:
        self.opened.append(key)
        self.entered.set()
        try:
            await self.go.wait()
        except asyncio.CancelledError:
            self.cancelled += 1
            raise
        if self.fail is not None:
            raise self.fail

    async def drop(self, key: UpstreamKey) -> None:
        self.dropped.append(key)


@pytest.fixture(autouse=True)
def _clean_gauge() -> Iterator[None]:
    """The gauge is module-level: each test reads its own series only (as test_metric_labels)."""
    cv_ws_upstream_consumers_in_use.clear()
    yield
    cv_ws_upstream_consumers_in_use.clear()


def _series() -> dict[tuple[str, str], float]:
    return {
        (s.labels["symbol"], s.labels["topic"]): s.value
        for metric in cv_ws_upstream_consumers_in_use.collect()
        for s in metric.samples
    }


async def _within(awaitable: Awaitable[object]) -> None:
    """Await it, bounded: a regression that leaves it waiting fails the test, not the run."""
    async with asyncio.timeout(5):
        await awaitable


async def _opening(refs: UpstreamRefs, sink: _HeldSink) -> asyncio.Task[None]:
    """A's acquire of KEY, once it waits in the sink's `open` (bounded: 5 s)."""
    task = asyncio.create_task(refs.acquire(KEY, "A"))
    await _within(sink.entered.wait())
    return task


async def _joining(refs: UpstreamRefs, consumer: str) -> asyncio.Task[None]:
    """`consumer`'s acquire of KEY, once it has run up to its first suspension."""
    task = asyncio.create_task(refs.acquire(KEY, consumer))
    await asyncio.sleep(0)  # one scheduling turn, not a wait: the new task runs its first step
    return task


async def test_a_failed_open_fails_every_acquire_that_joined_it_and_leaves_no_consumer() -> None:
    """The bug: B's acquire joined A's pending open and returned at once, so when the open failed
    B held a reference to an upstream that never opened. Now both raise, B's chained to the
    sink's error, and no consumer, key or series is left."""
    sink = _HeldSink()
    refs = UpstreamRefs(sink)
    a = await _opening(refs, sink)
    b = await _joining(refs, "B")
    sink.fail = boom = RuntimeError("upstream down")
    sink.go.set()
    with pytest.raises(RuntimeError) as opener:
        await _within(a)
    with pytest.raises(UpstreamOpenFailed) as joined:
        await _within(b)
    assert opener.value is boom and joined.value.__cause__ is boom
    assert issubclass(UpstreamOpenFailed, WsError)  # the M23 domain base
    assert (refs.consumers(KEY), KEY in refs.active(), _series()) == (0, False, {})


async def test_a_joined_acquire_returns_only_once_the_open_completes() -> None:
    sink = _HeldSink()
    refs = UpstreamRefs(sink)
    a = await _opening(refs, sink)
    b = await _joining(refs, "B")
    assert not b.done() and refs.consumers(KEY) == 2  # it waits, counted
    sink.go.set()
    await _within(asyncio.gather(a, b))
    assert (refs.consumers(KEY), sink.opened, _series()) == (2, [KEY], {SERIES: 2.0})


async def test_a_cancelled_joined_acquire_leaves_at_once_and_the_open_goes_on() -> None:
    """B and C wait on A's open and B is cancelled: B alone leaves (as on `release`), its cancel
    propagates, and the open is neither cancelled nor failed for A and C."""
    sink = _HeldSink()
    refs = UpstreamRefs(sink)
    a = await _opening(refs, sink)
    b, c = await _joining(refs, "B"), await _joining(refs, "C")
    b.cancel()
    with pytest.raises(asyncio.CancelledError):
        await _within(b)
    assert (refs.consumers(KEY), _series()) == (2, {SERIES: 2.0})
    sink.go.set()
    await _within(asyncio.gather(a, c))
    assert (refs.consumers(KEY), sink.opened, sink.cancelled) == (2, [KEY], 0)


async def test_a_joined_acquire_cancelled_after_its_open_resolved_still_leaves() -> None:
    """B's cancel lands after A's open resolved but before B resumed: B must still leave."""
    sink = _HeldSink()
    refs = UpstreamRefs(sink)
    a = await _opening(refs, sink)
    b = await _joining(refs, "B")
    sink.go.set()
    await _within(a)
    assert not b.done()  # the open is resolved and B's wake-up is queued: B has not resumed
    b.cancel()
    with pytest.raises(asyncio.CancelledError):
        await _within(b)
    assert (refs.consumers(KEY), _series()) == (1, {SERIES: 1.0})


async def test_the_opening_acquire_s_cancel_cancels_the_open_and_fails_each_joined_one() -> None:
    """The choice `acquire` documents: the open runs in A's task, so cancelling A cancels the open,
    and B, which joined it, raises `UpstreamOpenFailed` from that cancel (B itself was not
    cancelled, so it gets no `CancelledError`). Nothing is left."""
    sink = _HeldSink()
    refs = UpstreamRefs(sink)
    a = await _opening(refs, sink)
    b = await _joining(refs, "B")
    a.cancel()
    with pytest.raises(asyncio.CancelledError):
        await _within(a)
    with pytest.raises(UpstreamOpenFailed) as joined:
        await _within(b)
    assert isinstance(joined.value.__cause__, asyncio.CancelledError)
    assert (sink.cancelled, refs.consumers(KEY), KEY in refs.active()) == (1, 0, False)
    assert _series() == {}


async def test_a_key_a_cancelled_acquire_left_empty_starts_its_grace_at_the_next_sweep() -> None:
    """A cancelled acquire has no `now` to start the grace with. A is released while its open is
    pending; B joins and is cancelled: once the open succeeds, the key has no consumer and no
    deadline. The first sweep starts its grace, and the key is dropped at its end."""
    sink = _HeldSink()
    refs = UpstreamRefs(sink, grace_s=30.0)
    a = await _opening(refs, sink)
    refs.release(KEY, "A", now=0.0)
    b = await _joining(refs, "B")
    b.cancel()
    with pytest.raises(asyncio.CancelledError):
        await _within(b)
    sink.go.set()
    await _within(a)
    assert [await refs.sweep(t) for t in (100.0, 129.9, 130.0)] == [[], [], [KEY]]
    assert (sink.dropped, refs.active()) == ([KEY], set())


async def test_a_release_during_the_open_leaves_at_once_and_the_key_opens_into_its_grace() -> None:
    """`release` while the open is pending: A leaves at once. `sweep` leaves the key alone while
    it opens, past its deadline too; once open, the key is in the grace its release started."""
    sink = _HeldSink()
    refs = UpstreamRefs(sink, grace_s=30.0)
    a = await _opening(refs, sink)
    refs.release(KEY, "A", now=5.0)
    assert (refs.consumers(KEY), _series()) == (0, {})
    assert await refs.sweep(35.0) == [] and KEY in refs.active()  # due, but still opening
    sink.go.set()
    await _within(a)
    assert (await refs.sweep(35.0), sink.dropped) == ([KEY], [KEY])


async def test_a_release_during_the_open_then_a_failed_open_leave_nothing() -> None:
    sink = _HeldSink()
    refs = UpstreamRefs(sink, grace_s=30.0)
    a = await _opening(refs, sink)
    refs.release(KEY, "A", now=5.0)
    assert await refs.sweep(35.0) == []  # due, but still opening
    sink.fail = RuntimeError("upstream down")
    sink.go.set()
    with pytest.raises(RuntimeError):
        await _within(a)
    assert (await refs.sweep(35.0), refs.active(), sink.dropped, _series()) == ([], set(), [], {})


async def test_two_sockets_subscribing_the_key_both_fail_when_its_shared_open_fails() -> None:
    """What a client saw: B's `sub` of the topic A's `sub` was opening answered `ok` at once and
    kept the key, though nothing would open it, so B got no data and its `unsub` released nothing.
    Now B's `sub` raises with A's (a raise closes the socket 1011, `handle_sub`): no `sub_ok` is
    sent, and neither subscription holds the key."""
    sink = _HeldSink()
    services = SubscriptionServices(upstream=UpstreamRefs(sink), clock=lambda: 0.0)
    a, b = ConnectionAuthz(PRINCIPAL, services), ConnectionAuthz(PRINCIPAL, services)
    sent: list[dict[str, Any]] = []

    async def send(frame: dict[str, Any]) -> None:
        sent.append(frame)

    frame = {"t": "sub", "id": "s1", "p": {"topics": ["trades.ZZPENDUSDT"]}}
    first = asyncio.create_task(handle_sub(a, frame, send))
    await _within(sink.entered.wait())
    second = asyncio.create_task(handle_sub(b, frame, send))
    await asyncio.sleep(0)  # one scheduling turn: B's `sub` reaches the shared open
    sink.fail = RuntimeError("upstream down")
    sink.go.set()
    with pytest.raises(RuntimeError):
        await _within(first)
    with pytest.raises(UpstreamOpenFailed):
        await _within(second)
    held = [s.upstream for conn in (a, b) for s in conn.by_id.values()]
    assert (sent, held) == ([], [(), ()])


async def test_a_failed_open_frees_its_symbol_label_for_the_next_symbol() -> None:
    sink = _HeldSink()
    refs = UpstreamRefs(sink)
    sink.fail = RuntimeError("upstream down")
    sink.go.set()  # no hold: each open fails at once
    for i in range(MAX_SYMBOL_LABELS):
        with pytest.raises(RuntimeError):
            await refs.acquire((f"ZZ{i:03d}USDT", "trades", ()), "c")
    sink.fail = None
    await refs.acquire(("ZZNEWUSDT", "trades", ()), "c")
    assert _series() == {("ZZNEWUSDT", "trades"): 1.0}  # its own label, not `other`


async def test_the_consumer_series_stay_within_the_catalogue_bound() -> None:
    """(#2227, item a) One series per symbol label and topic family: at most `MAX_SYMBOL_LABELS`
    symbols plus `other`, times each family whose subscriptions reach `acquire` (the public ones:
    replay and private subscriptions return before it, `ConnectionAuthz._upstream`). Counted from
    the registry, so a new public family that breaks the catalogue's `max_series` fails here."""
    (spec,) = [s for s in CATALOGUE if s.name == "cv_ws_upstream_consumers_in_use"]
    families = [f.family for f in FAMILIES.values() if not f.private]
    refs = UpstreamRefs()
    for family in families:
        for i in range(MAX_SYMBOL_LABELS + 3):
            await refs.acquire((f"ZZ{i:03d}USDT", family, ()), "c")
    assert len(_series()) == (MAX_SYMBOL_LABELS + 1) * len(families) <= spec.max_series

"""#913 L1d-2a: the adapter's private-stream tombstones, its bounded revoke close and the registry's
loop guard (24 §14.2 rule 13; SR-E27-17, KV-E13; RC-G8B-03, RC-G8B-04), on the real B13
interpreter, a fake venue and a virtual clock.

The adapter holds one `KeyTombstones` and shares it with every registry it builds, so a key closed
before any registry exists is refused by the first one, and a key one registry closed or marked is
refused by every other; `reopen_private_streams` needs no registry. `close_key` tombstones the key
itself before it awaits a close, and returns within `CLOSE_TIMEOUT_S` plus 1 s: past that it pages
and raises `PrivateStreamCloseOverran`, naming the streams still closing (`accounts`) and those it
closed in time (`closed`), while the close runs on; the adapter's call raises it as is, and a retry
names none of them. The registry serves the loop of the `open` that creates its first stream, so a
refused one binds no loop; another loop's `open` or `close_key` is refused before anything is
signed, dialled or closed, the first refusal of each window pages, and a revoke from another loop
still tombstones the key first. `ready()` counts what `__anext__` returns with no wait. RC-G8B-04: a
stream B13 ended is not named by a later `close_key`, and three refusals mark the key even when a
close queued first.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

import pytest
from structlog.testing import capture_logs

from candleviewer.exchange.base.errors import AuthError, ExchangeError
from candleviewer.exchange.base.models import AccountRef, PrivateStreamStatus
from candleviewer.exchange.bybit import private_stream as ps
from candleviewer.exchange.bybit.metrics import bybit_private_ws_disconnects_total
from candleviewer.exchange.bybit.service import ExchangeBybitService
from candleviewer.observability.context import spawn
from tests._signing import Call, fake_capability
from tests.chaos.ingestion._clock import VirtualClock
from tests.unit.exchange.bybit._private import linear_order, push
from tests.unit.exchange.bybit._private_venue import (
    REFUSED_AUTH,
    Consumer,
    PrivateVenue,
    VenueSocket,
    make_streams,
    until,
)
from tests.unit.exchange.bybit._trading import ACCOUNT_A, ACCOUNT_B, SIGNER_ID, account

NEW_KEY = "00000000-0000-4000-8000-0000000000c2"
#: `close_key`'s bound, as 24 §14.2 rule 13 states it.
BOUND_S = ps.CLOSE_TIMEOUT_S + 1.0


def _adapter(venue: PrivateVenue, calls: list[Call] | None = None) -> ExchangeBybitService:
    return ExchangeBybitService(
        fake_capability(SIGNER_ID, calls), private_ws_connect=venue.connect, environment="demo"
    )


def _ended(reason: str) -> float:
    value: float = bybit_private_ws_disconnects_total.labels(reason=reason)._value.get()
    return value


async def _next(stream: Any, count: int) -> list[str]:
    """The stream's next `count` items, each a status shown as `state:reason`."""
    seen: list[str] = []
    async with asyncio.timeout(5):  # a guard only: the chart reaches `live` with no clock
        for _ in range(count):
            item = await stream.__anext__()
            assert isinstance(item, PrivateStreamStatus)
            seen.append(f"{item.state}:{item.reason}")
    return seen


@pytest.mark.parametrize("reason", ["key_revoked", "key_rotated"])
async def test_a_key_closed_before_any_registry_is_refused_by_the_first_one(reason: Any) -> None:
    """RC-G8B-03: before any stream is opened the adapter has no registry, yet the close
    tombstones the key, so the first registry refuses it with nothing signed, dialled or
    reserved (for `key_rotated`, M2 would still sign the old key through the overlap)."""
    venue, calls = PrivateVenue(VirtualClock()), list[Call]()
    adapter = _adapter(venue, calls)
    assert await adapter.close_private_streams(account().key_ref, reason=reason) == ()
    budget = adapter.ws_connection_budget.remaining("private")
    with pytest.raises(AuthError):
        await adapter.trading_port("demo").subscribe_private(account())
    assert (calls, venue.dialled) == ([], [])
    assert adapter.ws_connection_budget.remaining("private") == budget
    await adapter.stop(5.0)


async def test_every_registry_over_the_adapters_table_refuses_its_closed_and_marked_keys() -> None:
    """RC-G8B-03: the table is the adapter's, shared by reference: a key one registry's three
    refusals marked, and a key the adapter closed while it had no registry, are refused by every
    registry over it. The mark stands until an operator's `reopen_private_streams`, which needs
    no registry; a closed key stays closed."""
    clock = VirtualClock()
    venue = PrivateVenue(clock)
    venue.auth.extend([REFUSED_AUTH] * ps.MAX_AUTH_REFUSALS)
    adapter = _adapter(venue)
    first = make_streams(venue, tombstones=adapter._tombstones)
    second = make_streams(venue, tombstones=adapter._tombstones)
    refused = Consumer(await first.open(account(), clock_offset_ms=lambda: 0))
    await until(clock, lambda: refused.task.done(), within_s=60, what="three refusals")
    await adapter.close_private_streams(NEW_KEY)  # the adapter has built no registry of its own
    for streams in (first, second):
        for key_ref in (account().key_ref, NEW_KEY):
            with pytest.raises(AuthError):
                await streams.open(account(ACCOUNT_B, key_ref=key_ref))
    assert adapter.reopen_private_streams(account().key_ref) is True
    assert adapter.reopen_private_streams(NEW_KEY) is False
    again = Consumer(await second.open(account(), clock_offset_ms=lambda: 0))
    await until(clock, lambda: len(again.statuses()) == 2, within_s=5, what="reopened")
    with pytest.raises(AuthError):
        await first.open(account(ACCOUNT_B, key_ref=NEW_KEY))
    await again.stop()
    for streams in (first, second):
        await streams.aclose()


@dataclass
class _StuckSocket(VenueSocket):
    """A socket whose read, once `stuck`, swallows its cancel and holds on until `release`: the
    session's reader never ends, so the stream's close cannot get to the socket."""

    stuck: bool = False
    release: asyncio.Event = field(default_factory=asyncio.Event)

    async def recv(self, max_bytes: int) -> str:
        try:
            return await super().recv(max_bytes)
        except asyncio.CancelledError:
            if not self.stuck:
                raise
        await self.release.wait()
        raise ConnectionResetError("released")


@dataclass
class _StuckVenue(PrivateVenue):
    async def connect(self, url: str) -> VenueSocket:
        self.dialled.append(url)
        sock = _StuckSocket(self, url)
        self.sockets.append(sock)
        return sock


async def test_a_revoke_whose_close_overruns_pages_raises_and_still_closes() -> None:
    """Q6 (RC-G8B-03): a close held past `CLOSE_TIMEOUT_S` plus 1 s pages once (CRITICAL,
    `cv_page`, ids only), and the adapter's `close_private_streams` raises
    `PrivateStreamCloseOverran` to its caller as raised, unwrapped: a bare `TimeoutError` with a
    fixed text, no `ExchangeError`, naming the account still closing and none closed in time.
    The close runs on: a retry waits for the same close and names no account, so the overrun's
    `accounts` is the audit's source for it;
    once the close finishes the socket is closed and `closed(key_revoked)` is the last item."""
    clock = VirtualClock()
    venue = _StuckVenue(clock)
    adapter = _adapter(venue)
    # the adapter's one registry, over its table, on the virtual clock
    adapter._private_streams = make_streams(venue, tombstones=adapter._tombstones)
    consumer = Consumer(await adapter.open_private_stream(account()))
    await until(clock, lambda: len(consumer.statuses()) == 2, within_s=5, what="live")
    sock = venue.sockets[0]
    assert isinstance(sock, _StuckSocket)
    sock.stuck = True
    with capture_logs() as logs:
        revoke = spawn(adapter.close_private_streams(account().key_ref), name="revoke")
        await clock.advance(BOUND_S - 0.1)
        assert not revoke.done()
        await clock.advance(0.2)
        assert revoke.done()
    with pytest.raises(TimeoutError) as overran:
        revoke.result()
    assert type(overran.value) is ps.PrivateStreamCloseOverran  # no boundary wraps it
    assert not isinstance(overran.value, ExchangeError)
    assert (overran.value.accounts, overran.value.closed) == ((ACCOUNT_A,), ())
    assert str(overran.value) == "the key's private streams are still closing"
    # bare, as the open's refusals (SR-E29-08): nothing chained, no context shown
    assert overran.value.__cause__ is None and overran.value.__context__ is None
    assert overran.value.__suppress_context__
    pages = [e for e in logs if e["event"] == "bybit_private_key_close_overran"]
    assert pages == [
        {
            "event": "bybit_private_key_close_overran",
            "log_level": "critical",
            "cv_page": True,
            "reason": "key_revoked",
            "accounts": [str(ACCOUNT_A)],
        }
    ]
    assert account().key_ref not in repr(logs) and not sock.closed
    retry = spawn(adapter.close_private_streams(account().key_ref), name="retry")
    await clock.settle()
    sock.release.set()
    await clock.advance(ps.CLOSE_TIMEOUT_S)
    assert retry.done() and retry.result() == ()
    assert sock.closed and consumer.statuses()[-1] == "closed:key_revoked:1"
    await adapter.stop(5.0)


async def test_an_overrun_names_the_stream_it_closed_in_time_beside_the_one_still_closing() -> None:
    """24 §14.2 rule 13: the overrun's `accounts` names the streams still closing and its `closed`
    the ones the call closed in time, so together they name every stream whose close the call
    started. The call returns none of them and a retry names none, so the audit reads both: a
    stream closed in time is named there or nowhere. Production keeps one stream per key; the
    rule does not lean on it."""
    clock = VirtualClock()
    venue = _StuckVenue(clock)
    streams = make_streams(venue)
    first = Consumer(await streams.open(account()))
    await until(clock, lambda: len(first.statuses()) == 2, within_s=5, what="first live")
    second = Consumer(await streams.open(account(ACCOUNT_B)))  # the same key
    await until(clock, lambda: len(second.statuses()) == 2, within_s=5, what="second live")
    held = venue.sockets[1]
    assert isinstance(held, _StuckSocket)
    held.stuck = True
    revoke = spawn(streams.close_key(account().key_ref, reason="key_revoked"), name="revoke")
    await clock.advance(BOUND_S + 0.1)
    assert venue.sockets[0].closed and first.statuses()[-1] == "closed:key_revoked:1"
    assert revoke.done() and not held.closed
    with pytest.raises(ps.PrivateStreamCloseOverran) as overran:
        revoke.result()
    assert (overran.value.closed, overran.value.accounts) == ((ACCOUNT_A,), (ACCOUNT_B,))
    retry = spawn(streams.close_key(account().key_ref, reason="key_revoked"), name="retry")
    await clock.settle()
    held.release.set()
    await clock.advance(ps.CLOSE_TIMEOUT_S)
    assert retry.done() and retry.result() == ()
    assert held.closed and second.statuses()[-1] == "closed:key_revoked:1"
    await streams.aclose()


async def test_a_stuck_close_refuses_a_stream_on_its_key_with_no_adapter_ahead_of_it() -> None:
    """24 §14.2 rule 13: the registry itself tombstones the key before it awaits any close, so
    while one is stuck a stream on that key is refused (`AuthError`) with nothing dialled, with
    no adapter writing the tombstone ahead of it."""
    clock = VirtualClock()
    venue = _StuckVenue(clock)
    streams = make_streams(venue)
    consumer = Consumer(await streams.open(account()))
    await until(clock, lambda: len(consumer.statuses()) == 2, within_s=5, what="live")
    sock = venue.sockets[0]
    assert isinstance(sock, _StuckSocket)
    sock.stuck = True
    revoke = spawn(streams.close_key(account().key_ref, reason="key_revoked"), name="revoke")
    await clock.settle()
    assert not revoke.done()
    with pytest.raises(AuthError):
        await streams.open(account(ACCOUNT_B))
    assert len(venue.dialled) == 1
    sock.release.set()
    await clock.advance(ps.CLOSE_TIMEOUT_S)
    assert revoke.done() and revoke.result() == (ACCOUNT_A,)
    await streams.aclose()


async def _elsewhere(work: Callable[[], Awaitable[Any]]) -> str:
    """`work()` on an event loop of its own, in another thread: its refusal's text, or `ran`."""

    async def run() -> str:
        try:
            await work()
        except RuntimeError as refused:
            return str(refused)
        return "ran"

    return await asyncio.to_thread(asyncio.run, run())


async def test_the_registry_refuses_an_open_from_another_loop_before_anything_is_signed() -> None:
    """Q5 (D6): the registry serves the loop of the `open` that created its first stream. An `open`
    or a `close_key` from any other loop is refused (`RuntimeError`) before anything is signed,
    dialled, built or closed, so a mis-wiring never reaches M2's binding (whose refusal would mark
    the key) and never leaves a stream half closed; the first refusal of the window pages."""
    clock, calls = VirtualClock(), list[Call]()
    venue = PrivateVenue(clock)
    streams = make_streams(venue, calls=calls)
    consumer = Consumer(await streams.open(account()))
    await until(clock, lambda: len(consumer.statuses()) == 2, within_s=5, what="live")
    before = (len(calls), list(venue.dialled), streams.count())
    with capture_logs() as logs:
        opened = await _elsewhere(lambda: streams.open(account(ACCOUNT_B, key_ref=NEW_KEY)))
        assert opened == "the private streams serve another event loop"
        closed = await _elsewhere(
            lambda: streams.close_key(account().key_ref, reason="key_revoked")
        )
        assert closed == "the private streams serve another event loop"
    assert (len(calls), venue.dialled, streams.count()) == before
    assert not venue.sockets[0].closed and not streams.tombstones.refuses(account().key_ref)
    assert [(e["event"], e["log_level"], e.get("cv_page")) for e in logs] == [
        ("bybit_private_streams_wrong_loop", "critical", True)
    ]
    await consumer.stop()
    await streams.aclose()


async def test_the_registry_pages_the_first_wrong_loop_refusal_of_each_window() -> None:
    """D6, as L2a-1's writer (CR-S3L2-08): every call from another loop is refused, and only the
    first refusal of each `WRONG_LOOP_PAGE_S` window on the registry's clock pages. A window opens
    at the refusal that paged, and a clock stepped back reads as expired."""
    clock = VirtualClock()
    venue = PrivateVenue(clock)
    streams = make_streams(venue)
    stream = await streams.open(account())  # binds this loop
    pages = list[int]()
    for at in (0.0, 4.0, 6.0, 10.0, 1.0):
        clock.now = at
        with capture_logs() as logs:
            refused = await _elsewhere(lambda: streams.open(account(ACCOUNT_B, key_ref=NEW_KEY)))
        assert refused == "the private streams serve another event loop"
        pages.append(len([e for e in logs if e["event"] == "bybit_private_streams_wrong_loop"]))
    assert pages == [1, 0, 1, 0, 1]
    await stream.aclose()
    await streams.aclose()


async def test_a_revoke_from_another_loop_tombstones_first_and_its_retry_closes() -> None:
    """24 §14.2 rule 13 (D6, RC-G8B-03): `close_private_streams` from any loop but the
    registry's writes the key's tombstone first, in the adapter, then raises `RuntimeError`, not
    a `TimeoutError`: any exception means the close is not done. The socket stays open and the
    call pages once, and a stream on the key is refused at once, with nothing signed or dialled.
    A retry on the registry's loop closes the socket and names the account, whose close it
    started, with `closed(key_revoked)` the stream's last item."""
    venue, calls = PrivateVenue(VirtualClock()), list[Call]()
    adapter = _adapter(venue, calls)
    stream = await adapter.open_private_stream(account())
    assert await _next(stream, 2) == ["heartbeat:evidence", "resyncing:connected"]
    signed, dialled = len(calls), list(venue.dialled)
    with capture_logs() as logs:
        refused = await _elsewhere(lambda: adapter.close_private_streams(account().key_ref))
        assert refused == "the private streams serve another event loop"
        assert not venue.sockets[0].closed
        with pytest.raises(AuthError):  # the same key: tombstoned by the refused call itself
            await adapter.open_private_stream(account(ACCOUNT_B))
        assert (len(calls), venue.dialled) == (signed, dialled)
        assert await adapter.close_private_streams(account().key_ref) == (ACCOUNT_A,)
    assert venue.sockets[0].closed and await _next(stream, 1) == ["closed:key_revoked"]
    pages = [e for e in logs if e["event"] == "bybit_private_streams_wrong_loop"]
    assert [(e["log_level"], e.get("cv_page")) for e in pages] == [("critical", True)]
    await stream.aclose()
    await adapter.stop(5.0)


@pytest.mark.parametrize(
    ("first", "refusal"),
    [
        (account(ACCOUNT_B, environment="live"), ValueError),
        (account(ACCOUNT_B, key_ref=NEW_KEY), AuthError),
    ],
    ids=["another-environment", "closed-key"],
)
async def test_a_refused_first_open_from_another_loop_binds_no_loop(
    first: AccountRef, refusal: type[Exception]
) -> None:
    """Q5 (D6): the registry takes the loop of the `open` that creates its first stream, after
    every refusal, so a first open from another loop refused for its own reason (another
    environment's account, a closed key) binds nothing and pages nothing: the serving loop then
    opens, reaches `live` and closes as before. Once bound, the loop check still comes first: the
    same open from another loop is refused as off the registry's loop."""
    clock = VirtualClock()
    venue = PrivateVenue(clock)
    streams = make_streams(venue)
    assert await streams.close_key(NEW_KEY, reason="key_revoked") == ()  # binds nothing either
    with capture_logs() as logs:
        with pytest.raises(refusal):
            await _elsewhere(lambda: streams.open(first))
        assert venue.dialled == []
        consumer = Consumer(await streams.open(account()))
        await until(clock, lambda: len(consumer.statuses()) == 2, within_s=5, what="live")
        refused = await _elsewhere(lambda: streams.open(first))
        assert refused == "the private streams serve another event loop"
    pages = [e for e in logs if e["event"] == "bybit_private_streams_wrong_loop"]
    assert len(pages) == 1  # the open after the bind; the refused first one paged nothing
    assert await streams.close_key(account().key_ref, reason="key_revoked") == (ACCOUNT_A,)
    await consumer.stop()
    await streams.aclose()


async def test_ready_counts_the_items_anext_returns_without_waiting() -> None:
    """L1d-2b's hop takes a batch: the stream's next items that are already queued, in arrival
    order, each returned at once; none once the stream is done."""
    clock = VirtualClock()
    venue = PrivateVenue(clock)
    streams = make_streams(venue)
    stream = await streams.open(account())
    assert isinstance(stream, ps._Stream)
    assert stream.ready() == 0
    await until(clock, lambda: stream.ready() == 2, within_s=5, what="live")
    venue.socket.push(push("order.linear", linear_order(), linear_order()))
    await clock.settle()
    assert stream.ready() == 4
    async with asyncio.timeout(5):  # a guard only: each read returns at once
        shown = [type(await stream.__anext__()).__name__ for _ in range(4)]
    assert shown == ["PrivateStreamStatus"] * 2 + ["PrivateEvent"] * 2
    assert stream.ready() == 0
    venue.socket.push(push("order.linear", linear_order()))
    await clock.settle()
    assert stream.ready() == 1
    await stream.aclose()
    assert stream.ready() == 0
    await streams.aclose()


async def test_a_stream_b13_ended_is_not_named_by_a_later_close_key() -> None:
    """RC-G8B-04: three refusals end the stream on B13's own edge; until its consumer reads
    `closed(auth_refused)` the registry still holds it, and a revoke of its key then names no
    account (E27-S04 audits what the revoke closed), and leaves that item last."""
    clock = VirtualClock()
    venue = PrivateVenue(clock)
    venue.auth.extend([REFUSED_AUTH] * ps.MAX_AUTH_REFUSALS)
    streams = make_streams(venue)
    ended = _ended("auth_refused")
    stream = await streams.open(account(), clock_offset_ms=lambda: 0)  # nobody reads it yet
    await until(clock, lambda: _ended("auth_refused") == ended + 1, within_s=60, what="ended")
    assert streams.count() == 1
    assert await streams.close_key(account().key_ref, reason="key_revoked") == ()
    async with asyncio.timeout(5):  # a guard only
        items = [item async for item in stream]
    assert [(i.state, i.reason) for i in items if isinstance(i, PrivateStreamStatus)] == [
        ("closed", "auth_refused")
    ]
    await streams.aclose()


async def test_three_refusals_mark_the_key_even_when_a_close_queued_first() -> None:
    """RC-G8B-04: the consumer's close lands as the third refusal arrives, and its `_end` runs
    before B13's, queueing no `closed` (the consumer reads nothing more); the key is marked all
    the same, so the next stream on it is refused."""
    clock = VirtualClock()
    venue = PrivateVenue(clock)
    venue.auth.extend([REFUSED_AUTH, REFUSED_AUTH, None])  # the third reply is the test's
    streams = make_streams(venue)
    stream = await streams.open(account(), clock_offset_ms=lambda: 0)
    await until(clock, lambda: len(venue.sent("auth")) == 3, within_s=60, what="third auth")
    venue.socket.push(REFUSED_AUTH)
    closing = spawn(stream.aclose(), name="consumer-close")
    await clock.settle()
    assert closing.done()
    with pytest.raises(AuthError):
        await streams.open(account())
    await streams.aclose()

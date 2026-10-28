"""#913 L1d-2b (E29-T04; 20-architecture.md Sec.6.2, ruling Q2 (b)): the order lane's private
streams across its bridge (`oms_streams.LaneStreams`). Each runs on a real order lane
(`oms_lane.OrderLane`) whose serving loop is this test's, through `oms_lane.Serving`, over the
adapter's own registry (`PrivateStreams`) and the fake venue (`PrivateVenue`): the registry on the
chaos suite's virtual clock, and the lane's own bounds on a loop whose clock moves only when a test
advances it (`LaneClock`). A stalled serving loop is one blocked on an event, a wedged lane one
whose thread is; each wait on another thread is a bound on the test, never a time it expects
(C-13.7). Those cross-thread waits (`BOUND_S`) are a stated exception to 03 Sec.14's rule: the
suite's timeout interrupts only the main thread, so a lane thread blocked on an event, or a
`finally` that must stop the lane, needs a bound of its own. No network (C-13.5)."""

from __future__ import annotations

import ast
import asyncio
import contextlib
import threading
from collections.abc import AsyncIterator, Callable, Coroutine
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest
from structlog.testing import capture_logs

from candleviewer.domain.primitives import AccountId
from candleviewer.exchange.base.models import AccountRef, PrivateEvent, PrivateStreamStatus
from candleviewer.exchange.base.ports import PrivateStream
from candleviewer.exchange.bybit import private_stream as ps
from candleviewer.exchange.bybit.private_stream import (
    CLOSE_TIMEOUT_S,
    DATA_SLOTS,
    KEY_CLOSE_BOUND_S,
    PrivateStreams,
)
from candleviewer.exchange.bybit.service import ExchangeBybitService
from candleviewer.observability.metrics import Metrics
from candleviewer.oms import config as oms_config
from candleviewer.oms.config import HOP_BATCH, STREAM_CLOSE_BOUND_S, STREAM_READ_BOUND_S
from candleviewer.oms.stream_consumer import STREAM_SILENCE_S
from candleviewer.oms_lane import HOP_TIMEOUT_S, OrderLane, Serving
from candleviewer.oms_streams import LaneStreams
from candleviewer.secrets import CredentialBorrower, Purpose, RequestSignature
from candleviewer.secrets.signing import SigningMessage
from candleviewer.statechart import build
from tests._signing import Call, fake_capability
from tests.chaos.ingestion._clock import VirtualClock
from tests.unit.exchange.bybit._private import push, row
from tests.unit.exchange.bybit._private_venue import PrivateVenue, VenueSocket, make_streams, until
from tests.unit.exchange.bybit._trading import ACCOUNT_A, ACCOUNT_B, SIGNER_ID, account
from tests.unit.oms.test_order_lane import BOUND_S, running
from tests.unit.test_oms_stream_wiring import World as StreamWiringWorld

type Item = PrivateEvent | PrivateStreamStatus
type OffsetReader = Callable[[], int | None] | None


class LaneClock:
    """The order lane's clock for the bridge's own bounds: its loop's `time()`, which moves only
    when a test advances it (`now`), from the lane's own thread."""

    def __init__(self) -> None:
        self.now = 0.0

    def loop(self) -> asyncio.AbstractEventLoop:
        return _OnLaneClock(self)


class _OnLaneClock(asyncio.SelectorEventLoop):
    def __init__(self, clock: LaneClock) -> None:
        super().__init__()
        self._clock = clock

    def time(self) -> float:
        return self._clock.now


@pytest.fixture
def lane_clock(monkeypatch: pytest.MonkeyPatch) -> LaneClock:
    """Each lane the test starts runs on a `LaneClock`."""
    clock = LaneClock()
    monkeypatch.setattr(OrderLane, "loop_factory", staticmethod(clock.loop))
    return clock


class Hops(Serving):
    """`Serving`, noting each awaited call by its coroutine's name and each read's batch."""

    def __init__(self, loop: asyncio.AbstractEventLoop, metrics: Metrics) -> None:
        super().__init__(loop, metrics)
        self.calls: list[str] = []
        self.batches: list[list[str]] = []

    async def call[T](self, coro: Coroutine[Any, Any, T], *, timeout_s: float = HOP_TIMEOUT_S) -> T:
        name = getattr(coro, "__qualname__", "?")
        self.calls.append(name)
        answer = await super().call(coro, timeout_s=timeout_s)
        if name == "_take" and isinstance(answer, tuple):
            self.batches.append([shown(item) for item in answer])
        return answer


class Rig:
    """The serving loop's side: the adapter's registry over the fake venue on its virtual clock,
    the way back to this loop, and the bridge over the registry's `open`, as the adapter's
    `open_private_stream` runs it."""

    def __init__(self) -> None:
        self.clock = VirtualClock()
        self.venue = PrivateVenue(self.clock)
        self.streams: PrivateStreams = make_streams(self.venue)
        self.serving = Hops(asyncio.get_running_loop(), Metrics("demo"))
        self.bridge = LaneStreams(self.streams.open, self.serving)

    def pending(self, account_id: AccountId = ACCOUNT_A) -> int:
        """The items the account's stream has queued in the adapter, not yet taken."""
        return self.streams._conns[account_id].queue.pending()

    async def live(self, *accounts: AccountId) -> None:
        """Until each stream has queued its first epoch's `heartbeat` and `resyncing`."""
        for account_id in accounts or (ACCOUNT_A,):
            await until(
                self.clock, lambda a=account_id: self.pending(a) == 2, within_s=5, what="live"
            )


def shown(item: Item) -> str:
    """A status as `state:reason:epoch`, an event as `kind:seq`."""
    if isinstance(item, PrivateStreamStatus):
        return f"{item.state}:{item.reason}:{item.epoch}"
    return f"{item.kind}:{item.seq}"


def rows(seqs: range) -> list[dict[str, Any]]:
    """Position rows, told apart by their `seq`."""
    return [row("position") | {"seq": seq} for seq in seqs]


def positions(seqs: range) -> list[str]:
    return [f"position:{seq}" for seq in seqs]


async def turns() -> None:
    """A few turns of the running loop, so what it has queued runs."""
    for _ in range(8):
        await asyncio.sleep(0)


async def read(stream: PrivateStream, count: int) -> list[str]:
    """On the lane: `count` items, in the order the stream yields them."""
    return [shown(await anext(stream)) for _ in range(count)]


async def read_all(stream: PrivateStream) -> list[str]:
    """On the lane: every item until the stream ends."""
    return [shown(item) async for item in stream]


async def on_lane() -> threading.Thread:
    return threading.current_thread()


def batch_held(stream: PrivateStream) -> int:
    """The items a lane stream holds that its consumer has not taken."""
    held: Any = stream
    return len(held._batch)


async def lane_holds(stream: PrivateStream) -> int:
    return batch_held(stream)


def _signer(calls: list[Call], threads: list[threading.Thread]) -> CredentialBorrower:
    """The adapter's M2 double, noting the thread each signature is asked on."""
    inner = fake_capability(SIGNER_ID, calls)

    async def sign(key_id: UUID, message: SigningMessage, purpose: Purpose) -> RequestSignature:
        threads.append(threading.current_thread())
        return await inner.sign(key_id, message, purpose=purpose)

    return CredentialBorrower(sign)


@asynccontextmanager
async def wedged(lane: OrderLane) -> AsyncIterator[None]:
    """The lane's thread blocked on an event until the block's end."""
    began, release = threading.Event(), threading.Event()

    async def blocks() -> None:
        began.set()
        release.wait(BOUND_S)

    held = lane.call(blocks())
    assert await asyncio.to_thread(began.wait, BOUND_S)
    try:
        yield
    finally:
        release.set()
        await held


# --- the bounds, from the code's own constants ---------------------------------------------------


def test_a_hop_carries_64_items_at_most_and_a_read_outlives_the_consumers_silence() -> None:
    """The orchestrator's ruling of 2026-10-26 16:50Z: `HOP_BATCH` is 64, a named constant, no
    setting; a read's hop is cut at 120 s, finite (C-2.18) and above the consumer's 30 s silence
    bound, its default and the one S8b's composition gives it (`build_stream_consumer`), so it
    never cuts an idle read; the lane waits for a close as long as a revoke waits for the adapter's
    own (`CLOSE_TIMEOUT_S` plus 1 s)."""
    assert HOP_BATCH == 64 and HOP_BATCH * 32 == DATA_SLOTS
    assert STREAM_READ_BOUND_S == 120.0 > STREAM_SILENCE_S
    assert STREAM_READ_BOUND_S > StreamWiringWorld().build().consumer._silence_s
    assert STREAM_CLOSE_BOUND_S == CLOSE_TIMEOUT_S + 1.0 == KEY_CLOSE_BOUND_S


def test_the_bounds_module_imports_nothing_but_typing() -> None:
    """Fable N-2 (C-2.20): `oms/config.py`, which the bridge on the hot-path contract reads, is a
    leaf of constants: it imports nothing but `__future__` and `typing`, so no setting or other
    module joins that contract's graph through it."""
    tree = ast.parse(Path(oms_config.__file__).read_text(encoding="utf-8"))
    imports = [node for node in ast.walk(tree) if isinstance(node, ast.Import | ast.ImportFrom)]
    assert {getattr(node, "module", None) for node in imports} <= {"__future__", "typing"}


# --- R11, R21: the lane's port over the adapter --------------------------------------------------


@pytest.mark.parametrize("kind", ["asyncio", "uvloop"])
async def test_a_stream_the_lane_port_opens_is_dialled_and_signed_on_the_serving_loop(
    kind: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """R11 (ruling Q2 (b), C-2.9): the lane's port opens through the bridge, so the adapter's one
    registry binds the serving loop, never the lane's, and dials, builds B13 (lane `platform`) and
    signs each dial's `auth` there, through the adapter's own borrower, never the lane's
    `LoopSigning`; it reads the port's offset snapshot, on that thread too; and the items reach
    the lane in arrival order. Run on a lane of asyncio's loop and of uvloop's."""
    if kind == "uvloop":
        new_loop = pytest.importorskip("uvloop").new_event_loop
        monkeypatch.setattr(OrderLane, "loop_factory", staticmethod(new_loop))
    venue, calls, lane_calls = PrivateVenue(VirtualClock()), list[Call](), list[Call]()
    signed, dialled, offsets = list[threading.Thread](), list[threading.Thread](), []
    built: list[tuple[str, str, threading.Thread]] = []

    async def connect(url: str) -> VenueSocket:
        dialled.append(threading.current_thread())
        return await venue.connect(url)

    async def spied(machine_key: str, **kwargs: Any) -> Any:
        built.append((machine_key, kwargs["lane"], threading.current_thread()))
        return await build(machine_key, **kwargs)

    def offset() -> int | None:  # the port's snapshot reader: a read that changes nothing
        offsets.append(threading.current_thread())
        return None

    monkeypatch.setattr(ps, "build", spied)
    adapter = ExchangeBybitService(
        _signer(calls, signed), private_ws_connect=connect, environment="demo"
    )
    bridge = LaneStreams(
        adapter.open_private_stream, Serving(asyncio.get_running_loop(), Metrics("demo"))
    )
    port = adapter.lane_trading_port(
        "demo", credentials=fake_capability(SIGNER_ID, lane_calls), clock_offset_ms=offset,
        private_streams=bridge,
    )  # fmt: skip
    here = threading.current_thread()
    async with running() as lane:
        stream = await lane.call(port.subscribe_private(account()))
        assert await lane.call(read(stream, 2)) == ["heartbeat:evidence:1", "resyncing:connected:1"]
        venue.socket.push(push("position.linear", *rows(range(3))))
        assert await lane.call(read(stream, 3)) == positions(range(3))
        registry = adapter._private_streams
        assert registry is not None and registry._loop is asyncio.get_running_loop()
        assert registry._conns[ACCOUNT_A]._offset is offset
        assert (await lane.call(on_lane())) is not here
        await lane.call(stream.aclose())
        await lane.call(port.aclose())
    assert ([c[2] for c in calls], signed, lane_calls) == (["sign_ws_auth"], [here], [])
    assert built == [("ws_conn", "platform", here)] and dialled == [here]
    assert offsets and set(offsets) == {here}
    assert venue.socket.closed
    await adapter.stop(5.0)


async def test_another_environments_account_is_refused_with_no_hop() -> None:
    """R21 (C-2.11): the lane's port refuses an account of another environment on the lane, before
    anything crosses: no hop, nothing dialled or signed."""
    venue, calls = PrivateVenue(VirtualClock()), list[Call]()
    adapter = ExchangeBybitService(
        fake_capability(SIGNER_ID, calls), private_ws_connect=venue.connect, environment="demo"
    )
    serving = Hops(asyncio.get_running_loop(), Metrics("demo"))
    port = adapter.lane_trading_port(
        "demo", credentials=fake_capability(SIGNER_ID), private_streams=LaneStreams(
            adapter.open_private_stream, serving
        ),
    )  # fmt: skip
    async with running() as lane:
        with pytest.raises(ValueError, match="another environment"):
            await lane.call(port.subscribe_private(account(environment="live")))
    assert (serving.calls, venue.dialled, calls) == ([], [], [])
    assert adapter._private_streams is None  # no registry was even built
    await adapter.stop(5.0)


# --- R12, R13: one batch at a time, in order ------------------------------------------------------


async def test_the_hop_holds_one_batch_and_the_adapters_queue_the_rest() -> None:
    """R12 (C-2.18): while the consumer does not read, the lane holds one batch at most, the rest
    waits in the adapter's queue; past its 2,048 events an event ends the epoch, announced as
    `down(slow_consumer)` after the last row it kept, nothing dropped silently, and the next
    epoch's `resyncing` makes the consumer reconcile."""
    rig = Rig()
    async with running() as lane:
        stream = await lane.call(rig.bridge.open(account()))
        await rig.live()
        rig.venue.socket.push(push("position.linear", *rows(range(1000))))
        await rig.clock.advance(0)
        assert await lane.call(read(stream, 1)) == ["heartbeat:evidence:1"]
        assert await lane.call(lane_holds(stream)) == HOP_BATCH - 1  # one hop, one batch
        assert rig.pending() == 1002 - HOP_BATCH  # the rest is the adapter's
        frames = [push("position.linear", *rows(range(n, n + 1000))) for n in (1000, 2000)]
        rig.venue.socket.push(*frames)  # 2,938 events queued: the last frame does not fit
        await rig.clock.advance(0)
        assert await lane.call(lane_holds(stream)) == HOP_BATCH - 1  # no read, no hop
        assert rig.pending() == 1002 - HOP_BATCH + 1000 + 1  # the second frame and the `down`
        assert rig.serving.calls.count("_take") == 1
        epoch = await lane.call(read(stream, 1 + 2000 + 1))
        assert epoch == ["resyncing:connected:1", *positions(range(2000)), "down:slow_consumer:1"]
        await until(rig.clock, lambda: rig.pending() == 2, within_s=60, what="the next epoch")
        again = await lane.call(read(stream, 2))
        assert again == ["heartbeat:evidence:2", "resyncing:reconnected:2"]
        await lane.call(stream.aclose())
    assert all(len(batch) <= HOP_BATCH for batch in rig.serving.batches)
    await rig.streams.aclose()


async def test_a_thousand_row_frame_crosses_in_order_in_batches_of_64() -> None:
    """R13: the rows of one 1,000-row frame cross in 16 hops (a spy on `Serving.call`), each
    batch every item already queued, at most 64, in arrival order."""
    rig = Rig()
    async with running() as lane:
        stream = await lane.call(rig.bridge.open(account()))
        await rig.live()
        assert await lane.call(read(stream, 2)) == ["heartbeat:evidence:1", "resyncing:connected:1"]
        rig.serving.batches.clear()
        rig.venue.socket.push(push("position.linear", *rows(range(1000))))
        await rig.clock.advance(0)
        assert await lane.call(read(stream, 1000)) == positions(range(1000))
        await lane.call(stream.aclose())
    sizes = [len(batch) for batch in rig.serving.batches]
    assert sizes == [HOP_BATCH] * 15 + [1000 - 15 * HOP_BATCH]
    assert [item for batch in rig.serving.batches for item in batch] == positions(range(1000))
    await rig.streams.aclose()


async def test_a_batch_ends_at_its_epochs_down_and_the_next_epoch_crosses_after_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """R13, its epochs (24 Sec.14.2 rule 13): a batch takes those behind its first item in the
    turn its await returns, so it never runs past a `down` into the next epoch, whose dial needs
    awaits: once the hop has taken the epoch, the next one dials and queues its own statuses, none
    taken. Each status keeps its place, `resyncing` ahead of its epoch's rows and `down` after the
    last of them, and a `down` ends its batch."""
    rig, entered = Rig(), entered_reads(monkeypatch)
    async with running() as lane:
        stream = await lane.call(rig.bridge.open(account()))
        await rig.live()
        rig.venue.socket.push(push("position.linear", *rows(range(10))))
        await rig.clock.advance(0)
        rig.venue.socket.drop()  # the socket ends: its epoch's `down` follows its last row
        await rig.clock.advance(0)
        reading = lane.call(read(stream, 2 + 10 + 1))
        assert await asyncio.to_thread(entered.wait, BOUND_S)  # the hop has begun its take
        await until(rig.clock, lambda: rig.pending() == 2, within_s=60, what="the next epoch")
        assert await reading == [
            "heartbeat:evidence:1", "resyncing:connected:1", *positions(range(10)),
            "down:socket_closed:1",
        ]  # fmt: skip
        rig.venue.socket.push(push("position.linear", *rows(range(10, 110))))
        await rig.clock.advance(0)
        second = await lane.call(read(stream, 2 + 100))
        assert second == [
            "heartbeat:evidence:2",
            "resyncing:reconnected:2",
            *positions(range(10, 110)),
        ]
        await lane.call(stream.aclose())
    for batch in rig.serving.batches:
        downs = [n for n, item in enumerate(batch) if item.startswith("down:")]
        assert downs in ([], [len(batch) - 1])  # a `down` ends its batch: nothing after it
    await rig.streams.aclose()


# --- R14 to R17: cancel, close and open -----------------------------------------------------------


async def cancelled_once_begun(stream: PrivateStream, entered: threading.Event) -> str:
    """On the lane: a read, cancelled once the serving loop has begun it."""
    reading = asyncio.ensure_future(anext(stream))
    assert await asyncio.to_thread(entered.wait, BOUND_S)
    reading.cancel()
    try:
        await reading
    except asyncio.CancelledError:
        return "cancelled"
    return "read"


async def cancelled_unbegun(stream: PrivateStream, done: threading.Event) -> str:
    """On the lane: a read, cancelled while the blocked serving loop cannot begin it."""
    reading = asyncio.ensure_future(anext(stream))
    await turns()
    reading.cancel()
    try:
        await reading
    except asyncio.CancelledError:
        return "cancelled"
    finally:
        done.set()
    return "read"


@pytest.mark.parametrize("begun", [True, False], ids=["begun", "unbegun"])
async def test_a_read_the_consumer_cancels_closes_the_stream_as_on_one_loop(
    begun: bool, monkeypatch: pytest.MonkeyPatch
) -> None:
    """R14: a read the consumer cancels (its silence bound, or its task's cancel) is cancelled on
    the serving loop too, which the registry takes as the consumer's own close, as on one loop;
    one the serving loop had not begun, which it closes unrun, the bridge's notice closes. Either
    way the cancel reaches the consumer, the socket closes, the account is freed with no `closed`
    queued, and nothing more is read."""
    rig, entered = Rig(), entered_reads(monkeypatch)
    async with running() as lane:
        stream = await lane.call(rig.bridge.open(account()))
        await rig.live()
        assert await lane.call(read(stream, 2)) == ["heartbeat:evidence:1", "resyncing:connected:1"]
        entered.clear()
        if begun:
            outcome = await lane.call(cancelled_once_begun(stream, entered))
        else:
            done = threading.Event()
            answer = lane.call(cancelled_unbegun(stream, done))
            assert done.wait(BOUND_S)  # this loop is blocked meanwhile: the read cannot begin
            outcome = await answer
        assert outcome == "cancelled"
        await until(rig.clock, lambda: rig.streams.count() == 0, within_s=5, what="freed")
        assert rig.venue.socket.closed and entered.is_set() is begun
        assert await lane.call(read_all(stream)) == []  # nothing more, no `closed` either
    await rig.streams.aclose()


async def closed_and_reopened(bridge: LaneStreams, stream: PrivateStream) -> PrivateStream:
    """On the lane: the consumer's close, then at once its resubscribe."""
    await stream.aclose()
    return await bridge.open(account())


async def test_the_consumers_close_returns_once_the_socket_is_closed_and_a_resubscribe_opens(
    lane_clock: LaneClock,
) -> None:
    """R15: the consumer's close returns once the serving loop has closed the socket and freed the
    account, so its own resubscribe, at once, is not refused ("already has a private stream"),
    as the registry's refusal of a second stream is, raised on the lane. The close's waiter is
    answered: the lane's clock stands still, so its 2 s bound cannot end the wait, and no overrun
    is logged."""
    rig = Rig()
    with capture_logs() as logs:
        async with running() as lane:
            stream = await lane.call(rig.bridge.open(account()))
            await rig.live()
            with pytest.raises(ValueError, match="already has a private stream"):
                await lane.call(rig.bridge.open(account()))
            again = await lane.call(closed_and_reopened(rig.bridge, stream))
            assert rig.venue.sockets[0].closed
            await rig.live()
            read_again = await lane.call(read(again, 2))
            assert read_again == ["heartbeat:evidence:1", "resyncing:connected:1"]
            assert len(rig.venue.dialled) == 2 and not rig.venue.socket.closed
            await lane.call(again.aclose())
            await lane.call(stream.aclose())  # idempotent
    assert not [e for e in logs if e["event"] == "oms_private_stream_close_overran"]
    assert rig.streams.count() == 0
    await rig.streams.aclose()


def entered_reads(monkeypatch: pytest.MonkeyPatch) -> threading.Event:
    """An event set as the serving loop begins a read of the registry's stream."""
    entered, anext_of = threading.Event(), ps._Stream.__anext__

    async def noted(self: Any) -> Item:
        entered.set()
        item: Item = await anext_of(self)
        return item

    monkeypatch.setattr(ps._Stream, "__anext__", noted)
    return entered


async def cancelled_then_closed(stream: PrivateStream, entered: threading.Event) -> str:
    """On the lane: the consumer's read cancelled once the serving loop has begun it, then its
    close."""
    outcome = await cancelled_once_begun(stream, entered)
    await stream.aclose()
    return outcome


async def test_a_read_cancelled_then_closed_closes_the_stream_once_and_answers_the_close(
    lane_clock: LaneClock, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The consumer's cancel, then its close (its silence bound cuts a read, then it closes the
    stream): the cancel's notice and the close both cross for one stream, which closes once on
    the serving loop, and the close's waiter is answered as that close ends, not by its 2 s bound,
    which the lane's clock never reaches."""
    rig, entered, aclose_of = Rig(), entered_reads(monkeypatch), ps._Stream.aclose
    closes: list[threading.Thread] = []

    async def counted(self: Any) -> None:
        closes.append(threading.current_thread())
        await aclose_of(self)

    monkeypatch.setattr(ps._Stream, "aclose", counted)
    with capture_logs() as logs:
        async with running() as lane:
            stream = await lane.call(rig.bridge.open(account()))
            await rig.live()
            first = await lane.call(read(stream, 2))
            assert first == ["heartbeat:evidence:1", "resyncing:connected:1"]
            entered.clear()
            assert await lane.call(cancelled_then_closed(stream, entered)) == "cancelled"
            await until(rig.clock, lambda: rig.streams.count() == 0, within_s=5, what="freed")
            assert rig.venue.socket.closed
    assert closes == [threading.current_thread()]
    assert not [e for e in logs if e["event"] == "oms_private_stream_close_overran"]
    await rig.streams.aclose()


async def close_overran(
    stream: PrivateStream, clock: LaneClock, done: threading.Event
) -> list[bool]:
    """On the lane: the consumer's close, and whether it has returned at 1.5 s and at 2 s on the
    lane's clock."""
    closing = asyncio.ensure_future(stream.aclose())
    returned = []
    for step in (STREAM_CLOSE_BOUND_S - 0.5, 0.5):
        await turns()
        clock.now += step
        await turns()
        returned.append(closing.done())
    done.set()
    if not closing.done():
        closing.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await closing
    return returned


async def test_a_close_the_stalled_serving_loop_has_not_taken_returns_in_2_s_and_still_runs(
    lane_clock: LaneClock,
) -> None:
    """R16: the consumer's close is a notice the stalled serving loop cannot take yet; the lane
    waits for it 2 s on its clock (`STREAM_CLOSE_BOUND_S`), logs the overrun with ids only and
    returns, and the close still runs once the serving loop turns again, never cut short."""
    rig = Rig()
    async with running() as lane:
        stream = await lane.call(rig.bridge.open(account()))
        await rig.live()
        done = threading.Event()
        with capture_logs() as logs:
            answer = lane.call(close_overran(stream, lane_clock, done))
            assert done.wait(BOUND_S)  # this loop is blocked meanwhile: the stall
            assert not rig.venue.socket.closed
            assert await answer == [False, True]
        overran = [e for e in logs if e["event"] == "oms_private_stream_close_overran"]
        assert overran == [
            {
                "event": "oms_private_stream_close_overran", "log_level": "error",
                "account_id": str(ACCOUNT_A), "bound_s": STREAM_CLOSE_BOUND_S,
            }
        ]  # fmt: skip
        await until(rig.clock, lambda: rig.streams.count() == 0, within_s=5, what="closed")
        assert rig.venue.socket.closed
    await rig.streams.aclose()


async def abandoned(bridge: LaneStreams, go: threading.Event) -> bool:
    """On the lane: an open whose answer the lane stops waiting for, its thread held while the
    serving loop opens the stream, then the open cancelled before the lane takes its answer. One
    turn sends the open's hop; the lane blocks in the same turn, so no answer lands before the
    cancel, however soon the serving loop opens the stream."""
    opening = asyncio.ensure_future(bridge.open(account()))
    await asyncio.sleep(0)  # its hop is sent
    assert go.wait(BOUND_S)  # the lane is held: the serving loop opens the stream meanwhile
    opening.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await opening
    return opening.cancelled()


async def test_an_open_the_lane_stopped_waiting_for_is_closed_once_it_opens() -> None:
    """R17: the lane stops waiting for an open (the consumer's 5 s bound, a cancel) after the
    serving loop opened the stream; its discard notice closes that stream there, so the account
    is not held (a later subscribe would be refused "already has a private stream")."""
    rig, go, opened = Rig(), threading.Event(), asyncio.Event()

    async def opens(account: AccountRef, *, clock_offset_ms: OffsetReader = None) -> PrivateStream:
        stream = await rig.streams.open(account, clock_offset_ms=clock_offset_ms)
        opened.set()  # the bridge holds the stream in this same turn
        return stream

    bridge = LaneStreams(opens, rig.serving)
    async with running() as lane:
        answer = lane.call(abandoned(bridge, go))
        await opened.wait()
        assert len(bridge._held) == 1
        go.set()
        assert await answer
        await until(rig.clock, lambda: rig.streams.count() == 0, within_s=5, what="discarded")
        assert not bridge._held and all(sock.closed for sock in rig.venue.sockets)
        again = await lane.call(bridge.open(account()))  # the account is free
        await lane.call(again.aclose())
    await rig.streams.aclose()


async def dies_opening(bridge: LaneStreams, go: threading.Event) -> None:
    """On the lane: an open whose hop is sent, its thread held while the serving loop opens the
    stream, then the lane's death, the open's answer untaken."""
    opening = asyncio.ensure_future(bridge.open(account()))
    await asyncio.sleep(0)  # its hop is sent
    assert go.wait(BOUND_S)  # the lane is held: the serving loop opens the stream meanwhile
    assert not opening.done()
    raise SystemExit


async def test_a_lane_that_dies_during_an_open_hop_leaves_no_stream_held() -> None:
    """R17 by the lane's death (OM-D12): the lane dies with an open's answer untaken, once the
    serving loop has opened the stream; the death's cleanup cancels the open, whose discard
    notice closes the stream there, so the account is freed, the lane playing no further part."""
    rig, go, opened, lane = Rig(), threading.Event(), asyncio.Event(), OrderLane()

    async def opens(account: AccountRef, *, clock_offset_ms: OffsetReader = None) -> PrivateStream:
        stream = await rig.streams.open(account, clock_offset_ms=clock_offset_ms)
        opened.set()  # the bridge holds the stream in this same turn
        return stream

    bridge = LaneStreams(opens, rig.serving)
    await lane.start()
    try:
        async with asyncio.timeout(BOUND_S):
            thread = await lane.call(on_lane())
            with capture_logs() as logs:
                dying = lane.call(dies_opening(bridge, go))
                await opened.wait()
                assert len(bridge._held) == 1
                go.set()
                with pytest.raises(asyncio.CancelledError):
                    await dying
                await asyncio.to_thread(thread.join, BOUND_S)
            died = [e["error"] for e in logs if e["event"] == "oms_lane_died"]
            assert lane.dead and died == ["SystemExit"]
            await until(rig.clock, lambda: rig.streams.count() == 0, within_s=5, what="freed")
            assert not bridge._held and all(sock.closed for sock in rig.venue.sockets)
    finally:
        await lane.stop()
    await rig.streams.aclose()


async def closed_while_waiting(stream: PrivateStream) -> str:
    """On the lane: a read waiting for the next item, then the consumer's close from another
    task."""
    reading = asyncio.ensure_future(anext(stream))
    await turns()  # its hop is sent ahead of the close's notice
    await stream.aclose()
    try:
        await reading
    except StopAsyncIteration:
        return "ended"
    return "read"


async def test_a_read_waiting_when_its_consumer_closes_the_stream_ends_with_no_item() -> None:
    """The stream's close from another task ends a read waiting there (24 Sec.14.1): the serving
    loop's read finds the stream over and answers no item, and the lane yields nothing more."""
    rig = Rig()
    async with running() as lane:
        stream = await lane.call(rig.bridge.open(account()))
        await rig.live()
        assert await lane.call(read(stream, 2)) == ["heartbeat:evidence:1", "resyncing:connected:1"]
        assert await lane.call(closed_while_waiting(stream)) == "ended"
        assert rig.serving.batches[-1] == [] and rig.venue.socket.closed
        assert rig.streams.count() == 0
    await rig.streams.aclose()


async def gave_up(bridge: LaneStreams, began: threading.Event) -> bool:
    """On the lane: an open cancelled once the serving loop has begun it."""
    opening = asyncio.ensure_future(bridge.open(account()))
    assert await asyncio.to_thread(began.wait, BOUND_S)
    opening.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await opening
    return opening.cancelled()


async def test_a_stream_that_opens_after_the_discard_notice_is_closed_at_once() -> None:
    """The discard notice can land before the open ends, should the opener outlive its cancel:
    the stream it opens then is closed at once and never held."""
    rig, began, opened = Rig(), threading.Event(), asyncio.Event()

    async def outlives(
        account: AccountRef, *, clock_offset_ms: OffsetReader = None
    ) -> PrivateStream:
        began.set()
        with contextlib.suppress(asyncio.CancelledError):  # its cancel swallowed
            await asyncio.Event().wait()
        stream = await rig.streams.open(account, clock_offset_ms=clock_offset_ms)
        opened.set()
        return stream

    bridge = LaneStreams(outlives, rig.serving)
    async with running() as lane:
        assert await lane.call(gave_up(bridge, began))
        await opened.wait()
        await until(rig.clock, lambda: rig.streams.count() == 0, within_s=5, what="closed")
        assert not bridge._held and all(sock.closed for sock in rig.venue.sockets)
    await rig.streams.aclose()


class Unbatched:
    """A stream with no `ready()`, whose close fails with a peer's text."""

    def __aiter__(self) -> Unbatched:
        return self

    async def __anext__(self) -> Item:
        return PrivateStreamStatus(
            account_id=ACCOUNT_A, state="heartbeat", reason="evidence", epoch=1, ts=1
        )

    async def aclose(self) -> None:
        raise ConnectionError("a peer's text, never logged")


async def test_a_stream_without_ready_crosses_an_item_a_hop_and_a_failed_close_logs_its_class() -> (
    None
):
    """A stream without `ready()` crosses one item a hop; on the serving loop itself every hop is
    a plain call; and a close that fails is logged by its class alone, the waiting close
    answered, with no overrun logged."""
    serving = Hops(asyncio.get_running_loop(), Metrics("demo"))

    async def opens(account: AccountRef, *, clock_offset_ms: OffsetReader = None) -> PrivateStream:
        return Unbatched()

    stream = await LaneStreams(opens, serving).open(account())
    assert await read(stream, 2) == ["heartbeat:evidence:1"] * 2
    assert [len(batch) for batch in serving.batches] == [1, 1]
    with capture_logs() as logs:
        await stream.aclose()
    failed = [e for e in logs if e["event"] == "oms_private_stream_close_failed"]
    assert failed == [
        {
            "event": "oms_private_stream_close_failed",
            "log_level": "error",
            "error": "ConnectionError",
        }
    ]
    assert "a peer's text" not in str(logs)
    assert not [e for e in logs if e["event"] == "oms_private_stream_close_overran"]


# --- R18 to R20, the read's bound: revoke, death, isolation ---------------------------------------


async def test_a_revoke_closes_the_socket_with_the_lane_wedged_and_the_lane_reads_closed_last() -> (
    None
):
    """R18 (SR-E27-17; 24 Sec.14.2 rule 13): a revoke closes the socket on the serving loop, where
    the registry is, and never waits for the lane, wedged meanwhile; the lane then reads the
    stream's rows in order and `closed(key_revoked)` last, and the stream ends."""
    rig = Rig()
    async with running() as lane:
        stream = await lane.call(rig.bridge.open(account()))
        await rig.live()
        rig.venue.socket.push(push("position.linear", *rows(range(3))))
        await rig.clock.advance(0)
        async with wedged(lane):
            closed = await rig.streams.close_key(account().key_ref, reason="key_revoked")
            assert closed == (ACCOUNT_A,) and rig.venue.socket.closed
        assert await lane.call(read_all(stream)) == [
            "heartbeat:evidence:1", "resyncing:connected:1", *positions(range(3)),
            "closed:key_revoked:1",
        ]  # fmt: skip
        await lane.call(stream.aclose())
    assert rig.streams.count() == 0
    await rig.streams.aclose()


async def exits() -> None:
    raise SystemExit


async def test_a_dead_lane_frees_its_streams_and_the_stop_closes_the_rest_on_the_serving_loop() -> (
    None
):
    """R19 (OM-D12): a lane that dies cancels its parked read with its tasks, which closes that
    stream on the serving loop and frees its account and socket; the runtime's stop closes the
    rest there (`LaneStreams.aclose`, as its `private_streams` closer runs it, a plain call on
    this loop), the dead lane playing no part."""
    rig, lane = Rig(), OrderLane()
    await lane.start()
    try:
        parked_on = await lane.call(rig.bridge.open(account(ACCOUNT_A)))
        idle = await lane.call(rig.bridge.open(account(ACCOUNT_B)))
        await rig.live(ACCOUNT_A, ACCOUNT_B)
        for stream in (parked_on, idle):
            assert await lane.call(read(stream, 2)) == [
                "heartbeat:evidence:1", "resyncing:connected:1",
            ]  # fmt: skip
        parked = lane.call(read(parked_on, 1))  # nothing is queued: the read waits
        thread = await lane.call(on_lane())
        with capture_logs() as logs:
            with pytest.raises(asyncio.CancelledError):
                await lane.call(exits())
            await asyncio.to_thread(thread.join, BOUND_S)
        assert lane.dead and [e["error"] for e in logs if e["event"] == "oms_lane_died"] == [
            "SystemExit"
        ]
        with pytest.raises(asyncio.CancelledError):
            await parked
        await until(
            rig.clock, lambda: ACCOUNT_A not in rig.streams._conns, within_s=5, what="freed"
        )
        assert rig.venue.sockets[0].closed and not rig.venue.sockets[1].closed
        await rig.serving.call(rig.bridge.aclose())
        assert rig.venue.sockets[1].closed and rig.streams.count() == 0
        assert not rig.bridge._held
    finally:
        await lane.stop()
    await rig.streams.aclose()


async def owned(stream: PrivateStream, count: int) -> list[tuple[AccountId, str]]:
    """On the lane: `count` items, each with the account it carries."""
    items = [await anext(stream) for _ in range(count)]
    return [(item.account_id, shown(item)) for item in items]


async def both(first: PrivateStream, second: PrivateStream, count: int) -> list[Any]:
    """On the lane: two streams read at once."""
    return list(await asyncio.gather(owned(first, count), owned(second, count)))


async def test_two_accounts_streams_never_mix_across_the_hop() -> None:
    """R20 (SR-E29-02): two accounts' streams, read at once, each cross on their own hops, with
    their own account's items only, in their own order."""
    rig = Rig()
    async with running() as lane:
        first = await lane.call(rig.bridge.open(account(ACCOUNT_A)))
        await rig.live(ACCOUNT_A)
        second = await lane.call(rig.bridge.open(account(ACCOUNT_B)))
        await rig.live(ACCOUNT_B)
        on_a, on_b = rig.venue.sockets
        for n in range(0, 200, 50):
            on_a.push(push("position.linear", *rows(range(n, n + 50))))
            on_b.push(push("position.linear", *rows(range(1000 + n, 1050 + n))))
        await rig.clock.advance(0)
        got_a, got_b = await lane.call(both(first, second, 2 + 200))
        live = ["heartbeat:evidence:1", "resyncing:connected:1"]
        assert got_a == [(ACCOUNT_A, item) for item in [*live, *positions(range(200))]]
        assert got_b == [(ACCOUNT_B, item) for item in [*live, *positions(range(1000, 1200))]]
        for stream in (first, second):
            await lane.call(stream.aclose())
    await rig.streams.aclose()


async def read_cut(stream: PrivateStream, clock: LaneClock) -> list[bool]:
    """On the lane: a read the serving loop does not answer, and whether it has ended at 119.5 s
    and at 120 s on the lane's clock."""
    reading = asyncio.ensure_future(anext(stream))
    ended = []
    for step in (STREAM_READ_BOUND_S - 0.5, 0.5):
        await turns()
        clock.now += step
        await turns()
        ended.append(reading.done())
    if not reading.done():
        reading.cancel()
    with contextlib.suppress(asyncio.CancelledError, StopAsyncIteration):
        await reading
    return ended


async def test_a_read_not_answered_in_120_s_ends_the_stream_on_the_lane_and_closes_it(
    lane_clock: LaneClock,
) -> None:
    """The read's bound (`STREAM_READ_BOUND_S`, finite, C-2.18): a hop not answered within 120 s on
    the lane's clock fails, the stream ends on the lane, logged with ids only, and its read on the
    serving loop is cancelled, which closes it there and frees the account."""
    rig = Rig()
    async with running() as lane:
        stream = await lane.call(rig.bridge.open(account()))
        await rig.live()
        assert await lane.call(read(stream, 2)) == ["heartbeat:evidence:1", "resyncing:connected:1"]
        with capture_logs() as logs:
            assert await lane.call(read_cut(stream, lane_clock)) == [False, True]
        failed = [e for e in logs if e["event"] == "oms_private_stream_hop_failed"]
        assert failed == [
            {
                "event": "oms_private_stream_hop_failed", "log_level": "error",
                "account_id": str(ACCOUNT_A), "error": "TimeoutError",
            }
        ]  # fmt: skip
        await until(rig.clock, lambda: rig.streams.count() == 0, within_s=5, what="closed")
        assert rig.venue.socket.closed
        assert await lane.call(read_all(stream)) == []
    await rig.streams.aclose()


async def cut_unbegun(stream: PrivateStream, clock: LaneClock, done: threading.Event) -> bool:
    """On the lane: a read the blocked serving loop cannot begin, and whether it has ended once
    the lane's clock reaches 120 s."""
    reading = asyncio.ensure_future(anext(stream))
    await turns()
    clock.now += STREAM_READ_BOUND_S
    await turns()
    ended = reading.done()
    done.set()
    if not ended:
        reading.cancel()
    with contextlib.suppress(asyncio.CancelledError, StopAsyncIteration):
        await reading
    return ended


async def test_a_read_the_stalled_serving_loop_never_began_is_closed_by_its_notice_at_120_s(
    lane_clock: LaneClock, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The read's bound, unbegun: the stalled serving loop has not begun the read when its hop is
    cut at 120 s on the lane's clock, so no read there is cancelled and the registry sees no close;
    the stream ends on the lane, logged, and its close notice closes it once the serving loop
    turns again, freeing the account."""
    rig, entered = Rig(), entered_reads(monkeypatch)
    async with running() as lane:
        stream = await lane.call(rig.bridge.open(account()))
        await rig.live()
        assert await lane.call(read(stream, 2)) == ["heartbeat:evidence:1", "resyncing:connected:1"]
        entered.clear()
        done = threading.Event()
        with capture_logs() as logs:
            answer = lane.call(cut_unbegun(stream, lane_clock, done))
            assert done.wait(BOUND_S)  # this loop is blocked meanwhile: the read cannot begin
            assert rig.streams.count() == 1
            assert await answer
        failed = [e["error"] for e in logs if e["event"] == "oms_private_stream_hop_failed"]
        assert failed == ["TimeoutError"]
        await until(rig.clock, lambda: rig.streams.count() == 0, within_s=5, what="closed")
        assert rig.venue.socket.closed and not entered.is_set()
        assert await lane.call(read_all(stream)) == []
    await rig.streams.aclose()

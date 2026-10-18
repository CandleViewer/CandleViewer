"""E12-T06 D2-C1 (#2787): a `bars.*` subscribe holds its series BEFORE it leases the builder, so a
close a restoring builder emits while `register` awaits (its tape replay) is not missed: it is in
the store, so in the first `snap`, or it arrives as a `d` after it. The stack is real: a
`BarBuilderSet` restoring from a blob and replaying the recorded BTCUSDT tape, the `SeriesStore`,
the publisher on the hub, the snapshot source and `subscribe_upstream`."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest

from candleviewer.bars.models import Bar, BarSpec
from candleviewer.bars.reader import BarTail
from candleviewer.bars.series_store import RECENT_CLOSES, SeriesStore
from candleviewer.bars.state_store import StateStore, StoredState, Watermark
from candleviewer.bars.time_builder import TimeBarBuilder
from candleviewer.bus.bus import Bus
from candleviewer.exchange.base.models import TradeEvent
from candleviewer.ws.bars_publish import BarsPublisher
from candleviewer.ws.bars_source import BarsSnapshotSource
from candleviewer.ws.bars_wire import bar_item
from candleviewer.ws.permissions import ConnectionAuthz, SubscriptionServices, handle_sub
from candleviewer.ws.sequencing import SequencingHub, TopicEmitter
from tests.unit.bars._set_harness import M1, FakeTape, make_set
from tests.unit.bars._trades import SYM, final_bars
from tests.unit.bars.test_time_builder_golden import _tape
from tests.unit.ws._seq_support import Clock, principal, validate

CH, GEN = "bars.BTCUSDT.time.1", 7
#: The blob holds the first CUT prints; the replay parks after PARK until released, and ends at END.
CUT, PARK, END = 50, 80, 110


def _bars(tape: list[TradeEvent]) -> list[Bar]:
    """The series a plain builder holds after `tape`: its closed bars, then the forming one."""
    builder = TimeBarBuilder(M1, SYM)
    return final_bars([u for t in tape for u in builder.on_trade(t)])


def _items(bars: list[Bar]) -> list[dict[str, Any]]:
    return [bar_item(b, generation=GEN, bar_kind="time", include_delta=False) for b in bars]


class _GatedTape(FakeTape):
    """Replays like `FakeTape`, parked once `after` is applied until released."""

    def __init__(self, trades: list[TradeEvent], after: TradeEvent) -> None:
        super().__init__(trades)
        self.after, self.parked, self.release = after, asyncio.Event(), asyncio.Event()

    async def since(self, symbol: str, ts_us: int) -> AsyncIterator[TradeEvent]:
        async for t in super().since(symbol, ts_us):
            yield t  # the set applies it, and emits what it closes, before this resumes
            if t is self.after:
                self.parked.set()
                await self.release.wait()


class _Rig:
    """`create_app`'s wiring (store, then publisher, on the emit path) over a set that restores
    the blob of `tape[:CUT]`; the bars it had closed are what the store's first read finds."""

    def __init__(self, root: Path, tape: list[TradeEvent], rows: list[Bar]) -> None:
        async def read(symbol: str, spec: BarSpec, limit: int) -> BarTail:
            return BarTail([(GEN, b) for b in rows])

        self.rows, self.tape = rows, _GatedTape(tape[:END], tape[PARK])
        self.hub, self.store = SequencingHub(), SeriesStore(read)
        publisher = BarsPublisher(self.hub, lambda _s: (1, 3), swap_reason="generation_swap")
        self.bset = make_set(root, bus=Bus(), sinks=[self.store, publisher], tape=self.tape)
        self.source = BarsSnapshotSource(
            self.store, lambda _s: (1, 3), seed=publisher.note_generation
        )


class _Conn:
    """One connection: its `ConnectionAuthz` and emitter on the hub, and the frames it gets."""

    def __init__(self, rig: _Rig) -> None:
        self.out: list[dict[str, Any]] = []
        services = SubscriptionServices(
            bars=rig.bset, series=rig.store, snapshots=rig.source, clock=Clock()
        )
        self.authz = ConnectionAuthz(principal(), services)
        self.emitter = TopicEmitter(
            self.push, connection_id="c", wall_ms=lambda: 1, clock=lambda: 0.0,
            source=rig.source, cache=services.snapshot_cache,
        )  # fmt: skip
        rig.hub.register(self.authz, self.emitter)

    def push(self, frame: dict[str, Any]) -> None:
        validate(frame)
        self.out.append(frame)

    async def subscribe(self) -> None:
        async def send(frame: dict[str, Any]) -> None:
            self.push(frame)

        entry = {"ch": CH, "opts": {"encoding": "structured"}}
        await handle_sub(self.authz, {"t": "sub", "id": "s", "p": {"topics": [entry]}}, send)
        self.emitter.flush_pending(self.authz.by_id.values())  # the gateway's flush: the `snap`

    def bars(self, i: int) -> list[dict[str, Any]]:
        bars: list[dict[str, Any]] = self.out[i]["p"]["bars"]
        return bars


async def _subscribing(rig: _Rig, conn: _Conn) -> asyncio.Task[None]:
    """`conn.subscribe()` as a task, once the replay it starts is parked (`register` is awaiting the
    tape). A `subscribe` that ends first has failed: its own exception is raised, not a timeout."""
    task = asyncio.create_task(conn.subscribe())
    parked = asyncio.create_task(rig.tape.parked.wait())
    await asyncio.wait({task, parked}, timeout=5, return_when=asyncio.FIRST_COMPLETED)
    parked.cancel()
    if task.done():
        task.result()  # raises what `subscribe` raised
    assert rig.tape.parked.is_set(), "the replay did not park"
    return task


@pytest.fixture
async def rig(tmp_path: Path) -> AsyncIterator[_Rig]:
    tape, builder = _tape(), TimeBarBuilder(M1, SYM)
    rows = [u.bar for t in tape[:CUT] for u in builder.on_trade(t) if u.kind == "close"]
    at = tape[CUT - 1].ts_event  # the blob's watermark: the prints applied at its last timestamp
    mark = Watermark(at, frozenset(t.trade_id for t in tape[:CUT] if t.ts_event == at))
    state = StoredState(builder.snapshot(), mark, GEN)  # what a `stop()` after CUT prints leaves
    await StateStore(tmp_path).save(state)
    world = _Rig(tmp_path, tape, rows)
    yield world
    world.tape.release.set()
    await world.bset.stop()


async def test_a_close_emitted_while_register_awaits_is_in_the_store_so_in_the_first_snap(
    rig: _Rig,
) -> None:
    """`ensure` runs before `register`, so the closes the restore replays under `register` reach
    the held series as they are emitted, and the first `snap` holds them all: more than the ring
    of the last `RECENT_CLOSES` closes, which is all a hold taken afterwards would start from."""
    conn, tape = _Conn(rig), rig.tape.trades
    pending = await _subscribing(rig, conn)  # `register` is awaiting the tape, mid-replay
    held = rig.store.latest(SYM, M1.spec_hash, 1000)
    assert held is not None and [*held.closed, held.forming] == _bars(tape[: PARK + 1])
    assert conn.out == []  # no `sub_ok`, so no `snap` yet
    rig.tape.release.set()
    async with asyncio.timeout(5):
        await pending
    whole = _bars(tape)
    replayed = len(whole) - 1 - len(rig.rows)  # the closes the replay emitted
    assert replayed > RECENT_CLOSES, "retune CUT, PARK or END: the ring would hold them all"
    assert [f["t"] for f in conn.out] == ["sub_ok", "snap"] and conn.bars(1) == _items(whole)


async def test_a_subscriber_attaching_mid_restore_gets_the_rest_of_the_closes_as_d_frames(
    rig: _Rig,
) -> None:
    """A second connection subscribes while the first one's `register` awaits the replay: its own
    `register` returns at once (the lease exists), its `snap` holds the closes emitted so far, and
    each later one reaches it as a `d`, `s` contiguous, so `snap` plus `d`s are the whole series."""
    first, second, tape = _Conn(rig), _Conn(rig), rig.tape.trades
    pending = await _subscribing(rig, first)
    async with asyncio.timeout(5):
        await second.subscribe()
    assert [f["t"] for f in second.out] == ["sub_ok", "snap"]
    rig.tape.release.set()
    async with asyncio.timeout(5):
        await pending
    deltas, whole = second.out[2:], _items(_bars(tape))
    assert deltas, "no `d` reached it, its `snap` held it all: retune CUT, PARK or END"
    assert [(f["t"], f["s"]) for f in deltas] == [("d", n) for n in range(2, 2 + len(deltas))]
    series = {i["index"]: i for i in second.bars(1)}
    for frame in deltas:
        series.update({i["index"]: i for i in frame["p"]["bars"]})
    assert [series[k] for k in sorted(series)] == whole and first.bars(1) == whole

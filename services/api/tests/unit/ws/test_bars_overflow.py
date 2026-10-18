"""#399 (E12-T06) D7, SR-E12-07 part 3: with `CV_WS_BACKPRESSURE_ENABLED` on, a `bars` close that
§8.4 step 1 drops from the queue or from a pending window, or that a window past its key bound
refuses, is in the topic's `backpressure` snapshot (step 2) when it is among the `history` newest
bars: every snapshot reads the series store, which each close reaches before its `d` exists (the
store is the emit path's first sink; a store sink that times out or raises is BR-13's residual).
With `history: 0` the snapshot holds no bar, and the client re-reads closes over REST (§6.1). The
real `/ws` router behind `_Wire` (a peer that stops reading, then drains), under `cv.v1.json` and
`cv.v1.msgpack`, wired as the bars conformance rig is, on the recorded BTCUSDT tape (C-13.5)."""

from __future__ import annotations

import asyncio
from typing import Any, Literal

import pytest

from candleviewer.bars.emit import EmitRouter
from candleviewer.bars.reader import BarReader
from candleviewer.bars.series_store import SeriesStore
from candleviewer.ws import pacing
from candleviewer.ws.backpressure_config import BackpressureConfig
from candleviewer.ws.bars_publish import BarsPublisher
from candleviewer.ws.bars_source import BarsSnapshotSource
from candleviewer.ws.coalescing import CoalescingQueue
from candleviewer.ws.gateway import _Connection
from candleviewer.ws.outbound import OutboundQueue
from candleviewer.ws.permissions import Subscription
from candleviewer.ws_wiring import SnapshotRouter
from tests.contract.test_market_bars_contract import _NOW, _SERIES, _STORE
from tests.contract.ws._harness import MODES, structured_of
from tests.contract.ws.test_ws_bars_contract import (
    _MINUTE,
    CH,
    _bar_state,
    _closed,
    _item_state,
    _no_rebuild,
    _Series,
    _State,
    _Storage,
    _up,
)
from tests.unit.ws.test_pipeline_outbound import _DEADLINE_S, _ENCODINGS, _overflow, _Rig, _Wire
from tests.unit.ws.test_subscriptions import _Bars

_SPEC = _SERIES[_MINUTE]


class _BarsWire(_Rig):
    """`_Rig` with the bars wiring of the conformance rig: on the emit path the store, then the
    publisher; the store behind the hold and the snapshots, hydrated with the tape's first three
    one-minute bars (indexes 0 to 2)."""

    def __init__(self, config: BackpressureConfig) -> None:
        super().__init__(config)
        reader = BarReader(_Storage({"1m": _STORE["1m"][:3]}), _no_rebuild, now_us=lambda: _NOW)
        self.store = SeriesStore(reader.read_tail, release_grace_s=0.0, clock=lambda: 0.0)
        publisher = BarsPublisher(self.sequencing, lambda _s: (1, 3), swap_reason="generation_swap")
        self.router = EmitRouter([self.store, publisher])
        source = BarsSnapshotSource(self.store, lambda _s: (1, 3), seed=publisher.note_generation)
        services = self.registry.services
        services.bars, services.series = _Bars(), self.store
        services.snapshots = SnapshotRouter({"bars": source})

    async def subscribe(self, sock: _Wire, **opts: Any) -> dict[str, Any]:
        """`sub` `CH` with `opts`; its `snap`."""
        sock.feed({"t": "sub", "id": "s", "p": {"topics": [{"ch": CH, "opts": opts}]}})
        ok, snap = await sock.next(2)
        assert ok["p"]["results"][0]["ok"] and snap["t"] == "snap"
        return snap

    async def emit(self, kind: Literal["open", "update", "close"], index: int) -> None:
        """One emission of the tape's one-minute bar `index`, in one synchronous turn."""
        await self.router.emit(_SPEC, [_up(kind, _closed(*_MINUTE)[index])], 0)

    @staticmethod
    def parts(conn: _Connection) -> tuple[Subscription, OutboundQueue, pacing.Pacer]:
        """`CH`'s subscription on `conn`, and the connection's outbound queue and pacer."""
        pipe, authz = conn.pipeline, conn.authz
        assert pipe is not None and pipe.ladder is not None and authz is not None
        sub = authz.find(CH)
        assert sub is not None
        return sub, pipe.queue, pipe.ladder.pacer

    def ends(self, mine: _Series) -> tuple[list[_State], list[_State]]:
        """The client's series and the store's (its closed bars, then the forming one)."""
        latest = self.store.latest("BTCUSDT", _SPEC.spec_hash, 1000)
        assert latest is not None
        held = [*latest.closed, *([latest.forming] if latest.forming else [])]
        return [_item_state(i) for _, i in sorted(mine.bars.items())], [_bar_state(b) for b in held]


@pytest.mark.parametrize("history", [500, 0])
@pytest.mark.parametrize("where", ["queued", "pending"])
@pytest.mark.parametrize("mode", MODES)
@_ENCODINGS
async def test_bars_a_close_the_ladder_drops_is_in_the_backpressure_snapshot(
    encoding: str, mode: str, where: str, history: int
) -> None:
    """§8.4 steps 1 and 2, the writer held. `queued`: bar 3's close is the update that leaves at
    once, and `system` frames take the queue past its four frames. `pending`: bar 3's update has
    been delivered and its close waits in the window, the topic has no frame queued, and `system`
    frames take the queue past 4 KiB only with the window's bytes, so step 1 reaches the topic
    through its window alone. Step 1 drops the topic's frame or window and marks it; once the
    queue is below half its `backpressure` snapshot holds the close, the deltas go on from its
    `s` and the client's series ends as the store's. With `history: 0` the snapshot is empty: no
    frame carries that close (the client reads it over REST, §6.1)."""
    queued = where == "queued"
    config = BackpressureConfig(max_frames=4) if queued else BackpressureConfig(max_bytes=4096)
    rig, sock, mine = _BarsWire(config), _Wire(encoding), _Series(binary=mode == "binary")
    before = [_overflow("drop"), _overflow("resnapshot")]
    async with asyncio.timeout(_DEADLINE_S):
        handler, conn = await rig.open(sock)
        assert mine.apply(await rig.subscribe(sock, encoding=mode, history=history))
        if not queued:
            await rig.emit("update", 3)  # leaves at once and is delivered
            assert mine.apply((await sock.next())[0])
        sock.hold()
        rig.hub.broadcast_system({"kind": "held"})
        await sock.parked.wait()  # the writer holds it: what follows queues behind it
        await rig.emit("close", 3)  # `queued`: leaves at once; `pending`: waits in the window
        sub, queue, pacer = rig.parts(conn)
        assert ((CH, None) in queue.key_bytes(), pacer.pending_bytes > 0) == (queued, not queued)
        ticks = 0
        while sub.pending_reason != "backpressure":  # the step 1 that marks the topic
            assert ticks < 200 and not conn.closing
            rig.hub.broadcast_system({"kind": "tick", "n": ticks})
            ticks += 1
        assert not conn.closing and pacer.pending_bytes == 0  # dropped, and nothing closed
        sock.release()
        *system, snap = await sock.next(ticks + 2)
        rig.clock.now = 0.25  # the window has passed: the next update leaves at once
        await rig.emit("open", 4)
        (d,) = await sock.next()
        handler.cancel()
        await asyncio.wait({handler})
    assert {f["ch"] for f in system} == {"system"} and snap["t"] == "snap"
    assert (snap["meta"]["reason"], snap["meta"]["previous_seq"], d["s"]) == ("backpressure", 2, 4)
    held = [(i["index"], i["confirm"]) for i in structured_of(snap)["bars"]]
    assert held == ([(i, True) for i in range(4)] if history else [])  # 3 is the dropped close
    assert mine.apply(snap) and mine.apply(d)
    client, store = rig.ends(mine)
    assert client == (store if history else store[-1:])  # `history: 0`: bar 4 alone, from its `d`
    assert [_overflow("drop"), _overflow("resnapshot")] == [n + 1 for n in before]


@_ENCODINGS
async def test_bars_a_window_past_its_key_bound_is_dropped_and_its_snapshot_holds_the_close(
    encoding: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """§8.6 Pacing: a window holds at most 4 096 bars, one here. Bar 3's close waits in its window
    and bar 4's open, a second bar, is refused: the window is dropped whole (it no longer counts
    against the budget or waits to close), counted `drop`, and the topic marked for a
    `backpressure` snapshot, which holds the close and the open."""

    def one_bar(sub: Subscription) -> CoalescingQueue:
        return CoalescingQueue(sub.topic.family.family, max_keys=1)

    monkeypatch.setattr(pacing, "_queue", one_bar)
    rig, sock, mine = _BarsWire(BackpressureConfig()), _Wire(encoding), _Series(binary=False)
    async with asyncio.timeout(_DEADLINE_S):
        handler, conn = await rig.open(sock)
        assert mine.apply(await rig.subscribe(sock))
        await rig.emit("update", 3)  # leaves at once
        assert mine.apply((await sock.next())[0])
        await rig.emit("close", 3)  # waits in the window: one bar, the bound
        drops = _overflow("drop")
        await rig.emit("open", 4)  # a second bar: refused
        sub, _, pacer = rig.parts(conn)
        marks = (sub.pending_reason, pacer.pending_bytes, pacer.next_due())
        assert marks == ("backpressure", 0, None) and _overflow("drop") == drops + 1
        (snap,) = await sock.next()  # the writer's next turn sends it
        handler.cancel()
        await asyncio.wait({handler})
    held = [(i["index"], i["confirm"]) for i in structured_of(snap)["bars"]]
    assert (snap["meta"]["reason"], held) == ("backpressure", [(i, i < 4) for i in range(5)])
    assert mine.apply(snap)
    client, store = rig.ends(mine)
    assert client == store

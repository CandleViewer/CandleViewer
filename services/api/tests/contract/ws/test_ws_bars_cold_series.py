"""#2787 (E12-T06 D2) X1 and X3: `bars.*` against `23-ws-protocol.md` §6.1, §7.5, §7.6 and §7.7
through the real `/ws` router, on both wires, in both encodings, with the backpressure flag off and
on. Every frame is validated, and each one that matters is the very next received, so the order is
asserted. A `resync` and a resuming `ctl` on a series whose store is empty or not hydrated each get
a `snap`; `sub_ok` waits for the series' first read and no `snap` precedes it; a `snapshot: false`
attach, which never proves continuity, still gets one. Bars come from the recorded BTCUSDT tape
(C-13.5), built by the real builder."""

from __future__ import annotations

import asyncio
import threading
from typing import Any

import pytest

from candleviewer.bars.emit import EmitRouter
from candleviewer.bars.models import BarSpec, BarUpdate
from candleviewer.bars.reader import BarTail
from candleviewer.bars.series_store import SeriesStore, TailRead
from candleviewer.bars.time_builder import TimeBarBuilder
from candleviewer.ws.backpressure_config import BackpressureConfig
from candleviewer.ws.bars_publish import BarsPublisher
from candleviewer.ws.bars_source import BarsSnapshotSource
from candleviewer.ws_wiring import SnapshotRouter
from tests.contract.ws import _harness as h
from tests.unit.bars._trades import final_bars
from tests.unit.bars.test_time_builder_golden import _tape
from tests.unit.ws.test_subscriptions import _Bars

SPEC, CH, GEN = BarSpec(kind="time", interval_ms=60_000), "bars.BTCUSDT.time.1", 7
_FLAGS = pytest.mark.parametrize("flag", [None, BackpressureConfig()], ids=["flag-off", "flag-on"])


def _prints(n: int) -> list[list[BarUpdate]]:
    """What the real builder emits for each of the recorded tape's first `n` prints."""
    builder = TimeBarBuilder(SPEC, h.SYM)
    return [list(builder.on_trade(t)) for t in _tape()[:n]]


def _stored(n: int) -> TailRead:
    """A read that finds the bars the first `n` prints closed."""

    async def read(symbol: str, spec: BarSpec, limit: int) -> BarTail:
        return BarTail([(GEN, u.bar) for ems in _prints(n) for u in ems if u.kind == "close"])

    return read


async def _empty(symbol: str, spec: BarSpec, limit: int) -> BarTail:
    return BarTail([])


async def _fails(symbol: str, spec: BarSpec, limit: int) -> BarTail:
    raise OSError("storage is down")  # the read fails: the series is served live-only


#: The two cold series: a read that found nothing, and a read that failed (not hydrated).
COLD = {"empty": _empty, "unread": _fails}


class _Rig:
    """The conformance world with `create_app`'s bars wiring over a store that reads with `read`.
    The store's read bound (`asyncio.timeout`, real time) is 60 s, far past any step here: a parked
    read ends when the test releases it, so no row's result depends on elapsed time (C-13.7)."""

    def __init__(self, read: TailRead, flag: BackpressureConfig | None) -> None:
        self.w = h.World(backpressure=flag)
        self.store = SeriesStore(read, release_grace_s=0.0, clock=lambda: 0.0, timeout_s=60.0)
        publisher = BarsPublisher(self.w.hub, lambda _s: (1, 3), swap_reason="generation_swap")
        self.router = EmitRouter([self.store, publisher])
        source = BarsSnapshotSource(self.store, lambda _s: (1, 3), seed=publisher.note_generation)
        services = self.w.registry.services
        services.bars, services.series = _Bars(), self.store
        services.snapshots = SnapshotRouter({"bars": source})

    def emit(self, *updates: BarUpdate) -> None:
        self.w.call(self.router.emit, SPEC, updates, GEN)


def _keys(frame: dict[str, Any]) -> list[tuple[int, int, bool]]:
    """`(generation, index, confirm)` of each bar a `snap` or `d` carries, whichever encoding."""
    return [(b["generation"], b["index"], b["confirm"]) for b in h.structured_of(frame)["bars"]]


def _next(c: h.Client, t: str) -> dict[str, Any]:
    """The very next frame, which must be a `t`: no data or control frame is skipped to find it
    (server heartbeat `ping`s are), so the order holds."""
    frame = c.recv()
    assert frame["t"] == t, frame
    return frame


def _data(c: h.Client, t: str, mode: str) -> dict[str, Any]:
    """The next frame, a `t` in `mode`'s encoding (§3.2): `j`, or the wire's binary (`b`, `b64`)."""
    frame = _next(c, t)
    assert frame["e"] == ("j" if mode == "structured" else c.binary_e), frame
    return frame


def _sub(c: h.Client, opts: dict[str, Any], **p: Any) -> tuple[dict[str, Any], dict[str, Any]]:
    """`sub` to the series: the next two frames are its `sub_ok`, then its first `snap`."""
    c.send({"t": "sub", "id": "s", "p": {"topics": [{"ch": CH, "opts": opts}], **p}})
    return _next(c, "sub_ok"), _data(c, "snap", opts["encoding"])


@_FLAGS
@pytest.mark.parametrize("mode", h.MODES)
@pytest.mark.parametrize("cold", COLD)
def test_contract_bars_a_resync_on_a_cold_series_is_answered_with_an_empty_snap(
    cold: str, mode: str, flag: BackpressureConfig | None
) -> None:
    """§6.1: a series with no tape yet gets an empty `bars` array; §7.5: a `resync` is answered by
    a `snap`, never left pending, and the deltas go on from its `s`."""
    rig = _Rig(COLD[cold], flag)
    with h.connect(rig.w) as c:
        _, first = _sub(c, {"encoding": mode})
        c.send({"t": "resync", "id": "r", "ch": CH, "p": {"reason": "manual", "last_seq": 1}})
        snap = _data(c, "snap", mode)
        rig.emit(*_prints(1)[0])
        delta = _data(c, "d", mode)
        meta = snap["meta"]
        assert (first["s"], snap["s"], delta["s"]) == (1, 2, 3)
        assert (meta["reason"], meta["previous_seq"]) == ("client_resync", 1)
        assert _keys(first) == _keys(snap) == []
        assert rig.store.hydrated(h.SYM, SPEC.spec_hash) is (cold == "empty")


@_FLAGS
@pytest.mark.parametrize("mode", h.MODES)
@pytest.mark.parametrize("cold", COLD)
def test_contract_bars_a_ctl_resume_on_a_cold_series_is_answered_with_an_empty_snap(
    cold: str, mode: str, flag: BackpressureConfig | None
) -> None:
    """§5.4, §7.1: a resume re-snapshots, `ctl_ok` first; on a store with no bars that `snap` is
    empty, and a delta follows it."""
    rig = _Rig(COLD[cold], flag)
    with h.connect(rig.w) as c:
        _sub(c, {"encoding": mode})
        c.send({"t": "ctl", "id": "p", "ch": CH, "p": {"paused": True}})
        assert "resnapshot" not in _next(c, "ctl_ok")["p"]
        c.send({"t": "ctl", "id": "u", "ch": CH, "p": {"paused": False}})
        assert _next(c, "ctl_ok")["p"]["resnapshot"] is True
        snap = _data(c, "snap", mode)
        rig.emit(*_prints(1)[0])
        delta = _data(c, "d", mode)
        meta = snap["meta"]
        assert (snap["s"], meta["reason"], meta["previous_seq"]) == (2, "reconfigure", 1)
        assert _keys(snap) == [] and delta["s"] == 3


@_FLAGS
@pytest.mark.parametrize("mode", h.MODES)
def test_contract_bars_sub_ok_waits_for_the_first_read_and_no_snap_goes_out_before_it(
    mode: str, flag: BackpressureConfig | None
) -> None:
    """#2831, #2989: `ensure` awaits the series' first read before `sub_ok`, so a hub flush, a
    re-snapshot trigger and an emission while it reads send nothing; the first frames are then
    `sub_ok` and a `snap` holding the stored bars and what the emission built on them."""
    entered, release, stored = threading.Event(), asyncio.Event(), _stored(12)

    async def read(symbol: str, spec: BarSpec, limit: int) -> BarTail:
        entered.set()
        await release.wait()  # the series is cold until the test lets its first read end
        return await stored(symbol, spec, limit)

    rig, formed = _Rig(read, flag), _prints(13)[12]
    with h.connect(rig.w) as c:
        c.send({"t": "sub", "id": "s", "p": {"topics": [{"ch": CH, "opts": {"encoding": mode}}]}})
        assert entered.wait(5.0)  # `handle_sub` is awaiting `ensure`
        flushed = rig.w.call(rig.w.hub.flush_pending)
        resnapped = rig.w.call(rig.w.hub.upstream_reconnect, h.SYM)
        rig.emit(*formed)
        rig.w.call(release.set)
        _next(c, "sub_ok")
        snap = _data(c, "snap", mode)
        assert (flushed, resnapped) == (0, 0)  # snapshots sent while the read was in flight
        assert (snap["s"], snap["meta"]["reason"]) == (1, "initial")
        want = final_bars([u for ems in _prints(13) for u in ems])
        assert _keys(snap) == [(GEN, b.index, b.closed) for b in want]
        assert rig.store.hydrated(h.SYM, SPEC.spec_hash)
        c.send({"t": "ping", "id": "p"})
        # Flag off: nothing else is queued, so the emission made no `d` of its own. Flag on: an
        # early `d` is caught by the `snap` order assertion above.
        assert c.recv()["t"] == "pong"


@_FLAGS
@pytest.mark.parametrize("mode", h.MODES)
@pytest.mark.parametrize("held", [False, True], ids=["no-ts", "ts-held"])
def test_contract_bars_snapshot_false_never_proves_continuity_so_the_attach_gets_a_snap(
    held: bool, mode: str, flag: BackpressureConfig | None
) -> None:
    """§7.6, §7.7: bars keep no delta history, so an attach that names a time the stored tail will
    cover is answered `snapshot_forced` like one that names none; its `snap` follows `sub_ok`."""
    opts = {"from_ts_ms": _prints(1)[0][0].bar.open_time // 1000} if held else {}
    rig = _Rig(_stored(12), flag)
    with h.connect(rig.w) as c:
        sub_ok, snap = _sub(c, {"encoding": mode, "from_seq": 1, **opts}, snapshot=False)
        res = sub_ok["p"]["results"][0]
        assert res["ok"] and res["snapshot_pending"] is True and res["snapshot_forced"] is True
        assert (snap["s"], snap["meta"]["reason"]) == (1, "initial")
        assert _keys(snap) == [(GEN, i, True) for i in range(3)]  # the stored bars

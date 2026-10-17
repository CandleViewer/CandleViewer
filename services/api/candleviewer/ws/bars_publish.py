"""`bars.{symbol}.{bar_type}.{param}` deltas from the bar emit path (E12-T06 slice D1b, #399;
`23-ws-protocol.md` §3.6, §6.1, §7.1, §8.2, §14.3). D2 registers `BarsPublisher` on the
`EmitRouter` after the series store (a re-snapshot reads the new generation) and calls
`note_generation` for each bars snapshot it builds.

- **Groups.** Each `include_delta` group (§6.1) with a subscriber a frame reaches (live,
  snapshotted, unpaused) is encoded and sent alone (`publish(select=...)`, `meta.include_delta`):
  one group's refusal never drops the other's.
- **Chunks.** A `d` carries its bars' structured items and, for a group with a binary subscriber,
  their kind-4 frame at `covering_scales`, so both encodings share boundaries. A chunk ends at the
  u32 time span, or before the `d` would pass `max_frame_bytes` (§3.6) in an encoding it is sent in.
- **Structured instead of binary:** an amended close (no amended bit in kind 4; A2), no instrument
  scales, or a `FrameEncodeError`.
- **Generations** (§8.2, ADR-0033, #2704). Any change, up or down, is a swap: the series' live,
  snapshotted, unpaused subscriptions are re-snapshotted (`swap_reason`), with no delta; a pending
  one keeps its reason, as under ctl. One the swap leaves pending (no snapshot yet) is retried on
  each later emission, one `build` per such subscription, so `build` must be cheap; no other
  flow's pending one is (`_left_pending`). `Subscription.announced` holds a swap's `snap` until
  the subscription's `sub_ok` is queued (#2831); only a `d` for a §7.6 continuity attach, which is
  settled at admit, can still go out before it (#2909).
  Swaps are counted; over `SWAP_STORM` per `SWAP_WINDOW_S` on a channel warns once per window with
  the real count, as one live builder per series (E12-S12) never swaps that often. A swap from the
  mixed mark (`note_generation`) logs `mixed` and no `previous` generation. Residual: a
  series with no baseline (not seen or seeded since start, or evicted) adopts the first
  generation, missing an earlier swap; a refused emission waits for the series' next snapshot.

Drops and fallbacks are counted in `bar_emit_sink_errors_total{reason}` and logged once per
(series, cause) until it clears. Bounds (C-2.18): at most `max_series` series, least recently
emitting dropped first. `emit` never awaits and does no I/O; `ws` imports `bars`, not the reverse.
"""

from __future__ import annotations

import json
import time
from collections import OrderedDict, deque
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING, Any, Final

import structlog

from candleviewer.bars.emit import BarEmission
from candleviewer.bars.errors import BarSpecError
from candleviewer.bars.leases import CAP_GLOBAL
from candleviewer.bars.metrics import bar_emit_sink_errors_total
from candleviewer.bars.models import Bar, BarSpec, BarUpdate
from candleviewer.bars.spec import WireBarType, to_wire
from candleviewer.ws._generated.cvwb_layout import HEADER, KINDS
from candleviewer.ws.bars_wire import ITEM_MAX_BYTES, bar_item, bars_frames, covering_scales
from candleviewer.ws.binary import BARS, Frame, FrameEncodeError
from candleviewer.ws.sequencing import (
    MAX_OUTBOUND_FRAME_BYTES,
    SNAP_REASONS,
    SequencingHub,
    SnapReason,
    b64_budget,
)

if TYPE_CHECKING:
    from candleviewer.ws.permissions import Subscription

#: Series tracked: twice the process-wide spec cap, so a live series is rarely the one dropped.
MAX_SERIES: Final = 2 * CAP_GLOBAL
#: Pending reasons that belong to another flow (the subscribe flow, E17's backpressure hold),
#: so a swap may not use one: the publisher only ever flushes what its own swap left pending.
_FOREIGN_REASONS: Final = frozenset({"initial", "backpressure"})
#: A baseline no emission carries (a generation is 0..`MAX_GENERATION`: `check_generation` on
#: write and on read, `_sendable` on the wire), so the next emission swaps.
_MIXED: Final = -1
#: More swaps than `SWAP_STORM` within `SWAP_WINDOW_S` on a channel warn, once per window; the
#: warning counts up to `SWAP_COUNT_CAP` of them.
SWAP_STORM: Final = 3
SWAP_WINDOW_S: Final = 60.0
SWAP_COUNT_CAP: Final = 256
#: Wider than any `s`, `ts` or `coalesced_count` an envelope carries: sizes the overhead.
_WIDEST: Final = 2**64
_RECORD_BYTES: Final = KINDS[BARS].record.size
#: cause -> (`bar_emit_sink_errors_total` reason, log level): a group dropped or sent structured.
_CAUSES: Final = {
    "item_refused": ("ws", "error"),
    "no_scales": ("ws_no_scales", "warning"),
    "binary_refused": ("ws_binary_refused", "warning"),
}

#: A symbol's `(price_scale, qty_scale)` from the instrument catalogue; `None` when unknown.
Scales = Callable[[str], tuple[int, int] | None]
Item = dict[str, Any]  # a §14.3 `bars[]` item


def _log() -> Any:
    """Resolve per call: a module-level logger pins a stale processor chain (#2008)."""
    return structlog.get_logger(__name__)


def _size(doc: Any) -> int:
    """JSON length as the gateway writes it (`sequencing._dumps`)."""
    return len(json.dumps(doc, separators=(",", ":")))


def _flow(sub: Subscription) -> bool:
    """§6.1: `include_delta` defaults to false."""
    return sub.effective.get("include_delta") is True


def _paused(sub: Subscription) -> bool:
    return sub.effective.get("paused") is True


def _live(sub: Subscription) -> bool:
    return sub.replay_session_id is None


def _settled(sub: Subscription) -> bool:
    """Live, snapshotted and unpaused, so a `d` reaches it: one a swap left pending is flushed on
    a later emission and a paused one snapshots on resume."""
    return _live(sub) and not sub.snapshot_pending and not _paused(sub)


_SELECT: Final[Mapping[bool, Callable[[Subscription], bool]]] = {
    True: _flow,
    False: lambda sub: not _flow(sub),
}
_META: Final[Mapping[bool, Mapping[str, bool]]] = {f: {"include_delta": f} for f in (True, False)}


@dataclass(slots=True)
class _Series:
    ch: str
    bar_type: WireBarType
    head: dict[str, str]  # the §14.3 topic fields of every body
    room: int  # bytes for items in a structured `d`
    records: int  # kind-4 records in a binary `d`
    generation: int | None = None  # the baseline
    faults: set[str] = field(default_factory=set)  # causes logged and not cleared since
    swaps: deque[float] = field(default_factory=lambda: deque(maxlen=SWAP_COUNT_CAP))
    stormed: float | None = None  # when the last swap-storm warning was logged


class BarsPublisher:
    """The `BarSink` described in the module docstring."""

    name = "ws"

    def __init__(
        self,
        hub: SequencingHub,
        scales: Scales,
        *,
        swap_reason: SnapReason,
        max_series: int = MAX_SERIES,
        max_frame_bytes: int = MAX_OUTBOUND_FRAME_BYTES,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if swap_reason not in SNAP_REASONS or swap_reason in _FOREIGN_REASONS:
            raise ValueError(f"{swap_reason!r} is not a swap reason")
        self._hub, self._scales, self._swap, self._max = hub, scales, swap_reason, max_series
        self._frame_bytes, self._clock = max_frame_bytes, clock
        self._series: OrderedDict[tuple[str, str], _Series] = OrderedDict()
        self._seeds: OrderedDict[tuple[str, str], int] = OrderedDict()  # bounded like `_series`

    def series_count(self) -> int:
        return len(self._series)

    def note_generation(self, symbol: str, spec: BarSpec, generation: int) -> None:
        """Seed the baseline of a series not seen yet with the generation a snapshot of it was
        built at: its first emission takes it. Seeds sit apart from the series map, so they never
        age a live series out. A baseline or seed in another generation becomes `_MIXED`, as two
        clients may now hold two: the next emission re-snapshots every one (§7.1 guarantee 3).
        A negative generation (none is valid) is the mark itself."""
        key, generation = (symbol, spec.spec_hash), max(generation, _MIXED)
        if (series := self._series.get(key)) is not None:
            series.generation = generation if series.generation == generation else _MIXED
        elif self._seeds.get(key, generation) != generation:
            self._seeds[key] = _MIXED
        if key in self._series or key in self._seeds:
            return
        self._seeds[key] = generation
        if len(self._seeds) > self._max:
            self._seeds.popitem(last=False)

    async def emit(self, emission: BarEmission) -> None:
        """Never awaits: that keeps the store's generation reset and this baseline check atomic, so
        an `await` here is a protocol change (§7.4: a generation swap is a `snap`, never a `d`)."""
        by_symbol: dict[str, list[BarUpdate]] = {}
        for u in emission.updates:
            by_symbol.setdefault(u.bar.symbol, []).append(u)
        for symbol, updates in by_symbol.items():
            series = self._series_of(symbol, emission.spec)
            if series is not None and self._current(series, emission.generation):
                self._publish(series, emission.generation, updates)

    def _series_of(self, symbol: str, spec: BarSpec) -> _Series | None:
        key = (symbol, spec.spec_hash)
        series = self._series.get(key)
        if series is not None:
            self._series.move_to_end(key)
            return series
        try:
            bar_type, param = to_wire(spec)
        except BarSpecError:
            return None  # no topic can name this series
        ch = ".".join(("bars", symbol, bar_type, param))
        head = {"symbol": symbol, "bar_type": bar_type, "param": param}
        env = {"t": "d", "ch": ch, "s": _WIDEST, "ts": _WIDEST, "meta": _META[False], "e": "b64"}
        body = {**head, "bars": [], "coalesced": False, "coalesced_count": _WIDEST}
        room = self._frame_bytes - _size({**env, "p": body})
        raw = b64_budget(self._frame_bytes, _size({**env, "p": ""})) - HEADER.size
        records = max(1, raw // _RECORD_BYTES)
        series = _Series(ch, bar_type, head, room, records, self._seeds.pop(key, None))
        self._series[key] = series
        if len(self._series) > self._max:
            self._series.popitem(last=False)
        return series

    def _current(self, series: _Series, generation: int) -> bool:
        """Apply the generation rule (module docstring); True when deltas go out."""
        last, series.generation = series.generation, generation
        if last is None or generation == last:
            return True
        self._swapped(series, last, generation)
        ch = series.ch
        self._hub.resnapshot(lambda s: s.ch == ch and _settled(s), self._swap)
        return False

    def _swapped(self, series: _Series, last: int, generation: int) -> None:
        """Count a swap and log it; past `SWAP_STORM` in a window, warn once per window."""
        now, window = self._clock(), series.swaps
        while window and now - window[0] >= SWAP_WINDOW_S:
            window.popleft()
        window.append(now)
        bar_emit_sink_errors_total.labels(reason="ws_generation_swap").inc()
        mixed = last == _MIXED  # snapshots in two generations: no one previous generation
        previous = None if mixed else last
        fields = {"ch": series.ch, "previous": previous, "mixed": mixed, "generation": generation}
        if len(window) <= SWAP_STORM:
            _log().info("ws_bars_generation_swap", **fields)
        elif series.stormed is None or now - series.stormed >= SWAP_WINDOW_S:
            series.stormed = now
            _log().warning("ws_bars_generation_swap_storm", swaps=len(window), **fields)

    def _publish(self, series: _Series, generation: int, updates: Sequence[BarUpdate]) -> None:
        groups: dict[bool, tuple[bool, bool]] = {}  # include_delta -> (binary, structured)
        waiting = False  # a subscription this series' swap left pending
        for sub in self._hub.subscriptions(series.ch):
            if not _settled(sub):  # no frame reaches it, so no variant is built for it
                waiting = waiting or self._left_pending(sub)
                continue
            flow, binary = _flow(sub), sub.effective.get("encoding") == "binary"
            had = groups.get(flow, (False, False))
            groups[flow] = (had[0] or binary, had[1] or not binary)
        bars = [u.bar for u in updates]
        amended = any(u.amended for u in updates)
        refused = False
        for flow, (binary, json_) in groups.items():
            try:
                items = _items(series, generation, updates, flow)
            except FrameEncodeError as exc:
                refused = True
                self._fault(series, "item_refused", True, include_delta=flow, reason=str(exc))
                continue
            parts = self._parts(series, generation, bars, flow) if binary and not amended else ()
            self._send(series, flow, items, parts, json_ or not parts)
        if not refused:
            self._fault(series, "item_refused", False)
        if waiting:  # the swap's snapshot could not be built then: retry it now
            ch = series.ch
            self._hub.flush_pending(lambda s: s.ch == ch and self._left_pending(s))

    def _left_pending(self, sub: Subscription) -> bool:
        """The retry's match: live, unpaused and pending with this publisher's swap reason. A
        hub-level match must never accept `initial` (the subscribe flow's hold) or `backpressure`
        (E17's hold), so `__init__` refuses both as `swap_reason` (`_FOREIGN_REASONS`)."""
        pending = sub.snapshot_pending and sub.pending_reason == self._swap
        return pending and _live(sub) and not _paused(sub)

    def _parts(self, series: _Series, gen: int, bars: list[Bar], flow: bool) -> tuple[Frame, ...]:
        scales = self._scales(series.head["symbol"])
        self._fault(series, "no_scales", scales is None)
        if scales is None:
            return ()
        ps, qs = covering_scales(
            bars, price_scale=scales[0], qty_scale=scales[1], include_delta=flow
        )
        try:
            parts = bars_frames(
                bars, generation=gen, include_delta=flow, price_scale=ps, qty_scale=qs
            )
        except FrameEncodeError as exc:  # never 1011 the connection: structured instead
            self._fault(series, "binary_refused", True, reason=str(exc))
            return ()
        self._fault(series, "binary_refused", False)
        return parts

    def _send(
        self, series: _Series, flow: bool, items: list[Item], parts: tuple[Frame, ...], json_: bool
    ) -> None:
        """One `d` per chunk: the items of a run of bars and, when binary, their records."""
        spans: list[tuple[Frame | None, int]] = [(p, len(p.records)) for p in parts]
        meta, select, start = _META[flow], _SELECT[flow], 0
        for part, n in spans or [(None, len(items))]:
            for a, b in _cuts(series, items, start, start + n, part is not None, json_):
                frame = part and replace(part, records=part.records[a - start : b - start])
                body = {**series.head, "bars": items[a:b]}
                self._hub.publish(series.ch, body, part=frame, meta=meta, select=select)
            start += n

    def _fault(self, series: _Series, cause: str, failed: bool, **fields: Any) -> None:
        """Count a failure; log a (series, cause) on its first failure since it last cleared."""
        if not failed:
            series.faults.discard(cause)
            return
        reason, level = _CAUSES[cause]
        bar_emit_sink_errors_total.labels(reason=reason).inc()
        if cause not in series.faults:
            series.faults.add(cause)
            getattr(_log(), level)(f"ws_bars_{cause}", ch=series.ch, **fields)


def _items(
    series: _Series, generation: int, updates: Sequence[BarUpdate], flow: bool
) -> list[Item]:
    kind = series.bar_type
    return [
        bar_item(u.bar, generation=generation, bar_kind=kind, include_delta=flow, amended=u.amended)
        for u in updates
    ]


def _cuts(
    series: _Series, items: list[Item], start: int, stop: int, binary: bool, json_: bool
) -> Iterator[tuple[int, int]]:
    """Runs of `items[start:stop]` whose `d` fits the frame limit in each encoding the group
    receives (§3.6; `json_`: structured frames). An item is never split, and a run short enough at
    `ITEM_MAX_BYTES` per item is not measured."""
    records = series.records if binary else stop - start
    fits = min(records, series.room // (ITEM_MAX_BYTES + 1)) if json_ else records
    if stop - start <= fits:
        yield start, stop
        return
    a, used = start, 0
    for i in range(start, stop):
        size = _size(items[i]) + 1 if json_ else 0
        if i > a and (used + size > series.room or i - a >= records):
            yield a, i
            a, used = i, 0
        used += size
    yield a, stop

"""`bars.{symbol}.{bar_type}.{param}` snapshots (E12-T06 slice D2, #2195, #399; `23-ws-protocol.md`
§3.4, §6.1, §7.6, §14.3): the `bars` family's `SnapshotSource`. It renders, with `bars_wire`, the
series a live subscription holds in the series store (`subscribe_upstream` takes the hold), and
reads no storage itself.

- **Bars.** Up to `history`, oldest first, the forming bar last with `confirm: false`; none while
  no emission or read has named a generation. `None` keeps the subscription `snapshot_pending`: a
  replay one, a series the store does not keep, or a bar neither form can carry (§3.4). One a swap
  left pending is rebuilt on every emission, so `ws_bars_snapshot_{refused,structured}` are each
  logged once per channel until a build of it succeeds (a memory reset at `MAX_SERIES` entries).
- **`meta`.** `spec_hash`, `build_version` (the lowest among the bars sent, else the running
  `BUILD_VERSIONS[kind]`) and the `include_delta` echo.
- **Encodings.** Only the form the subscription receives is built. Binary: kind-4 frames at the
  `covering_scales` of the bars sent (no bars: one empty frame). The whole snapshot goes structured
  when the instrument scales are unknown or a value does not fit kind 4 (§3.4's trigger, logged).
- **Generation.** `generation` is the store's `version`, so the render cache refreshes on every
  change; `continuity` is False (§7.6). A build hands the generation it sent to `seed`
  (`BarsPublisher.note_generation`), which makes it the publisher's baseline: an emission in any
  other generation then re-snapshots (§7.1 guarantee 3).
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any

import structlog

from candleviewer.bars.errors import BarsError
from candleviewer.bars.models import Bar, BarSpec
from candleviewer.bars.rows import BUILD_VERSIONS
from candleviewer.bars.series_store import MAX_SERIES, SeriesStore
from candleviewer.bars.spec import WireBarType, from_wire, to_wire
from candleviewer.ws.bars_publish import Scales
from candleviewer.ws.bars_wire import bar_item, bars_frames, covering_scales
from candleviewer.ws.binary import BARS, Frame, FrameEncodeError
from candleviewer.ws.sequencing import SnapshotBody
from candleviewer.ws.topics import BARS_DEFAULTS

if TYPE_CHECKING:
    from candleviewer.ws.permissions import Subscription

#: `(symbol, spec, generation)` of a built snapshot: `BarsPublisher.note_generation`.
Seed = Callable[[str, BarSpec, int], None]
Item = dict[str, Any]


def _log() -> Any:
    """Resolve per call: a module-level logger pins a stale processor chain (#2008)."""
    return structlog.get_logger(__name__)


def _series(sub: Subscription) -> tuple[str, BarSpec, WireBarType, str] | None:
    """The live series `sub` names, with its wire `bar_type` and `param`; None for a replay."""
    t = sub.topic
    if sub.replay_session_id is not None or t.symbol is None:
        return None
    try:
        spec = from_wire(t.bar_type or "", t.param or "")
        bar_type, param = to_wire(spec)
    except BarsError:
        return None  # never held: `subscribe_upstream` refuses a spec it cannot build
    return t.symbol, spec, bar_type, param


class BarsSnapshotSource:
    """The `SnapshotSource` described in the module docstring."""

    def __init__(self, store: SeriesStore, scales: Scales, *, seed: Seed | None = None) -> None:
        self._store, self._scales, self._seed = store, scales, seed
        self._logged: set[tuple[str, str]] = set()  # (ch, what) logged: module docstring

    def build(self, sub: Subscription) -> SnapshotBody | None:
        series = _series(sub)
        if series is None:
            return None
        symbol, spec, bar_type, param = series
        history = int(sub.effective.get("history", BARS_DEFAULTS["history"]))
        latest = self._store.latest(symbol, spec.spec_hash, history)
        if latest is None:
            return None
        bars = list(latest.closed)
        if latest.forming is not None:
            bars.append(latest.forming)
        gen = 0 if latest.generation is None else latest.generation  # None: no bar held yet
        flow = sub.effective.get("include_delta") is True
        build = BUILD_VERSIONS[spec.kind] if latest.oldest_build is None else latest.oldest_build
        meta = {"spec_hash": spec.spec_hash, "build_version": build, "include_delta": flow}
        head = {"symbol": symbol, "bar_type": bar_type, "param": param, "bars": []}
        body = None
        if sub.effective.get("encoding") == "binary":
            body = self._kind4(sub.ch, symbol, bars, gen, flow, head, meta)
        if body is None:
            try:
                items = [bar_item(b, generation=gen, bar_kind=bar_type, include_delta=flow)
                         for b in bars]  # fmt: skip
            except FrameEncodeError as exc:
                self._once(sub.ch, "refused", "error", reason=str(exc))
                return None
            body = SnapshotBody({**head, "bars": items}, meta=meta)
        self._logged -= {(sub.ch, "refused"), (sub.ch, "structured")}
        if latest.generation is not None and self._seed is not None:
            self._seed(symbol, spec, latest.generation)
        return body

    def _kind4(
        self, ch: str, symbol: str, bars: list[Bar], gen: int, flow: bool, head: Item, meta: Item
    ) -> SnapshotBody | None:
        """The kind-4 body, or None when §3.4's trigger sends the whole snapshot structured."""
        scales = self._scales(symbol)
        if scales is None:
            self._once(ch, "structured", "warning", cause="no_scales")
            return None
        ps, qs = covering_scales(
            bars, price_scale=scales[0], qty_scale=scales[1], include_delta=flow
        )
        try:
            parts = bars_frames(
                bars, generation=gen, include_delta=flow, price_scale=ps, qty_scale=qs
            )
        except FrameEncodeError as exc:
            self._once(ch, "structured", "warning", cause="binary_refused", reason=str(exc))
            return None
        parts = parts or (Frame(BARS, price_scale=ps, qty_scale=qs),)  # no bars: one empty frame
        return SnapshotBody(head, parts, price_scale=ps, qty_scale=qs, meta=meta)

    def _once(self, ch: str, what: str, level: str, **fields: Any) -> None:
        if (ch, what) not in self._logged:
            if len(self._logged) >= MAX_SERIES:
                self._logged.clear()
            self._logged.add((ch, what))
            getattr(_log(), level)(f"ws_bars_snapshot_{what}", ch=ch, **fields)

    def generation(self, sub: Subscription) -> int:
        series = _series(sub)
        return 0 if series is None else self._store.version(series[0], series[1].spec_hash)

    def continuity(self, sub: Subscription, from_ts_ms: int | None) -> bool:
        return False

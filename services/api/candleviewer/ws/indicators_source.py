"""`indicators.{symbol}.{bar_type}.{param}` snapshots (E13-T02, #426; `23-ws-protocol.md` §6.1,
§7.2, §7.6, §14.10): the `indicators` family's `SnapshotSource`, over the indicator engine.

- **Instances.** One per entry of the subscription's `effective.instances`, in its order, each
  with its newest `history` points (§6.1: default 500; 0 sends none), oldest first. `None` keeps
  the subscription `snapshot_pending`: a replay one (the topic is live only), or while one of its
  instances primes from stored bars; the engine's listener flushes it once that is done.
- **`stale`** (§7.2) while the injected `stale` holds, as on `bars.*`: the series' builder is
  quarantined or its trade feed is past the watchdog's limit (`ws_wiring.series_stale`, #2487);
  `generation` is negated meanwhile, so the render cache refreshes.
- **Generation** is the series' change counter in the engine, so every change refreshes the
  render cache; `continuity` is False (§7.6).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from typing import TYPE_CHECKING

from candleviewer.bars.errors import BarsError
from candleviewer.bars.models import BarSpec
from candleviewer.bars.spec import from_wire
from candleviewer.orderflow.indicators.engine import IndicatorEngine
from candleviewer.ws.indicators_publish import instance_item, instance_keys, topic_head
from candleviewer.ws.sequencing import SnapshotBody
from candleviewer.ws.topics import INDICATORS_DEFAULTS

if TYPE_CHECKING:
    from candleviewer.ws.permissions import Subscription

#: `(symbol, spec_hash) -> bool`: `BarBuilderSet.quarantined`.
Stale = Callable[[str, str], bool]


def _series(sub: Subscription) -> tuple[str, BarSpec] | None:
    """The live series `sub` names; None for a replay one or a spec no builder could serve."""
    t = sub.topic
    if sub.replay_session_id is not None or t.symbol is None:
        return None
    try:
        return t.symbol, from_wire(t.bar_type or "", t.param or "")
    except BarsError:
        return None  # never admitted: `subscribe_upstream` refuses a spec it cannot build


class IndicatorsSnapshotSource:
    """The `SnapshotSource` described in the module docstring."""

    def __init__(self, engine: IndicatorEngine, *, stale: Stale | None = None) -> None:
        self._engine, self._stale = engine, stale

    def build(self, sub: Subscription) -> SnapshotBody | None:
        series = _series(sub)
        named = None if series is None else topic_head(*series)
        if series is None or named is None:
            return None
        symbol, spec = series
        history = int(sub.effective.get("history", INDICATORS_DEFAULTS["history"]))
        items = []
        for key in instance_keys(sub):
            batch = self._engine.snapshot(symbol, key, history)
            if batch is None:
                return None
            items.append(instance_item(batch))
        body = SnapshotBody({**named[1], "instances": items})
        return replace(body, stale=True) if self._quarantined(symbol, spec) else body

    def _quarantined(self, symbol: str, spec: BarSpec) -> bool:
        return self._stale is not None and self._stale(symbol, spec.spec_hash)

    def generation(self, sub: Subscription) -> int:
        series = _series(sub)
        if series is None:
            return 0
        version = self._engine.version(series[0], series[1].spec_hash)
        return -version if self._quarantined(*series) else version

    def continuity(self, sub: Subscription, from_ts_ms: int | None) -> bool:
        return False

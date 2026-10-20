"""`indicators.{symbol}.{bar_type}.{param}` deltas from the indicator engine (E13-T02, #426;
`23-ws-protocol.md` §6.1, §7.4, §8.2, §14.10). With `bars_enabled`, `create_app` makes
`IndicatorsPublisher` the engine's listener (`IndicatorEngine.listen`).

- **Deltas.** A close's new or amended points go out in one `d` per group of subscriptions that
  name the same instances (`publish(select=...)`), so each subscriber gets its own instances, those
  with a point in that close, and no other. Structured only: the topic has no binary form.
- **Re-snapshots.** When the engine re-primes a series, its settled subscriptions (live,
  snapshotted, unpaused) re-snapshot under the engine's reason, `generation_swap` or
  `history_repair`, with no `d`; a pending one keeps its reason, a paused one snapshots on resume,
  as on `bars.*`. `ready` flushes the channel's pending subscriptions once an instance has primed:
  their snapshot (`indicators_source`) waited for it.
- **Values** (§14.10) are each output's float64 as its shortest round-trip digits in plain
  positional form, `-0` as `0`, and `null` where there is none (a non-finite value too, which no
  kernel makes).

Nothing here awaits or does I/O, and `orderflow` never imports `ws`.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Mapping
from decimal import Decimal
from typing import TYPE_CHECKING, Any, Final

from candleviewer.bars.errors import BarSpecError
from candleviewer.bars.models import BarSpec
from candleviewer.bars.spec import to_wire
from candleviewer.orderflow.indicators.engine import Batch, Point, Reprime
from candleviewer.ws.sequencing import SequencingHub

if TYPE_CHECKING:
    from candleviewer.ws.permissions import Subscription

Item = dict[str, Any]  # a §14.10 instance or point
FAMILY: Final = "indicators"


def wire_value(x: float | None) -> str | None:
    """§14.10's decimal form of a kernel value: `1e-07` is `"0.0000001"`, `-0.0` is `"0"`."""
    if x is None or not math.isfinite(x):
        return None
    if x == 0:
        return "0"
    return format(Decimal(repr(x)).normalize(), "f")


def point_item(p: Point) -> Item:
    item: Item = {
        "generation": p.generation,
        "index": p.index,
        "t_ms": p.t_us // 1_000,
        "v": [wire_value(v) for v in p.values],
    }
    if p.amended:
        item["amended"] = True
    return item


def instance_item(batch: Batch) -> Item:
    info = batch.info
    return {
        "key": info.key,
        "indicator": info.indicator,
        "params": dict(info.params),
        "outputs": list(info.outputs),
        "build_version": info.build_version,
        "points": [point_item(p) for p in batch.points],
    }


def topic_head(symbol: str, spec: BarSpec) -> tuple[str, dict[str, str]] | None:
    """The channel of a series and the §14.10 topic fields of its bodies; None when no topic can
    name the series (a spec with no wire form)."""
    try:
        bar_type, param = to_wire(spec)
    except BarSpecError:
        return None
    head = {"symbol": symbol, "bar_type": bar_type, "param": param}
    return ".".join((FAMILY, symbol, bar_type, param)), head


def instance_keys(sub: Subscription) -> tuple[str, ...]:
    """The instance keys a subscription reads, in its order (`effective.instances`, §6.1)."""
    instances = sub.effective.get("instances") or ()
    return tuple(str(i["key"]) for i in instances if isinstance(i, Mapping) and "key" in i)


def _naming(keys: tuple[str, ...]) -> Callable[[Subscription], bool]:
    """`publish`'s `select` for the subscriptions that name exactly `keys`."""
    return lambda sub: instance_keys(sub) == keys


def _settled(sub: Subscription) -> bool:
    paused = sub.effective.get("paused") is True
    return sub.replay_session_id is None and not sub.snapshot_pending and not paused


class IndicatorsPublisher:
    """The engine listener described in the module docstring."""

    def __init__(self, hub: SequencingHub) -> None:
        self._hub = hub

    def points(self, symbol: str, spec: BarSpec, batches: Mapping[str, Batch]) -> None:
        named = topic_head(symbol, spec)
        if named is None:
            return
        ch, head = named
        groups = dict.fromkeys(
            instance_keys(sub) for sub in self._hub.subscriptions(ch) if _settled(sub)
        )
        for keys in groups:
            items = [instance_item(batches[k]) for k in keys if k in batches]
            if items:
                body = {**head, "instances": items}
                self._hub.publish(ch, body, select=_naming(keys))

    def resnapshot(self, symbol: str, spec: BarSpec, reason: Reprime) -> None:
        named = topic_head(symbol, spec)
        if named is not None:
            ch = named[0]
            self._hub.resnapshot(lambda s: s.ch == ch and _settled(s), reason)

    def ready(self, symbol: str, spec: BarSpec) -> None:
        named = topic_head(symbol, spec)
        if named is not None:
            ch = named[0]
            self._hub.flush_pending(lambda s: s.ch == ch and s.replay_session_id is None)

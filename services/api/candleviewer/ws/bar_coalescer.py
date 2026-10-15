"""Bars-topic coalescer (`23-ws-protocol.md` §8.2, #2018).

Pure, bounded state: pending bar items are keyed by ``(generation, index)``
— never by ``t_ms`` (non-time bars share open times). Last write wins, except
a confirmed bar is never replaced by an unconfirmed one, and a confirmed bar
is replaced by another confirmed bar only when the incoming item sets
``amended`` (late-trade re-close, 24 §3.2).

Unconsumed until the publisher wiring lands (E17 gateway fan-out, epic #32;
bar emit source #2031).
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

BarKey = tuple[int, int]
BarItem = Mapping[str, Any]


def bar_key(item: BarItem) -> BarKey:
    """Return the coalescing key; `generation` and `index` are required."""
    return (int(item["generation"]), int(item["index"]))


class BarCoalescer:
    """Accumulates bar updates between flushes; the flush keeps final state exact."""

    def __init__(self, max_pending: int = 4096) -> None:
        self._max = max_pending
        self._pending: dict[BarKey, dict[str, Any]] = {}
        self._count = 0
        self.overflowed = False

    def add(self, item: BarItem) -> bool:
        """Keep `item` unless a confirmed bar outranks it or the bound refuses it; True if kept."""
        key = bar_key(item)
        self._count += 1
        cur = self._pending.get(key)
        if cur is not None and cur.get("confirm"):
            if not item.get("confirm"):
                return False
            if not item.get("amended"):
                return False
        elif cur is None and len(self._pending) >= self._max:
            self.overflowed = True  # caller must drop pending + force re-snapshot (§8.3)
            return False
        self._pending[key] = dict(item)
        return True

    def flush(self) -> tuple[list[dict[str, Any]], int]:
        """Return (items ordered by key, coalesced_count) and reset pending state."""
        items = [self._pending[k] for k in sorted(self._pending)]
        count = self._count
        self._pending = {}
        self._count = 0
        return items, count

    def take_overflow(self) -> bool:
        """Return and clear the overflow flag.

        When True, updates were refused: the caller MUST discard the flushed
        batch, mark the topic ``resnapshot_required`` and send a fresh snapshot
        (§8.3) — the pending state no longer equals the applied stream.
        """
        flag = self.overflowed
        self.overflowed = False
        return flag

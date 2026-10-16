"""Per-connection backpressure configuration (E17-T03, `23-ws-protocol.md` §4.3, §8.3, §8.4).

`BackpressureConfig` is what the composition root hands `make_ws_router` while
`CV_WS_BACKPRESSURE_ENABLED` is on: the outbound budget (`max_bytes` or `max_frames`, whichever
binds first) and the cadence of the adaptive classification. Without one (`None`, the default) the
gateway keeps today's 1 024-frame push bound: the flag swaps the bounding mechanism and never
removes the bound (C-2.18).

The defaults are the contract values. `Settings` owns the ceilings (the same numbers as `le=`: the
budget may be lowered, never raised, D10), so this class only holds values and a harness may build
one with a small budget. Plain data: no I/O, no clock.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from candleviewer.ws.outbound import QUEUE_BYTES, QUEUE_FRAMES
from candleviewer.ws.pacing import CLASSIFY_INTERVAL_S

if TYPE_CHECKING:
    from candleviewer.settings import Settings


@dataclass(frozen=True, slots=True)
class BackpressureConfig:
    """One connection's outbound budget (§8.4) and classification cadence (§8.3)."""

    max_bytes: int = QUEUE_BYTES
    max_frames: int = QUEUE_FRAMES
    classify_interval_ms: int = round(CLASSIFY_INTERVAL_S * 1000)

    @classmethod
    def from_settings(cls, settings: Settings) -> BackpressureConfig:
        """The three `CV_WS_*` budget settings, already range-checked by `Settings`."""
        return cls(
            max_bytes=settings.ws_queue_bytes,
            max_frames=settings.ws_queue_frames,
            classify_interval_ms=settings.ws_classify_interval_ms,
        )

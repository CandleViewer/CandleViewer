"""Per-connection backpressure configuration (E17-T03, `23-ws-protocol.md` §4.3, §8.3, §8.4).

`BackpressureConfig` is what the composition root hands `make_ws_router` while
`CV_WS_BACKPRESSURE_ENABLED` is on: the outbound budget (`max_bytes` or `max_frames`, whichever
binds first), the cadence of the adaptive classification and the close flush deadline. Without one
(`None`, the default) the gateway keeps today's 1 024-frame push bound: the flag swaps the bounding
mechanism and never removes the bound (C-2.18).

The defaults are the contract values. A config is checked as it is built and fails closed with
`ValueError` (C-2.18, WS-D01), so no consumer runs on an unchecked budget, hand-built or not:
`max_bytes` and `max_frames` are `int`s above zero and at most `QUEUE_BYTES` and `QUEUE_FRAMES`,
the ceilings `Settings` gives as `le=` (the budget may be lowered, never raised, E17 threat model
§6), and `classify_interval_ms` is an `int` above zero. The floors stay with `Settings`, so a
harness may build a small budget. The close deadline, which `Settings` never sets, may only be
lowered too, because the stop budget counts `CLOSE_FLUSH_TIMEOUT_S`. Plain data: no I/O, no clock.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from candleviewer.settings import CLOSE_FLUSH_TIMEOUT_S
from candleviewer.ws.outbound import QUEUE_BYTES, QUEUE_FRAMES
from candleviewer.ws.pacing import CLASSIFY_INTERVAL_S

if TYPE_CHECKING:
    from candleviewer.settings import Settings


@dataclass(frozen=True, slots=True)
class BackpressureConfig:
    """One connection's outbound budget (§8.4), classification cadence (§8.3) and close flush
    deadline (§4.4)."""

    max_bytes: int = QUEUE_BYTES
    max_frames: int = QUEUE_FRAMES
    classify_interval_ms: int = round(CLASSIFY_INTERVAL_S * 1000)
    #: Seconds a closing connection may spend flushing, from its close on (§8.4). Lower only:
    #: `settings.MIN_DRAIN_TIMEOUT_S` and the stop budget count `CLOSE_FLUSH_TIMEOUT_S` once.
    close_flush_s: float = CLOSE_FLUSH_TIMEOUT_S

    def __post_init__(self) -> None:
        if not 0 < self.close_flush_s <= CLOSE_FLUSH_TIMEOUT_S:
            raise ValueError(
                f"close_flush_s must lie in (0, {CLOSE_FLUSH_TIMEOUT_S:g}] s: the stop budget "
                "counts the close flush, so it may only be lowered"
            )
        # Fail closed: an `int` (never a `bool` or a `float`), above zero, at most its ceiling.
        for name, value, ceiling in (
            ("max_bytes", self.max_bytes, QUEUE_BYTES),
            ("max_frames", self.max_frames, QUEUE_FRAMES),
            ("classify_interval_ms", self.classify_interval_ms, None),
        ):
            if type(value) is not int or value <= 0 or (ceiling is not None and value > ceiling):
                bound = "above 0" if ceiling is None else f"in (0, {ceiling}] (lower only)"
                raise ValueError(f"{name} must be an int {bound}")

    @classmethod
    def from_settings(cls, settings: Settings) -> BackpressureConfig:
        """The three `CV_WS_*` budget settings, already range-checked by `Settings`."""
        return cls(
            max_bytes=settings.ws_queue_bytes,
            max_frames=settings.ws_queue_frames,
            classify_interval_ms=settings.ws_classify_interval_ms,
        )

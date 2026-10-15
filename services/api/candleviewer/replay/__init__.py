"""replay module (M12).

Deterministic replay clock, scrubbing, speed control.

Public interface only — internal implementation modules are not re-exported.
Allowed dependencies (CONSTITUTION.md C-3.1): M1, M5, M8, M9, M10.

E26-T02 adds the replay read path: the validated `ReplayRequest`, the in-stream `ReplayGap`
marker, the storage ports (`ReplayTiers`), the typed errors and `ReplaySource`, the ordered,
bounded read the replay clock (E26-T03) and seek engine (E26-T04) consume.

E26-T03 adds `ReplayClock`, the paced playback of one session, and the playback ports it drives:
`MonotonicTime` (production `LoopTime`), the `ReplaySink` it delivers to, the `PlaybackObserver`
it reports gaps, backpressure and stops to, and `ClockConfig`.
"""

from __future__ import annotations

from candleviewer.replay.clock import ReplayClock
from candleviewer.replay.errors import (
    ReplayClockStateError,
    ReplayError,
    ReplayMemoryCeilingExceeded,
    ReplayRequestInvalid,
    ReplaySourceUnavailable,
    ReplayTierStraddle,
    ReplayWindowTooLarge,
)
from candleviewer.replay.models import ReplayGap, ReplayItem, ReplayRequest, ReplayTiers, SourceTier
from candleviewer.replay.playback import (
    STEP,
    UNBOUNDED,
    ClockConfig,
    GapPolicy,
    LoopTime,
    MonotonicTime,
    PlaybackObserver,
    PlaybackStats,
    ReplaySink,
    ReplayStream,
    StopReason,
    check_speed,
)
from candleviewer.replay.source import ReadAheadConfig, ReplaySource

__all__ = [
    "STEP",
    "UNBOUNDED",
    "ClockConfig",
    "GapPolicy",
    "LoopTime",
    "MonotonicTime",
    "PlaybackObserver",
    "PlaybackStats",
    "ReadAheadConfig",
    "ReplayClock",
    "ReplayClockStateError",
    "ReplayError",
    "ReplayGap",
    "ReplayItem",
    "ReplayMemoryCeilingExceeded",
    "ReplayRequest",
    "ReplayRequestInvalid",
    "ReplaySink",
    "ReplaySource",
    "ReplaySourceUnavailable",
    "ReplayStream",
    "ReplayTierStraddle",
    "ReplayTiers",
    "ReplayWindowTooLarge",
    "SourceTier",
    "StopReason",
    "check_speed",
]

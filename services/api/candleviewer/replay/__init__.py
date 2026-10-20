"""replay module (M12).

Deterministic replay clock, scrubbing, speed control.

Public interface only — internal implementation modules are not re-exported.
Allowed dependencies (CONSTITUTION.md C-3.1): M1, M5, M8, M9, M10.

E26-T02 adds the replay read path: the validated `ReplayRequest`, the in-stream `ReplayGap`
marker, the storage ports (`ReplayTiers`), the typed errors and `ReplaySource`, the ordered,
bounded read-ahead the replay clock (E26-T03) and seek engine (E26-T04) consume.

E26-T03 adds `ReplayClock`, the paced playback of one session, and the playback ports it drives:
`MonotonicTime` (production `LoopTime`), the `ReplaySink` it delivers to, the `PlaybackObserver`
it reports gaps, backpressure and stops to, the `BarProbe` behind `step_bar`, and `ClockConfig`.
`RegroupedStream` wraps the stream the clock reads so that one book update is one event, and
`ReplayInjector`, the clock's sink, re-emits each recorded event as its live type on the
session's own bus namespace: trades on the bus, book events through a `ReplayBookHook` into the
session's replay-scoped book, built from the `LiveEventModels` the composition root hands in.
`ReplayRun` is one session's playback: it opens the session's sources (a `SourceFactory`), owns
the clock and its driver in one structured scope, wraps the loop and reports to the session
layer through a `ReplayRunPort`.
"""

from __future__ import annotations

from candleviewer.replay.clock import ReplayClock
from candleviewer.replay.errors import (
    ReplayClockStateError,
    ReplayConfigInvalid,
    ReplayError,
    ReplayEventRefused,
    ReplayInternalError,
    ReplayLoopStartUnknown,
    ReplayMemoryCeilingExceeded,
    ReplayPriceOffGrid,
    ReplayRequestInvalid,
    ReplaySourceUnavailable,
    ReplayTickSizeMissing,
    ReplayTierStraddle,
)
from candleviewer.replay.injector import (
    REEMITTED_STREAMS,
    LiveEventModels,
    ReplayBookHook,
    ReplayInjector,
)
from candleviewer.replay.models import ReplayGap, ReplayItem, ReplayRequest, ReplayTiers, SourceTier
from candleviewer.replay.playback import (
    STEP,
    UNBOUNDED,
    BarProbe,
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
from candleviewer.replay.regroup import RegroupedStream
from candleviewer.replay.runner import ReplayRun, ReplayRunPort, SourceFactory
from candleviewer.replay.source import ReadAheadConfig, ReplaySource

__all__ = [
    "REEMITTED_STREAMS",
    "STEP",
    "UNBOUNDED",
    "BarProbe",
    "ClockConfig",
    "GapPolicy",
    "LiveEventModels",
    "LoopTime",
    "MonotonicTime",
    "PlaybackObserver",
    "PlaybackStats",
    "ReadAheadConfig",
    "RegroupedStream",
    "ReplayBookHook",
    "ReplayClock",
    "ReplayClockStateError",
    "ReplayConfigInvalid",
    "ReplayError",
    "ReplayEventRefused",
    "ReplayGap",
    "ReplayInjector",
    "ReplayInternalError",
    "ReplayItem",
    "ReplayLoopStartUnknown",
    "ReplayMemoryCeilingExceeded",
    "ReplayPriceOffGrid",
    "ReplayRequest",
    "ReplayRequestInvalid",
    "ReplayRun",
    "ReplayRunPort",
    "ReplaySink",
    "ReplaySource",
    "ReplaySourceUnavailable",
    "ReplayStream",
    "ReplayTickSizeMissing",
    "ReplayTierStraddle",
    "ReplayTiers",
    "SourceFactory",
    "SourceTier",
    "StopReason",
    "check_speed",
]

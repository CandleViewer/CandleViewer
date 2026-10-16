"""replay module (M12).

Deterministic replay clock, scrubbing, speed control.

Public interface only — internal implementation modules are not re-exported.
Allowed dependencies (CONSTITUTION.md C-3.1): M1, M5, M8, M9, M10.

E26-T02 adds the replay read path: the validated `ReplayRequest`, the in-stream `ReplayGap`
marker, the storage ports (`ReplayTiers`) and the typed errors; the ordered source that the
replay clock (E26-T03) and seek engine (E26-T04) consume is built on them.
"""

from __future__ import annotations

from candleviewer.replay.errors import (
    ReplayConfigInvalid,
    ReplayError,
    ReplayMemoryCeilingExceeded,
    ReplayRequestInvalid,
    ReplaySourceUnavailable,
    ReplayTierStraddle,
)
from candleviewer.replay.models import ReplayGap, ReplayItem, ReplayRequest, ReplayTiers, SourceTier

__all__ = [
    "ReplayConfigInvalid",
    "ReplayError",
    "ReplayGap",
    "ReplayItem",
    "ReplayMemoryCeilingExceeded",
    "ReplayRequest",
    "ReplayRequestInvalid",
    "ReplaySourceUnavailable",
    "ReplayTierStraddle",
    "ReplayTiers",
    "SourceTier",
]

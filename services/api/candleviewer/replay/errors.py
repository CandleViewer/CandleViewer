"""Domain errors for the replay module (M12).

Each error carries a stable `code`; the HTTP edge (E26-T05) maps them to problem responses.
Messages name streams and limits, never recorded values.
"""

from __future__ import annotations

from collections.abc import Sequence

from candleviewer.storage.models import StreamKind, TimeRange


class ReplayError(Exception):
    """Base exception for the M12 `replay` module."""

    code: str = "REPLAY_ERROR"


class ReplayRequestInvalid(ReplayError, ValueError):
    """A replay read was asked for something outside the session (symbol, instant, window)."""

    code = "REPLAY_REQUEST_INVALID"


class ReplayWindowTooLarge(ReplayRequestInvalid):
    """The window exceeds the source's span cap (defence in depth behind E26-T01's
    `CV_REPLAY_MAX_WINDOW_HOURS`), so a crafted request cannot scan the whole lake."""

    code = "REPLAY_WINDOW_TOO_LARGE"


class ReplayClockStateError(ReplayError):
    """A clock control call its current state does not allow: playing at speed 0, a step while
    playing, playing while a stop is still in progress, or any call after the clock closed."""

    code = "REPLAY_CLOCK_STATE"


class ReplayMemoryCeilingExceeded(ReplayError):
    """The per-session memory budget cannot hold even the smallest read of one stream: the
    replay stops with this error instead of growing memory (ticket E26-T02)."""

    code = "REPLAY_MEMORY_CEILING_EXCEEDED"

    def __init__(self, *, budget_bytes: int, symbol: str, stream: StreamKind) -> None:
        super().__init__(
            f"replay memory budget of {budget_bytes} bytes cannot hold one read of "
            f"{stream.value} for {symbol}"
        )
        self.budget_bytes = budget_bytes
        self.symbol = symbol
        self.stream = stream


class ReplaySourceUnavailable(ReplayError):
    """A storage read failed or timed out. `reason` is the storage error code or `timeout`;
    nothing after the failure point is emitted (no silent skip)."""

    code = "REPLAY_SOURCE_UNAVAILABLE"

    def __init__(self, *, tier: str, symbol: str, stream: StreamKind | None, reason: str) -> None:
        what = stream.value if stream is not None else "recording_gaps"
        super().__init__(f"replay read of {what} for {symbol} from {tier} failed: {reason}")
        self.tier = tier
        self.symbol = symbol
        self.stream = stream
        self.reason = reason


class ReplayTierStraddle(ReplayError):
    """`source_tier="auto"` found the range only partly archived to Parquet. A session never
    mixes tiers (ADR-0035 decision 4) and neither tier alone is known to hold the whole range,
    so the replay is refused before any event instead of replaying a hole. `symbol`/`stream` is
    the first stream whose range is not wholly archived and `archived` what Parquet covers of
    it, the true available range (C-2.14): replay from one tier, or split at the archive edge."""

    code = "REPLAY_TIER_STRADDLE"

    def __init__(self, *, symbol: str, stream: StreamKind, archived: Sequence[TimeRange]) -> None:
        super().__init__(
            "source_tier auto found the replay range only partly archived to Parquet "
            f"(first mismatch: {stream.value} of {symbol}); one session never mixes tiers"
        )
        self.symbol = symbol
        self.stream = stream
        self.archived = tuple(archived)

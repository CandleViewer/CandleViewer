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


class ReplayRequestInvalid(ReplayError):
    """A replay request breaks one of `ReplayRequest`'s bounds (symbols, streams, window,
    depth, tier, the window cap). The message names the fields at fault, never a value.

    Deliberately not a `ValueError`: pydantic folds a `ValueError` raised during validation
    into its own `ValidationError`, so the request could not raise this type."""

    code = "REPLAY_REQUEST_INVALID"


class ReplayConfigInvalid(ReplayError, ValueError):
    """A replay read was configured outside its bounds (read windows, storage timeout, memory
    budget): a composition bug, refused before any storage read rather than looping or
    waiting without a bound."""

    code = "REPLAY_CONFIG_INVALID"


class ReplayMemoryCeilingExceeded(ReplayError):
    """A read cannot fit the replay's bounds, so the replay stops with this error instead of
    growing memory (ticket E26-T02): the per-session byte budget cannot hold even the smallest
    read of one stream, or one instant (one µs) holds more rows than the per-read row ceiling.

    `max_rows` is that ceiling when it, not the byte budget, bound the read, so a larger budget
    would not help; otherwise `None`. `stream` is `None` for one symbol's `recording_gaps` read,
    which is bounded by rows only and refused whole rather than reported in part."""

    code = "REPLAY_MEMORY_CEILING_EXCEEDED"

    def __init__(
        self,
        *,
        budget_bytes: int,
        symbol: str,
        stream: StreamKind | None,
        max_rows: int | None = None,
    ) -> None:
        what = stream.value if stream is not None else "recording_gaps"
        bound = (
            f"replay memory budget of {budget_bytes} bytes"
            if max_rows is None
            else f"replay row ceiling of {max_rows} rows per read"
        )
        super().__init__(f"{bound} cannot hold one read of {what} for {symbol}")
        self.budget_bytes = budget_bytes
        self.symbol = symbol
        self.stream = stream
        self.max_rows = max_rows


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

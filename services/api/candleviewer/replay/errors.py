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
    """A replay read was configured or used outside its bounds (read windows, storage timeout,
    memory and read-ahead budgets, a single-pass merge read twice): a composition bug, refused
    before any storage read rather than looping, waiting without a bound or skipping events."""

    code = "REPLAY_CONFIG_INVALID"


class ReplayClockStateError(ReplayError):
    """A clock control call its current state does not allow: playing at speed 0, a step while
    playing, playing while a stop is still in progress, or any call after the clock closed."""

    code = "REPLAY_CLOCK_STATE"


class ReplayEventRefused(ReplayError):
    """The injector (E26-T03) refused an item it does not re-emit: a gap marker, a stream whose
    derivations 24 Sec.13.7 does not list, a book row the stream adapter did not regroup, a
    symbol outside the session, or a recorded event that does not fit the live event model.
    A bug or corrupt data, never skipped: playback stops at it. The message names the stream and
    the fields at fault, never a recorded value."""

    code = "REPLAY_EVENT_REFUSED"


class ReplayTickSizeMissing(ReplayError):
    """A session symbol has no tick size pinned from the instrument-info cache, so its prices
    cannot be put on a grid: the injector, and so the session, is refused at creation (24
    Sec.13.7 `price_ticks`)."""

    code = "REPLAY_TICK_SIZE_MISSING"

    def __init__(self, *, symbols: Sequence[str]) -> None:
        super().__init__(f"no pinned tick size for {', '.join(symbols)}: the replay is refused")
        self.symbols = tuple(symbols)


class ReplayPriceOffGrid(ReplayError):
    """A recorded price is not a whole number of ticks of the session's pinned tick size (the
    grid changed after the recording, #3806). The replay stops at that event, after every event
    before it, and never rounds (24 Sec.13.7 `price_ticks`). Names the stream, not the price."""

    code = "REPLAY_PRICE_OFF_GRID"

    def __init__(self, *, symbol: str, stream: StreamKind) -> None:
        super().__init__(
            f"a recorded {stream.value} price of {symbol} is off the session's pinned tick grid"
        )
        self.symbol = symbol
        self.stream = stream


class ReplayLoopStartUnknown(ReplayError):
    """A loop restart was asked before playback reached the loop start since it was configured,
    so the injector does not know where the loop begins: seek there instead (E26-T04)."""

    code = "REPLAY_LOOP_START_UNKNOWN"

    def __init__(self) -> None:
        super().__init__("playback has not reached the loop start: seek to it instead")


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


class ReplayInternalError(ReplayError):
    """The read failed for a reason that is no typed replay failure: a bug, a reader that broke
    the port's contract by raising something that is neither a storage error nor a timeout, or a
    producer cancelled by anyone but the source's own close. `ReplaySource` raises this in its
    place with a fixed text and nothing of the original (which can carry a path or a value,
    RP-I02); the original is logged by type."""

    code = "REPLAY_INTERNAL_ERROR"

    def __init__(self) -> None:
        super().__init__("the replay read failed unexpectedly")


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

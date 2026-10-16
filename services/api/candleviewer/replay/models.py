"""Replay request, in-stream gap marker and storage ports (E26-T02)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Final, Literal

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    ModelWrapValidatorHandler,
    ValidationError,
    field_validator,
    model_validator,
)

from candleviewer.domain.primitives import Symbol
from candleviewer.domain.sql_names import EPOCH
from candleviewer.replay.errors import ReplayRequestInvalid
from candleviewer.storage.models import StreamKind
from candleviewer.storage.repositories.recorded import (
    REPLAYABLE_STREAMS,
    ManifestCoverage,
    RecordedEvent,
    RecordedStreamReader,
    RecordingGapReader,
)

#: `replay_sessions.source_tier` (21 Sec.3.6.4 `rps_tier`). Internal and operator-only: the
#: client contract `CreateReplaySessionRequest` (22-api) has no such field, so every client
#: session reads `auto` (RP-T07).
SourceTier = Literal["auto", "questdb", "parquet"]

US_PER_HOUR: Final = 3_600_000_000
#: Default of `ReplayRequest.max_span_us`: the default of E26-T01's `CV_REPLAY_MAX_WINDOW_HOURS`
#: (24 h), which owns the cap. Only a default: callers pass the configured value.
DEFAULT_MAX_SPAN_US: Final = 24 * US_PER_HOUR
_ONE_US = timedelta(microseconds=1)


def to_us(moment: datetime) -> int:
    """Exact epoch microseconds of an aware datetime (integer arithmetic, no float rounding)."""
    return (moment - EPOCH) // _ONE_US


class ReplayRequest(BaseModel):
    """What one replay read covers: `symbols` x `streams` over `[start, end)` at one recorded
    book depth, from `source_tier`. Bounds mirror `CreateReplaySessionRequest` (22-api).

    The window cap has one source of truth, E26-T01's `CV_REPLAY_MAX_WINDOW_HOURS` (bounded in
    `settings.py`): the caller passes it in µs as `max_span_us`, defaulting to the setting's
    default of 24 h, so a window the session service accepted is never refused here and a
    crafted request still cannot scan the whole lake (ticket security notes). Every refusal,
    the cap included, raises `ReplayRequestInvalid` naming the fields at fault, never a value.

    `source_tier` is internal and operator-only (see `SourceTier`, RP-T07)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    symbols: tuple[Symbol, ...] = Field(min_length=1, max_length=8)
    streams: tuple[StreamKind, ...] = Field(min_length=1)
    start: AwareDatetime
    end: AwareDatetime
    depth: Literal[1, 50, 200, 500] = 200
    source_tier: SourceTier = "auto"
    max_span_us: int = Field(default=DEFAULT_MAX_SPAN_US, gt=0, strict=True)

    @model_validator(mode="wrap")
    @classmethod
    def _typed_refusal(
        cls, data: object, handler: ModelWrapValidatorHandler[ReplayRequest]
    ) -> ReplayRequest:
        """Pydantic's own refusals leave as `ReplayRequestInvalid`, not a `ValidationError`.
        Raised after the handler, so no exception context keeps the refused input."""
        try:
            return handler(data)
        except ValidationError as exc:
            faults: dict[str, set[str]] = {}
            for err in exc.errors():
                faults.setdefault(_field(err["loc"]), set()).add(err["type"])
        detail = "; ".join(f"{name} ({', '.join(sorted(kinds))})" for name, kinds in faults.items())
        raise ReplayRequestInvalid(f"invalid replay request: {detail}")

    @field_validator("symbols")
    @classmethod
    def _unique_symbols(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(set(value)) != len(value):
            raise ReplayRequestInvalid("invalid replay request: symbols must be unique")
        return value

    @field_validator("streams")
    @classmethod
    def _replayable_streams(cls, value: tuple[StreamKind, ...]) -> tuple[StreamKind, ...]:
        if len(set(value)) != len(value):
            raise ReplayRequestInvalid("invalid replay request: streams must be unique")
        if any(stream not in REPLAYABLE_STREAMS for stream in value):
            raise ReplayRequestInvalid(
                "invalid replay request: streams must be recorded streams (derived data is "
                "rebuilt, never replayed)"
            )
        return value

    @model_validator(mode="after")
    def _ordered_and_bounded(self) -> ReplayRequest:
        span_us = self.end_us - self.start_us
        if span_us <= 0:
            raise ReplayRequestInvalid("invalid replay request: end must be after start")
        if span_us > self.max_span_us:
            raise ReplayRequestInvalid(
                f"invalid replay request: the window exceeds the {self.max_span_us} µs cap"
            )
        return self

    @property
    def start_us(self) -> int:
        return to_us(self.start)

    @property
    def end_us(self) -> int:
        return to_us(self.end)


def _field(loc: tuple[int | str, ...]) -> str:
    return str(loc[0]) if loc else "request"


@dataclass(frozen=True, slots=True)
class ReplayGap:
    """In-stream control marker: `stream` of `symbol` has no recorded data in
    `[gap_start_us, gap_end_us)` because of `cause` (the stored value, never relabelled).

    Emitted at `ts_us`, the gap start clipped to the window start, before the market events of
    that instant. Not a market event: the injector (E26-T03) must never publish it on a
    market-data topic."""

    ts_us: int
    symbol: str
    stream: StreamKind
    gap_start_us: int
    gap_end_us: int
    cause: str


type ReplayItem = RecordedEvent | ReplayGap


@dataclass(frozen=True, slots=True)
class ReplayTiers:
    """The storage ports a replay reads through, injected by the composition root.
    `coverage` is the cold tier's manifest view that `source_tier="auto"` routes on."""

    hot: RecordedStreamReader
    cold: RecordedStreamReader
    coverage: ManifestCoverage
    gaps: RecordingGapReader

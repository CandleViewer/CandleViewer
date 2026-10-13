"""Replay request, in-stream gap marker, storage ports and read-ahead bounds (E26-T02)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Final, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator, model_validator

from candleviewer.domain.primitives import Symbol
from candleviewer.domain.sql_names import EPOCH
from candleviewer.storage.models import StreamKind
from candleviewer.storage.repositories.recorded import (
    REPLAYABLE_STREAMS,
    ArchiveCoverage,
    RecordedEvent,
    RecordedStreamReader,
    RecordingGapReader,
)

#: `replay_sessions.source_tier` (21 Sec.3.6.4 `rps_tier`).
SourceTier = Literal["auto", "questdb", "parquet"]

_ONE_US = timedelta(microseconds=1)
#: Hard ceiling on one request's window: E26-T01's `CV_REPLAY_MAX_WINDOW_HOURS` default (24).
MAX_REPLAY_SPAN: Final = timedelta(hours=24)


def to_us(moment: datetime) -> int:
    """Exact epoch microseconds of an aware datetime (integer arithmetic, no float rounding)."""
    return (moment - EPOCH) // _ONE_US


class ReplayRequest(BaseModel):
    """What one `ReplaySource` reads: `symbols` x `streams` over `[start, end)` at one recorded
    book depth, from `source_tier`. Bounds mirror `CreateReplaySessionRequest` (22-api).

    The window is capped at three points, so a crafted request cannot scan the whole lake (ticket
    security notes): E26-T01's session service applies `CV_REPLAY_MAX_WINDOW_HOURS` first
    (configurable, default 24); this model refuses any window over `MAX_REPLAY_SPAN` (24 h);
    and `ReplaySource` refuses one over its `ReadAheadConfig.max_span_us` (default 24 h) with
    `ReplayWindowTooLarge` before any read."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    symbols: tuple[Symbol, ...] = Field(min_length=1, max_length=8)
    streams: tuple[StreamKind, ...] = Field(min_length=1)
    start: AwareDatetime
    end: AwareDatetime
    depth: Literal[1, 50, 200, 500] = 200
    source_tier: SourceTier = "auto"

    @field_validator("symbols")
    @classmethod
    def _unique_symbols(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(set(value)) != len(value):
            raise ValueError("symbols must be unique")
        return value

    @field_validator("streams")
    @classmethod
    def _replayable_streams(cls, value: tuple[StreamKind, ...]) -> tuple[StreamKind, ...]:
        if len(set(value)) != len(value):
            raise ValueError("streams must be unique")
        derived = sorted(s.value for s in value if s not in REPLAYABLE_STREAMS)
        if derived:
            raise ValueError(f"not recorded streams: {derived}")
        return value

    @model_validator(mode="after")
    def _ordered_and_bounded(self) -> ReplayRequest:
        if self.end <= self.start:
            raise ValueError("end must be after start")
        if self.end - self.start > MAX_REPLAY_SPAN:
            raise ValueError("the replay window exceeds the 24 h cap")
        return self

    @property
    def start_us(self) -> int:
        return to_us(self.start)

    @property
    def end_us(self) -> int:
        return to_us(self.end)


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
    coverage: ArchiveCoverage
    gaps: RecordingGapReader

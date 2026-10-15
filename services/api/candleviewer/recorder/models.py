"""Domain models for the recorder module (M11) — E16-T02 recording policy, E16-T07 disk budget.

`RecorderSetChanged` is the bus contract in `docs/plan/24-internal-schemas.md` §13.1 and
`DiskPressureChanged` the one in §13.4.1; `StorageUsage` mirrors the OpenAPI schema.
"""

from __future__ import annotations

from enum import IntEnum
from typing import Final, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

Reason = Literal["manual", "position_open", "chart_open"]

#: Precedence, highest first (ADR-0015 / E16-T02): manual > position_open > chart_open.
PRECEDENCE: Final[tuple[Reason, ...]] = ("manual", "position_open", "chart_open")

#: Eviction priority consumed by the E16-T07 ladder: higher survives longer.
PRIORITY: Final[dict[Reason, int]] = {"manual": 300, "position_open": 200, "chart_open": 100}


class Actor(BaseModel):
    """Who caused a recorder action (audit `actor`, C-2.9). Never an empty id."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: Literal["user", "system"]
    id: str = Field(min_length=1, max_length=128, pattern=r"^\S+$")


#: The policy's own principal for automatic (chart/position/grace) transitions.
SYSTEM_ACTOR: Final = Actor(kind="system", id="recorder-policy")


class EffectiveEntry(BaseModel):
    """One symbol in the effective recorded set."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    symbol: str
    reason: Reason
    reasons: tuple[Reason, ...]
    priority: int
    #: `False` for manual entries: exempt from the E16-T07 auto-eviction ladder.
    auto_evictable: bool
    #: In the stop grace window (B11 `lingering`): still recording.
    lingering: bool
    pinned: bool
    streams: tuple[str, ...] = ()
    depth: int | None = None


class RecorderSetChanged(BaseModel):
    """Published on `{env}.recorder.set_changed` when the effective set changes."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    symbol: str
    change: Literal["added", "removed", "reason_changed"]
    reason: Reason
    reasons: tuple[Reason, ...]
    priority: int
    auto_evictable: bool
    ts_event: int


class RecorderCapRefused(BaseModel):
    """Warning event on `{env}.recorder.cap_refused`: a desired start was refused by
    `CV_RECORDER_MAX_SYMBOLS`; it stays queued and is retried every tick."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    symbol: str
    reason: Reason
    ts_event: int


class DiskPressureLevel(IntEnum):
    """The E16-T07 ladder (24-internal-schemas §13.4.1): a plain enum, never an interpreter."""

    NORMAL = 0
    WARN = 1
    AUTOSTOP = 2
    HALT = 3


class DiskPressureChanged(BaseModel):
    """Published on `{env}.recorder.disk_pressure` on every level / acceleration change."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    level: DiskPressureLevel
    previous: DiskPressureLevel
    accelerate_retention: bool
    used_bytes: int = Field(ge=0)
    cap_bytes: int = Field(gt=0)
    free_bytes: int = Field(ge=0)
    total_bytes: int = Field(gt=0)
    ts_event: int


TierName = Literal["questdb", "parquet", "postgres"]


class TierUsage(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    tier: TierName
    used_bytes: int
    retention_days: int | None


class SymbolUsage(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    symbol: str = Field(pattern=r"^[A-Z0-9]{2,20}USDT$")
    used_bytes: int
    daily_growth_bytes: int
    pinned: bool


class StorageUsage(BaseModel):
    """OpenAPI `StorageUsage` (`GET /recording/storage`, served by E16-T08) from the last sample."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    disk_total_bytes: int
    disk_used_bytes: int
    disk_free_bytes: int
    projected_full_at: AwareDatetime | None
    daily_growth_bytes: int
    tiers: tuple[TierUsage, ...]
    symbols: tuple[SymbolUsage, ...]
    generated_at: AwareDatetime

"""Per-tier health reporting types for the storage module (M10).

The supervisor-wide `HealthReport` (`candleviewer.observability.health`) is
one-row-per-module; `storage.health()` additionally reports the finer-
grained per-tier detail the ticket's "Technical notes / design" specifies
(`{tier, state, latency_ms, detail}`) so `/readyz` can require
`postgres=ok` while allowing `questdb` degraded to still serve reads.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict

from candleviewer.storage.models import StorageTier


class TierState(StrEnum):
    """One tier's health state, distinct from the module-wide `HealthStatus`."""

    OK = "ok"
    DEGRADED = "degraded"
    DOWN = "down"


class TierHealth(BaseModel):
    """Health of one storage tier (`postgres` | `questdb` | `cold` | `fake`)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    tier: StorageTier
    state: TierState
    latency_ms: float = 0.0
    detail: str = ""


class GuardedPrivilegesHealth(BaseModel):
    """What the start's guarded-privilege check counted (#3998, `storage.guarded_privileges`):
    `held`, the pinned pairs counted against the login as `cv_db_guarded_privileges_held` counts
    them (a pair that could not be checked too), and `missing`, the pinned tables not in schema
    `public`. Either above 0 makes `/readyz` degraded; `live` refuses to start instead."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    held: int
    missing: int


class StorageHealthReport(BaseModel):
    """`StorageService.health()`'s return value: one `TierHealth` per tier."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    tiers: tuple[TierHealth, ...]
    #: The start's guarded-privilege check on the real backend (#3998); None until it has run.
    guarded_privileges: GuardedPrivilegesHealth | None = None

    def overall_ok(self) -> bool:
        """`True` only if every tier reports `ok` (used by readiness gates
        that need "no tier missing", as opposed to the `postgres`-only gate
        described in the ticket's own readiness rule)."""
        return all(t.state is TierState.OK for t in self.tiers)

    def tier(self, name: StorageTier) -> TierHealth | None:
        return next((t for t in self.tiers if t.tier == name), None)

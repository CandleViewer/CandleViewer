"""Health/build-info routes (E02-T05 acceptance criteria 3).

`/healthz` and `/readyz` are static responses here; E04 replaces the readyz
checks array with real probes (Postgres, QuestDB, exchange connectivity).
Neither route touches a datastore or the network — `create_app()` must be
constructible and servable with fakes only.

QA defect #1578 blocker 2: `/readyz` also exposes the mesh guard's current
`ReadOnlyGate` state (`mesh_binding_safe`/`mesh_reason_code`) so SCR-137
(Admin security centre) and SCR-016 (first-run wizard) have a data source,
per the ticket's explicit deliverable ("self-check result exposed on the
health payload"). `mesh_read_only_gate` is optional and structurally typed
(mirrors `oms.validator.ReadOnlyCheck`) so this module never needs to import
`candleviewer.net` directly, and a caller that does not pass one (e.g. a
bare unit test) still gets a valid response with `mesh_binding_safe=None`.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Protocol

from fastapi import APIRouter, Response

from candleviewer.api.models import LivenessResponse, ReadinessResponse, ReadyCheck
from candleviewer.observability.health_probes import HOT_TIER_WRITE_BEHIND, INGESTION
from candleviewer.observability.metrics import (
    CONTENT_TYPE_LATEST,
    CollectorRegistry,
    generate_latest,
)
from candleviewer.observability.models import HealthReport, HealthStatus
from candleviewer.settings import Settings


class ReadOnlyGateLike(Protocol):
    """Structural type for `candleviewer.net.ReadOnlyGate` (no import edge)."""

    @property
    def is_read_only(self) -> bool: ...

    @property
    def reason_code(self) -> str | None: ...


class WriteBehindStatus(Protocol):
    """Structural view of a hot-tier write-behind buffer (#1918; no import edge)."""

    @property
    def degraded(self) -> bool: ...


def _build_info(settings: Settings) -> dict[str, str]:
    return {
        "git_sha": settings.git_sha,
        "version": settings.version,
        "environment": settings.environment.value,
    }


def make_health_router(
    settings: Settings,
    metrics: CollectorRegistry | None = None,
    mesh_read_only_gate: ReadOnlyGateLike | None = None,
    write_behind: Callable[[], Sequence[WriteBehindStatus]] | None = None,
    ingestion_health: Callable[[], HealthReport] | None = None,
    secrets_health: Callable[[], HealthReport] | None = None,
    accounts_health: Callable[[], HealthReport] | None = None,
) -> APIRouter:
    """Bind the health/metrics routes to a concrete `Settings` instance.

    Returned as a fresh router (rather than reusing the module-level
    `router`) so `create_app()` can inject settings without a global.
    `metrics` is the `AppContext.metrics` registry (E02-T05); `/metrics` is
    the Prometheus scrape target `infra/prometheus/prometheus.yml` polls at
    `api:8000/metrics` (E02-T08 acceptance criteria). Falls back to the
    default global registry when not supplied so this router stays usable
    standalone (e.g. in unit tests that only exercise `make_health_router`).
    """
    bound = APIRouter(tags=["health"])
    registry = metrics if metrics is not None else CollectorRegistry()

    @bound.get("/healthz", response_model=LivenessResponse)
    def healthz() -> LivenessResponse:
        return LivenessResponse(**_build_info(settings))

    @bound.get("/readyz", response_model=ReadinessResponse)
    def readyz() -> ReadinessResponse:
        mesh_binding_safe = (
            not mesh_read_only_gate.is_read_only if mesh_read_only_gate is not None else None
        )
        mesh_reason_code = (
            mesh_read_only_gate.reason_code if mesh_read_only_gate is not None else None
        )
        # #1918: hot-tier write-behind retrying = degraded, not fatal (still 200).
        buffers = write_behind() if write_behind is not None else ()
        checks = (
            [ReadyCheck(name=HOT_TIER_WRITE_BEHIND, ok=not any(b.degraded for b in buffers))]
            if buffers
            else []
        )
        if ingestion_health is not None:  # #1919: DEGRADED feed = degraded, still 200
            rep = ingestion_health()
            if rep.status is not HealthStatus.STOPPED:
                ok = rep.status is HealthStatus.OK
                checks.append(ReadyCheck(name=INGESTION, ok=ok, detail=rep.detail))
        if secrets_health is not None:  # E27-T02: KEK unavailable = trading off
            rep = secrets_health()
            if rep.status is not HealthStatus.STOPPED:
                ok = rep.status is HealthStatus.OK
                checks.append(ReadyCheck(name="secrets", ok=ok, detail=rep.detail))
        # E27-T03: a failing stored key or a latched self-check; E27-T04: an account health loop
        # that ended or keeps failing
        if accounts_health is not None:
            rep = accounts_health()
            if rep.status is not HealthStatus.STOPPED:
                ok = rep.status is HealthStatus.OK
                checks.append(ReadyCheck(name="accounts", ok=ok, detail="" if ok else rep.detail))
        degraded = any(not c.ok for c in checks)
        return ReadinessResponse(
            status="degraded" if degraded else "ok",
            checks=checks,
            mesh_binding_safe=mesh_binding_safe,
            mesh_reason_code=mesh_reason_code,
            **_build_info(settings),
        )

    @bound.get("/metrics")
    def metrics_endpoint() -> Response:
        return Response(content=generate_latest(registry), media_type=CONTENT_TYPE_LATEST)

    return bound

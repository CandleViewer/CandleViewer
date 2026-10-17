"""Unit (E42-T05): `AdminHealthService`, the read model behind `GET /admin/health`. The clock is
injected and the registry is the E04 one, settled once: no probe runs on a read."""

from __future__ import annotations

import pytest

from candleviewer.admin.errors import OpsNotWired, OpsUnavailable
from candleviewer.admin.ops.health import AdminHealthService
from candleviewer.observability.health_probes import HealthRegistry
from tests.unit.admin._ops_fakes import settled_registry


async def test_the_reading_carries_the_cached_snapshot_the_build_facts_and_the_uptime() -> None:
    registry = await settled_registry()
    ticks = iter([100.0, 4300.5])  # construction, then the read
    health = AdminHealthService(
        registry, version="1.2.3", git_sha="abc", environment="demo", monotonic=lambda: next(ticks)
    )
    reading = health.report()
    assert reading.snapshot is registry.snapshot()
    assert (reading.version, reading.git_sha, reading.environment) == ("1.2.3", "abc", "demo")
    assert reading.uptime_seconds == 4200


def test_without_a_registry_the_report_is_not_wired() -> None:
    with pytest.raises(OpsNotWired):
        AdminHealthService(None, version="v", git_sha="g", environment="demo").report()


def test_before_the_first_snapshot_the_report_is_unavailable_never_an_empty_one() -> None:
    health = AdminHealthService(HealthRegistry(), version="v", git_sha="g", environment="demo")
    with pytest.raises(OpsUnavailable):  # an empty report would read as a healthy system
        health.report()

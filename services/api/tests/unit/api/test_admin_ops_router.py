"""Unit (E42-T05): the `GET /admin/health` handler: its payload and the registered problem every
refusal uses. The guard is tested in `test_admin_http.py`, the RBAC cells in the contract test of
this slice (`tests/contract/test_admin_ops_routes_contract.py`)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from httpx import Response

from candleviewer.admin.errors import OpsUnavailable
from candleviewer.admin.ops.health import HealthSource
from candleviewer.observability.health_probes import HealthRegistry, HealthSnapshot
from tests.unit.admin._ops_fakes import make_app, settled_registry


def _get(health: HealthSource | None) -> Response:
    app, _ = make_app(health)
    response: Response = TestClient(app).get("/admin/health", headers={"x-role": "owner"})
    return response


async def test_every_component_is_passed_through_with_its_staleness() -> None:
    body = _get(await settled_registry()).json()
    by = {c["name"]: c for c in body["components"]}
    assert len(by) == 11 and "made_up_probe" in by  # a component no client knows is not dropped
    stuck = by["parquet_store"]
    assert (stuck["state"], stuck["detail"], stuck["last_good_at"]) == (
        "degraded",
        "probe timeout",
        None,
    )
    assert by["postgres"]["last_good_at"] == "2026-10-15T09:00:00Z"
    assert by["oms"]["state"] == "not_deployed"  # honest absence, not "healthy"
    assert body["overall"] == "degraded"


async def test_the_report_carries_the_build_facts_and_the_uptime() -> None:
    body = _get(await settled_registry()).json()
    assert (body["version"], body["git_sha"], body["environment"]) == ("1.2.3", "abc", "demo")
    assert body["server_time"] == "2026-10-15T09:00:00Z" and body["uptime_seconds"] >= 0


async def test_clock_offset_is_null_and_alerts_active_is_left_out_never_made_up() -> None:
    body = _get(await settled_registry()).json()
    assert body["clock_offset_ms"] is None  # E08 has not landed: never a fabricated 0
    assert "alerts_active" not in body  # no alert source exists: omitted, never a 0


@pytest.mark.parametrize(
    ("health", "status", "code", "retry"),
    [(None, 501, "not_implemented", False), (HealthRegistry(), 503, "store_unavailable", True)],
    ids=["not-wired", "no-snapshot-yet"],
)
def test_a_report_that_cannot_be_read_is_refused_with_a_registered_problem(
    health: HealthRegistry | None, status: int, code: str, retry: bool
) -> None:
    response = _get(health)
    body = response.json()
    assert response.status_code == status and body["code"] == code and body["status"] == status
    assert response.headers["content-type"] == "application/problem+json"
    assert ("retry-after" in response.headers, "retry_after_seconds" in body) == (retry, retry)
    assert "components" not in body  # never an empty report: that would read as healthy


class _SnapshotLost(OpsUnavailable):
    """A refusal a later slice may add: it must answer as its parent, never as a 500."""


class _LosesItsSnapshot:
    def snapshot(self) -> HealthSnapshot | None:
        raise _SnapshotLost("health: snapshot lost")


def test_a_subclass_of_a_refusal_answers_as_its_parent_not_as_a_500() -> None:
    response = _get(_LosesItsSnapshot())
    assert (response.status_code, response.json()["code"]) == (503, "store_unavailable")

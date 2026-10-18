"""E42-T05 (#966 BK7-01, BK7b-R2-02): `create_app` has one job store. The poll it serves reads it,
the recorder job routes consult it, and the lost-jobs count is over it."""

from __future__ import annotations

from typing import Any

import pytest

from candleviewer.api.recorder_admin import Job
from tests.contract.rbac.rbac_harness import World, bearer

_KEY = "00000000-0000-4000-8000-0000000000b8"
_PURGE = {"symbol": "BTCUSDT", "confirm_symbol": "BTCUSDT", "reason": "free disk"}


def test_the_poll_and_the_lost_count_use_the_store_the_job_routes_submit_to(world: World) -> None:
    store = world.app.state.admin_jobs
    job = Job(id="00000000-0000-4000-8000-0000000000b7", kind="archive_import", status="succeeded")
    store._jobs[job.id] = job  # as a recorder route's submit leaves it; nothing runs
    try:
        polled = world.client.get(f"/admin/jobs/{job.id}", headers=bearer("owner"))
    finally:
        del store._jobs[job.id]
    assert (polled.status_code, polled.json()) == (200, job.view())
    assert [record["action"] for record in world.audit.records] == ["admin.area_entered"]
    assert world.app.state.admin_jobs_lost._jobs is store


@pytest.mark.parametrize(
    ("path", "kind", "body"),
    [
        ("/admin/recorder/compact", "retention_sweep", {}),
        ("/admin/recorder/purge", "retention_purge", _PURGE | {"include_pinned": True}),
    ],
)
def test_the_recorder_job_routes_consult_the_store_the_poll_reads(
    world: World, path: str, kind: str, body: dict[str, Any]
) -> None:
    """The other side of the poll's pin: a job in the poll's store holds the route's kind busy,
    so only a router built over that store answers 409 (a store of its own would accept)."""
    store = world.app.state.admin_jobs
    job = Job(id="00000000-0000-4000-8000-0000000000b9", kind=kind, status="running")
    store._jobs[job.id] = job  # as the route's own submit leaves it; nothing runs
    try:
        refused = world.client.post(
            path, json=body, headers={**bearer("owner"), "Idempotency-Key": _KEY}
        )
    finally:
        del store._jobs[job.id]
    assert (refused.status_code, refused.json()["code"]) == (409, "job_running")

"""E42-T05 (#966 BK7-01, BK7b-R2-02): `create_app` has one job store. The poll it serves reads it,
the recorder job routes consult it, and the lost-jobs count is over it."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from typing import Any

import pytest

from candleviewer.api.recorder_admin import Job
from tests.contract.rbac.rbac_harness import World, bearer, user_id_of
from tests.unit.api.test_audit_exports import manifest

_KEY = "00000000-0000-4000-8000-0000000000b8"
_PURGE = {
    "symbol": "BTCUSDT",
    "confirm_symbol": "BTCUSDT",
    "reason": "free disk",
    "before": "2026-10-20T12:00:00Z",
}
_EXPORT = "00000000-0000-4000-8000-0000000000ba"


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


@pytest.mark.parametrize(("requester", "status"), [("owner", 503), ("viewer", 404)])
def test_the_export_download_reads_the_store_the_poll_reads(
    world: World, requester: str, status: int
) -> None:
    """#889 S9: the Owner's export, placed in that store, is found and passes every check up to its
    file, which this world has not (`503`, unservable); another user's is an unknown job's `404`."""
    store = world.app.state.admin_jobs
    result = manifest("0" * 64, 1, expires=datetime(2100, 1, 1, tzinfo=UTC))
    job = Job(_EXPORT, "audit_export", "succeeded", 100.0, None, None, result, None)
    store._jobs[job.id] = replace(job, requester=str(user_id_of(requester)))
    try:
        answer = world.client.get(f"/admin/audit/exports/{job.id}", headers=bearer("owner"))
    finally:
        del store._jobs[job.id]
    assert (answer.status_code, answer.json()["code"]) == (
        status, "store_unavailable" if status == 503 else "not_found"
    )  # fmt: skip

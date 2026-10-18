"""E42-T05 (#966 BK7-01): the job poll `create_app` serves reads the one job store its job routes
submit to, an allowed poll is recorded too, and the lost-jobs count is over that same store."""

from __future__ import annotations

from candleviewer.api.recorder_admin import Job
from tests.contract.rbac.rbac_harness import World, bearer


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

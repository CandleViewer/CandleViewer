"""E42-Q03 scenario 3, server half: Postgres slow, every admin read inside its own bound (#1216).

C-13.6 #10 (datastore outage), its slow form. The relay holds every chunk 800 ms each way (the
plan's figure), so no round trip to Postgres fits any read budget below. Each read must end inside
its own bound and say so, never hang: the overview's Postgres slices and the hung recorder end at
the 300 ms slice budget as `error` "timed out after 300 ms"; the flag list ends at its 500 ms read
budget as `resolution: fail_closed`; the audit page answers inside the 4 s stop, a `503` with
`Retry-After` when Postgres did not answer in time. The area's entry records go to the audit WAL
first, so the guard never waits on the slow store. The UI half (stale and error states with Retry,
never a spinner) is part 3's. Marked `harness`: needs Docker, runs nightly.
"""

from __future__ import annotations

import time
from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from candleviewer.admin.overview.fanout import SliceFanOut
from candleviewer.admin.overview.service import AdminOverviewService
from candleviewer.admin_wiring import AdminCountsAdapter
from candleviewer.api.audit import make_audit_router
from candleviewer.api.feature_flags import make_feature_flags_routers
from candleviewer.audit.access import AuditPrincipal
from candleviewer.storage.repositories.admin_readmodel_sqlalchemy import SqlAlchemyAdminCounts
from candleviewer.storage.repositories.relational_sqlalchemy import (
    SqlAlchemyRelationalRepository,
)
from tests.chaos.admin._relay import HOST, Relay
from tests.chaos.admin._server import (
    FixedPrincipal,
    HungRecorder,
    app_of,
    audit_module,
    client,
    flags_runtime,
    problem_is_clean,
    relational,
)

pytestmark = [pytest.mark.chaos, pytest.mark.harness]

DELAY_MS = 800
SLICE_BOUND_S = 0.3 + 0.2  # the 300 ms budget plus scheduling slack
FLAGS_BOUND_S = 0.5 + 0.5  # the 500 ms read budget plus the guard's WAL write
STOP_DELAY_MS = 3000  # one round trip alone is 6 s: the 4 s stop must end the read
AUDIT_BOUND_S = 5.0  # the 4 s stop plus slack: the plan's "longest request under 5 s"


def _hidden(relay: Relay) -> tuple[str, ...]:
    """What no problem body may name: the loopback host and the relay's and upstream's ports."""
    return (HOST, f":{relay.port}", f":{relay.upstream[1]}")


@pytest.fixture
async def repo(relay: Relay, pg_dsn: str) -> AsyncIterator[SqlAlchemyRelationalRepository]:
    made = relational(relay.through(pg_dsn), "admin")
    yield made
    await made.dispose()


async def test_s3_overview_slices_end_at_their_budget_as_errors(
    relay: Relay, repo: SqlAlchemyRelationalRepository
) -> None:
    counts = AdminCountsAdapter(SqlAlchemyAdminCounts(repo, env="testnet"))
    overview = AdminOverviewService(SliceFanOut(), counts=counts, recorder=HungRecorder())
    healthy = await overview.overview()
    assert healthy.users.status == "ok", healthy.users
    relay.delay(DELAY_MS)
    slow = AdminOverviewService(SliceFanOut(), counts=counts, recorder=HungRecorder())
    started = time.monotonic()
    snap = await slow.overview()
    took = time.monotonic() - started
    print(f"S3: the overview answered in {took * 1000:.0f} ms under a {DELAY_MS} ms delay")
    assert took < SLICE_BOUND_S
    for name in ("users", "accounts", "incidents", "recorder", "storage"):
        part = getattr(snap, name)
        assert (part.status, part.detail) == ("error", "timed out after 300 ms"), name
    assert snap.trading.status == "unavailable"  # no OMS port in this composition
    await relay.heal()
    await relay.ensure_up()


async def test_s3_the_flag_list_fails_closed_at_its_read_budget(
    relay: Relay, pg_dsn: str, owner: AuditPrincipal, tmp_path: Path
) -> None:
    async with (
        audit_module(relay.through(pg_dsn), tmp_path) as audit,
        flags_runtime(relay.through(pg_dsn), audit.writer) as flags,
    ):
        read, _write = make_feature_flags_routers(
            flags, resolver=FixedPrincipal(owner), audit=audit.writer
        )
        relay.delay(DELAY_MS)
        async with client(app_of(read)) as http:
            started = time.monotonic()
            listed = await http.get("/admin/feature-flags")
            took = time.monotonic() - started
        print(f"S3: the flag list answered in {took * 1000:.0f} ms")
        assert listed.status_code == 200, listed.text
        assert listed.json()["resolution"] == "fail_closed"
        assert took < FLAGS_BOUND_S
        await relay.heal()
        await relay.ensure_up()


async def test_s3_the_audit_page_answers_inside_the_4_s_stop(
    relay: Relay, pg_dsn: str, owner: AuditPrincipal, tmp_path: Path
) -> None:
    async with audit_module(relay.through(pg_dsn), tmp_path) as audit:
        app = app_of(make_audit_router(audit, FixedPrincipal(owner)))
        async with client(app) as http:
            assert (await http.get("/admin/audit", params={"limit": "50"})).status_code == 200
            relay.delay(DELAY_MS)
            started = time.monotonic()
            page = await http.get("/admin/audit", params={"limit": "50"})
            took = time.monotonic() - started
        print(f"S3: the audit page answered {page.status_code} in {took * 1000:.0f} ms")
        assert took < AUDIT_BOUND_S, "the audit read outlived its stop"
        assert page.status_code in {200, 503}, page.text
        assert problem_is_clean(page.text, *_hidden(relay))
        await relay.heal()
        await relay.ensure_up()


async def test_s3_the_audit_page_is_stopped_at_4_s_with_a_503_and_retry_after(
    relay: Relay, pg_dsn: str, owner: AuditPrincipal, tmp_path: Path
) -> None:
    """A delay no read can finish under: the stop must fire, so the 503 is always exercised."""
    async with audit_module(relay.through(pg_dsn), tmp_path) as audit:
        app = app_of(make_audit_router(audit, FixedPrincipal(owner)))
        async with client(app) as http:
            assert (await http.get("/admin/audit", params={"limit": "50"})).status_code == 200
            relay.delay(STOP_DELAY_MS)
            started = time.monotonic()
            page = await http.get("/admin/audit", params={"limit": "50"})
            took = time.monotonic() - started
        print(f"S3: the audit page was stopped with {page.status_code} in {took * 1000:.0f} ms")
        assert page.status_code == 503, page.text
        assert page.json()["code"] == "store_unavailable"
        assert page.headers["Retry-After"]
        assert problem_is_clean(page.text, *_hidden(relay))
        assert took < AUDIT_BOUND_S, "the audit read outlived its stop"
        await relay.heal()
        await relay.ensure_up()

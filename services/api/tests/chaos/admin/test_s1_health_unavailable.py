"""E42-Q03 scenario 1, server half: Postgres cut while the `system` topic stays up (#1216).

[BQ-5] Plan row 1. A cut reaches the `system` topic's `health` frame within 2 s with `postgres`
down and every other component as it was; no frame names a host or carries a trace. `GET
/admin/health` itself answers `503 store_unavailable` with `Retry-After` only while its source has
no snapshot (the stand-in): under the cut alone it answers `200` with `postgres` down, because the
area's entry record goes to the audit WAL (`audit/writer.py`), never to Postgres first. The UI
half (HL-11, HL-14) is part 3's. Marked `harness`: needs Docker, runs nightly.
"""

from __future__ import annotations

import json
import time
from collections.abc import AsyncIterator
from pathlib import Path
from typing import cast

import pytest
from fastapi import FastAPI

from candleviewer.admin.ops.health import AdminHealthService, HealthSource
from candleviewer.admin.ops.incidents import AdminIncidentsService
from candleviewer.api.admin_ops import make_admin_ops_router
from candleviewer.audit.access import AuditPrincipal
from candleviewer.health_wiring import HealthSystemPublisher, register_real_probes
from candleviewer.observability.health_probes import HealthRegistry, HealthSnapshot
from candleviewer.storage.repositories.relational_sqlalchemy import (
    SqlAlchemyRelationalRepository,
)
from tests.chaos.admin._relay import HOST, Relay
from tests.chaos.admin._server import (
    BUILD_SHA,
    BUILD_VERSION,
    FixedPrincipal,
    NoSnapshot,
    app_of,
    audit_module,
    client,
    closed_port,
    problem_is_clean,
    relational,
)

pytestmark = [pytest.mark.chaos, pytest.mark.harness]

FRAME_WITHIN_S = 2.0  # the plan's bound from the cut to the `health` frame


def _hidden(relay: Relay) -> tuple[str, ...]:
    """What no frame or body may name: the loopback host and the relay's and upstream's ports."""
    return (HOST, f":{relay.port}", f":{relay.upstream[1]}")


def _states(snap: HealthSnapshot) -> dict[str, str]:
    return {c.name: c.state.value for c in snap.components}


@pytest.fixture
async def repo(relay: Relay, pg_dsn: str) -> AsyncIterator[SqlAlchemyRelationalRepository]:
    """The health probe's engine, through the relay."""
    made = relational(relay.through(pg_dsn), "health")
    yield made
    await made.dispose()


def _registry(
    repo: SqlAlchemyRelationalRepository, tmp: Path, sink: list[dict[str, object]]
) -> HealthRegistry:
    publisher = HealthSystemPublisher()
    publisher.direct_sinks.append(sink.append)
    registry = HealthRegistry(on_snapshot=publisher)
    registry.register_placeholders()
    register_real_probes(
        registry,
        pg_repo=repo,
        questdb_host=HOST,
        questdb_port=closed_port(),
        parquet_root=str(tmp),
        disk_path=str(tmp),
    )
    return registry


async def test_s1_a_cut_reaches_the_system_frame_within_2_s_and_names_no_host(
    relay: Relay, repo: SqlAlchemyRelationalRepository, tmp_path: Path
) -> None:
    frames: list[dict[str, object]] = []
    registry = _registry(repo, tmp_path, frames)
    before = _states(await registry.refresh())
    assert before["postgres"] == "healthy"
    relay.cut()
    started = time.monotonic()
    after = _states(await registry.refresh())
    took = time.monotonic() - started
    print(f"S1: the cut reached the health frame in {took * 1000:.0f} ms")
    assert took < FRAME_WITHIN_S
    assert after["postgres"] in {"down", "degraded"}
    assert {k: v for k, v in after.items() if k != "postgres"} == {
        k: v for k, v in before.items() if k != "postgres"
    }, "a Postgres cut moved another component"
    frame = frames[-1]
    shown = {c["name"]: c["state"] for c in cast(list[dict[str, str]], frame["components"])}
    assert shown["postgres"] == after["postgres"]
    assert problem_is_clean(json.dumps(frame), *_hidden(relay))
    await relay.heal()
    await relay.ensure_up()
    assert _states(await registry.refresh())["postgres"] == "healthy"


async def test_s1_admin_health_is_503_with_no_snapshot_and_200_through_a_cut(
    relay: Relay,
    repo: SqlAlchemyRelationalRepository,
    pg_dsn: str,
    owner: AuditPrincipal,
    tmp_path: Path,
) -> None:
    registry = _registry(repo, tmp_path, [])
    await registry.refresh()
    async with audit_module(relay.through(pg_dsn), tmp_path) as audit:

        def health_app(source: HealthSource) -> FastAPI:
            service = AdminHealthService(
                source, version=BUILD_VERSION, git_sha=BUILD_SHA, environment="testnet"
            )
            router = make_admin_ops_router(
                service,
                AdminIncidentsService(None),
                resolver=FixedPrincipal(owner),
                audit=audit.writer,
            )
            return app_of(router)

        async with client(health_app(NoSnapshot())) as empty:
            refused = await empty.get("/admin/health")
        assert refused.status_code == 503
        assert refused.json()["code"] == "store_unavailable"
        assert refused.headers["Retry-After"] == "5"
        assert problem_is_clean(refused.text, *_hidden(relay))
        relay.cut()
        await registry.refresh()
        async with client(health_app(registry)) as live:
            through_cut = await live.get("/admin/health")
        # [BQ-5] not the 503 of plan row 1: the entry record is WAL-first, so a cut keeps the read
        assert through_cut.status_code == 200, through_cut.text
        states = {c["name"]: c["state"] for c in through_cut.json()["components"]}
        assert states["postgres"] in {"down", "degraded"}
        assert problem_is_clean(through_cut.text, *_hidden(relay))
        await relay.heal()
        await relay.ensure_up()

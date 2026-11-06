"""E42-Q03 scenario 2, server half: an incident raised while the client is away (#1216).

The client's reconnect, resubscribe and `auth_ok` after a socket drop are the gateway's, pinned by
E17-Q02's suite (`tests/chaos/ws`, scenarios 1 and 5). What the admin screen adds is the re-read of
the incident list after it resubscribes (SCR-144, IL-10): the same failure raised again while the
client was away must come back as the one incident it already shows, its `occurrences` grown, never
as a second row and never lost. Here a component flaps twice through the real health registry and
its `system_events` writer, and the list is read through the shipped read model. Between the flaps
Postgres is a blackhole: the read of the list while the client is away hangs (it is the reader's
budget that ends it) and nothing may be lost or doubled once the relay heals. The UI half and
the socket `drop()` are part 3's. Marked `harness`: needs Docker, runs nightly.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

import pytest

from candleviewer.admin.ops.incidents import AdminIncidentsService
from candleviewer.admin.wiring import system_event_redactor
from candleviewer.health_wiring import PgSystemEventWriter
from candleviewer.observability.health_probes import (
    CallableProbe,
    ComponentState,
    HealthRegistry,
    ProbeResult,
)
from candleviewer.storage.repositories.incidents_sqlalchemy import SqlAlchemyIncidents
from candleviewer.storage.repositories.relational_sqlalchemy import (
    SqlAlchemyRelationalRepository,
)
from tests.chaos.admin._relay import Relay
from tests.chaos.admin._server import relational

pytestmark = [pytest.mark.chaos, pytest.mark.harness]

READ_HELD_S = 0.5  # how long the away client waits on a blackholed read


@pytest.fixture
async def repo(relay: Relay, pg_dsn: str) -> AsyncIterator[SqlAlchemyRelationalRepository]:
    made = relational(relay.through(pg_dsn), "admin")
    yield made
    await made.dispose()


async def test_s2_a_failure_raised_twice_while_away_is_one_incident_with_two_occurrences(
    relay: Relay, repo: SqlAlchemyRelationalRepository
) -> None:
    state = [ComponentState.HEALTHY]

    async def recorder() -> ProbeResult:
        return ProbeResult(state[0], "" if state[0] is ComponentState.HEALTHY else "stalled")

    registry = HealthRegistry(
        events=PgSystemEventWriter(repo, redact_details=system_event_redactor())
    )
    registry.register(CallableProbe("recorder", recorder))
    incidents = AdminIncidentsService(SqlAlchemyIncidents(repo))
    await registry.refresh()  # the first observation writes nothing (edge-triggered)

    async def flap() -> None:  # down, then up: one failure and its recovery
        state[0] = ComponentState.DOWN
        await registry.refresh()
        state[0] = ComponentState.HEALTHY
        await registry.refresh()

    await flap()
    first = await incidents.page(status=None, cursor=None, limit=100)
    shown = [row for row in first.items if row.component == "recorder"]
    assert [row.occurrences for row in shown] == [1]
    relay.blackhole()  # the client is away: its read of the list gets no answer
    with pytest.raises(TimeoutError):
        async with asyncio.timeout(READ_HELD_S):
            await incidents.page(status=None, cursor=None, limit=100)
    await relay.heal()
    await relay.ensure_up()
    await flap()  # the same failure again, raised after the outage
    page = await incidents.page(status=None, cursor=None, limit=100)
    mine = [row for row in page.items if row.component == "recorder"]
    assert len(mine) == 1, f"{len(mine)} rows for one failure"
    assert mine[0].id == shown[0].id, "the same incident, not a new row"
    assert mine[0].occurrences == 2
    assert mine[0].severity == "error"
    again = await incidents.page(status=None, cursor=None, limit=100)
    assert [row.id for row in again.items if row.component == "recorder"] == [mine[0].id]
    await relay.ensure_up()

"""E17-T08: `ReplaySessionService` feeds `machines.replay:{id}.state` (23 §6.4). Built or restored,
a session's entry is bound to its user from its row; `destroy` leaves a terminal entry for the
retention, and a stop removes the live ones. The service rig is `test_sessions_service`'s."""

from __future__ import annotations

from uuid import UUID

from candleviewer.ws.topics import EntityScope
from tests.unit.replay.test_sessions_service import USER_A, _persistence, make_env, request
from tests.unit.ws._feed_support import Feed


async def test_a_session_publishes_its_entry_bound_to_its_user_and_destroy_ends_it() -> None:
    feed = Feed()
    env = make_env(machine_feed=feed.port)
    row = await env.s.create(USER_A, request(), prepare=True)
    ch = f"machines.replay:{row.id}.state"
    assert feed.registry.scope(ch) == EntityScope(user=UUID(USER_A)) and feed.scope_missing() == 0
    served = feed.served(ch)
    assert served is not None and (served["machine_kind"], served["state"]) == ("replay", "paused")
    await env.s.destroy(USER_A, row.id)
    served = feed.served(ch)
    assert served is not None and served["state"] == "destroyed" and "terminal" in served["tags"]
    feed.expire()
    assert feed.served(ch) is None and feed.scope_missing() == 0


async def test_a_stopped_service_removes_the_entries_of_its_live_sessions() -> None:
    feed = Feed()
    env = make_env(machine_feed=feed.port)
    row = await env.s.create(USER_A, request())
    ch = f"machines.replay:{row.id}.state"
    assert feed.served(ch) is not None
    await env.s.stop()
    assert feed.served(ch) is None and len(feed.registry) == 0


async def test_a_restored_session_binds_its_scope_and_publishes_the_state_it_returns_in() -> None:
    feed = Feed()
    _, persistence = _persistence()
    env = make_env(machine_feed=feed.port, **persistence)
    row = await env.s.create(USER_A, request(), prepare=True)
    ch = f"machines.replay:{row.id}.state"
    await env.s.stop()  # sealed, then stopped: its live entry goes
    assert feed.served(ch) is None
    again = make_env(repo=env.repo, machine_feed=feed.port, **persistence)
    await again.s.start()  # restored, not rebuilt: `paused`, where a rebuild gives `created`
    served = feed.served(ch)
    assert again.s.state_of(row.id) == "paused" and served is not None
    assert (served["state"], served["degraded"]) == ("paused", False)
    assert feed.registry.scope(ch) == EntityScope(user=UUID(USER_A)) and feed.scope_missing() == 0
    assert len(feed.registry) == 1  # the one live machine of the entity
    await again.s.stop()

"""#2811 (E26-T05, #624 reclaim AC; 23 §11, §9.5): a destroyed replay session's subscriptions end.

`ReplaySessionService(on_ended=...)` tells the composition root once a session is destroyed, by
the client or by the idle reclaim. `WsEvents.replay_session_ended` hands that to
`ConnectionRegistry.replay_session_ended(rs, user_id)`, which ends every subscription of that
replay session on each of the owner's sockets: one `revoked` per topic, in `ch` order, reason
`replay_session_ended`, naming the subscription (`sub_id`, envelope `rs`), never resubscribable,
then its `ws.subscription.revoked` rows. The live twin, another session and another user's
sockets are untouched. Pure asyncio over the registry and the real B12 session service.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from typing import Any, cast

import pytest

from candleviewer.app import _attach_replay_sessions
from candleviewer.auth.generated_permissions import Permission
from candleviewer.replay.service import ReplayService
from candleviewer.replay.sessions_service import DestroyOutcome
from candleviewer.settings import Settings
from candleviewer.ws.permissions import ConnectionAuthz
from candleviewer.ws_wiring import KillSwitchView, WsEvents
from tests.unit.replay.test_sessions_service import make_env, request
from tests.unit.ws.test_revocation_fanout import USER, _principal, _revoked_rows, _Sink, _World

PEER = uuid.UUID(int=0x2811)
READ = frozenset({Permission.MARKETDATA_READ})
TOPICS = ("trades.BTCUSDT", "ticker.BTCUSDT")


def _world() -> _World:
    world = _World(_Sink())
    for uid in (USER, PEER):
        world.principals[uid] = _principal(uid, READ)
    return world


def _replay(world: _World, uid: uuid.UUID, rs: str, *topics: str) -> ConnectionAuthz:
    """A socket of `uid` with a live `trades` and each of `topics` in replay session `rs`."""
    authz = world.connect(uid, ["trades.BTCUSDT"])
    for ch in topics:
        assert authz.admit(ch, replay_session_id=rs)[1] is not None
    return authz


def _held(authz: ConnectionAuthz) -> set[tuple[str, str | None]]:
    return {(s.ch, s.replay_session_id) for s in authz.by_id.values()}


async def test_registry_ends_each_replay_subscription_of_the_session_once_per_topic() -> None:
    world, rs, other = _world(), str(uuid.uuid4()), str(uuid.uuid4())
    authz = _replay(world, USER, rs, *TOPICS)
    assert authz.admit("trades.BTCUSDT", replay_session_id=other)[1] is not None
    assert await world.registry.replay_session_ended(rs, USER) == 1
    [revoked] = world.revoked()
    shown = [(f["ch"], f["rs"], f["p"]["reason"], f["p"]["resubscribe_allowed"]) for f in revoked]
    assert shown == [
        ("ticker.BTCUSDT", rs, "replay_session_ended", False),
        ("trades.BTCUSDT", rs, "replay_session_ended", False),
    ]
    assert all(f["p"]["sub_id"].startswith("s_") for f in revoked)
    assert _held(authz) == {("trades.BTCUSDT", None), ("trades.BTCUSDT", other)}
    assert world.sink.rows == _revoked_rows(world)


async def test_registry_reaches_every_socket_of_the_owner() -> None:
    world, rs = _world(), str(uuid.uuid4())
    first, second = _replay(world, USER, rs, "trades.BTCUSDT"), _replay(world, USER, rs, *TOPICS)
    assert await world.registry.replay_session_ended(rs, USER) == 2
    assert [len(r) for r in world.revoked()] == [1, 2]
    assert _held(first) == _held(second) == {("trades.BTCUSDT", None)}


async def test_registry_leaves_another_users_subscriptions_untouched() -> None:
    world, rs = _world(), str(uuid.uuid4())
    _replay(world, USER, rs, "trades.BTCUSDT")
    peer = _replay(world, PEER, rs, "trades.BTCUSDT")
    assert await world.registry.replay_session_ended(rs, USER) == 1
    assert world.revoked()[1] == [] and ("trades.BTCUSDT", rs) in _held(peer)


async def test_registry_is_idempotent_and_ignores_an_id_that_is_not_a_uuid() -> None:
    world, rs = _world(), str(uuid.uuid4())
    _replay(world, USER, rs, "trades.BTCUSDT")
    assert await world.registry.replay_session_ended(rs.upper(), USER) == 1  # read canonically
    assert await world.registry.replay_session_ended(rs, USER) == 0
    assert await world.registry.replay_session_ended("not-a-uuid", USER) == 0
    assert await world.registry.replay_session_ended(rs, uuid.uuid4()) == 0  # no socket
    assert [len(r) for r in world.revoked()] == [1] and len(world.sink.rows) == 1


async def test_registry_evicts_a_socket_whose_send_fails_and_still_ends_the_others() -> None:
    world, rs = _world(), str(uuid.uuid4())

    async def broken(_frame: dict[str, Any]) -> None:
        raise OSError("socket gone")

    world.connect(USER, [], send=broken).admit("trades.BTCUSDT", replay_session_id=rs)
    _replay(world, USER, rs, "trades.BTCUSDT")
    assert await world.registry.replay_session_ended(rs, USER) == 2
    assert world.closed == [0] and [f["ch"] for f in world.revoked()[1]] == ["trades.BTCUSDT"]


async def test_ws_events_takes_the_session_services_arguments() -> None:
    world, rs = _world(), str(uuid.uuid4())
    authz = _replay(world, USER, rs, "trades.BTCUSDT")
    events = WsEvents(world.registry, cast(Any, None), KillSwitchView())
    await events.replay_session_ended(rs, str(USER), "idle_reclaim")
    assert _held(authz) == {("trades.BTCUSDT", None)}


# -- through the real B12 session service (the `on_ended` seam) ---------------------------------


def _wired() -> tuple[_World, Any]:
    """The session service whose `on_ended` is the WS entry point, as `app.py` wires it."""
    world = _world()
    events = WsEvents(world.registry, cast(Any, None), KillSwitchView())
    return world, make_env(on_ended=events.replay_session_ended)


async def test_a_client_destroy_revokes_the_owners_replay_subscriptions() -> None:
    world, env = _wired()
    sid = (await env.s.create(str(USER), request())).id
    authz = _replay(world, USER, sid, *TOPICS)
    assert await env.s.destroy(str(USER), sid) is DestroyOutcome.DESTROYED
    assert {f["p"]["reason"] for f in world.revoked()[0]} == {"replay_session_ended"}
    assert [f["ch"] for f in world.revoked()[0]] == sorted(TOPICS)
    assert _held(authz) == {("trades.BTCUSDT", None)}


async def test_an_idle_reclaim_revokes_the_owners_replay_subscriptions() -> None:
    world, env = _wired()
    sid = (await env.s.create(str(USER), request())).id
    authz = _replay(world, USER, sid, "trades.BTCUSDT")
    peer = _replay(world, PEER, sid, "trades.BTCUSDT")  # not the owner: left alone
    env.clock.advance(hours=3)
    assert await env.s.reclaim_idle(env.clock()) == 1
    assert [(f["ch"], f["rs"], f["p"]["reason"]) for f in world.revoked()[0]] == [
        ("trades.BTCUSDT", sid, "replay_session_ended")
    ]
    assert _held(authz) == {("trades.BTCUSDT", None)}
    assert world.revoked()[1] == [] and ("trades.BTCUSDT", sid) in _held(peer)


async def test_a_failing_revocation_never_fails_the_destroy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    world, env = _wired()
    sid = (await env.s.create(str(USER), request())).id
    _replay(world, USER, sid, "trades.BTCUSDT")

    async def down(*_args: Any) -> int:
        raise RuntimeError("registry down")

    monkeypatch.setattr(world.registry, "replay_session_ended", down)
    assert await env.s.destroy(str(USER), sid) is DestroyOutcome.DESTROYED
    assert await env.s.destroy(str(USER), sid) is DestroyOutcome.GONE


def test_the_composition_root_wires_on_ended_into_the_session_service() -> None:
    async def on_ended(session_id: str, user_id: str, reason: str) -> None:
        return None

    ctx = SimpleNamespace(replay=ReplayService(), audit=object())
    settings = Settings(_env_file=None)  # type: ignore[call-arg]  # pydantic-settings kwarg
    _attach_replay_sessions(
        cast(Any, ctx), settings, cast(Any, object()), cast(Any, object()), on_ended=on_ended
    )
    assert ctx.replay.sessions is not None and ctx.replay.sessions._on_ended is on_ended

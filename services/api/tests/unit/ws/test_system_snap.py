"""#4992 (`23-ws-protocol.md` §12.1): a socket's first `auth_ok` is followed by the `system` snap,
`s` 1, `kind` `health`: the latest health frame's fields, the kill switch `auth_ok` gave and the
flags the role may see, cut per role as every `system` frame is (§15.9, SR-188). Every later
`system` frame is a `d` from `s` 2; a new socket (a reconnect) gets a new snap; an in-place
re-`auth` keeps the socket's sequence and sends none. A failed health or flag read costs only its
fields. By construction no `system` `d` is ever queued before the snap.

The real `/ws` router runs on the test's loop behind a fake socket (the SR-188 rig of
`test_system_topic_roles.py`): no threads, no sleeps. Every snap passes this directory's schema
harness (`_seq_support.validate`)."""

from __future__ import annotations

import asyncio
import json
import uuid
from typing import Any, cast

import pytest
from fastapi import WebSocket
from hypothesis import given, settings
from hypothesis import strategies as st

from candleviewer.admin.flags import default_registry
from candleviewer.auth.scopes import PrincipalSnapshot
from candleviewer.health_wiring import HealthSystemPublisher
from candleviewer.observability.health_probes import (
    ComponentState,
    HealthRegistry,
)
from candleviewer.ws.backpressure_config import BackpressureConfig
from candleviewer.ws.gateway import FlagSnapshot, SystemBaseline, _Connection
from candleviewer.ws.permissions import ConnectionAuthz
from candleviewer.ws.system_filter import system_view
from tests.unit.observability._health_frames import Probe
from tests.unit.ws._seq_support import validate
from tests.unit.ws.test_system_filter import BODIES, DENY_ALL, MANAGER, OWNER, VIEWER
from tests.unit.ws.test_system_topic_roles import (
    _DEADLINE_S,
    KILL,
    NOTICE,
    STATE,
    _as,
    _Rig,
    _Socket,
    _system,
)

ROLES = ("owner", "manager", "viewer")
#: A health frame as `HealthSystemPublisher` builds one: a component `detail` only the Owner gets.
HEALTH = {
    "kind": "health",
    "health": "degraded",
    "components": [{"name": "bybit_rest", "state": "degraded", "detail": "slow"}],
    "exchange": {"public_ws": "connected", "private_ws": "connected", "rest": "degraded"},
    "clock_offset_ms": 7,
}
ALL_ROLES_FLAG, OWNER_ONLY_FLAG = "trading.one_click", "killswitch.ingestion"
FLAGS = {"kind": "feature_flags", "feature_flags": {ALL_ROLES_FLAG: True, OWNER_ONLY_FLAG: False}}


async def _flags(user: uuid.UUID, roles: frozenset[str]) -> dict[str, Any] | None:
    return FLAGS


async def _broken_flags(user: uuid.UUID, roles: frozenset[str]) -> dict[str, Any] | None:
    raise RuntimeError("flag store down")


def _broken_health() -> dict[str, Any] | None:
    raise RuntimeError("health source down")


#: The health sources: a frame, none yet, a read that raises, and no source at all.
BASELINES: dict[str, SystemBaseline | None] = {
    "frame": lambda: HEALTH,
    "none-yet": lambda: None,
    "raises": _broken_health,
    "unwired": None,
}
FLAG_SOURCES: dict[str, FlagSnapshot | None] = {
    "flags": _flags,
    "raises": _broken_flags,
    "unwired": None,
}


def _rig(baseline: SystemBaseline | None = None, flags: FlagSnapshot | None = None) -> _Rig:
    return _Rig(
        flag_visible=default_registry().visible_to, flag_snapshot=flags, system_baseline=baseline
    )


def _snap(sock: _Socket) -> dict[str, Any]:
    assert sock.snap is not None
    validate(sock.snap)  # the §13.1 envelope and §15.9 `system.schema.json`
    return sock.snap


@pytest.mark.parametrize("flags", FLAG_SOURCES)
@pytest.mark.parametrize("baseline", BASELINES)
@pytest.mark.parametrize("role", ROLES)
async def test_the_first_system_frame_after_auth_ok_is_the_snap_whatever_the_sources(
    role: str, baseline: str, flags: str
) -> None:
    rig = _rig(BASELINES[baseline], FLAG_SOURCES[flags])
    async with asyncio.timeout(_DEADLINE_S):
        sock = await rig.connect(_as(uuid.uuid4(), role))  # asserts `snap`, `system`, `s` 1
        snap = _snap(sock)
        p = snap["p"]
        assert p["kind"] == "health"
        assert p["kill_switch"] == sock.auth_ok["p"]["kill_switch"]  # the one state, one cut
        if baseline == "frame":
            assert (p["health"], p["clock_offset_ms"]) == ("degraded", 7)
            assert p["exchange"] == HEALTH["exchange"]
            details = ["detail" in c for c in p["components"]]
            assert details == [role == "owner"]  # §7.2.2 row 48: the Owner's alone
        else:  # unknown health: the schema has no word for it, so the snap names none
            assert not {"health", "components", "exchange", "clock_offset_ms"} & set(p)
        if flags == "flags":
            want = {ALL_ROLES_FLAG, OWNER_ONLY_FLAG} if role == "owner" else {ALL_ROLES_FLAG}
            assert set(p["feature_flags"]) == want
        else:
            assert "feature_flags" not in p
        assert await _system(sock) == []  # the flags are not sent a second time
        await rig.close()


@pytest.mark.parametrize("role", ROLES)
async def test_the_snap_is_the_principal_view_of_the_baseline(role: str) -> None:
    rig = _rig(lambda: HEALTH, _flags)
    async with asyncio.timeout(_DEADLINE_S):
        principal = _as(uuid.uuid4(), role)
        sock = await rig.connect(principal)
        body = HEALTH | {"kill_switch": STATE, "feature_flags": FLAGS["feature_flags"]}
        want = system_view(body, principal, flag_visible=default_registry().visible_to)
        assert _snap(sock)["p"] == want
        await rig.close()


async def test_a_principal_with_no_role_gets_no_snap_and_no_system_frame() -> None:
    rig = _rig(lambda: HEALTH, _flags)
    async with asyncio.timeout(_DEADLINE_S):
        sock = await rig.connect(_as(uuid.uuid4()))
        rig.hub.broadcast_system(NOTICE)
        assert sock.snap is None and await _system(sock) == []
        await rig.close()


@pytest.mark.parametrize("role", ROLES)
async def test_the_deltas_after_the_snap_continue_at_s_2(role: str) -> None:
    rig = _Rig(notices=[NOTICE])
    async with asyncio.timeout(_DEADLINE_S):
        sock = await rig.connect(_as(uuid.uuid4(), role))
        rig.hub.broadcast_system(KILL)
        frames = await _system(sock)
        assert [s for s, _ in frames] == [2, 3]
        assert [p["kind"] for _, p in frames] == ["notice", "kill_switch"]
        await rig.close()


async def test_a_reconnect_gets_a_new_snap_with_the_state_of_now() -> None:
    """The chaos scenario (reconnect): every socket's first `auth_ok` sends the snap, `s` 1, built
    from the sources as they are then."""
    health = dict(HEALTH)
    rig, user = _rig(lambda: health), uuid.uuid4()
    async with asyncio.timeout(_DEADLINE_S):
        first = await rig.connect(_as(user, "manager"))
        rig.hub.broadcast_system(NOTICE)
        assert [s for s, _ in await _system(first)] == [2]
        first.inbound.put_nowait({"type": "websocket.disconnect", "code": 1006})
        health["health"] = "healthy"
        second = await rig.connect(_as(user, "manager"))
        assert (_snap(second)["s"], _snap(second)["p"]["health"]) == (1, "healthy")
        assert _snap(first)["p"]["health"] == "degraded"
        rig.hub.broadcast_system(NOTICE)
        assert [s for s, _ in await _system(second)] == [2]
        await rig.close()


async def test_an_in_place_reauth_sends_no_new_snap_and_keeps_the_sequence() -> None:
    rig, user = _rig(lambda: HEALTH), uuid.uuid4()
    async with asyncio.timeout(_DEADLINE_S):
        sock = await rig.connect(_as(user, "owner"))
        sock.feed({"t": "auth", "id": "re", "p": {"access_token": str(user)}})
        assert (await sock.sent.get())["t"] == "auth_ok"
        assert await _system(sock) == []
        rig.hub.broadcast_system(NOTICE)
        assert await _system(sock) == [(2, NOTICE)]
        await rig.close()


async def test_a_socket_with_no_role_at_its_first_auth_gets_the_snap_at_a_reauth_with_one() -> None:
    rig, user = _rig(lambda: HEALTH), uuid.uuid4()
    async with asyncio.timeout(_DEADLINE_S):
        sock = await rig.connect(_as(user))  # the deny-all principal: no snap
        rig.principals[user] = _as(user, "viewer")
        sock.feed({"t": "auth", "id": "re", "p": {"access_token": str(user)}})
        auth_ok, snap = await sock.sent.get(), await sock.sent.get()
        assert auth_ok["t"] == "auth_ok"
        assert (snap["t"], snap["ch"], snap["s"]) == ("snap", "system", 1)
        assert snap["p"]["kill_switch"] == auth_ok["p"]["kill_switch"]
        await rig.close()


async def test_the_late_snap_of_a_socket_that_gained_a_role_is_followed_by_the_notices() -> None:
    """Fable Minor 2 on #5039: the snap a re-auth sends (the first auth had no role) is the
    socket's first `system` state, so the first-auth notices (the read-only latch, break-glass)
    follow it, as they follow a first auth's snap."""
    rig, user = _Rig(notices=[NOTICE]), uuid.uuid4()
    async with asyncio.timeout(_DEADLINE_S):
        sock = await rig.connect(_as(user))  # the deny-all principal: no snap, no notice
        rig.principals[user] = _as(user, "viewer")
        sock.feed({"t": "auth", "id": "re", "p": {"access_token": str(user)}})
        assert (await sock.sent.get())["t"] == "auth_ok"
        assert (await sock.sent.get())["t"] == "snap"
        assert await _system(sock) == [(2, NOTICE)]
        await rig.close()


def test_a_hold_past_its_bound_keeps_the_newest_and_counts_each_drop() -> None:
    """Fable Minor 1 on #5039: the hold before the snap is bounded (C-2.18); past it the oldest
    goes, never silently: each drop is counted as `held_overflow`."""
    from prometheus_client import REGISTRY

    from candleviewer.ws.gateway import SYSTEM_HELD_MAX

    def count() -> float:
        name, labels = "cv_ws_system_frames_withheld_total", {"reason": "held_overflow"}
        return REGISTRY.get_sample_value(name, labels) or 0.0

    before = count()
    conn = _bare(OWNER)
    bodies = [dict(NOTICE, reason=f"r{i}") for i in range(SYSTEM_HELD_MAX + 3)]
    for body in bodies:
        conn.push_system(body)
    assert count() - before == 3
    conn.push_system(_SNAP_BODY, snap=True)
    frames = _queued(conn)
    held = [f["p"]["reason"] for f in frames if f.get("ch") == "system" and f["t"] == "d"]
    assert held == [b["reason"] for b in bodies[3:]]  # the newest SYSTEM_HELD_MAX, in order


async def test_a_frame_broadcast_while_the_snap_is_built_follows_it() -> None:
    """The flag read is the one await between `auth_ok` and the snap: a kill switch broadcast to
    the socket meanwhile (it is authenticated) is held, then queued after the snap as `s` 2."""
    gate, reading = asyncio.Event(), asyncio.Event()

    async def slow(user: uuid.UUID, roles: frozenset[str]) -> dict[str, Any] | None:
        reading.set()
        await gate.wait()
        return FLAGS

    rig, principal = _rig(lambda: HEALTH, slow), _as(uuid.uuid4(), "owner")
    async with asyncio.timeout(_DEADLINE_S):
        rig.principals[principal.user_id] = principal
        sock = _Socket()
        rig.handlers.append((sock, asyncio.create_task(rig.endpoint(sock))))
        sock.feed({"t": "hello", "id": "h"})
        assert (await sock.sent.get())["t"] == "welcome"
        sock.feed({"t": "auth", "id": "a", "p": {"access_token": str(principal.user_id)}})
        await reading.wait()
        assert rig.hub.broadcast_system(KILL) == 1  # it reaches this very socket
        gate.set()
        frames = [await sock.sent.get() for _ in range(3)]
        assert [(f["t"], f.get("s")) for f in frames] == [("auth_ok", None), ("snap", 1), ("d", 2)]
        assert frames[2]["p"] == KILL
        await rig.close()


async def test_the_baseline_is_the_last_frame_the_health_publisher_built() -> None:
    publisher = HealthSystemPublisher()
    assert publisher.latest() is None
    registry = HealthRegistry(on_snapshot=publisher)
    registry.register(Probe("bybit_rest", ComponentState.DEGRADED, "slow"))
    await registry.refresh()
    latest = publisher.latest()
    assert latest is not None and latest["kind"] == "health" and latest["health"] == "degraded"
    latest["health"] = "down"  # a reader's copy: the publisher's frame is unchanged
    assert cast(dict[str, Any], publisher.latest())["health"] == "degraded"
    rig = _rig(publisher.latest)
    async with asyncio.timeout(_DEADLINE_S):
        sock = await rig.connect(_as(uuid.uuid4(), "owner"))
        assert _snap(sock)["p"]["health"] == "degraded"
        await rig.close()


# -- by construction: a bare connection, any push order -----------------------------------------

_WHO = [OWNER, MANAGER, VIEWER, DENY_ALL]
_SNAP_BODY = HEALTH | {"kill_switch": STATE}
#: One step: a `system` frame offered (`push_system`), the snap (`snap=True`), or a swap of
#: the principal (a role change, §9.5).
_STEPS = st.one_of(
    st.tuples(st.just("push"), BODIES),
    st.tuples(st.just("snap"), st.just(_SNAP_BODY)),
    st.tuples(st.just("who"), st.sampled_from(_WHO)),
)


def _bare(who: PrincipalSnapshot) -> _Connection:
    conn = _Connection(
        cast(WebSocket, None),  # the frames are queued; the writer is not running
        encoding="cv.v1.json",
        clock=lambda: 0.0,
        wall_ms=lambda: 0,
        auth_timeout_s=10.0,
        flag_visible=default_registry().visible_to,
        backpressure=BackpressureConfig(),  # #2409: the budgeted pipeline
    )
    conn.authz = ConnectionAuthz(who)
    return conn


def _queued(conn: _Connection) -> list[dict[str, Any]]:
    """Every frame `conn`'s pipeline holds, in order (§8.4; `system` rides the priority lane)."""
    assert conn.pipeline is not None
    frames = []
    while (item := conn.pipeline.queue.pop()) is not None:
        frames.append(json.loads(item.payload))
    return frames


@settings(max_examples=300, deadline=None)
@given(who=st.sampled_from(_WHO), steps=st.lists(_STEPS, max_size=30))
def test_no_system_delta_is_ever_queued_before_the_snap(
    who: PrincipalSnapshot, steps: list[tuple[str, Any]]
) -> None:
    conn = _bare(who)
    for op, arg in steps:
        if op == "push":
            conn.push_system(arg)
        elif op == "snap":
            conn.push_system(arg, snap=True)
        else:
            assert conn.authz is not None
            conn.authz.principal = arg
    frames = _queued(conn)
    system = [f for f in frames if f.get("ch") == "system"]
    if system:
        assert (system[0]["t"], system[0]["s"]) == ("snap", 1)
    assert [f["t"] for f in system[1:]] == ["d"] * (len(system) - 1)  # one snap, then deltas
    assert [f["s"] for f in system] == list(range(1, len(system) + 1))  # gapless from 1

"""#2302 (`23-ws-protocol.md` §15.9; the security review's M2): a socket's safety state follows a
change of its scope at once, through the real `/ws` router. A grant withdrawn mid-session sends
the `cleared` of what it no longer may see, stamped with the change's time; a grant added sends
the `raised` of a live incident it now may see; neither waits for the publisher. Same rig as
`test_system_topic_roles.py`: no threads, no sleeps."""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Callable
from typing import Any, cast

import pytest
from fastapi import WebSocket

from candleviewer.admin.flags import default_registry
from candleviewer.ws import gateway
from candleviewer.ws.backpressure_config import BackpressureConfig
from candleviewer.ws.gateway import SYSTEM_HELD_MAX, _Connection
from candleviewer.ws.metrics import cv_ws_system_frames_withheld_total
from candleviewer.ws.permissions import ConnectionAuthz
from tests.unit.ws.test_system_filter import ACC_A, ACC_B
from tests.unit.ws.test_system_snap import _SNAP_BODY, _queued, _rig
from tests.unit.ws.test_system_topic_roles import (
    _DEADLINE_S,
    BASE_MS,
    KILL,
    _as,
    _Rig,
    _Socket,
    _system,
)

_T0 = BASE_MS - 9_000
#: risk_lockout raised on A (1) and B (2), as the publisher hands it over.
_ON_A_AND_B: dict[str, Any] = {
    "kind": "safety",
    "severity": "critical",
    "safety_class": "risk_lockout",
    "environment": "live",
    "state": "raised",
    "affected_count": 3,
    "since_ms": _T0,
    "_by_account": {
        str(ACC_A): {"affected_count": 1, "since_ms": _T0 + 1},
        str(ACC_B): {"affected_count": 2, "since_ms": _T0},
    },
    "_at_ms": _T0 + 1,
}
_WIRE = {k: v for k, v in _ON_A_AND_B.items() if not k.startswith("_")}


async def test_a_grant_withdrawn_mid_session_clears_at_once_stamped_with_the_change() -> None:
    rig, user = _Rig(), uuid.uuid4()
    async with asyncio.timeout(_DEADLINE_S):
        sock = await rig.connect(_as(user, "manager", accounts=(ACC_A,)))
        rig.hub.broadcast_system(_ON_A_AND_B)
        assert await _system(sock) == [(2, _WIRE | {"affected_count": 1, "since_ms": _T0 + 1})]
        rig.principals[user] = _as(user, "manager", accounts=())  # A withdrawn
        await rig.registry.grants_changed(user)
        assert await _system(sock) == [
            (
                3,
                _WIRE
                | {"state": "cleared", "severity": "info", "affected_count": 0}
                | {"since_ms": BASE_MS},  # the change's time (the rig's wall clock)
            )
        ]
        # B's own clear later carries B's event time: never sent to this socket.
        rig.hub.broadcast_system(
            _ON_A_AND_B
            | {"state": "cleared", "severity": "info", "affected_count": 0, "since_ms": 7}
            | {"_by_account": {}, "_at_ms": 7}
        )
        assert await _system(sock) == []
        await rig.close()


async def test_a_grant_added_mid_session_shows_the_live_incident_at_once() -> None:
    rig, user = _Rig(), uuid.uuid4()
    async with asyncio.timeout(_DEADLINE_S):
        sock = await rig.connect(_as(user, "manager", accounts=(ACC_A,)))
        only_b = _ON_A_AND_B | {
            "affected_count": 2,
            "_by_account": {str(ACC_B): {"affected_count": 2, "since_ms": _T0}},
        }
        rig.hub.broadcast_system(only_b)
        assert await _system(sock) == []  # nothing of B: not even a frame
        rig.principals[user] = _as(user, "manager", accounts=(ACC_A, ACC_B))
        await rig.registry.grants_changed(user)
        assert await _system(sock) == [(2, _WIRE | {"affected_count": 2, "since_ms": _T0})]
        await rig.close()


async def test_an_in_place_reauth_that_narrows_the_scope_clears_too() -> None:
    rig, user = _Rig(), uuid.uuid4()
    async with asyncio.timeout(_DEADLINE_S):
        sock = await rig.connect(_as(user, "manager", accounts=(ACC_A,)))
        rig.hub.broadcast_system(_ON_A_AND_B)
        assert len(await _system(sock)) == 1
        rig.principals[user] = _as(user, "manager", accounts=())
        sock.feed({"t": "auth", "id": "re", "p": {"access_token": str(user)}})
        assert (await sock.sent.get())["t"] == "auth_ok"
        [(_, cleared)] = await _system(sock)
        assert (cleared["state"], cleared["since_ms"]) == ("cleared", BASE_MS)
        await rig.close()


async def test_a_role_removed_then_a_clear_then_the_role_restored_revives_nothing() -> None:
    """L4: the publisher's clear while the socket may see nothing is still kept, so restoring
    the role sends no stale `raised`."""
    rig, user = _Rig(), uuid.uuid4()
    async with asyncio.timeout(_DEADLINE_S):
        sock = await rig.connect(_as(user, "manager", accounts=(ACC_A,)))
        rig.hub.broadcast_system(_ON_A_AND_B)
        assert len(await _system(sock)) == 1  # raised
        rig.principals[user] = _as(user)  # no role: the cut is nothing
        await rig.registry.grants_changed(user)
        [(_, cleared)] = await _system(sock)
        assert cleared["state"] == "cleared"
        rig.hub.broadcast_system(
            _ON_A_AND_B
            | {"state": "cleared", "severity": "info", "affected_count": 0, "since_ms": 7}
            | {"_by_account": {}, "_at_ms": 7}
        )
        assert await _system(sock) == []
        rig.principals[user] = _as(user, "manager", accounts=(ACC_A,))
        await rig.registry.grants_changed(user)
        assert await _system(sock) == []  # no stale `raised`
        await rig.close()


async def test_a_scoped_clear_on_the_live_path_takes_the_gateways_time() -> None:
    """A's own clear arrives in the body that also clears B: the socket on A gets `cleared`
    stamped with the gateway's time on receipt, not the body's event time."""
    rig, user = _Rig(), uuid.uuid4()
    async with asyncio.timeout(_DEADLINE_S):
        sock = await rig.connect(_as(user, "manager", accounts=(ACC_A,)))
        rig.hub.broadcast_system(_ON_A_AND_B)
        assert len(await _system(sock)) == 1
        rig.hub.broadcast_system(
            _ON_A_AND_B
            | {"state": "cleared", "severity": "info", "affected_count": 0, "since_ms": 7}
            | {"_by_account": {}, "_at_ms": 7}
        )
        [(_, cleared)] = await _system(sock)
        assert (cleared["state"], cleared["since_ms"]) == ("cleared", BASE_MS)
        await rig.close()


class _Held:
    """Set on the class, so called unbound: a timer the test runs itself, never the loop."""

    def __init__(self) -> None:
        self.timers: list[asyncio.TimerHandle] = []
        self.callbacks: list[Callable[[], None]] = []

    def __call__(self, delay: float, callback: Callable[[], None]) -> Any:
        handle = asyncio.get_running_loop().call_later(3600.0, callback)  # never reached here
        self.timers.append(handle)
        self.callbacks.append(callback)
        return handle


async def test_a_held_count_goes_at_the_windows_end_and_teardown_cancels_the_rest(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    held = _Held()
    monkeypatch.setattr(gateway._Connection, "_call_later", held)
    rig, user = _Rig(), uuid.uuid4()
    async with asyncio.timeout(_DEADLINE_S):
        sock = await rig.connect(_as(user, "manager", accounts=(ACC_A,)))
        rig.hub.broadcast_system(_ON_A_AND_B)
        assert len(await _system(sock)) == 1
        a_grew = _ON_A_AND_B | {
            "affected_count": 4,
            "_by_account": _ON_A_AND_B["_by_account"]
            | {str(ACC_A): {"affected_count": 2, "since_ms": _T0 + 1}},
        }
        rig.hub.broadcast_system(a_grew)
        assert await _system(sock) == []  # inside the window opened by the raise
        held.timers[0].cancel()
        held.callbacks[0]()  # the window ends
        assert await _system(sock) == [(3, _WIRE | {"affected_count": 2, "since_ms": _T0 + 1})]
        assert not held.timers[-1].cancelled()
        await rig.close()
        assert held.timers[-1].cancelled()  # teardown cancels the open window


async def test_an_unknown_safety_class_reaches_no_owner_and_is_counted() -> None:
    def invalid() -> float:
        (family,) = cv_ws_system_frames_withheld_total.collect()
        return sum(
            s.value
            for s in family.samples
            if s.name == "cv_ws_system_frames_withheld_total"
            and s.labels["reason"] == "invalid_body"
        )

    rig = _Rig()
    async with asyncio.timeout(_DEADLINE_S):
        sock = await rig.connect(_as(uuid.uuid4(), "owner"))
        before = invalid()
        rig.hub.broadcast_system(_WIRE | {"safety_class": "naked_position"})
        assert await _system(sock) == []
        assert invalid() == before + 1
        await rig.close()


class _Wall:
    def __init__(self) -> None:
        self.ms = BASE_MS

    def __call__(self) -> int:
        return self.ms


def _bare(wall: _Wall, accounts: tuple[uuid.UUID, ...] = (ACC_A,)) -> _Connection:
    """A connection whose frames are queued, the writer not running (`test_system_snap.py`)."""
    conn = _Connection(
        cast(WebSocket, None),
        encoding="cv.v1.json",
        clock=lambda: 0.0,
        wall_ms=wall,
        auth_timeout_s=10.0,
        flag_visible=default_registry().visible_to,
        backpressure=BackpressureConfig(),
    )
    conn.authz = ConnectionAuthz(_as(uuid.uuid4(), "manager", accounts=accounts))
    return conn


def _safety_sent(conn: _Connection) -> list[dict[str, Any]]:
    return [f["p"] for f in _queued(conn) if f.get("ch") == "system" and f["t"] == "d"]


def _b_moved(n: int) -> dict[str, Any]:
    """`_ON_A_AND_B` with B's count at `n`: a change of B only."""
    return _ON_A_AND_B | {
        "affected_count": 1 + n,
        "_by_account": _ON_A_AND_B["_by_account"]
        | {str(ACC_B): {"affected_count": n, "since_ms": _T0}},
        "_at_ms": _T0 + 2,
    }


async def test_a_change_of_principal_is_sent_at_its_settle_not_at_a_later_body() -> None:
    """After the principal changes, a body for another scope queues nothing; the settle queues
    one `cleared`, stamped with the settle's time."""
    wall = _Wall()
    conn = _bare(wall)
    conn.push_system(_SNAP_BODY, snap=True)
    conn.push_system(_ON_A_AND_B)
    assert [p["state"] for p in _safety_sent(conn)] == ["raised"]
    assert conn.authz is not None
    conn.authz.principal = _as(uuid.uuid4(), "manager", accounts=())  # not settled yet
    wall.ms = BASE_MS + 4_321
    conn.push_system(_b_moved(5))
    assert _safety_sent(conn) == []
    wall.ms = BASE_MS + 9_876
    conn.reconcile_safety()  # the settle
    sent = _safety_sent(conn)
    assert [(p["state"], p["since_ms"]) for p in sent] == [("cleared", BASE_MS + 9_876)]
    conn.push_system(_b_moved(6))
    assert _safety_sent(conn) == []
    conn.stop_close_timer()


async def test_a_window_that_ends_before_the_settle_sends_nothing_until_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A count update held in a window that ends before the settle goes out at the settle,
    under the new principal, and not before."""
    held = _Held()
    monkeypatch.setattr(gateway._Connection, "_call_later", held)
    wall = _Wall()
    conn = _bare(wall, accounts=(ACC_A, ACC_B))
    conn.push_system(_SNAP_BODY, snap=True)
    conn.push_system(_ON_A_AND_B)
    assert [p["affected_count"] for p in _safety_sent(conn)] == [3]
    conn.push_system(_b_moved(4))  # inside the raise's window: held
    assert _safety_sent(conn) == []
    assert conn.authz is not None
    conn.authz.principal = _as(uuid.uuid4(), "manager", accounts=(ACC_A, ACC_B))
    held.timers[0].cancel()
    held.callbacks[0]()  # the window ends before the settle
    assert _safety_sent(conn) == []
    conn.reconcile_safety()  # the settle
    assert [(p["state"], p["affected_count"]) for p in _safety_sent(conn)] == [("raised", 5)]
    conn.stop_close_timer()


async def test_safety_bodies_before_the_snap_never_displace_a_held_frame() -> None:
    """Before the snap a `safety` body is not held (the snap states the safety state), so the
    hold keeps every other frame, in order, and nothing is dropped."""

    def overflowed() -> float:
        (family,) = cv_ws_system_frames_withheld_total.collect()
        return sum(
            s.value
            for s in family.samples
            if s.name == "cv_ws_system_frames_withheld_total"
            and s.labels["reason"] == "held_overflow"
        )

    before = overflowed()
    conn = _bare(_Wall(), accounts=(ACC_A, ACC_B))
    conn.push_system(KILL)
    for n in range(SYSTEM_HELD_MAX + 5):
        conn.push_system(_ON_A_AND_B | {"affected_count": 3 + n})
    conn.push_system(_SNAP_BODY, snap=True)
    frames = [f for f in _queued(conn) if f.get("ch") == "system"]
    assert [(f["t"], f["s"]) for f in frames] == [("snap", 1), ("d", 2)]
    assert frames[1]["p"]["kind"] == "kill_switch"
    assert overflowed() == before
    conn.stop_close_timer()


async def test_a_safety_body_during_the_snaps_flag_read_is_in_the_snap() -> None:
    """The flag read is the snap's one await: a safety body broadcast meanwhile is not held, and
    the coverage read after it states the class, so the snap carries it."""
    gate, reading = asyncio.Event(), asyncio.Event()
    coverage: list[dict[str, Any]] = []

    async def slow(user: uuid.UUID, roles: frozenset[str]) -> dict[str, Any] | None:
        reading.set()
        await gate.wait()
        return None

    rig = _rig(lambda: {"kind": "health", "safety_classes": list(coverage)}, slow)
    principal = _as(uuid.uuid4(), "manager", accounts=(ACC_A,))
    async with asyncio.timeout(_DEADLINE_S):
        rig.principals[principal.user_id] = principal
        sock = _Socket()
        rig.handlers.append((sock, asyncio.create_task(rig.endpoint(sock))))
        sock.feed({"t": "hello", "id": "h"})
        assert (await sock.sent.get())["t"] == "welcome"
        sock.feed({"t": "auth", "id": "a", "p": {"access_token": str(principal.user_id)}})
        await reading.wait()
        coverage.append(
            {k: v for k, v in _ON_A_AND_B.items() if k not in {"kind", "severity", "_at_ms"}}
        )
        assert rig.hub.broadcast_system(_ON_A_AND_B) == 1  # it reaches this very socket
        gate.set()
        assert (await sock.sent.get())["t"] == "auth_ok"
        snap = await sock.sent.get()
        assert (snap["t"], snap["s"]) == ("snap", 1)
        assert snap["p"]["safety_classes"] == [
            {
                "safety_class": "risk_lockout",
                "environment": "live",
                "state": "raised",
                "affected_count": 1,
                "since_ms": _T0 + 1,
            }
        ]
        assert await _system(sock) == []  # the body itself is not sent after the snap
        await rig.close()

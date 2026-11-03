"""#2302 (`23-ws-protocol.md` §15.9; the security review's M2): a socket's safety state follows a
change of its scope at once, through the real `/ws` router. A grant withdrawn mid-session sends
the `cleared` of what it no longer may see, stamped with the change's time; a grant added sends
the `raised` of a live incident it now may see; neither waits for the publisher. Same rig as
`test_system_topic_roles.py`: no threads, no sleeps."""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Callable
from typing import Any

import pytest

from candleviewer.ws import gateway
from candleviewer.ws.metrics import cv_ws_system_frames_withheld_total
from tests.unit.ws.test_system_filter import ACC_A, ACC_B
from tests.unit.ws.test_system_topic_roles import _DEADLINE_S, BASE_MS, _as, _Rig, _system

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

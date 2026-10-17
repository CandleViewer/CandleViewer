"""#2272 through the real `create_app()` wiring (23-ws-protocol.md §4.1, §9.5; E09-S03).

An owner TOTP reset closes every open socket of the target user with `bye session_revoked`
+ `4401` within 5 s: a receive deadline on the monotonic clock. No injected time passes, so no
token deadline closed them. A refused reset closes nothing, another user's socket stays open,
and a refresh-token rotation leaves the socket open for its in-place re-`auth`.

The composition root wires the auth module only with a real database, so `build_auth_service`
returns the same `AuthService` over in-memory fakes here. Its `start()` builds the session and
step-up services as in production, so they publish to the sink `create_app()` attached.
"""

from __future__ import annotations

import functools
import time
import uuid
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi import Request
from fastapi.testclient import TestClient

from candleviewer import app as app_module
from candleviewer.app import create_app
from candleviewer.auth.generated_permissions import Permission
from candleviewer.auth.models import MintedSession
from candleviewer.auth.scopes import PrincipalSnapshot
from candleviewer.auth.service import AuthService
from candleviewer.auth.step_up import GRACE_WINDOW
from candleviewer.settings import Settings
from candleviewer.ws.gateway import make_ws_router
from candleviewer.ws.revocation import CLOSE_TOKEN_EXPIRED, CLOSE_USER_DISABLED, RevocationHub
from tests.csrf_helpers import arm_csrf
from tests.unit.auth.auth_fakes import FakeUserRepository, make_user
from tests.unit.auth.mfa_fakes import FakeMfaRepository
from tests.unit.auth.session_fakes import FakeSessionRepository

_T0 = datetime(2026, 10, 15, 12, 0, 0, tzinfo=UTC)
#: E09-S03 "Revocation propagation": the socket closes within 5 s of the revocation.
_CLOSE_BOUND = timedelta(seconds=5)
_WS_TIMEOUT_S = 5.0
_ORIGIN = "http://testserver"  # §2.5: allow-listed and sent on every request and upgrade
_OWNER, _MANAGER, _TARGET = (uuid.uuid5(uuid.NAMESPACE_URL, f"cv-2272/{n}") for n in "omt")
_ROLES = {_OWNER: "owner", _MANAGER: "manager", _TARGET: "manager"}
_INERT_DIGEST = "unused"  # stored-hash placeholder: no password is ever verified here


class _Clock:
    def __init__(self) -> None:
        self.now = _T0

    def __call__(self) -> datetime:
        return self.now


class _Users:
    """`UserRoleStore` over the three users of this module."""

    async def get_roles(self, user_id: uuid.UUID) -> frozenset[str] | None:
        role = _ROLES.get(user_id)
        return None if role is None else frozenset({role})

    async def count_active_owners(self) -> int:
        return 1

    async def apply_roles(self, user_id: uuid.UUID, roles: frozenset[str]) -> bool:
        return user_id in _ROLES


class _Principals:
    """`SnapshotResolver`: the bearer's user, from the tokens this module minted."""

    def __init__(self) -> None:
        self.by_token: dict[str, uuid.UUID] = {}

    def resolve(self, request: Request) -> PrincipalSnapshot | None:
        token = request.headers.get("authorization", "").partition(" ")[2].strip()
        user = self.by_token.get(token)
        if user is None:
            return None
        perms = frozenset(Permission) if _ROLES[user] == "owner" else frozenset()
        return PrincipalSnapshot(user, frozenset({_ROLES[user]}), perms)


async def _ws_principal(user_id: uuid.UUID) -> PrincipalSnapshot:
    return PrincipalSnapshot(
        user_id, frozenset({"manager"}), frozenset({Permission.MARKETDATA_READ})
    )


class _Env:
    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.clock = _Clock()
        self.repo = FakeSessionRepository()
        # Every session belongs to a user with a confirmed TOTP method: a session of an unknown
        # user is never a full one (#2295).
        users = FakeUserRepository()
        for user_id in _ROLES:
            user = make_user(password_hash=_INERT_DIGEST, username=str(user_id), email="u@x.t")
            users.add(user.model_copy(update={"id": user_id}))
        self.auth = AuthService(
            users,
            mfa_repository=FakeMfaRepository(),
            session_repository=self.repo,
            clock=self.clock,
        )
        monkeypatch.setattr(app_module, "build_auth_service", lambda *_a, **_k: self.auth)
        # The gateway checks token expiry on its wall clock (#2259): share the injected one.
        monkeypatch.setattr(
            app_module,
            "make_ws_router",
            functools.partial(
                make_ws_router, wall_ms=lambda: int(self.clock.now.timestamp() * 1000)
            ),
        )
        self.principals = _Principals()
        self.app = create_app(
            Settings(allowed_origins=_ORIGIN),
            snapshot_loader=_ws_principal,
            principal_resolver=self.principals,
            user_role_store=_Users(),
            auth_clock=self.clock,
        )
        self.audit: list[dict[str, Any]] = []
        self.app.state.app_context.audit._writer = self  # stand-in for the started AuditWriter
        self.client = TestClient(self.app, client=("127.0.0.1", 50000), headers={"origin": _ORIGIN})

    async def emit(self, action: str, **kw: Any) -> None:
        self.audit.append({"action": action, **kw})

    def run(self, fn: Any, *args: Any, **kwargs: Any) -> Any:
        assert self.client.portal is not None
        return self.client.portal.call(lambda: fn(*args, **kwargs))

    def mint(self, user: uuid.UUID) -> MintedSession:
        minted: MintedSession = self.run(self.auth.sessions.mint, str(user))
        self.principals.by_token[minted.access_token] = user
        return minted

    def elevate(self, minted: MintedSession) -> None:
        """A completed step-up for `users` on this session (SR-025), as the row stores it."""
        self.run(
            self.repo.save_step_up_state,
            str(minted.session_id),
            elevations={"users": self.clock.now + GRACE_WINDOW},
            failures=0,
            readonly_until=None,
        )

    def reset(self, actor: MintedSession, target: uuid.UUID) -> Any:
        arm_csrf(self.client, self.app.state.csrf_codec, actor.session_id)
        return self.client.post(
            f"/users/{target}/mfa/reset",
            headers={"Authorization": f"Bearer {actor.access_token}"},
            json={"acknowledge_unknown_positions": True},  # no position store: must acknowledge
        )


@pytest.fixture
def env(monkeypatch: pytest.MonkeyPatch) -> Iterator[_Env]:
    e = _Env(monkeypatch)
    with e.client:
        e.run(e.auth.start, e.app.state.app_context)
        yield e
        e.run(e.auth.stop, 1.0)


def _recv(ws: Any, *, deadline: float | None = None) -> dict[str, Any]:
    """`receive_json` failing after `_WS_TIMEOUT_S`, or at monotonic *deadline*, not hanging."""
    timeout = _WS_TIMEOUT_S if deadline is None else max(0.0, deadline - time.monotonic())
    pool = ThreadPoolExecutor(max_workers=1)
    try:
        frame: dict[str, Any] = pool.submit(ws.receive_json).result(timeout=timeout)
    except FutureTimeout:
        pytest.fail(f"no WS frame within {timeout:.1f}s (expected frame never arrived)")
    finally:
        pool.shutdown(wait=False, cancel_futures=True)
    return frame


def _authenticate(ws: Any, token: str) -> dict[str, Any]:
    ws.send_json({"t": "hello", "id": "h"})
    assert _recv(ws)["t"] == "welcome"
    ws.send_json({"t": "auth", "id": "a", "p": {"access_token": token}})
    return _recv(ws)


def _still_open(ws: Any) -> bool:
    ws.send_json({"t": "ping", "id": "p", "p": {}})
    kind: str = _recv(ws)["t"]
    return kind == "pong"


def test_owner_totp_reset_closes_every_socket_of_the_target_within_the_bound(env: _Env) -> None:
    owner = env.mint(_OWNER)
    env.elevate(owner)
    phone, desktop = env.mint(_TARGET), env.mint(_TARGET)
    url = "/ws"
    with (
        env.client.websocket_connect(url, subprotocols=["cv.v1.json"]) as ws_phone,
        env.client.websocket_connect(url, subprotocols=["cv.v1.json"]) as ws_desktop,
        env.client.websocket_connect(url, subprotocols=["cv.v1.json"]) as ws_owner,
    ):
        for ws, minted in ((ws_phone, phone), (ws_desktop, desktop), (ws_owner, owner)):
            assert _authenticate(ws, minted.access_token)["t"] == "auth_ok"
        action_at = env.clock.now
        deadline = time.monotonic() + _CLOSE_BOUND.total_seconds()  # E09-S03, from the reset

        response = env.reset(owner, _TARGET)

        assert response.status_code == 200, response.text
        assert response.json()["sessions_revoked"] == 2
        for ws in (ws_phone, ws_desktop):
            bye = _recv(ws, deadline=deadline)
            assert bye["t"] == "bye"
            assert bye["p"]["code"] == CLOSE_TOKEN_EXPIRED
            assert bye["p"]["reason"] == "session_revoked"
            assert bye["p"]["reconnect"] is False
        assert _still_open(ws_owner), "the reset must not close another user's socket"
    assert env.clock.now == action_at, "no injected time passed, so no token deadline fired"
    for minted in (phone, desktop):
        row = env.repo.sessions[str(minted.session_id)]
        assert row.revoked_reason == "mfa_reset_by_owner"
        assert row.revoked_at == action_at
    assert "auth.mfa_reset_by_owner" in [e["action"] for e in env.audit]


def test_refused_reset_by_a_manager_closes_nothing(env: _Env) -> None:
    manager = env.mint(_MANAGER)
    env.elevate(manager)
    target = env.mint(_TARGET)
    with env.client.websocket_connect("/ws", subprotocols=["cv.v1.json"]) as ws:
        assert _authenticate(ws, target.access_token)["t"] == "auth_ok"

        response = env.reset(manager, _TARGET)

        assert response.status_code == 403, response.text
        assert _still_open(ws)
    assert env.repo.sessions[str(target.session_id)].revoked_at is None


def test_refresh_rotation_keeps_the_socket_open_for_its_in_place_reauth(env: _Env) -> None:
    target = env.mint(_TARGET)
    with env.client.websocket_connect("/ws", subprotocols=["cv.v1.json"]) as ws:
        assert _authenticate(ws, target.access_token)["t"] == "auth_ok"

        rotated = env.run(env.auth.sessions.refresh, target.refresh_token)

        assert _still_open(ws), "a rotation must not close the socket (§4.1)"
        ws.send_json({"t": "auth", "id": "r", "p": {"access_token": rotated.minted.access_token}})
        ok = _recv(ws)
        assert ok["t"] == "auth_ok"
        assert ok["p"]["session_id"] == str(rotated.minted.session_id)


@pytest.mark.parametrize(
    ("revoke_reason", "bye_reason", "close_code"),
    [
        ("mfa_reset_by_owner", "session_revoked", CLOSE_TOKEN_EXPIRED),
        ("unlock_attempts_exceeded", "session_revoked", CLOSE_TOKEN_EXPIRED),
        # The SR-029 cascade keeps its own §9.5 `bye`, and 4403 so the client does not reconnect.
        ("user_disabled", "user_disabled", CLOSE_USER_DISABLED),
    ],
)
async def test_hub_publisher_sends_the_client_only_a_closed_set_reason(
    revoke_reason: str, bye_reason: str, close_code: int
) -> None:
    hub = RevocationHub()
    closes: list[tuple[str, int, int]] = []

    async def closer(frame: dict[str, Any], code: int) -> None:
        closes.append((frame["p"]["reason"], frame["p"]["code"], code))

    hub.register("sid", closer)

    await app_module._hub_publisher(hub)("sid", revoke_reason)

    assert closes == [(bye_reason, close_code, close_code)]

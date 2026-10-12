"""E09-X04 SR-029 automated counterpart of the disable-user drill (in-process, no network).

The `DELETE /users/{userId}` disable cascade is owned by E42-T04 (#965) and does not exist yet,
so this test drives the same primitives that cascade must call, through the real
`create_app()` wiring: `SessionService.revoke_all` and the app's own `RevocationHub`. It is a
regression guard for the propagation path, not the staging drill (which a human still runs).

Measured on the injected clock only: revocation is stamped at the action instant (zero
injected-time delay, i.e. no timer/deferred path), and every effect is observed before the call
returns. Every WS read has a hard deadline so a missing `bye` fails fast instead of hanging.
"""

from __future__ import annotations

import functools
import os
import uuid
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient

from candleviewer import app as app_module
from candleviewer.app import create_app
from candleviewer.auth.envelope import TotpEncryptor
from candleviewer.auth.errors import SessionNotFound, SessionRevoked
from candleviewer.auth.generated_permissions import Permission
from candleviewer.auth.hashing import Hasher
from candleviewer.auth.scopes import PrincipalSnapshot
from candleviewer.auth.session_service import SessionService
from candleviewer.auth.step_up import StepUpService
from candleviewer.ws.gateway import make_ws_router
from candleviewer.settings import Settings
from candleviewer.ws.revocation import CLOSE_TOKEN_EXPIRED, RevocationHub
from tests.unit.auth.auth_fakes import FakeUserRepository
from tests.unit.auth.mfa_fakes import FakeMfaRepository
from tests.unit.auth.session_fakes import FakeSessionRepository

_T0 = datetime(2026, 10, 9, 12, 0, 0, tzinfo=UTC)
#: SR-029 says "immediately"; E42-T04 states the product bound as 5 s.
_SR029_BOUND = timedelta(seconds=5)
_WS_TIMEOUT_S = 5.0
_ORIGIN = "http://testserver"  # §2.5: in CV_ALLOWED_ORIGINS and sent on every WS upgrade


class _Clock:
    def __init__(self) -> None:
        self.now = _T0
        self.reads = 0

    def __call__(self) -> datetime:
        self.reads += 1
        return self.now


async def _snapshot(uid: uuid.UUID) -> PrincipalSnapshot:
    return PrincipalSnapshot(uid, frozenset({"manager"}), frozenset({Permission.MARKETDATA_READ}))


class _Env:
    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.clock = _Clock()
        self.repo = FakeSessionRepository()
        # The gateway checks the token's real expiry (#2259) on its wall clock: give it the
        # injected clock, so both sides of that comparison share one time base.
        monkeypatch.setattr(
            app_module,
            "make_ws_router",
            functools.partial(
                make_ws_router, wall_ms=lambda: int(self.clock.now.timestamp() * 1000)
            ),
        )
        self.app = create_app(snapshot_loader=_snapshot, auth_clock=self.clock)
        self.app = create_app(
            Settings(allowed_origins=_ORIGIN), snapshot_loader=_snapshot, auth_clock=self.clock
        )
        auth: Any = self.app.state.app_context.auth
        self.sessions = SessionService(
            self.repo, Hasher(pepper=os.urandom(16).hex()), clock=self.clock
        )
        self.step_up = StepUpService(
            FakeMfaRepository(),
            self.repo,
            TotpEncryptor(os.urandom(32)),
            FakeUserRepository(),
            Hasher(),
            clock=self.clock,
        )
        # The composition root wires these only with a real database; same seams, fake storage.
        auth._sessions = self.sessions
        auth._step_up = self.step_up
        self.audit: list[dict[str, Any]] = []
        self.app.state.app_context.audit._writer = self  # stand-in for the started AuditWriter
        self.hub: RevocationHub = self.app.state.revocation_hub
        self.client = TestClient(self.app, client=("127.0.0.1", 50000), headers={"origin": _ORIGIN})

    async def emit(self, action: str, **kw: Any) -> None:
        self.audit.append({"action": action, **kw})

    def run(self, fn: Any, *args: Any, **kwargs: Any) -> Any:
        assert self.client.portal is not None
        return self.client.portal.call(lambda: fn(*args, **kwargs))

    async def disable(self, user_id: str) -> int:
        """What SR-029 requires of the cascade: revoke every session, then close every socket."""
        revoked = await self.sessions.revoke_all(user_id, reason="user_disabled")
        closed = 0
        for record in revoked:
            closed += await self.hub.revoke(str(record.id), "user_disabled")
        return closed


@pytest.fixture
def env(monkeypatch: pytest.MonkeyPatch) -> Any:
    e = _Env(monkeypatch)
    with e.client:
        yield e
        e.run(e.step_up.stop)


def _recv(ws: Any) -> dict[str, Any]:
    """`receive_json` with a hard deadline (same pattern as the E09-Q03 RBAC pack). The blocking
    read runs in a worker thread; leaving the `with` block closes the socket and unblocks it."""
    pool = ThreadPoolExecutor(max_workers=1)
    try:
        frame: dict[str, Any] = pool.submit(ws.receive_json).result(timeout=_WS_TIMEOUT_S)
    except FutureTimeout:
        pytest.fail(f"no WS frame within {_WS_TIMEOUT_S}s (expected frame never arrived)")
    finally:
        pool.shutdown(wait=False, cancel_futures=True)
    return frame


def _auth_ws(ws: Any, token: str, attempts: int = 1) -> dict[str, Any]:
    """`hello` then `attempts` x `auth` (§4.3: a failure closes on the 3rd attempt)."""
    ws.send_json({"t": "hello", "id": "h"})
    assert _recv(ws)["t"] == "welcome"
    frame: dict[str, Any] = {}
    for _ in range(attempts):
        ws.send_json({"t": "auth", "id": "a", "p": {"access_token": token}})
        frame = _recv(ws)
    return frame


def test_disable_user_drill_terminates_sessions_sockets_and_pending_actions(env: Any) -> None:
    user = str(uuid.uuid4())
    other = str(uuid.uuid4())
    a = env.run(env.sessions.mint, user)
    b = env.run(env.sessions.mint, user)
    bystander = env.run(env.sessions.mint, other)
    # Pending activity: a step-up challenge recorded against the live session.
    env.run(env.step_up.record_pending, str(a.session_id), "users")
    assert env.run(env.step_up.pending_action_class, str(a.session_id)) == "users"

    with env.client.websocket_connect("/ws", subprotocols=["cv.v1.json"]) as ws:
        ok = _auth_ws(ws, a.access_token)
        assert ok["t"] == "auth_ok"
        ws.send_json({"t": "sub", "id": "s", "p": {"topics": [{"ch": "book.BTCUSDT.50"}]}})
        assert _recv(ws)["p"]["results"][0]["ok"] is True

        action_at = env.clock.now
        closed = env.run(env.disable, user)

        bye = _recv(ws)
        assert bye["t"] == "bye"
        assert bye["p"]["code"] == CLOSE_TOKEN_EXPIRED
        assert bye["p"]["reason"] == "user_disabled"
        assert bye["p"]["reconnect"] is False
    assert closed == 1

    # Sessions terminated, stamped at the action instant on the injected clock.
    for minted in (a, b):
        rec = env.repo.sessions[str(minted.session_id)]
        assert rec.revoked_at is not None
        assert rec.revoked_at - action_at == timedelta(0)
        assert rec.revoked_at - action_at <= _SR029_BOUND
        assert rec.revoked_reason == "user_disabled"
        with pytest.raises((SessionRevoked, SessionNotFound)):
            env.run(env.sessions.authenticate_access_token, minted.access_token)
    # Pending activity cancelled: the challenge is gone and cannot be completed.
    assert env.run(env.step_up.pending_action_class, str(a.session_id)) is None
    # Blast radius: another user's session is untouched.
    assert env.repo.sessions[str(bystander.session_id)].revoked_at is None


def test_disable_user_drill_revoked_token_cannot_reopen_a_socket(env: Any) -> None:
    user = str(uuid.uuid4())
    minted = env.run(env.sessions.mint, user)
    env.run(env.disable, user)
    with env.client.websocket_connect("/ws", subprotocols=["cv.v1.json"]) as ws:
        bye = _auth_ws(ws, minted.access_token, attempts=3)
        assert (bye["t"], bye["p"]["reason"]) == ("bye", "auth_failed")


def test_disable_user_drill_is_idempotent(env: Any) -> None:
    user = str(uuid.uuid4())
    env.run(env.sessions.mint, user)
    env.run(env.disable, user)
    assert env.run(env.disable, user) == 0

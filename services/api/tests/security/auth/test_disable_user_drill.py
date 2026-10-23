"""E09-X04 SR-029 automated counterpart of the disable-user drill (in-process, no network).

The Owner disables a manager through the real route, `DELETE /users/{userId}` (E42-T04, #965),
on the deployed `create_app()` that `test_disable_user_e2e.py` builds: its world is imported here,
never copied. That module pins the cascade's records (`users.disable` with `positions_decision`,
the rule disarmed, the grants revoked); this one pins what the drill watches from the manager's
side: a private subscription ends with `bye user_disabled` (`4403`, `reconnect: false`) and then
the close, with no frame after the `bye` (23-ws-protocol.md §9.5, never the `4401` re-auth close,
#2493); a pending step-up challenge is gone; the revoked token opens no socket; a second disable
changes nothing; and the wall time from the `DELETE` to the `bye`, measured, under the 5 s bound.
The dev-stack drill that a person-or-agent runs (#2494) is recorded in
`docs/security/reviews/e09-auth-review.md` section 4 with #300's second PR. The #2911 cases (a
stray session no disable swept) keep their own harness: they drive the session service's refusal,
not the route.
"""

from __future__ import annotations

import functools
import os
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from candleviewer import app as app_module
from candleviewer.app import create_app
from candleviewer.auth.envelope import TotpEncryptor
from candleviewer.auth.generated_permissions import Permission
from candleviewer.auth.hashing import Hasher
from candleviewer.auth.models import UserStatus
from candleviewer.auth.scopes import PrincipalSnapshot
from candleviewer.auth.session_service import SessionService
from candleviewer.auth.step_up import StepUpService
from candleviewer.settings import Settings
from candleviewer.ws.gateway import make_ws_router
from candleviewer.ws.revocation import CLOSE_USER_DISABLED, RevocationHub
from tests.unit.auth.auth_fakes import FakeUserRepository, FullUsers
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
        auth._repository = FullUsers(self.repo.user_statuses)  # #2295, as #2911 reads users
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


def _e2e() -> Any:
    """`test_disable_user_e2e`, whose deployed world the route's cases run in. Imported on use:
    that module imports this one's socket helpers, so a module-level import would be circular."""
    from tests.security.auth import test_disable_user_e2e

    return test_disable_user_e2e


def _until_bye(ws: Any) -> list[dict[str, Any]]:
    """The frames up to and including the `bye`: a `snap` the subscription queued before the
    disable may come first, never after it."""
    frames = [_recv(ws)]
    while frames[-1].get("t") != "bye":
        frames.append(_recv(ws))
    return frames


def _disable_a_subscribed_manager() -> tuple[int, list[dict[str, Any]], int, float]:
    """M with one live session and a socket subscribed to `positions` on its live grant;
    the Owner, stepped up, disables M through the route. The route's status, the frames up to the
    `bye`, the close code that follows, and the wall time from the `DELETE` to the `bye`."""
    e2e = _e2e()
    with e2e._world() as (w, app, client):
        assert client.portal is not None  # inside the client's `with`
        run = client.portal.call
        w.repo.grants[(e2e._M, e2e._ACCOUNT)]["frozen"] = False  # in scope: a frozen grant is not
        headers = e2e._owner_headers(app, run, w, str(e2e._OWNER))
        minted = run(app.state.app_context.auth.sessions.mint, str(e2e._M))
        positions = {"ch": "positions", "opts": {"exchange_account_ids": [str(e2e._ACCOUNT)]}}
        with client.websocket_connect("/ws", subprotocols=["cv.v1.json"]) as ws:
            assert _auth_ws(ws, minted.access_token)["t"] == "auth_ok"
            ws.send_json({"t": "sub", "id": "s", "p": {"topics": [positions]}})
            answer = _recv(ws)
            assert (answer["t"], answer["p"]["results"][0]["ok"]) == ("sub_ok", True)
            started = time.monotonic()
            status = e2e.delete_disable(client, str(e2e._M), headers, ack=True).status_code
            frames = _until_bye(ws)
            elapsed = time.monotonic() - started
            with pytest.raises(WebSocketDisconnect) as close:  # §9.5: no frame after the `bye`
                _recv(ws)
    return status, frames, close.value.code, elapsed


def test_a_disable_through_the_route_ends_a_private_subscription_with_bye_and_4403() -> None:
    status, frames, code, _ = _disable_a_subscribed_manager()
    p = frames[-1]["p"]
    assert status == 204
    # 23-ws-protocol.md section 9.5's number, not the module's constant: the interface it pins
    assert (p["reason"], p["reconnect"], p["code"], code) == ("user_disabled", False, 4403, 4403)


def test_a_disable_through_the_route_reaches_the_socket_within_the_sr029_bound() -> None:
    """The drill's measured figure: the wall time from the Owner's `DELETE` to the manager's
    `bye`, in-process, under the 5 s bound E42-T04 states for SR-029's "immediately"."""
    _, _, _, elapsed = _disable_a_subscribed_manager()
    assert elapsed < _SR029_BOUND.total_seconds(), f"the DELETE to the bye took {elapsed:.3f} s"


def test_a_disable_through_the_route_cancels_a_pending_step_up_challenge() -> None:
    e2e = _e2e()
    with e2e._world() as (w, app, client):
        assert client.portal is not None
        run, auth = client.portal.call, app.state.app_context.auth
        headers = e2e._owner_headers(app, run, w, str(e2e._OWNER))
        minted = run(auth.sessions.mint, str(e2e._M))
        run(auth.step_up.record_pending, str(minted.session_id), "users")
        assert run(auth.step_up.pending_action_class, str(minted.session_id)) == "users"
        assert e2e.delete_disable(client, str(e2e._M), headers, ack=True).status_code == 204
        assert run(auth.step_up.pending_action_class, str(minted.session_id)) is None


def test_a_disabled_managers_token_opens_no_socket() -> None:
    e2e = _e2e()
    with e2e._world() as (w, app, client):
        assert client.portal is not None
        run = client.portal.call
        headers = e2e._owner_headers(app, run, w, str(e2e._OWNER))
        minted = run(app.state.app_context.auth.sessions.mint, str(e2e._M))
        assert e2e.delete_disable(client, str(e2e._M), headers, ack=True).status_code == 204
        with client.websocket_connect("/ws", subprotocols=["cv.v1.json"]) as ws:
            bye = _auth_ws(ws, minted.access_token, attempts=3)
    assert (bye["t"], bye["p"]["reason"]) == ("bye", "auth_failed")


def test_a_second_disable_answers_204_and_writes_no_record() -> None:
    """A repeat needs no acknowledgement and writes no `users.disable` (E42-T04 AC5)."""
    e2e = _e2e()
    with e2e._world() as (w, app, client):
        assert client.portal is not None
        records = app.state.app_context.audit.writer.records
        headers = e2e._owner_headers(app, client.portal.call, w, str(e2e._OWNER))
        assert e2e.delete_disable(client, str(e2e._M), headers, ack=True).status_code == 204
        written = sum(1 for r in records if r["action"] == "users.disable")
        assert e2e.delete_disable(client, str(e2e._M), headers, ack=False).status_code == 204
        assert sum(1 for r in records if r["action"] == "users.disable") == written == 1


def _with_the_hubs_sink(env: Any) -> Any:
    """The app's auth service with sessions wired as the composition root wires them: a revocation
    reaches the hub, which the env's own `SessionService` does not (it has no sink)."""
    auth: Any = env.app.state.app_context.auth
    auth._sessions = SessionService(
        env.repo,
        Hasher(pepper=os.urandom(16).hex()),
        clock=env.clock,
        publish_revocation=app_module._hub_publisher(env.hub),
    )
    return auth


def test_disable_user_drill_stray_session_is_refused_and_its_socket_closed_4403(env: Any) -> None:
    """#2911: a live session of a disabled user that no disable revoked (one minted after the
    sweep, before mints read `users.status`) is refused on its next use: REST answers 401 and
    its socket ends `bye user_disabled` + 4403, never the 4401 re-auth close."""
    auth = _with_the_hubs_sink(env)
    user = str(uuid.uuid4())
    stray = env.run(auth.sessions.mint, user)

    with env.client.websocket_connect("/ws", subprotocols=["cv.v1.json"]) as ws:
        assert _auth_ws(ws, stray.access_token)["t"] == "auth_ok"
        env.repo.user_statuses[user] = UserStatus.DISABLED  # disabled; this session was not swept
        bearer = {"Authorization": f"Bearer {stray.access_token}"}
        assert env.client.get("/auth/session", headers=bearer).status_code == 401

        bye = _recv(ws)
        assert (bye["t"], bye["p"]["reason"], bye["p"]["code"]) == ("bye", "user_disabled", 4403)
        with pytest.raises(WebSocketDisconnect) as close:
            _recv(ws)
        assert close.value.code == CLOSE_USER_DISABLED
    assert env.repo.sessions[str(stray.session_id)].revoked_reason == "user_disabled"
    assert env.run(env.repo.find_live_by_user, user) == ()


def test_disable_user_drill_stray_token_is_refused_auth_failed_on_a_fresh_socket(env: Any) -> None:
    """#2911 (§9.5): a socket whose first `auth` presents the stray token is not registered with
    the hub yet, so it gets `err auth_failed` like any refused `auth`, never `bye user_disabled`;
    the session is revoked all the same."""
    auth = _with_the_hubs_sink(env)
    user = str(uuid.uuid4())
    stray = env.run(auth.sessions.mint, user)
    env.repo.user_statuses[user] = UserStatus.DISABLED  # disabled; this session was not swept

    with env.client.websocket_connect("/ws", subprotocols=["cv.v1.json"]) as ws:
        refused = _auth_ws(ws, stray.access_token)

    assert (refused["t"], refused["p"]["code"]) == ("err", "auth_failed")
    assert env.repo.sessions[str(stray.session_id)].revoked_reason == "user_disabled"

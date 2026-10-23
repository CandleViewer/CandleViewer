"""#3085 S12: `GET` and `DELETE /auth/session/view-as`, the viewer's own read and end of its
session's view-as context (22-api-openapi.yaml `getViewAs`, `endViewAs`, "View-as session").

The router behind the guards `create_app` puts in front of it, outermost first (SR-041, the idle
lock, the enrolment-only guard, the view-as guard), or bare. The session service and the view-as
service are real, over one fake store (S4's rig: recording ports and a fake clock); the target's
names are a fake `TargetNames`. No sleep and no network: the clock is fake, and a test awaits the
end record's task."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from structlog.testing import capture_logs

from candleviewer.api.contract_conformance import load_openapi_spec
from candleviewer.api.csrf import CsrfMiddleware
from candleviewer.api.deny_by_default import declared_operations, served_operations
from candleviewer.api.enrolment_guard import make_enrolment_only_guard, sessionless_operations
from candleviewer.api.idle_lock import IdleLockMiddleware, ungated_operations
from candleviewer.api.view_as import PATH, make_view_as_router
from candleviewer.api.view_as_guard import make_view_as_guard
from candleviewer.api.view_as_policy import ProtectiveWrites
from candleviewer.app import create_app
from candleviewer.auth.models import MintedSession, SessionRecord
from candleviewer.auth.session_service import (
    ACCESS_TOKEN_TTL,
    MIN_IDLE_TIMEOUT_S,
    SessionClass,
    SessionService,
)
from candleviewer.auth.view_as import ViewAsEndReason, ViewAsState
from candleviewer.storage.repositories.user_purge import surrogate
from tests.csrf_helpers import csrf_headers
from tests.unit.admin.test_view_as_service import _TARGET, _VIEWER, _at, _Rig
from tests.unit.api._fakes import BASE, CSRF_CODEC, HASHER, RecordingWriter, enrolment_recorder
from tests.unit.auth.session_fakes import FakeSessionRepository
from tests.unit.auth.test_step_up import _Clock
from tests.unit.test_view_as_wiring import _real

_SPEC = load_openapi_spec()
_DECLARED = frozenset(declared_operations(_SPEC))


class Store(FakeSessionRepository):
    """`on_leave` runs just before the leave's conditional write, as another request's write (a
    refresh's rotation, another leave) landing between the route's read and its own. A method
    named in `fails` raises, as an unreachable store does."""

    def __init__(self) -> None:
        super().__init__()
        self.on_leave: Callable[[str], Awaitable[None]] | None = None
        self.fails: set[str] = set()

    def _reach(self, method: str) -> None:
        if method in self.fails:
            raise ConnectionError("session store unreachable")

    async def find_by_access_token_jti(self, access_token_jti: str) -> SessionRecord | None:
        self._reach("find_by_access_token_jti")
        return await super().find_by_access_token_jti(access_token_jti)

    async def find_by_id(self, session_id: str) -> SessionRecord | None:
        self._reach("find_by_id")
        return await super().find_by_id(session_id)

    async def leave_view_as(
        self, session_id: str, context_id: UUID, **kwargs: Any
    ) -> tuple[SessionRecord, bool] | None:
        if self.on_leave is not None:
            await self.on_leave(session_id)
        self._reach("leave_view_as")
        return await super().leave_view_as(session_id, context_id, **kwargs)


class Names:
    """`TargetNames`: the target's row; `fails` raises from every read."""

    def __init__(self) -> None:
        self.rows: dict[str, tuple[str, str | None]] = {str(_TARGET): ("bo", "Bo B.")}
        self.fails: Exception | None = None
        self.asked: list[str] = []

    async def names(self, user_id: str) -> tuple[str, str | None]:
        self.asked.append(user_id)
        if self.fails is not None:
            raise self.fails
        if user_id not in self.rows:
            raise LookupError("unknown user")
        return self.rows[user_id]


class Auth:
    """`AuthService` as the routes and the guards read it; `enrolment_only` names the sessions the
    enrolment-only guard refuses."""

    step_up_is_active = False  # the guard reads `step_up` only to refuse a write
    step_up: Any = None
    enrolment_gate_is_active = True

    def __init__(self, sessions: SessionService) -> None:
        self.sessions, self.sessions_is_active = sessions, True
        self.enrolment_only: set[UUID] = set()

    async def classify(self, session: SessionRecord) -> SessionClass:
        return (
            SessionClass.ENROLMENT_ONLY if session.id in self.enrolment_only else SessionClass.FULL
        )


class World:
    def __init__(self, *, guarded: bool = True) -> None:
        self.repo = Store()
        self.rig = _Rig(repo=self.repo)
        self.clock, self.ports = self.rig.clock, self.rig.ports
        self.sessions = SessionService(self.repo, HASHER, clock=self.clock)
        self.auth, self.names, self.audit = Auth(self.sessions), Names(), RecordingWriter()
        self.service: Any = self.rig.service
        app = FastAPI()
        app.include_router(
            make_view_as_router(
                self.auth, views=lambda: self.service, names=self.names, clock=self.clock
            )
        )
        if guarded:  # added innermost first, so the last one added runs first
            guard = make_view_as_guard(
                self.auth,
                views=lambda: self.service,
                refusals=lambda: None,  # an own operation is never refused
                protective=ProtectiveWrites(_DECLARED),
                operations=_DECLARED,
                clock=self.clock,
            )
            app.middleware("http")(guard)
            enrolment = make_enrolment_only_guard(
                self.auth,
                refusals=enrolment_recorder(self.audit),
                operations=_DECLARED,
                sessionless=sessionless_operations(_SPEC),
            )
            app.middleware("http")(enrolment)
            app.add_middleware(IdleLockMiddleware, sessions=lambda: self.sessions, spec=_SPEC)
            app.add_middleware(
                CsrfMiddleware,
                codec=CSRF_CODEC,
                sessions=lambda: self.sessions,
                audit=self.audit,
                allowed_origins=frozenset(),
            )
        self.client = AsyncClient(transport=ASGITransport(app=app), base_url=BASE)

    async def sign_in(self, **kwargs: Any) -> MintedSession:
        return await self.sessions.mint(str(_VIEWER), **kwargs)

    async def view(self, minted: MintedSession, *, started: int = 0) -> ViewAsState:
        """Put a context on *minted*'s row, started at `_at(started)`, as the start writes it."""
        state = ViewAsState.start(uuid4(), _TARGET, now=_at(started))
        assert await self.repo.start_view_as(str(minted.session_id), state, now=self.clock())
        return state

    def held(self, minted: MintedSession) -> ViewAsState | None:
        return self.repo.sessions[str(minted.session_id)].view_as

    async def call(
        self, method: str, minted: MintedSession | None = None, *, csrf: bool = True, **kw: Any
    ) -> httpx.Response:
        headers: dict[str, str] = {}
        if minted is not None:
            headers = {"Authorization": f"Bearer {minted.access_token}"}
            headers |= csrf_headers(CSRF_CODEC, minted.session_id) if csrf else {}
        return await self.client.request(method, PATH, headers=headers, **kw)


def _code(response: httpx.Response) -> tuple[int, str]:
    assert response.headers["content-type"].startswith("application/problem+json")
    return response.status_code, response.json()["code"]


def _iso(at: datetime) -> str:
    return at.isoformat().replace("+00:00", "Z")


def _context(state: ViewAsState, phase: str, names: tuple[str, str | None]) -> dict[str, Any]:
    return {
        "target_user_id": str(_TARGET),
        "target_username": names[0],
        "target_display_name": names[1],
        "started_at": _iso(state.started_at),
        "expires_at": _iso(state.expires_at),
        "read_only": True,
        "state": phase,
    }


async def _caller(w: World, kind: str) -> MintedSession | None:
    """A caller with no live session: none at all, a token never issued, a signed-out session,
    or an access token past its 12 minutes."""
    if kind == "none":
        return None
    minted = await w.sign_in()
    if kind == "unknown":
        return minted.model_copy(update={"access_token": "never-issued"})
    if kind == "signed_out":
        await w.sessions.revoke(str(minted.session_id), reason="logout")
    if kind == "token_expired":
        w.clock.now = _at(0) + ACCESS_TOKEN_TTL
    return minted


# -- GET -------------------------------------------------------------------------------------------


async def test_get_with_no_context_answers_204() -> None:
    w = World()
    response = await w.call("GET", await w.sign_in())
    assert (response.status_code, response.content, w.names.asked) == (204, b"", [])


async def test_get_answers_a_live_context_active_and_changes_nothing() -> None:
    """Nor is it activity: the idle deadline stays where it was (contract "Idle lock")."""
    w = World()
    minted = await w.sign_in()
    state = await w.view(minted)
    w.clock.now = _at(5)
    response = await w.call("GET", minted)
    assert (response.status_code, response.json()) == (
        200,
        _context(state, "active", ("bo", "Bo B.")),
    )
    assert (w.held(minted), w.ports.closed, w.rig.runner.tasks) == (state, [], [])
    assert w.repo.sessions[str(minted.session_id)].last_seen_at == _at(0)


async def test_a_query_parameter_never_names_the_target() -> None:
    """The target is the one the session's row names, whatever the request carries."""
    w = World()
    minted = await w.sign_in()
    await w.view(minted)
    params = {"user_id": str(_VIEWER), "target_user_id": str(uuid4())}
    response = await w.call("GET", minted, params=params)
    assert (response.status_code, response.json()["target_user_id"]) == (200, str(_TARGET))
    assert w.names.asked == [str(_TARGET)]


async def test_get_answers_a_context_past_its_expiry_expired_and_writes_nothing() -> None:
    """A refresh carried the context past its expiry: held at the auth clock, and `evaluate`
    neither writes the expiry (the sweeper does) nor reads eligibility."""
    w = World()
    w.clock.now = _at(31)
    minted = await w.sign_in()
    state = await w.view(minted, started=0)
    response = await w.call("GET", minted)
    assert (response.status_code, response.json()) == (
        200,
        _context(state, "expired", ("bo", "Bo B.")),
    )
    assert (w.held(minted), w.ports.asked, w.ports.calls) == (state, 0, [])


async def test_get_ends_an_ineligible_context_and_answers_it_expired() -> None:
    w = World()
    minted = await w.sign_in()
    await w.view(minted)
    w.clock.now, w.ports.reason = _at(5), ViewAsEndReason.TARGET_INELIGIBLE
    response = await w.call("GET", minted)
    await w.rig.settled()
    held = w.held(minted)
    assert (response.status_code, response.json()["state"]) == (200, "expired")
    assert held is not None and (held.ended_at, held.end_reason) == (_at(5), "target_ineligible")
    assert w.ports.closed == [(str(minted.session_id), "view_as_expired")]
    assert [call["reason"] for call in w.ports.calls] == ["target_ineligible"]


async def test_get_names_an_anonymised_target_by_its_surrogate() -> None:
    """Q12: the target's row whatever its status. A purged user is disabled, so the context reads
    expired, and its row keeps a surrogate username and no display name: still a 200, never 204."""
    w = World()
    minted = await w.sign_in()
    state = await w.view(minted)
    w.ports.reason = ViewAsEndReason.TARGET_INELIGIBLE
    w.names.rows[str(_TARGET)] = anonymised = (surrogate(_TARGET), None)
    response = await w.call("GET", minted)
    await w.rig.settled()
    assert (response.status_code, response.json()) == (200, _context(state, "expired", anonymised))


def _eligibility_unread(w: World) -> None:
    w.ports.fails["ineligible"] = ConnectionError("identity store unreachable")


def _names_unread(w: World) -> None:
    w.names.fails = ConnectionError("users store unreachable")


def _target_row_gone(w: World) -> None:
    w.names.rows.clear()  # the session's foreign key keeps it: a store fault, never a 204


@pytest.mark.parametrize(
    "arrange",
    [_eligibility_unread, _names_unread, _target_row_gone],
    ids=["eligibility", "names", "no-row"],
)
async def test_get_answers_503_when_a_read_fails_never_a_fallback(
    arrange: Callable[[World], None],
) -> None:
    w = World()
    minted = await w.sign_in()
    state = await w.view(minted)
    arrange(w)
    assert _code(await w.call("GET", minted)) == (503, "store_unavailable")
    assert w.held(minted) == state


async def test_a_failed_read_is_logged_by_what_it_read_with_its_traceback() -> None:
    """The class and a traceback (which the redaction filter scans), never a session id."""
    w = World()
    minted = await w.sign_in()
    await w.view(minted)
    _names_unread(w)
    with capture_logs() as logs:
        await w.call("GET", minted)
    (line,) = [log for log in logs if log["event"] == "auth.view_as_route_failed"]
    assert (line["read"], line["error"], type(line["exc_info"])) == (
        "users",
        "ConnectionError",
        ConnectionError,
    )
    assert str(minted.session_id) not in str(logs)


async def test_get_after_leaving_answers_204() -> None:
    """The read a window makes after its own leave (22 `getViewAs`): the cleared context is none."""
    w = World()
    minted = await w.sign_in()
    await w.view(minted)
    assert (await w.call("DELETE", minted)).status_code == 204
    response = await w.call("GET", minted)
    assert (response.status_code, response.content) == (204, b"")


async def test_get_after_clearing_a_held_context_answers_204() -> None:
    w = World()
    minted = await w.sign_in()
    await w.view(minted)
    row = w.repo.sessions[str(minted.session_id)]
    assert await w.rig.service.end(row, reason=ViewAsEndReason.TARGET_INELIGIBLE, now=_at(3))
    assert (await w.call("DELETE", minted)).status_code == 204
    response = await w.call("GET", minted)
    assert (response.status_code, response.content) == (204, b"")


# -- DELETE ----------------------------------------------------------------------------------------


async def test_delete_ends_and_clears_a_live_context_and_records_it_once() -> None:
    w = World()
    minted = await w.sign_in()
    await w.view(minted)
    w.clock.now = _at(5)
    assert (await w.call("DELETE", minted)).status_code == 204
    await w.rig.settled()
    held = w.held(minted)
    assert held is not None
    assert (held.ended_at, held.end_reason, held.cleared_at) == (_at(5), "ended", _at(5))
    assert w.ports.closed == [(str(minted.session_id), "view_as_changed")]
    assert [(c["action"], c["reason"]) for c in w.ports.calls] == [("admin.view_as_ended", "ended")]


async def test_a_leave_ends_only_its_own_sessions_context() -> None:
    """C-12.4 (the #4171 security look's L-1): the viewer's other session, and another user's
    session viewing the same target, keep their contexts, and only the leaving one's sockets close.
    """
    w = World()
    mine, my_other = await w.sign_in(), await w.sign_in()
    theirs = await w.sessions.mint(str(UUID(int=4171)))
    kept = [await w.view(minted) for minted in (mine, my_other, theirs)][1:]
    w.clock.now = _at(5)
    assert (await w.call("DELETE", mine)).status_code == 204
    await w.rig.settled()
    assert [w.held(my_other), w.held(theirs)] == kept
    assert (await w.call("GET", my_other)).json()["state"] == "active"
    assert w.ports.closed == [(str(mine.session_id), "view_as_changed")]
    assert [c["action"] for c in w.ports.calls] == ["admin.view_as_ended"]


async def test_delete_clears_a_held_context_and_records_nothing() -> None:
    w = World()
    minted = await w.sign_in()
    await w.view(minted)
    row = w.repo.sessions[str(minted.session_id)]
    assert await w.rig.service.end(row, reason=ViewAsEndReason.TARGET_INELIGIBLE, now=_at(3))
    await w.rig.settled()
    w.clock.now = _at(5)
    assert (await w.call("DELETE", minted)).status_code == 204
    held = w.held(minted)
    assert held is not None
    assert (held.ended_at, held.end_reason, held.cleared_at) == (
        _at(3),
        "target_ineligible",
        _at(5),
    )
    assert (len(w.ports.closed), len(w.ports.calls), len(w.rig.runner.tasks)) == (1, 1, 1)


async def test_a_second_delete_after_ending_answers_204_and_records_nothing_more() -> None:
    w = World()
    minted = await w.sign_in()
    await w.view(minted)
    w.clock.now = _at(5)
    assert (await w.call("DELETE", minted)).status_code == 204
    await w.rig.settled()
    assert (await w.call("DELETE", minted)).status_code == 204
    await w.rig.settled()
    assert [c["action"] for c in w.ports.calls] == ["admin.view_as_ended"]


async def test_delete_with_no_context_answers_204_and_changes_nothing() -> None:
    w = World()
    minted = await w.sign_in()
    w.clock.now = _at(2)
    assert (await w.call("DELETE", minted)).status_code == 204
    assert (w.held(minted), w.ports.closed, w.rig.runner.tasks) == (None, [], [])
    assert w.repo.sessions[str(minted.session_id)].last_seen_at == _at(0)  # no activity either


async def test_delete_on_a_session_revoked_under_it_answers_401_and_ends_nothing() -> None:
    """S2b's leave race: a refresh rotated the session away between the route's read and its
    write, so the store refuses the revoked row. Its successor still carries the context, so the
    client must re-authenticate onto it and retry: 401, never 204."""
    w = World()
    minted = await w.sign_in()
    state = await w.view(minted)

    async def rotate(session_id: str) -> None:
        await w.repo.revoke(session_id, reason="rotated", now=w.clock())

    w.repo.on_leave = rotate
    assert _code(await w.call("DELETE", minted)) == (401, "unauthenticated")
    assert (w.held(minted), w.ports.closed, w.rig.runner.tasks) == (state, [], [])


def _another_leave_wins(
    w: World, state: ViewAsState, then: Callable[[], None] = lambda: None
) -> None:
    """Another leave lands just before this request's own write, and `then` runs after it."""

    async def leave_first(session_id: str) -> None:
        w.repo.on_leave = None
        at, ended = w.clock(), ViewAsEndReason.ENDED
        assert await w.repo.leave_view_as(
            session_id, state.context_id, ended_at=at, reason=ended, now=at
        )
        then()

    w.repo.on_leave = leave_first


async def test_delete_after_another_leave_rereads_the_live_session_and_answers_204() -> None:
    """Nothing is left to leave on a live session, and the other leave ended it."""
    w = World()
    minted = await w.sign_in()
    _another_leave_wins(w, await w.view(minted))
    assert (await w.call("DELETE", minted)).status_code == 204
    assert (w.ports.closed, w.rig.runner.tasks) == ([], [])


async def test_delete_after_another_leave_answers_503_when_the_reread_fails() -> None:
    """Never a 204 it cannot vouch for."""
    w = World()
    minted = await w.sign_in()
    _another_leave_wins(w, await w.view(minted), lambda: w.repo.fails.add("find_by_id"))
    assert _code(await w.call("DELETE", minted)) == (503, "store_unavailable")


async def test_the_reread_after_another_leave_waives_the_idle_lock() -> None:
    """A session that idle-locks between the route's read and its re-read has nothing left to
    leave: 204, not `unauthenticated` (the security look's I-3)."""
    w = World()
    minted = await w.sign_in(idle_timeout_s=MIN_IDLE_TIMEOUT_S)
    idle = _at(0) + timedelta(seconds=MIN_IDLE_TIMEOUT_S + 1)
    _another_leave_wins(w, await w.view(minted), lambda: setattr(w.clock, "now", idle))
    assert (await w.call("DELETE", minted)).status_code == 204


async def test_delete_answers_503_on_a_store_failure_and_changes_nothing() -> None:
    w = World()
    minted = await w.sign_in()
    state = await w.view(minted)
    w.repo.fails.add("leave_view_as")
    assert _code(await w.call("DELETE", minted)) == (503, "store_unavailable")
    assert (w.held(minted), w.ports.closed, w.rig.runner.tasks) == (state, [], [])


async def test_delete_without_the_csrf_pair_is_refused_and_changes_nothing() -> None:
    w = World()
    minted = await w.sign_in()
    state = await w.view(minted)
    assert _code(await w.call("DELETE", minted, csrf=False)) == (403, "csrf_token_invalid")
    assert w.held(minted) == state


# -- both ------------------------------------------------------------------------------------------


@pytest.mark.parametrize("method", ["GET", "DELETE"])
@pytest.mark.parametrize("kind", ["none", "unknown", "signed_out", "token_expired"])
async def test_no_live_session_answers_401(method: str, kind: str) -> None:
    """The route's own answer, one for every cause (no session oracle)."""
    w = World(guarded=False)
    assert _code(await w.call(method, await _caller(w, kind))) == (401, "unauthenticated")


@pytest.mark.parametrize("method", ["GET", "DELETE"])
async def test_a_session_read_that_fails_answers_503(method: str) -> None:
    """The route's own answer; behind the guards the idle lock reads the session first."""
    w = World(guarded=False)
    minted = await w.sign_in()
    w.repo.fails.add("find_by_access_token_jti")
    assert _code(await w.call(method, minted)) == (503, "store_unavailable")


@pytest.mark.parametrize("guarded", [True, False], ids=["behind-the-gate", "route-alone"])
@pytest.mark.parametrize("method", ["GET", "DELETE"])
async def test_an_idle_locked_session_is_refused(method: str, guarded: bool) -> None:
    """Q6: both stay behind the idle lock, and the route refuses a locked session on its own too,
    with the lock's time."""
    w = World(guarded=guarded)
    minted = await w.sign_in(idle_timeout_s=MIN_IDLE_TIMEOUT_S)
    state = await w.view(minted)
    w.clock.now = _at(0) + timedelta(seconds=MIN_IDLE_TIMEOUT_S + 1)
    response = await w.call(method, minted)
    assert _code(response) == (401, "session_idle_locked") and response.json()["idle_locked_at"]
    assert w.held(minted) == state


def test_the_idle_lock_exempts_neither_route() -> None:
    assert {("GET", PATH), ("DELETE", PATH)}.isdisjoint(ungated_operations(_SPEC))


@pytest.mark.parametrize("method", ["GET", "DELETE"])
async def test_no_session_backend_answers_503_before_authenticating(method: str) -> None:
    """As the docstring says: with no session service at all, even a caller without a bearer."""
    w = World(guarded=False)
    w.auth.sessions_is_active = False
    assert _code(await w.call(method)) == (503, "store_unavailable")


@pytest.mark.parametrize(
    ("method", "status", "reason"), [("GET", 200, "viewer_ineligible"), ("DELETE", 204, "ended")]
)
async def test_a_session_without_users_write_still_reads_and_leaves(
    method: str, status: int, reason: str
) -> None:
    """No permission: the session lost `users:write` (any role but an Owner's), so a read ends
    its context `viewer_ineligible`, and the viewer still reads it and leaves."""
    w = World()
    minted = await w.sign_in()
    await w.view(minted)
    w.ports.reason = ViewAsEndReason.VIEWER_INELIGIBLE
    response = await w.call(method, minted)
    await w.rig.settled()
    held = w.held(minted)
    assert (response.status_code, held and held.end_reason) == (status, reason)


@pytest.mark.parametrize("method", ["GET", "DELETE"])
async def test_an_unwired_backend_answers_503_after_authenticating(method: str) -> None:
    """The fake backend has no view-as service: 503 once the caller is known (as `GET /me`
    answers an unwired backend)."""
    w = World()
    w.service = None
    assert _code(await w.call(method, await w.sign_in())) == (503, "store_unavailable")


def test_create_app_builds_the_routes_over_its_service_identity_read_and_auth_clock(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """On the real backend the routes read the app's one view-as service, the identity provider's
    names and the app's auth clock, and both are served."""
    seen: list[dict[str, Any]] = []

    def spy(*args: Any, **kwargs: Any) -> Any:
        seen.append(kwargs)
        return make_view_as_router(*args, **kwargs)

    monkeypatch.setattr("candleviewer.app.make_view_as_router", spy)
    app = create_app(_real(), auth_clock=(clock := _Clock()))
    (kwargs,) = seen
    assert kwargs["views"]() is app.state.view_as is not None
    assert kwargs["names"] is app.state.identity_provider is not None
    assert kwargs["clock"] is clock
    assert {("GET", PATH), ("DELETE", PATH)} <= served_operations(app)

"""#3085 S8: a request of a view-as session answers in the subject's scope, and the viewer acts.

The guard (S7) stamps each request it passes; these tests stamp as it does, with a small
middleware, so each resolver is read on its own. Q2: principals are keyed to the target on a live
read, with the viewer as the actor of every record and budget, and a tripwire behind the writer.
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from contextlib import AbstractContextManager, nullcontext
from datetime import UTC, datetime, timedelta
from functools import partial
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import FastAPI, Request
from fastapi.responses import Response
from fastapi.testclient import TestClient

from candleviewer.api.audit import make_audit_router
from candleviewer.api.audit_limiter import AuditQueryLease, AuditQueryLimiter
from candleviewer.api.audit_principal import SessionAuditPrincipalResolver
from candleviewer.api.rules_actor import SessionRulesActorResolver, make_rules_audit
from candleviewer.api.step_up import make_step_up_router
from candleviewer.api.view_as_guard import view_as_unstamped_handler
from candleviewer.api.view_as_subject import (
    STATE_KEY,
    TargetNamedAsActor,
    ViewAsUnstamped,
    acting_user,
    view_as_subject,
)
from candleviewer.app import _LazyAuditEmitter, _refuse_target_as_actor, create_app
from candleviewer.audit.access import AuditPrincipal
from candleviewer.audit.writer import AuditUnavailable
from candleviewer.auth.generated_permissions import Permission, Scope
from candleviewer.auth.scopes import ForbiddenError, PrincipalSnapshot, enforce
from candleviewer.auth.view_as import (
    ViewAsPhase,
    ViewAsRequestContext,
    ViewAsState,
    bound_view_as,
)
from tests.unit.api import test_step_up_router as step_up_rig
from tests.unit.api.test_audit_router import _FakeAuditService
from tests.unit.api.test_me_router import _Env as _MeEnv
from tests.unit.api.test_me_router import _seed_step_up
from tests.unit.api.test_sessions_router import _NOW as _SESSIONS_NOW
from tests.unit.api.test_sessions_router import _Env as _SessionsEnv

_NOW = datetime(2026, 10, 22, 6, 0, tzinfo=UTC)
_VIEWER, _TARGET = uuid.uuid4(), uuid.uuid4()
_SESSION, _CONTEXT = uuid.uuid4(), uuid.uuid4()


def _state(*, cleared: bool = False) -> ViewAsState:
    state = ViewAsState.start(_CONTEXT, _TARGET, now=_NOW)
    if not cleared:
        return state
    return state.model_copy(
        update={
            "ended_at": _NOW,
            "end_reason": "ended",
            "end_recorded_at": _NOW,
            "cleared_at": _NOW,
        }
    )


def _stamp(
    *, subject: uuid.UUID = _TARGET, context: uuid.UUID = _CONTEXT, session: uuid.UUID = _SESSION
) -> ViewAsRequestContext:
    return ViewAsRequestContext(
        viewer_user_id=_VIEWER,
        viewer_session_id=session,
        viewer_label="owner-anna",
        target_user_id=_TARGET,
        context_id=context,
        subject_user_id=subject,
        phase=ViewAsPhase.LIVE,
    )


def _record(state: ViewAsState | None) -> Any:
    return SimpleNamespace(id=_SESSION, user_id=_VIEWER, view_as=state, step_up_elevations={})


def _request(stamp: ViewAsRequestContext | None) -> Request:
    scope: dict[str, Any] = {"type": "http", "headers": [], "state": {}}
    if stamp is not None:
        scope["state"][STATE_KEY] = stamp
    return Request(scope)


# --- the seam ---------------------------------------------------------------------------------


def test_a_session_with_no_context_answers_as_its_own_user() -> None:
    assert view_as_subject(_request(None), _record(None)) == _VIEWER


def test_a_cleared_context_answers_as_the_sessions_own_user_with_no_stamp() -> None:
    assert view_as_subject(_request(None), _record(_state(cleared=True))) == _VIEWER


@pytest.mark.parametrize("subject", [_TARGET, _VIEWER], ids=["a-live-read", "an-own-operation"])
def test_a_context_answers_as_the_subject_its_stamp_names(subject: uuid.UUID) -> None:
    assert view_as_subject(_request(_stamp(subject=subject)), _record(_state())) == subject


@pytest.mark.parametrize(
    "stamp",
    [None, _stamp(context=uuid.uuid4()), _stamp(session=uuid.uuid4())],
    ids=["no-stamp", "another-context", "another-session"],
)
def test_a_context_its_request_was_not_stamped_for_is_refused(
    stamp: ViewAsRequestContext | None,
) -> None:
    """A start between the guard's read and the resolver's: never the viewer's own scope."""
    with pytest.raises(ViewAsUnstamped):
        view_as_subject(_request(stamp), _record(_state()))


# --- the principal: the subject's scope, the viewer acting --------------------------------------


class _Sessions:
    def __init__(self, record: Any) -> None:
        self.record = record

    async def authenticate_access_token(self, token: str, *, touch: bool = False) -> Any:
        return self.record


class _Identity:
    async def user(self, user_id: str) -> dict[str, Any]:
        name = "owner-anna" if user_id == str(_VIEWER) else "manager-ben"
        roles = ["owner"] if user_id == str(_VIEWER) else ["manager"]
        return {"username": name, "status": "active", "roles": roles}

    async def session_info(self, user_id: str) -> dict[str, Any]:
        return {"permissions": ["*"] if user_id == str(_VIEWER) else ["accounts:read"]}


def _bearer(stamp: ViewAsRequestContext | None) -> Request:
    request = _request(stamp)
    request.scope["headers"] = [(b"authorization", b"Bearer tok")]
    return request


async def _live_principal() -> AuditPrincipal:
    resolver = SessionAuditPrincipalResolver(lambda: _Sessions(_record(_state())), _Identity())
    principal = await resolver.resolve(_bearer(_stamp()))
    assert principal is not None
    return principal


async def test_a_live_view_resolves_the_targets_principal() -> None:
    principal = await _live_principal()
    assert (principal.user_id, principal.username, principal.permissions, principal.is_owner) == (
        _TARGET,
        "manager-ben",
        frozenset({"accounts:read"}),
        False,
    )


async def test_a_live_views_principal_is_on_the_viewers_own_session() -> None:
    assert (await _live_principal()).session_id == _SESSION


async def test_a_live_views_principal_names_the_viewer_as_its_actor() -> None:
    principal = await _live_principal()
    assert (principal.actor_id, principal.actor_name) == (_VIEWER, "owner-anna")


async def test_a_live_view_resolves_the_targets_rules_actor() -> None:
    """The rules, alerts, deliveries and notifications reads' actor is the target's (Q2)."""
    resolver = SessionRulesActorResolver(
        lambda: _Sessions(_record(_state())), lambda: None, _Identity()
    )
    actor = await resolver.resolve(_bearer(_stamp()))
    assert actor is not None
    assert (actor.user_id, actor.perms, actor.is_owner) == (
        str(_TARGET),
        frozenset({"accounts:read"}),
        False,
    )


async def test_an_own_operation_resolves_the_viewers_principal_with_no_actor_fields() -> None:
    resolver = SessionAuditPrincipalResolver(lambda: _Sessions(_record(_state())), _Identity())
    principal = await resolver.resolve(_bearer(_stamp(subject=_VIEWER)))
    assert principal is not None
    assert principal.user_id == _VIEWER and principal.actor_user_id is None
    assert (principal.actor_id, principal.actor_name) == (_VIEWER, "owner-anna")


async def test_an_unstamped_context_is_not_resolved_to_any_principal() -> None:
    resolver = SessionAuditPrincipalResolver(lambda: _Sessions(_record(_state())), _Identity())
    with pytest.raises(ViewAsUnstamped):
        await resolver.resolve(_bearer(None))


def test_the_actor_is_the_user_when_no_one_views() -> None:
    principal = AuditPrincipal(user_id=_VIEWER, username="owner-anna", permissions=frozenset())
    assert (principal.actor_id, principal.actor_name) == (_VIEWER, "owner-anna")


# --- the audit router while viewing: the target's scope, the viewer's records and budget ------


def _stamping(stamp: ViewAsRequestContext) -> Callable[..., Awaitable[Response]]:
    async def guard(request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Any:
        request.scope.setdefault("state", {})[STATE_KEY] = stamp
        with bound_view_as(stamp):
            return await call_next(request)

    return guard


def test_a_viewers_refused_audit_read_is_the_targets_refusal_recorded_as_the_viewers() -> None:
    svc = _FakeAuditService()
    app = FastAPI()
    resolver = SessionAuditPrincipalResolver(lambda: _Sessions(_record(_state())), _Identity())
    app.include_router(make_audit_router(svc, resolver))
    app.middleware("http")(_stamping(_stamp()))
    response = TestClient(app).get("/admin/audit", headers={"Authorization": "Bearer tok"})
    assert response.status_code == 403  # the target, a Manager, may not read the log
    action, fields = svc.writer_service.emitted[0][0], svc.writer_service.emitted[0][1]
    assert action == "admin.audit_denied"
    assert (fields["actor_user_id"], fields["actor_label"]) == (_VIEWER, "owner-anna")


class _ReaderIdentity(_Identity):
    """The target holds `audit:read` (`OWN_REDACTED`): its audit read is its own events."""

    async def session_info(self, user_id: str) -> dict[str, Any]:
        return {"permissions": ["*"] if user_id == str(_VIEWER) else ["audit:read"]}


@pytest.mark.parametrize("params", [{}, {"actor_user_id": str(_TARGET)}], ids=["own", "target"])
def test_a_viewers_audit_read_is_scoped_to_the_targets_own_events(params: dict[str, str]) -> None:
    """A `scope: self` read answers as the target's (22 "View-as session"): the filter and the
    repository's restriction are the target's, and asking for the target's events is no
    cross-actor narrowing."""
    svc = _FakeAuditService()
    app = FastAPI()
    resolver = SessionAuditPrincipalResolver(
        lambda: _Sessions(_record(_state())), _ReaderIdentity()
    )
    app.include_router(make_audit_router(svc, resolver))
    app.middleware("http")(_stamping(_stamp()))
    bearer = {"Authorization": "Bearer tok"}
    response = TestClient(app).get("/admin/audit", params=params, headers=bearer)
    assert response.status_code == 200
    (call,) = svc.query_service.query_calls
    assert (call["actor_user_id"], call["restrict_to_actor"]) == (str(_TARGET), str(_TARGET))
    assert "admin.audit_denied" not in [action for action, *_ in svc.writer_service.emitted]


class _KeyedLimiter(AuditQueryLimiter):
    def __init__(self) -> None:
        super().__init__()
        self.keys: list[str] = []

    def acquire(self, user: str) -> AuditQueryLease:
        self.keys.append(user)
        return super().acquire(user)


def test_a_viewers_audit_read_spends_the_viewers_own_query_budget() -> None:
    """The limiter, the record budget and the over-cap answers are keyed by the actor: a viewer
    never spends the target's."""
    svc, limiter = _FakeAuditService(), _KeyedLimiter()
    app = FastAPI()
    resolver = SessionAuditPrincipalResolver(
        lambda: _Sessions(_record(_state())), _ReaderIdentity()
    )
    app.include_router(make_audit_router(svc, resolver, limiter=limiter))
    app.middleware("http")(_stamping(_stamp()))
    response = TestClient(app).get("/admin/audit", headers={"Authorization": "Bearer tok"})
    assert response.status_code == 200
    assert limiter.keys == [str(_VIEWER)]


class _StatusIdentity(_Identity):
    def __init__(self, status: str) -> None:
        self.status = status

    async def user(self, user_id: str) -> dict[str, Any]:
        found = await super().user(user_id)
        return found if user_id == str(_VIEWER) else {**found, "status": self.status}


@pytest.mark.parametrize("status", ["locked", "disabled"])
async def test_a_view_of_a_target_who_is_not_active_resolves_no_principal(status: str) -> None:
    """Q11, fail closed: a locked or disabled target's view has no scope, so no principal."""
    sessions = _Sessions(_record(_state()))
    resolver = SessionAuditPrincipalResolver(lambda: sessions, _StatusIdentity(status))
    assert await resolver.resolve(_bearer(_stamp())) is None


def test_the_guards_handler_answers_an_unstamped_view_503() -> None:
    svc = _FakeAuditService()
    app = FastAPI()
    resolver = SessionAuditPrincipalResolver(lambda: _Sessions(_record(_state())), _Identity())
    app.include_router(make_audit_router(svc, resolver))
    app.add_exception_handler(ViewAsUnstamped, view_as_unstamped_handler)
    response = TestClient(app).get("/admin/audit", headers={"Authorization": "Bearer tok"})
    assert response.status_code == 503 and response.json()["code"] == "store_unavailable"
    assert svc.writer_service.emitted == []


def test_the_app_answers_an_unstamped_view_with_the_guards_handler() -> None:
    assert create_app().exception_handlers[ViewAsUnstamped] is view_as_unstamped_handler


# --- the tripwire and the actors written without a principal -----------------------------------


_VIEWING = partial(bound_view_as, _stamp())


@pytest.mark.parametrize(
    "actor",
    [_TARGET, str(_TARGET), str(_TARGET).upper(), f"{{{_TARGET}}}", f"urn:uuid:{_TARGET}"],
    ids=["uuid", "str", "upper-case", "braces", "urn"],
)
def test_the_tripwire_refuses_a_record_naming_the_viewed_target(actor: Any) -> None:
    """Every spelling the writer would store as the target's id."""
    with _VIEWING(), pytest.raises(TargetNamedAsActor):
        _refuse_target_as_actor("admin.area_entered", {"actor_user_id": actor})


@pytest.mark.parametrize(
    ("binding", "fields"),
    [
        (_VIEWING, {"actor_user_id": _VIEWER}),
        (_VIEWING, {}),
        (_VIEWING, {"actor_user_id": "system"}),
        (nullcontext, {"actor_user_id": _TARGET}),
    ],
    ids=["names-the-viewer", "names-no-actor", "names-no-user-id", "no-view-bound"],
)
def test_the_tripwire_passes_a_record_naming_no_viewed_target(
    binding: Callable[[], AbstractContextManager[Any]], fields: dict[str, Any]
) -> None:
    with binding():
        _refuse_target_as_actor("admin.area_entered", fields)


def test_a_refused_record_is_one_the_callers_fail_closed_path_answers() -> None:
    """Every write-ahead caller refuses its action on `AuditUnavailable` (C-2.9)."""
    assert issubclass(TargetNamedAsActor, AuditUnavailable)


class _Writer:
    def __init__(self) -> None:
        self.written: list[str] = []

    async def emit(self, action: str, **fields: Any) -> None:
        self.written.append(action)

    async def emit_keyed(self, action: str, name: str, **fields: Any) -> None:
        self.written.append(action)


_WRITES: dict[str, Callable[[_LazyAuditEmitter, Any], Awaitable[None]]] = {
    "emit": lambda emitter, actor: emitter.emit("admin.area_entered", actor_user_id=actor),
    "emit_keyed": lambda emitter, actor: emitter.emit_keyed(
        "admin.view_as_ended", "context", actor_user_id=actor
    ),
}


def _apps_emitter(writer: _Writer) -> _LazyAuditEmitter:
    return _LazyAuditEmitter(SimpleNamespace(writer=writer))  # type: ignore[arg-type]  # the writer is all it reads


@pytest.mark.parametrize("write", _WRITES.values(), ids=_WRITES.keys())
async def test_the_apps_emitter_refuses_a_record_naming_the_viewed_target(
    write: Callable[[_LazyAuditEmitter, Any], Awaitable[None]],
) -> None:
    writer = _Writer()
    with _VIEWING(), pytest.raises(TargetNamedAsActor):
        await write(_apps_emitter(writer), _TARGET)
    assert writer.written == []


@pytest.mark.parametrize("write", _WRITES.values(), ids=_WRITES.keys())
async def test_the_apps_emitter_writes_a_record_naming_the_viewer(
    write: Callable[[_LazyAuditEmitter, Any], Awaitable[None]],
) -> None:
    writer = _Writer()
    with _VIEWING():
        await write(_apps_emitter(writer), _VIEWER)
    assert len(writer.written) == 1


class _Emitter:
    def __init__(self) -> None:
        self.records: list[tuple[str, dict[str, Any]]] = []

    async def emit(self, action: str, **fields: Any) -> None:
        self.records.append((action, fields))


async def test_a_denial_while_viewing_names_the_viewer_as_its_actor() -> None:
    emitter = _Emitter()
    target = PrincipalSnapshot(
        user_id=_TARGET, roles=frozenset({"manager"}), permissions=frozenset()
    )
    with bound_view_as(_stamp()), pytest.raises(ForbiddenError):
        await enforce(target, Permission.USERS_WRITE, scope=Scope.NONE, emitter=emitter)
    ((action, fields),) = emitter.records
    assert action == "rbac.denied"
    assert (fields["actor_user_id"], fields["actor_label"]) == (_VIEWER, str(_VIEWER))


@pytest.mark.parametrize(
    ("binding", "named", "acting"),
    [
        (_VIEWING, str(_TARGET), str(_VIEWER)),
        (_VIEWING, "system", "system"),
        (partial(bound_view_as, _stamp(subject=_VIEWER)), str(_TARGET), str(_TARGET)),
        (nullcontext, str(_TARGET), str(_TARGET)),
    ],
    ids=["the-viewed-target", "another-actor", "an-own-operation", "no-view-bound"],
)
def test_a_record_names_the_viewer_in_place_of_the_viewed_target_only(
    binding: Callable[[], AbstractContextManager[Any]], named: str, acting: str
) -> None:
    with binding():
        assert acting_user(named) == acting


async def test_a_rules_record_while_viewing_names_the_viewer() -> None:
    emitter = _Emitter()
    with _VIEWING():
        await make_rules_audit(emitter)("create", {"rule_id": "r1", "actor": str(_TARGET)})
    ((_, fields),) = emitter.records
    assert (fields["actor_user_id"], fields["actor_label"]) == (str(_VIEWER), str(_VIEWER))


# --- the routes S8 moves to the subject -------------------------------------------------------


def _context(viewer: Any, target: Any, session: Any, context: uuid.UUID) -> ViewAsRequestContext:
    return ViewAsRequestContext(
        viewer_user_id=uuid.UUID(str(viewer)),
        viewer_session_id=uuid.UUID(str(session)),
        viewer_label="owner-anna",
        target_user_id=uuid.UUID(str(target)),
        context_id=context,
        subject_user_id=uuid.UUID(str(target)),
        phase=ViewAsPhase.LIVE,
    )


async def test_a_viewer_asking_for_an_owner_only_preview_is_refused_403_not_401() -> None:
    """The principal is the target's, so the owner check compares it with the subject, not with
    the session's user: the refusal is the target's 403, recorded as the viewer's."""
    emitter = step_up_rig._Emitter()
    target = PrincipalSnapshot(
        user_id=_TARGET, roles=frozenset({"manager"}), permissions=frozenset()
    )
    app = FastAPI()
    app.include_router(
        make_step_up_router(
            step_up_rig._Auth(None, step_up_rig._Sessions({"tok": _record(_state())})),  # type: ignore[arg-type]  # no step-up read on this path
            emitter,
            principal_resolver=step_up_rig._Resolver(target),
            positions=step_up_rig._Positions(),
            users=step_up_rig._Users(),
            audit_ready=lambda: True,
        )
    )
    app.middleware("http")(_stamping(_stamp()))
    response = TestClient(app).get(
        f"/users/{uuid.uuid4()}/mfa/reset-preview", headers={"Authorization": "Bearer tok"}
    )
    assert response.status_code == 403
    (denied,) = [call for call in emitter.calls if call["action"] == "rbac.denied"]
    assert denied["actor_user_id"] == _VIEWER


async def _me_while_viewing(*, status: str = "active", stamped: bool = True) -> Any:
    """`GET /me` on an Owner's session, which holds a live step-up window, viewing as a Viewer
    whose status is `status`, through the guard's stamp or (`stamped=False`) without it."""
    env = _MeEnv()
    viewer, _, minted = await env.sign_in(roles=("owner",), permissions=["*"])
    target, _, _ = await env.sign_in(roles=("viewer",), email="ben@example.com", status=status)
    await _seed_step_up(env, minted, {"users": env.now + timedelta(minutes=4)})
    context = uuid.uuid4()
    await env.repo.start_view_as(
        str(minted.session_id),
        ViewAsState.start(context, uuid.UUID(target), now=env.now),
        now=env.now,
    )
    if stamped:
        env.client.app.middleware("http")(  # type: ignore[attr-defined]  # `app` is typed as ASGI
            _stamping(_context(viewer, target, minted.session_id, context))
        )
    response = env.client.get(
        "/api/v1/me", headers={"Authorization": f"Bearer {minted.access_token}"}
    )
    return SimpleNamespace(env=env, target=target, session=minted.session_id, response=response)


async def test_me_while_viewing_is_the_targets() -> None:
    seen = await _me_while_viewing()
    body = seen.response.json()
    assert (body["user"]["id"], body["role"]) == (seen.target, "viewer")
    assert seen.env.identity.account_reads == [seen.target]


async def test_me_while_viewing_names_the_viewers_own_session() -> None:
    seen = await _me_while_viewing()
    assert seen.response.json()["session"]["session_id"] == str(seen.session)


async def test_me_while_viewing_elevates_nothing_though_the_session_holds_a_window() -> None:
    """Q10: the session's own step-up window is not the target's elevation."""
    seen = await _me_while_viewing()
    assert seen.response.json()["session"]["elevated_until"] is None


@pytest.mark.parametrize("status", ["locked", "disabled"])
async def test_me_while_viewing_a_target_who_is_not_active_is_401(status: str) -> None:
    """Q11, fail closed: the target's status, not the viewer's, decides."""
    response = (await _me_while_viewing(status=status)).response
    assert (response.status_code, response.json()["code"]) == (401, "unauthenticated")


async def test_me_for_a_view_the_guard_did_not_stamp_is_503() -> None:
    response = (await _me_while_viewing(stamped=False)).response
    assert (response.status_code, response.json()["code"]) == (503, "store_unavailable")


async def test_the_session_list_while_viewing_is_the_targets() -> None:
    env = _SessionsEnv()
    now = _SESSIONS_NOW
    viewer, target = uuid.uuid4(), uuid.uuid4()
    minted = await env.mint(viewer)
    theirs = {str((await env.mint(target)).session_id) for _ in range(2)}
    context = uuid.uuid4()
    await env.repo.start_view_as(
        str(minted.session_id), ViewAsState.start(context, target, now=now), now=now
    )
    env.client.app.middleware("http")(  # type: ignore[attr-defined]  # `app` is typed as ASGI
        _stamping(_context(viewer, target, minted.session_id, context))
    )
    listed = env.client.get(
        "/api/v1/auth/sessions", headers={"Authorization": f"Bearer {minted.access_token}"}
    ).json()["items"]
    assert {item["id"] for item in listed} == theirs


async def test_the_session_list_for_a_view_the_guard_did_not_stamp_is_the_apps_503() -> None:
    env = _SessionsEnv()
    viewer, target = uuid.uuid4(), uuid.uuid4()
    minted = await env.mint(viewer)
    await env.repo.start_view_as(
        str(minted.session_id),
        ViewAsState.start(uuid.uuid4(), target, now=_SESSIONS_NOW),
        now=_SESSIONS_NOW,
    )
    env.client.app.add_exception_handler(  # type: ignore[attr-defined]  # `app` is typed as ASGI
        ViewAsUnstamped, view_as_unstamped_handler
    )
    response = env.client.get(
        "/api/v1/auth/sessions", headers={"Authorization": f"Bearer {minted.access_token}"}
    )
    assert (response.status_code, response.json()["code"]) == (503, "store_unavailable")

"""#3085 S8: a request of a view-as session answers in the subject's scope, and the viewer acts.

The guard (S7) stamps each request it passes; these tests stamp as it does, with a small
middleware, so each resolver is read on its own. Q2: principals are keyed to the target on a live
read, with the viewer as the actor of every record and budget, and a tripwire behind the writer.
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import FastAPI, Request
from fastapi.responses import Response
from fastapi.testclient import TestClient

from candleviewer.api.audit import make_audit_router
from candleviewer.api.audit_principal import SessionAuditPrincipalResolver
from candleviewer.api.rules_actor import _acting
from candleviewer.api.view_as_subject import (
    STATE_KEY,
    ViewAsUnstamped,
    view_as_subject,
)
from candleviewer.app import TargetNamedAsActor, _refuse_target_as_actor
from candleviewer.audit.access import AuditPrincipal
from candleviewer.auth.generated_permissions import Permission, Scope
from candleviewer.auth.scopes import ForbiddenError, PrincipalSnapshot, enforce
from candleviewer.auth.view_as import (
    ViewAsPhase,
    ViewAsRequestContext,
    ViewAsState,
    bound_view_as,
)
from tests.unit.api.test_audit_router import _FakeAuditService

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


async def test_a_live_view_resolves_the_targets_principal_with_the_viewer_acting() -> None:
    resolver = SessionAuditPrincipalResolver(lambda: _Sessions(_record(_state())), _Identity())
    principal = await resolver.resolve(_bearer(_stamp()))
    assert principal is not None
    assert (principal.user_id, principal.username, principal.permissions) == (
        _TARGET,
        "manager-ben",
        frozenset({"accounts:read"}),
    )
    assert principal.is_owner is False and principal.session_id == _SESSION
    assert (principal.actor_id, principal.actor_name) == (_VIEWER, "owner-anna")


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
    """A `scope: self` read answers as the target's (22 "View-as session"; the #4177 security
    look's H-1): the filter and the repository's restriction are the target's, and asking for the
    target's events is no cross-actor narrowing. The viewer still spends its own budget."""
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


def test_an_unstamped_view_is_answered_503_by_the_app() -> None:
    from candleviewer.api.view_as_guard import view_as_unstamped_handler

    svc = _FakeAuditService()
    app = FastAPI()
    resolver = SessionAuditPrincipalResolver(lambda: _Sessions(_record(_state())), _Identity())
    app.include_router(make_audit_router(svc, resolver))
    app.add_exception_handler(ViewAsUnstamped, view_as_unstamped_handler)
    response = TestClient(app).get("/admin/audit", headers={"Authorization": "Bearer tok"})
    assert response.status_code == 503 and response.json()["code"] == "store_unavailable"
    assert svc.writer_service.emitted == []


# --- the tripwire and the actors written without a principal -----------------------------------


def test_emitter_refuses_target_as_actor() -> None:
    with bound_view_as(_stamp()):
        with pytest.raises(TargetNamedAsActor):
            _refuse_target_as_actor("admin.area_entered", {"actor_user_id": _TARGET})
        with pytest.raises(TargetNamedAsActor):
            _refuse_target_as_actor("rules.scope_refused", {"actor_user_id": str(_TARGET)})
        _refuse_target_as_actor("admin.area_entered", {"actor_user_id": _VIEWER})
        _refuse_target_as_actor("system.tick", {})
    _refuse_target_as_actor("admin.area_entered", {"actor_user_id": _TARGET})  # no view bound


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


def test_a_rules_record_while_viewing_names_the_viewer() -> None:
    with bound_view_as(_stamp()):
        assert _acting(str(_TARGET)) == str(_VIEWER)
        assert _acting("system") == "system"
    assert _acting(str(_TARGET)) == str(_TARGET)


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
    from candleviewer.api.step_up import make_step_up_router
    from tests.unit.api.test_step_up_router import (
        _Auth,
        _Emitter,
        _Positions,
        _Resolver,
        _Sessions,
        _Users,
    )

    emitter = _Emitter()
    target = PrincipalSnapshot(
        user_id=_TARGET, roles=frozenset({"manager"}), permissions=frozenset()
    )
    app = FastAPI()
    app.include_router(
        make_step_up_router(
            _Auth(None, _Sessions({"tok": _record(_state())})),  # type: ignore[arg-type]  # no step-up read on this path
            emitter,
            principal_resolver=_Resolver(target),
            positions=_Positions(),
            users=_Users(),
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


async def test_me_while_viewing_is_the_targets_with_the_viewers_session_and_no_elevation() -> None:
    from tests.unit.api.test_me_router import _Env

    env = _Env()
    viewer, _, minted = await env.sign_in(roles=("owner",), permissions=["*"])
    target, _, _ = await env.sign_in(roles=("viewer",), email="ben@example.com")
    context = uuid.uuid4()
    await env.repo.start_view_as(
        str(minted.session_id),
        ViewAsState.start(context, uuid.UUID(target), now=env.now),
        now=env.now,
    )
    env.client.app.middleware("http")(  # type: ignore[attr-defined]  # `app` is typed as ASGI
        _stamping(_context(viewer, target, minted.session_id, context))
    )
    body = env.client.get(
        "/api/v1/me", headers={"Authorization": f"Bearer {minted.access_token}"}
    ).json()
    assert body["user"]["id"] == target and body["role"] == "viewer"
    assert env.identity.account_reads == [target]
    assert body["session"]["session_id"] == str(minted.session_id)
    assert body["session"]["elevated_until"] is None


async def test_the_session_list_while_viewing_is_the_targets() -> None:
    from tests.unit.api.test_sessions_router import _NOW as now
    from tests.unit.api.test_sessions_router import _Env

    env = _Env()
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

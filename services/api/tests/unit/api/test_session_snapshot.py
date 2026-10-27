"""#2492: `SessionSnapshotResolver` - bearer -> session -> SQL identity -> `PrincipalSnapshot`."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import pytest
from starlette.requests import Request

from candleviewer.api.session_snapshot import SessionSnapshotResolver
from candleviewer.api.view_as_subject import STATE_KEY
from candleviewer.auth.errors import SessionIdleLocked, SessionRevoked
from candleviewer.auth.generated_permissions import Permission
from candleviewer.auth.scopes import AccountGrant, account_scope
from candleviewer.auth.view_as import ViewAsPhase, ViewAsRequestContext, ViewAsState
from candleviewer.storage.repositories.accounts import GrantScope, OwnerScope

_UID = uuid.uuid4()
_A, _B = uuid.uuid4(), uuid.uuid4()


class _Sessions:
    def __init__(self, exc: Exception | None = None) -> None:
        self.exc, self.touched = exc, list[bool]()

    async def authenticate_access_token(self, token: str, *, touch: bool = False) -> Any:
        if self.exc is not None:
            raise self.exc
        self.touched.append(touch)
        return SimpleNamespace(view_as=None, id=uuid.uuid4(), user_id=_UID)


class _Identity:
    def __init__(
        self,
        roles: tuple[str, ...] = ("owner",),
        status: str = "active",
        scope: tuple[str, ...] = (),
    ) -> None:
        self.roles, self.status, self.scope = roles, status, scope

    async def user(self, user_id: str) -> dict[str, Any]:
        if self.status == "missing":
            raise LookupError(user_id)
        return {"roles": list(self.roles), "status": self.status}

    async def session_info(self, user_id: str) -> dict[str, Any]:
        return {"permissions": ["users:write", "not:a_code"], "account_scope": list(self.scope)}


def _request(authorization: str | None = "Bearer tok") -> Request:
    headers = [] if authorization is None else [(b"authorization", authorization.encode())]
    return Request({"type": "http", "headers": headers})


async def test_resolve_active_owner_maps_roles_and_known_permissions_only() -> None:
    sessions = _Sessions()
    snap = await SessionSnapshotResolver(lambda: sessions, _Identity()).resolve(_request())
    assert snap is not None and snap.user_id == _UID and snap.is_owner
    assert snap.permissions == frozenset({Permission.USERS_WRITE})  # unknown code dropped
    assert snap.account_grants == ()
    assert sessions.touched == [False]  # a resolve is never activity (#2300)


@pytest.mark.parametrize(
    ("authorization", "sessions", "identity"),
    [
        pytest.param(None, _Sessions(), _Identity(), id="no-header"),
        pytest.param("Basic tok", _Sessions(), _Identity(), id="not-bearer"),
        pytest.param("Bearer  ", _Sessions(), _Identity(), id="empty-token"),
        pytest.param("Bearer t", _Sessions(SessionRevoked("x")), _Identity(), id="revoked"),
        pytest.param("Bearer t", _Sessions(SessionIdleLocked("x")), _Identity(), id="idle"),
        pytest.param("Bearer t", _Sessions(RuntimeError("x")), _Identity(), id="not-started"),
        pytest.param("Bearer t", _Sessions(), _Identity(status="missing"), id="unknown-user"),
        pytest.param("Bearer t", _Sessions(), _Identity(status="disabled"), id="disabled"),
        pytest.param("Bearer t", _Sessions(), _Identity(("owner", "root")), id="unknown-role"),
    ],
)
async def test_resolve_any_failure_returns_no_principal(
    authorization: str | None, sessions: _Sessions, identity: _Identity
) -> None:
    resolver = SessionSnapshotResolver(lambda: sessions, identity)
    assert await resolver.resolve(_request(authorization)) is None


def _manager(*scope: Any) -> _Identity:
    return _Identity(("manager",), scope=tuple(str(a) for a in scope))


async def test_grants_are_loaded_only_when_asked_and_decide_the_account_scope() -> None:
    """#906 D1a: the profile reads' account scope is the caller's own view grants, which
    `session_info` lists (a view grant that is not frozen), as `/rules` and `/notifications`
    read it. `can_trade` is not loaded. Without the flag no grant is held."""
    identity = _manager(_A, _B)
    snap = await SessionSnapshotResolver(lambda: _Sessions(), identity, grants=True).resolve(
        _request()
    )
    assert snap is not None and not snap.is_owner
    assert snap.account_grants == (
        AccountGrant(_A, True, False, False),
        AccountGrant(_B, True, False, False),
    )
    assert account_scope(snap) == GrantScope(_UID, frozenset({_A, _B}))
    bare = await SessionSnapshotResolver(lambda: _Sessions(), identity).resolve(_request())
    assert bare is not None and bare.account_grants == ()
    assert account_scope(bare) == GrantScope(_UID, frozenset())  # nothing, never everything
    owner = SessionSnapshotResolver(lambda: _Sessions(), _Identity(scope=(str(_A),)), grants=True)
    held = await owner.resolve(_request())
    assert held is not None and account_scope(held) == OwnerScope(_UID)  # grants add nothing


async def test_a_grant_that_is_not_a_uuid_resolves_no_principal() -> None:
    """The tuple is built where a malformed id is a `ValueError`: 401, never a partial scope."""
    resolver = SessionSnapshotResolver(lambda: _Sessions(), _manager(_A, "not-a-uuid"), grants=True)
    assert await resolver.resolve(_request()) is None


async def test_a_live_view_loads_the_targets_grants_not_the_viewers() -> None:
    """#3085: under a live view `session_info` is read for the subject the guard stamped, so the
    grants are the target's. The viewer's own grants are never mixed in."""
    viewer, target, session, context = _UID, uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    now = datetime(2026, 10, 23, 6, 0, tzinfo=UTC)
    stamp = ViewAsRequestContext(
        viewer_user_id=viewer, viewer_session_id=session, viewer_label="owner-anna",
        target_user_id=target, context_id=context, subject_user_id=target,
        phase=ViewAsPhase.LIVE,
    )  # fmt: skip
    record = SimpleNamespace(
        id=session, user_id=viewer, view_as=ViewAsState.start(context, target, now=now)
    )

    class _Viewing(_Identity):
        async def user(self, user_id: str) -> dict[str, Any]:
            return {"roles": ["manager"], "status": "active"}

        async def session_info(self, user_id: str) -> dict[str, Any]:
            scope = [str(_A)] if user_id == str(target) else [str(_B)]  # the viewer's is `_B`
            return {"permissions": ["accounts:read"], "account_scope": scope}

    class _ViewSessions(_Sessions):
        async def authenticate_access_token(self, token: str, *, touch: bool = False) -> Any:
            return record

    request = _request()
    request.scope["state"] = {STATE_KEY: stamp}
    resolver = SessionSnapshotResolver(lambda: _ViewSessions(), _Viewing(), grants=True)
    snap = await resolver.resolve(request)
    assert snap is not None and snap.user_id == target
    assert account_scope(snap) == GrantScope(target, frozenset({_A}))

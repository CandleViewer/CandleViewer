"""#2492: `SessionSnapshotResolver` - bearer -> session -> SQL identity -> `PrincipalSnapshot`."""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from typing import Any

import pytest
from starlette.requests import Request

from candleviewer.api.session_snapshot import SessionSnapshotResolver
from candleviewer.auth.errors import SessionIdleLocked, SessionRevoked
from candleviewer.auth.generated_permissions import Permission

_UID = uuid.uuid4()


class _Sessions:
    def __init__(self, exc: Exception | None = None) -> None:
        self.exc, self.touched = exc, list[bool]()

    async def authenticate_access_token(self, token: str, *, touch: bool = False) -> Any:
        if self.exc is not None:
            raise self.exc
        self.touched.append(touch)
        return SimpleNamespace(id=uuid.uuid4(), user_id=_UID)


class _Identity:
    def __init__(self, roles: tuple[str, ...] = ("owner",), status: str = "active") -> None:
        self.roles, self.status = roles, status

    async def user(self, user_id: str) -> dict[str, Any]:
        if self.status == "missing":
            raise LookupError(user_id)
        return {"roles": list(self.roles), "status": self.status}

    async def session_info(self, user_id: str) -> dict[str, Any]:
        return {"permissions": ["users:write", "not:a_code"]}


def _request(authorization: str | None = "Bearer tok") -> Request:
    headers = [] if authorization is None else [(b"authorization", authorization.encode())]
    return Request({"type": "http", "headers": headers})


async def test_resolve_active_owner_maps_roles_and_known_permissions_only() -> None:
    sessions = _Sessions()
    snap = await SessionSnapshotResolver(lambda: sessions, _Identity()).resolve(_request())
    assert snap is not None and snap.user_id == _UID and snap.is_owner
    assert snap.permissions == frozenset({Permission.USERS_WRITE})  # unknown code dropped
    # #2300: resolving a principal is never activity (only extend and unlock are).
    assert snap.account_grants == () and sessions.touched == [False]


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

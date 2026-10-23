"""#4174: the session a refusal's audit record names (`api/refusal_session.py`)."""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from typing import Any

import pytest
from starlette.requests import Request
from structlog.testing import capture_logs

from candleviewer.api.refusal_session import NamesSession, refusal_session
from candleviewer.auth.generated_permissions import Permission
from candleviewer.auth.scopes import PrincipalSnapshot, enforce

SESSION = uuid.UUID(int=4174)


def _request(authorization: str | None = "Bearer tok") -> Request:
    headers = [] if authorization is None else [(b"authorization", authorization.encode())]
    return Request({"type": "http", "headers": headers})


class _Sessions:
    def __init__(self, fails: Exception | None = None) -> None:
        self.fails = fails
        self.read: list[str] = []

    async def peek_access_token(self, token: str) -> Any:
        self.read.append(token)
        if self.fails is not None:
            raise self.fails
        return SimpleNamespace(id=SESSION) if token == "tok" else None  # noqa: S105


class _Auth:
    def __init__(self, sessions: _Sessions, *, active: bool = True) -> None:
        self.sessions, self.sessions_is_active = sessions, active


class _Emitter:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def emit(self, action: str, **kwargs: Any) -> None:
        self.calls.append({"action": action, **kwargs})


async def test_it_names_the_session_behind_the_bearer_token() -> None:
    assert await refusal_session(_Auth(_Sessions()), _request()) == SESSION


@pytest.mark.parametrize(
    ("auth", "authorization"),
    [
        (None, "Bearer tok"),
        (_Auth(_Sessions(), active=False), "Bearer tok"),
        (_Auth(_Sessions()), None),
        (_Auth(_Sessions()), "Basic dG9rOg=="),
        (_Auth(_Sessions()), "Bearer other"),
    ],
    ids=["unwired", "inactive", "no-header", "not-bearer", "unknown-token"],
)
async def test_it_names_none_without_a_session_to_name(
    auth: _Auth | None, authorization: str | None
) -> None:
    assert await refusal_session(auth, _request(authorization)) is None


async def test_a_session_store_that_fails_names_none_and_is_logged() -> None:
    with capture_logs() as logs:
        found = await refusal_session(_Auth(_Sessions(ConnectionError("down"))), _request())
    assert found is None
    assert [(log["event"], log["error"]) for log in logs] == [
        ("refusal names no session", "ConnectionError")
    ]


async def test_the_emitter_names_the_session_over_the_none_enforce_passes() -> None:
    em = _Emitter()
    await NamesSession(em, _Auth(_Sessions()), _request()).emit(
        "rbac.denied", session_id=None, reason="missing_permission"
    )
    assert em.calls == [
        {"action": "rbac.denied", "session_id": SESSION, "reason": "missing_permission"}
    ]


async def test_an_allowed_request_reads_no_session() -> None:
    sessions, em = _Sessions(), _Emitter()
    allowed = PrincipalSnapshot(
        user_id=uuid.uuid4(), roles=frozenset({"owner"}), permissions=frozenset({"users:write"})
    )
    await enforce(
        allowed, Permission.USERS_WRITE, emitter=NamesSession(em, _Auth(sessions), _request())
    )
    assert (sessions.read, em.calls) == ([], [])


async def test_the_emitter_still_writes_when_the_session_store_fails() -> None:
    em = _Emitter()
    await NamesSession(em, _Auth(_Sessions(OSError("down"))), _request()).emit("rbac.denied")
    assert em.calls == [{"action": "rbac.denied", "session_id": None}]

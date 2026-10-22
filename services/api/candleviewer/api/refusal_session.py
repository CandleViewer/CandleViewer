"""The session a refusal's audit record names (#4174).

An `rbac.denied` written for a session's request names that session, as the `users:read` refusal
and the step-up's always have: the one behind the request's bearer token, read with
`peek_access_token`, which authorises nothing. None when the request carries no bearer token, no
session store is wired, the token names no session, or the store cannot say (logged): a refusal's
record is never lost for want of its session. While viewing as another user (#3085), the token is
the viewer's, so the record names the viewer's session.
"""

from __future__ import annotations

import uuid
from typing import Any, Protocol

import structlog
from fastapi import Request

from candleviewer.api.step_up import _bearer
from candleviewer.auth.models import SessionRecord


class _Peek(Protocol):
    async def peek_access_token(self, raw_access_token: str) -> SessionRecord | None: ...


class SessionsLike(Protocol):
    """The part of `AuthService` this reads."""

    @property
    def sessions_is_active(self) -> bool: ...

    @property
    def sessions(self) -> _Peek: ...


class _Emitter(Protocol):
    async def emit(self, action: str, **kwargs: Any) -> None: ...


def _log() -> Any:
    """Resolved per call: a module-level logger pins a stale processor chain (#2008)."""
    return structlog.get_logger(__name__)


async def refusal_session(auth: SessionsLike | None, request: Request) -> uuid.UUID | None:
    """The session behind `request`'s bearer token, or none (module docstring)."""
    token = _bearer(request)
    if auth is None or token is None:
        return None
    try:
        if not auth.sessions_is_active:
            return None
        found = await auth.sessions.peek_access_token(token)
    except Exception as exc:  # the session store may be down: name no session, drop no record
        _log().warning("refusal names no session", error=type(exc).__name__)
        return None
    return None if found is None else found.id


class NamesSession:
    """An emitter that names the caller's session on each record it writes, in place of the
    `None` that `enforce` passes. It reads the session store only when `emit` runs, so an allowed
    request pays no read."""

    def __init__(self, emitter: _Emitter, auth: SessionsLike | None, request: Request) -> None:
        self._emitter, self._auth, self._request = emitter, auth, request

    async def emit(self, action: str, **kwargs: Any) -> None:
        session = await refusal_session(self._auth, self._request)
        await self._emitter.emit(action, **kwargs | {"session_id": session})

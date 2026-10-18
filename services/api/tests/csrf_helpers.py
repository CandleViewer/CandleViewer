"""SR-041 test helpers (#2090): send a real double-submit pair, never a bypass.

The token is minted by the app's own `CsrfCodec` (`app.state.csrf_codec`) for the
session the request authenticates as, exactly like the browser client echoing the
`__Host-cv_csrf` cookie it received at login. Apps whose tests authenticate with a
fake principal resolver (no session store) get `FakeBearerSessions`, which maps
each test bearer to a fixed session id so the guard can verify the binding.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from typing import Any

from candleviewer.auth.csrf import CSRF_COOKIE, CSRF_HEADER, CsrfCodec
from candleviewer.auth.errors import SessionNotFound

#: The one session every fake test bearer resolves to (see `FakeBearerSessions`).
TEST_SID = uuid.UUID("00000000-0000-4000-8000-00000000c5ef")


def csrf_headers(codec: CsrfCodec, session_id: str | uuid.UUID | None = None) -> dict[str, str]:
    """Header + cookie pair bound to *session_id* (default `TEST_SID`)."""
    token = codec.issue(str(session_id or TEST_SID))
    return {CSRF_HEADER: token, "Cookie": f"{CSRF_COOKIE}={token}"}


def arm_csrf(client: Any, codec: CsrfCodec, session_id: str | uuid.UUID | None = None) -> Any:
    """Give a `TestClient` the cookie + default header a browser client would send."""
    token = codec.issue(str(session_id or TEST_SID))
    for cookie in [c for c in client.cookies.jar if c.name == CSRF_COOKIE]:
        client.cookies.jar.clear(cookie.domain, cookie.path, cookie.name)  # drop server-set copies
    client.cookies.set(CSRF_COOKIE, token)
    client.headers[CSRF_HEADER] = token
    return client


class FakeBearerSessions:
    """`peek_access_token` for apps authenticated by a fake principal resolver:
    any of *bearers* resolves to `TEST_SID`; anything else resolves to nothing,
    so the guard refuses it (no session, no CSRF authority). The idle-lock gate
    (#2300) authenticates with `authenticate_access_token`: a test bearer is a
    live, unlocked session and anything else is unknown."""

    def __init__(self, *bearers: str) -> None:
        self._bearers = frozenset(bearers)

    async def peek_access_token(self, token: str) -> Any:
        if token in self._bearers:
            return SimpleNamespace(id=TEST_SID, user_id=TEST_SID)
        return None

    async def authenticate_access_token(self, token: str, **_kw: Any) -> Any:
        """No live session for the enrolment-only guard (#2295): it leaves the request to the
        route, whose fake principal resolver authorises it."""
        raise SessionNotFound("a fake bearer has no session")


def wire_fake_sessions(app: Any, *bearers: str) -> None:
    """Install `FakeBearerSessions` for the CSRF guard only when the app has no
    real session backend (fake storage); routes still authorise via their own
    principal resolver."""
    auth = app.state.app_context.auth
    if not auth.sessions_is_active:
        auth._sessions = FakeBearerSessions(*bearers)

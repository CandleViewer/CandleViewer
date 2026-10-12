"""SR-041 test helpers (#2090): send a real double-submit pair, never a bypass.

The token is minted by the app's own `CsrfCodec` (`app.state.csrf_codec`) for the
session the request authenticates as, exactly like the browser client echoing
the `__Host-cv_csrf` cookie it received at login.
"""

from __future__ import annotations

import uuid
from typing import Any

from candleviewer.auth.csrf import CSRF_COOKIE, CSRF_HEADER, CsrfCodec


def csrf_headers(codec: CsrfCodec, session_id: str | uuid.UUID | None = None) -> dict[str, str]:
    """Header + cookie pair bound to *session_id* (a fresh id when the caller
    has no server session, e.g. a fake principal resolver or an unauthenticated
    request that must still reach the route's own 401)."""
    token = codec.issue(str(session_id or uuid.uuid4()))
    return {CSRF_HEADER: token, "Cookie": f"{CSRF_COOKIE}={token}"}


def arm_csrf(client: Any, codec: CsrfCodec, session_id: str | uuid.UUID | None = None) -> Any:
    """Give a `TestClient` the cookie + default header a browser client would send."""
    token = codec.issue(str(session_id or uuid.uuid4()))
    client.cookies.set(CSRF_COOKIE, token)
    client.headers[CSRF_HEADER] = token
    return client

"""#3990: the records the CSRF guard, the auth router and the session router write carry the id the
real `CorrelationMiddleware` bound, asserted through the real `create_app()` stack of `_stack.py`.
Their audit sites are on security paths, and the static guard
(`tests/unit/architecture/test_audit_request_id_carried.py`) accepts any value at them."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest

from candleviewer.api.sessions import REFRESH_COOKIE

from ._stack import Stack


def _csrf_refusal(stack: Stack) -> Any:
    return stack.client.post("/auth/logout")  # no token pair: the CSRF guard refuses it


def _login_failure(stack: Stack) -> Any:
    return stack.client.post("/auth/login", json={"identifier": "ghost", "password": "unit-test"})


def _session_reuse(stack: Stack) -> Any:
    uid, _ = stack.add_user("victim")
    minted = stack.call(stack.auth.sessions.mint, str(uid))
    stack.call(stack.auth.sessions.refresh, minted.refresh_token)  # rotates the minted token away
    rotated = {"Cookie": f"{REFRESH_COOKIE}={minted.refresh_token}"}
    return stack.client.get("/auth/session", headers=rotated)  # a reuse probe, no other credential


@pytest.mark.parametrize(
    ("act", "action"),
    [
        (_csrf_refusal, "auth.csrf_refused"),
        (_login_failure, "auth.login_failed"),
        (_session_reuse, "auth.refresh_reuse_detected"),
    ],
    ids=["csrf_refusal", "login_failure", "session_reuse"],
)
def test_the_record_carries_the_id_the_middleware_bound(
    stack: Stack, act: Callable[[Stack], Any], action: str
) -> None:
    response = act(stack)
    (record,) = stack.audit.of(action)
    assert str(record["request_id"]) == response.headers["x-correlation-id"]

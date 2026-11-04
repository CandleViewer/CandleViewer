"""E42-X02 (#1220) BQ-9: the step-up grace window is fixed by the server at grant; an expiry the
client supplies in a body, a header or a cookie changes nothing, `POST /auth/session/extend`
re-stamps idle time only, and the next dangerous write after the window is challenged and
recorded `auth.step_up_required`. Real `create_app()` stack, fixed clock, no network (C-13.5)."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime, timedelta

import pytest

from candleviewer.auth.generated_permissions import Permission
from candleviewer.auth.step_up import GRACE_WINDOW
from tests.security.auth._stack import Stack, open_stack

_FAR = "2099-01-01T00:00:00+00:00"
#: Names a client might use to carry an expiry; none is read by the server.
_EXPIRY_HEADERS = {
    "X-Step-Up-Expires-At": _FAR,
    "X-Reauth-Expires-At": _FAR,
    "X-Elevated-Until": _FAR,
}
_EXPIRY_COOKIES = f"cv_step_up_expires_at={_FAR}; cv_elevated_until={_FAR}"


@pytest.fixture
def stack(monkeypatch: pytest.MonkeyPatch) -> Iterator[Stack]:
    with open_stack(monkeypatch) as s:
        yield s


def _invite(name: str) -> dict[str, object]:
    return {"email": f"{name}@example.com", "username": name, "roles": ["viewer"]}


def _with_client_expiry(headers: dict[str, str]) -> dict[str, str]:
    """The session's own headers plus the expiry headers and cookies (the CSRF pair kept)."""
    return {**headers, **_EXPIRY_HEADERS, "Cookie": f"{headers['Cookie']}; {_EXPIRY_COOKIES}"}


def _granted_expiry(stack: Stack, headers: dict[str, str]) -> str | None:
    info = stack.client.get("/auth/session", headers=_with_client_expiry(headers))
    assert info.status_code == 200, info.text
    value = info.json()["step_up_expires_at"]
    return None if value is None else str(value)


def test_x02_a_client_supplied_expiry_changes_nothing_and_the_lapsed_write_is_challenged(
    stack: Stack,
) -> None:
    owner, seed = stack.principal("owner", "owner", Permission.USERS_WRITE)
    challenged = stack.client.post("/users", headers=owner, json=_invite("annie"))
    assert challenged.status_code == 403 and challenged.json()["code"] == "step_up_required"
    challenge_id = challenged.json()["challenge_id"]

    # Body: an expiry member is refused whole; no factor is checked, nothing is granted.
    body = {
        "code": stack.code(seed),
        "password": "unused-x02",  # test-only literal, never a credential
        "challenge_id": challenge_id,
        "step_up_expires_at": _FAR,
        "elevated_until": _FAR,
    }
    refused = stack.client.post("/auth/step-up", headers=owner, json=body)
    assert refused.status_code == 400
    errors = {(e["field"], e["rule"]) for e in refused.json()["errors"]}
    assert ("body", "extra_forbidden") in errors
    assert stack.audit.of("auth.step_up_granted") == []

    granted = stack.step_up(owner, seed, challenge_id)
    assert granted.status_code == 200, granted.text
    expiry = granted.json()["step_up_expires_at"]
    assert datetime.fromisoformat(expiry) == stack.clock.now + GRACE_WINDOW  # fixed at grant
    assert _granted_expiry(stack, owner) == expiry

    # Inside the window: extend and a grace write, each carrying the client's expiry.
    stack.clock.now += timedelta(minutes=4)
    extended = stack.client.post("/auth/session/extend", headers=_with_client_expiry(owner))
    assert extended.status_code == 200, extended.text
    assert extended.json()["session"]["idle_deadline"] is not None
    used = stack.client.post("/users", headers=_with_client_expiry(owner), json=_invite("bertha"))
    assert used.status_code == 201, used.text
    assert _granted_expiry(stack, owner) == expiry  # neither extend nor the expiry moved it

    # One second past the granted expiry: challenged and recorded, whatever the client sends.
    required = len(stack.audit.of("auth.step_up_required"))
    stack.clock.now = datetime.fromisoformat(expiry) + timedelta(seconds=1)
    lapsed = stack.client.post("/users", headers=_with_client_expiry(owner), json=_invite("carla"))
    assert (lapsed.status_code, lapsed.json()["code"]) == (403, "step_up_required"), lapsed.text
    assert lapsed.json()["action_class"] == "users"
    records = stack.audit.of("auth.step_up_required")
    assert len(records) == required + 1
    assert str(records[-1]["reason"]).startswith("users")
    assert _granted_expiry(stack, owner) is None

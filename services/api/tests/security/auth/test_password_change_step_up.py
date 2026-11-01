"""#2099 (E09-Q06 charter gap): a password change while a step-up grant is live. The change revokes
the session that holds the grant (SR-013) and mints a replacement with none (BQ-221), so the gated
action is refused again with a fresh `403 step_up_required`, the old token is refused, and the
audit order is kept: `auth.password_change` (intent) < `auth.session_revoked` <
`auth.session_created` < `auth.password_change` (outcome) < `auth.step_up_required`. The real
`create_app()` over the in-memory auth stack (`_stack.py`), the real B16 chart and step-up service.
No network, no sleeps.
"""

from __future__ import annotations

from typing import Any

from candleviewer.auth.generated_permissions import Permission
from tests.csrf_helpers import csrf_headers

from ._stack import PW, Stack

_INVITE = {"email": "ann@example.com", "username": "annie", "roles": ["viewer"]}
NEW = "brand-new-Secret-42!"  # test-only literal, never a credential


def _stepped_up_owner(stack: Stack) -> tuple[dict[str, str], str]:
    """A signed-in owner holding `users:write` with a live `users` grant; its access token."""
    headers, seed = stack.principal("owner", "owner", Permission.USERS_WRITE)
    denied = stack.client.post("/users", headers=headers, json=_INVITE)
    assert (denied.status_code, denied.json()["code"]) == (403, "step_up_required")
    assert stack.step_up(headers, seed, denied.json()["challenge_id"]).status_code == 200
    return headers, headers["Authorization"].removeprefix("Bearer ")


def _actions(stack: Stack, since: int) -> list[str]:
    return [r["action"] for r in stack.audit.records[since:]]


def test_a_password_change_ends_a_live_step_up_grant_and_the_gated_action_is_refused(
    stack: Stack,
) -> None:
    headers, token = _stepped_up_owner(stack)
    old = stack.call(stack.auth.sessions.peek_access_token, token)
    assert old is not None and "users" in old.step_up_elevations  # the grant is live
    seen = len(stack.audit.records)

    changed = stack.client.put(
        "/auth/password", headers=headers, json={"current_password": PW, "new_password": NEW}
    )

    assert changed.status_code == 200, changed.text
    new_token = changed.json()["tokens"]["access_token"]
    row = stack.call(stack.auth.sessions.peek_access_token, new_token)
    assert row is not None and row.id != old.id
    assert row.step_up_elevations == {} and row.step_up_failures == 0
    assert row.readonly_until is None
    gone = stack.call(stack.auth.sessions.peek_access_token, token)
    assert gone is not None and gone.revoked_reason == "password_change"
    # The principal of the owner routes is read per token (the identity store's stand-in).
    stack.resolver.by_token[new_token] = stack.resolver.by_token[token]
    fresh = {"Authorization": f"Bearer {new_token}", **csrf_headers(stack.state.csrf_codec, row.id)}

    refused = stack.client.post("/users", headers=fresh, json=_INVITE)
    stale = stack.client.post("/users", headers=headers, json=_INVITE)

    assert (refused.status_code, refused.json()["code"]) == (403, "step_up_required")
    assert refused.json()["challenge_id"]  # a new challenge, on the new session
    assert stale.status_code == 401
    actions = _actions(stack, seen)
    order = [
        actions.index("auth.password_change"),
        actions.index("auth.session_revoked"),
        actions.index("auth.session_created"),
        len(actions) - 1 - actions[::-1].index("auth.password_change"),
        actions.index("auth.step_up_required"),
    ]
    assert order == sorted(order) and len(set(order)) == len(order), actions
    stages = [
        (r.get("after_state") or {}).get("stage")
        for r in stack.audit.records[seen:]
        if r["action"] == "auth.password_change"
    ]
    assert stages == ["intent", "outcome"]
    assert stack.audit.of("users.create") == []  # nothing gated ran


def test_the_stepped_up_session_held_request_is_refused_on_the_old_token(stack: Stack) -> None:
    """The request the client held for its grant, re-sent with the old token after the change,
    is refused at authentication and executes nothing (BQ-221: no grace survives)."""
    headers, _ = _stepped_up_owner(stack)
    changed = stack.client.put(
        "/auth/password", headers=headers, json={"current_password": PW, "new_password": NEW}
    )
    assert changed.status_code == 200
    before = len(stack.audit.records)
    held: Any = stack.client.post("/users", headers=headers, json=_INVITE)
    assert held.status_code == 401
    assert "users.create" not in _actions(stack, before)

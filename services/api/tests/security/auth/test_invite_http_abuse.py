"""E09-X02 invite abuse over HTTP (U12/SR-027, #2144) through the real `create_app()` routers,
step-up middleware and `InviteService`. The audit writer refuses an unregistered action like the
real `AuditWriter`, so a 500 or a missing row here is what production would do."""

from __future__ import annotations

import base64
from typing import Any

from candleviewer.auth.generated_permissions import Permission
from candleviewer.auth.invite_service import hash_token
from tests.csrf_helpers import csrf_headers

from ._stack import INVITE_PW, Stack

_INVITE = {"email": "ann@example.com", "username": "annie", "roles": ["viewer"]}


def _owner(stack: Stack) -> dict[str, str]:
    """Headers of a signed-in owner holding `users:write`, stepped up for `users`."""
    headers, seed = stack.principal("owner", "owner", Permission.USERS_WRITE)
    assert stack.client.post("/users", headers=headers, json=_INVITE).status_code == 403
    assert stack.step_up(headers, seed).status_code == 200
    return headers


def _redeem(stack: Stack, token: str, headers: dict[str, str] | None = None) -> Any:
    """Invitee side: set the password, enrol TOTP, confirm with the first code."""
    start = _begin(stack, token, headers)
    code = stack.code(_seed(start))
    body = {"method_id": start.json()["method_id"], "code": code}
    return stack.client.post(f"/invites/{token}/confirm", headers=headers, json=body)


def _begin(stack: Stack, token: str, headers: dict[str, str] | None = None) -> Any:
    start = stack.client.post(f"/invites/{token}", headers=headers, json={"password": INVITE_PW})
    assert start.status_code == 200, start.text
    return start


def _seed(start: Any) -> bytes:
    b32 = str(start.json()["secret_base32"])
    return base64.b32decode(b32 + "=" * (-len(b32) % 8))


def _invite(stack: Stack, owner: dict[str, str], name: str = "annie") -> str:
    body = {**_INVITE, "email": f"{name}@example.com", "username": name}
    created = stack.client.post("/users", headers=owner, json=body)
    assert created.status_code == 201, created.text
    return str(created.json()["invite_url"]).rsplit("/", 1)[1]


def test_ac_inv_05_pre_elevated_invite_via_api_refused_and_audited(stack: Stack) -> None:
    owner = _owner(stack)
    for role in ("manager", "owner"):
        r = stack.client.post("/users", headers=owner, json={**_INVITE, "roles": [role]})
        assert r.status_code == 422 and r.json()["detail"] == "invalid invite request", r.text
    rows = stack.audit.of("users.invite_refused")
    assert [(x["reason"], x["outcome"].value, x["severity"].value) for x in rows] == [
        ("invalid_invite_request", "denied", "warning")
    ] * 2
    assert stack.client.get("/users/invites", headers=owner).json()["items"] == []


def test_ac_inv_06_legacy_pre_elevated_row_redeems_as_viewer_and_is_audited(
    stack: Stack,
) -> None:  # SR-027 defence in depth (#2109)
    owner = _owner(stack)
    token = _invite(stack, owner)
    repo: Any = stack.auth._invite_repository  # the in-memory fake
    key = hash_token(token)
    repo.rows[key] = repo.rows[key].model_copy(update={"role": "manager"})
    done = _redeem(stack, token)
    assert done.status_code == 200 and done.json()["role"] == "viewer", done.text
    (downgrade,) = stack.audit.of("users.invite_role_downgraded")
    assert downgrade["before_state"] == {"role": "manager"}
    assert downgrade["after_state"] == {"role": "viewer"}
    assert stack.audit.of("users.invite_redeemed")[0]["after_state"] == {"role": "viewer"}


def test_ac_inv_07_signed_in_other_identity_never_receives_the_invite(stack: Stack) -> None:
    owner = _owner(stack)
    token = _invite(stack, owner)
    bob, _ = stack.add_user("bob")
    minted = stack.call(stack.auth.sessions.mint, str(bob))
    as_bob = {
        "Authorization": f"Bearer {minted.access_token}",
        **csrf_headers(stack.state.csrf_codec, minted.session_id),
    }
    for claim in ({"username": "bob"}, {"user_id": str(bob)}, {"email": "bob@example.test"}):
        r = stack.client.post(
            f"/invites/{token}", headers=as_bob, json={"password": INVITE_PW, **claim}
        )
        assert r.status_code == 400, r.text  # the invited identity cannot be swapped
    assert stack.client.get(f"/invites/{token}").status_code == 200  # nothing was consumed
    done = _redeem(stack, token, headers=as_bob)
    assert (done.status_code, done.json()["role"]) == (200, "viewer")
    (redeemed,) = stack.audit.of("users.invite_redeemed")
    assert redeemed["actor_label"] == "annie" and redeemed["actor_user_id"] != bob
    caller = stack.call(stack.auth.sessions.authenticate_access_token, minted.access_token)
    assert caller.user_id == bob  # the caller's own session and identity are untouched
    late = stack.client.post(f"/invites/{token}", json={"password": INVITE_PW})
    assert late.status_code == 404  # the real invitee then finds the link spent...
    assert stack.audit.of("users.invite_rejected")[-1]["reason"] == "redeemed"  # ...audited


def test_ac_inv_08_invite_cannot_be_completed_with_another_invitees_totp(stack: Stack) -> None:
    owner = _owner(stack)
    alice, mallory = _invite(stack, owner, "alice"), _invite(stack, owner, "mallory")
    mine, theirs = _begin(stack, alice), _begin(stack, mallory)
    forged = {"method_id": theirs.json()["method_id"], "code": stack.code(_seed(theirs))}
    r = stack.client.post(f"/invites/{alice}/confirm", json=forged)
    assert r.status_code == 422 and r.json()["code"] == "invalid_code"
    assert stack.audit.of("users.invite_rejected")[-1]["reason"] == "enrollment_invalid"
    own = {"method_id": mine.json()["method_id"], "code": stack.code(_seed(mine))}
    assert stack.client.post(f"/invites/{alice}/confirm", json=own).status_code == 200

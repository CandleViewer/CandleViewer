"""`PUT /auth/password` end to end (#2110; contract #2330 `authChangePassword`; SR-013, SR-026,
SR-028; BQ-219..BQ-235 as ruled). The real `create_app()` over the in-memory auth stack of
`_stack.py`: the CSRF guard, the enrolment guard, the view-as policy, the read-only guard, the
idle-lock gate, the route and an audit writer that refuses unregistered actions all run as
deployed. Every refusal case also asserts nothing changed. No network, no sleeps (C-13.5, C-13.7).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any, cast

import pytest

from candleviewer.api.sessions import REFRESH_COOKIE
from candleviewer.audit.errors import AuditError
from candleviewer.auth.csrf import CSRF_COOKIE
from candleviewer.auth.generated_permissions import Permission
from candleviewer.auth.models import MintedSession
from candleviewer.auth.view_as import ViewAsState
from tests.csrf_helpers import csrf_headers
from tests.unit.auth.session_fakes import FakeSessionRepository

from . import _stack
from ._stack import PW, Stack

NEW = "brand-new-Secret-42!"  # test-only literals, never credentials
_WRONG = "not-the-password"
_PATH = "/auth/password"


def _signed_in(stack: Stack, username: str, **mint: Any) -> tuple[uuid.UUID, MintedSession]:
    uid, _ = stack.add_user(username)
    minted: MintedSession = stack.call(stack.auth.sessions.mint, str(uid), **mint)
    return uid, minted


def _headers(stack: Stack, minted: MintedSession) -> dict[str, str]:
    csrf = csrf_headers(stack.state.csrf_codec, minted.session_id)
    return {"Authorization": f"Bearer {minted.access_token}", **csrf}


def _change(stack: Stack, minted: MintedSession, **body: Any) -> Any:
    payload = {"current_password": PW, "new_password": NEW} | body
    return stack.client.put(_PATH, headers=_headers(stack, minted), json=payload)


def _hash(stack: Stack, uid: uuid.UUID) -> str:
    return stack.users.users[str(uid)].password_hash


def _rows(stack: Stack, since: int = 0) -> list[tuple[str, Any, Any]]:
    return [
        (r["action"], r.get("reason"), (r.get("after_state") or {}).get("stage"))
        for r in stack.audit.records[since:]
    ]


def _session_works(stack: Stack, minted: MintedSession) -> bool:
    auth = {"Authorization": f"Bearer {minted.access_token}"}
    return bool(stack.client.get("/auth/session", headers=auth).status_code == 200)


# -- success: rotation, revocation, audit (BQ-219, BQ-221, BQ-229) -----------------------------


def test_a_change_rotates_the_session_revokes_every_other_and_is_audited_ahead(
    stack: Stack,
) -> None:
    uid, minted = _signed_in(stack, "zed", idle_timeout_s=1200)
    other = stack.call(stack.auth.sessions.mint, str(uid))  # the same user on another device
    their_uid, theirs = _signed_in(stack, "bo")  # IDOR: another user's session and password
    their_hash, old_hash = _hash(stack, their_uid), _hash(stack, uid)
    old = stack.call(stack.auth.sessions.peek_refresh, minted.refresh_token)
    seen = len(stack.audit.records)

    r = _change(stack, minted)

    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "password_changed" and body["tokens"]["refresh_token"] is None
    assert {REFRESH_COOKIE, CSRF_COOKIE} <= set(r.cookies)
    assert _hash(stack, uid) != old_hash and stack.users.history[str(uid)][0][1] == old_hash
    new = MintedSession.model_construct(access_token=body["tokens"]["access_token"])
    assert _session_works(stack, new)
    assert not _session_works(stack, minted) and not _session_works(stack, other)
    assert _session_works(stack, theirs) and _hash(stack, their_uid) == their_hash
    row = stack.call(stack.auth.sessions.peek_access_token, body["tokens"]["access_token"])
    assert row is not None and old is not None
    assert row.expires_at == old.expires_at and row.idle_timeout_s == 1200  # never extended
    assert row.step_up_elevations == {} and row.step_up_failures == 0
    assert row.readonly_until is None
    assert _rows(stack, seen) == [
        ("auth.password_change", None, "intent"),
        ("auth.session_revoked", "password_change", None),
        ("auth.session_revoked", "password_change", None),
        ("auth.session_created", None, None),
        ("auth.password_change", None, "outcome"),
    ]
    created = stack.audit.of("auth.session_created")[-1]
    assert created["after_state"] == {"rotated_from": str(minted.session_id)}
    assert created["session_id"] == row.id
    assert all("password" not in str(r.get("after_state")) for r in stack.audit.records[seen:])


@pytest.mark.parametrize("role", ["owner", "manager", "viewer"])
def test_every_role_may_change_its_own_password(stack: Stack, role: str) -> None:
    """`x-rbac {permissions: [], scope: self}`: no permission is needed, any role passes."""
    headers, _ = stack.principal(f"r-{role}", role, Permission.MARKETDATA_READ)
    body = {"current_password": PW, "new_password": NEW}
    assert stack.client.put(_PATH, headers=headers, json=body).status_code == 200


def test_replay_after_a_change_is_refused_and_changes_nothing_more(stack: Stack) -> None:
    """BQ-235: the same request again carries the revoked session (401); the old refresh token
    is refused at `POST /auth/refresh`."""
    uid, minted = _signed_in(stack, "zed")
    headers = _headers(stack, minted) | {"Idempotency-Key": str(uuid.uuid4())}
    body = {"current_password": PW, "new_password": NEW}
    assert stack.client.put(_PATH, headers=headers, json=body).status_code == 200
    changed = _hash(stack, uid)
    again = stack.client.put(_PATH, headers=headers, json=body)
    assert again.status_code == 401 and _hash(stack, uid) == changed
    stack.client.cookies.clear()
    pair = csrf_headers(stack.state.csrf_codec, minted.session_id)
    body = {"refresh_token": minted.refresh_token}
    refreshed = stack.client.post("/auth/refresh", json=body, headers=pair)
    assert refreshed.status_code == 401


# -- refusals of the handler (steps 4 to 8) -------------------------------------------------------


def test_a_wrong_current_password_is_403_counts_toward_the_lockout_and_keeps_the_session(
    stack: Stack,
) -> None:
    """BQ-225: login's counters; the session stays signed in; not a step-up strike."""
    uid, minted = _signed_in(stack, "zed")
    before, seen = _hash(stack, uid), len(stack.audit.records)
    r = _change(stack, minted, current_password=_WRONG)
    assert (r.status_code, r.json()["code"]) == (403, "current_password_invalid")
    assert r.json()["detail"] == "Your current password is incorrect."
    assert stack.users.users[str(uid)].failed_login_count == 1 and _hash(stack, uid) == before
    assert _session_works(stack, minted)
    assert _rows(stack, seen) == [("auth.password_change", "current_password_invalid", None)]
    row = stack.call(stack.auth.sessions.peek_refresh, minted.refresh_token)
    assert row is not None and row.step_up_failures == 0


def test_the_fifth_wrong_password_locks_the_account_and_then_the_right_one_is_refused(
    stack: Stack,
) -> None:
    """The #2330 ruling: the code locks after 5 (SR-016 says 10); a locked account fails alike."""
    uid, minted = _signed_in(stack, "zed")
    for _ in range(5):
        assert _change(stack, minted, current_password=_WRONG).status_code == 403
    assert stack.users.users[str(uid)].locked_until is not None
    assert [r["reason"] for r in stack.audit.of("auth.account_locked")] == [
        "password_change_failed"
    ]
    assert _change(stack, minted).json()["code"] == "current_password_invalid"


@pytest.mark.parametrize(
    ("new", "code", "rule"),
    [
        ("passwordpassword", "password_breached", None),
        ("abababababababab", "password_breached", None),
        ("short-Zq7!", "password_policy", "min_length"),
        ("i-am-zed-the-user!", "password_policy", "contains_identity"),
        (PW, "password_reused", None),
    ],
)
def test_a_refused_new_password_is_422_with_its_code_and_nothing_changes(
    stack: Stack, new: str, code: str, rule: str | None
) -> None:
    uid, minted = _signed_in(stack, "zed")
    before, seen = _hash(stack, uid), len(stack.audit.records)
    r = _change(stack, minted, new_password=new)
    assert (r.status_code, r.json()["code"]) == (422, code), r.text
    errors = r.json().get("errors")
    assert (errors[0]["rule"] if errors else None) == rule
    assert new not in r.text
    assert _hash(stack, uid) == before and _session_works(stack, minted)
    assert _rows(stack, seen) == [("auth.password_change", code, None)]


def test_a_retired_password_is_reused(stack: Stack) -> None:
    uid, minted = _signed_in(stack, "zed")
    first = _change(stack, minted)
    assert first.status_code == 200
    new = MintedSession.model_construct(
        access_token=first.json()["tokens"]["access_token"],
        session_id=stack.call(
            stack.auth.sessions.peek_access_token, first.json()["tokens"]["access_token"]
        ).id,
    )
    back = stack.client.put(
        _PATH, headers=_headers(stack, new), json={"current_password": NEW, "new_password": PW}
    )
    assert (back.status_code, back.json()["code"]) == (422, "password_reused")
    assert len(stack.users.history[str(uid)]) == 1


@pytest.mark.parametrize(
    ("body", "field", "rule"),
    [
        ({"current_password": PW}, "new_password", "required"),
        ({"current_password": "", "new_password": NEW}, "current_password", "min_length"),
        ({"current_password": PW, "new_password": "x" * 513}, "new_password", "max_length"),
        ({"current_password": PW, "new_password": NEW, "user_id": "x"}, "body", None),
    ],
)
def test_a_malformed_body_is_422_before_any_password_is_checked(
    stack: Stack, body: dict[str, Any], field: str, rule: str | None
) -> None:
    """SR-026: a member naming a user is refused, never honoured (no IDOR); no failure counted."""
    uid, minted = _signed_in(stack, "zed")
    other_uid, _ = _signed_in(stack, "bo")
    others = _hash(stack, other_uid)
    r = stack.client.put(_PATH, headers=_headers(stack, minted), json=body)
    assert (r.status_code, r.json()["code"]) == (422, "validation_failed")
    assert r.json()["errors"][0]["field"] == field
    if rule is not None:
        assert r.json()["errors"][0]["rule"] == rule
    assert stack.users.users[str(uid)].failed_login_count == 0 and _hash(stack, other_uid) == others
    assert PW not in r.text


def test_a_query_parameter_naming_a_user_is_refused(stack: Stack) -> None:
    uid, minted = _signed_in(stack, "zed")
    other_uid, _ = _signed_in(stack, "bo")
    before = _hash(stack, other_uid)
    r = stack.client.put(
        f"{_PATH}?user_id={other_uid}",
        headers=_headers(stack, minted),
        json={"current_password": PW, "new_password": NEW},
    )
    assert r.status_code == 422 and _hash(stack, other_uid) == before
    assert stack.users.users[str(uid)].failed_login_count == 0


def test_a_full_verification_bound_is_429_with_retry_after(stack: Stack) -> None:
    """BQ-226: no new limiter; the sign-in bound, decided before any password is checked."""
    uid, minted = _signed_in(stack, "zed")
    bound = stack.auth._verify_admission
    held = 0
    while bound.try_enter():
        held += 1
    try:
        r = _change(stack, minted)
    finally:
        for _ in range(held):
            bound.leave()
    assert (r.status_code, r.json()["code"]) == (429, "rate_limited")
    assert r.headers["Retry-After"] == "1"
    assert stack.users.users[str(uid)].failed_login_count == 0


def test_an_audit_writer_that_refuses_the_intent_is_503_and_nothing_changes(
    stack: Stack, monkeypatch: pytest.MonkeyPatch
) -> None:
    uid, minted = _signed_in(stack, "zed")
    before = _hash(stack, uid)
    real = stack.audit.emit

    async def refusing(action: str, **kw: Any) -> None:
        if (kw.get("after_state") or {}).get("stage") == "intent":
            raise AuditError("wal full")
        await real(action, **kw)

    monkeypatch.setattr(stack.audit, "emit", refusing)
    r = _change(stack, minted)
    assert (r.status_code, r.json()["code"]) == (503, "audit_unavailable")
    assert _hash(stack, uid) == before and _session_works(stack, minted)


def test_a_concurrent_change_that_won_first_is_409_and_voids_the_records(
    stack: Stack, monkeypatch: pytest.MonkeyPatch
) -> None:
    """BQ-232: the compare-and-swap lost; nothing changes and the session stays."""
    uid, minted = _signed_in(stack, "zed")
    before = _hash(stack, uid)

    async def lost(*_a: Any, **_k: Any) -> bool:
        return False

    monkeypatch.setattr(stack.users, "change_password", lost)
    r = _change(stack, minted)
    assert (r.status_code, r.json()["code"]) == (409, "conflict")
    assert _hash(stack, uid) == before and _session_works(stack, minted)
    last = stack.audit.records[-1]
    assert (last["action"], last["reason"]) == ("auth.password_change", "conflict")
    assert "voids_session_created" in last["after_state"]


def test_a_rotation_that_fails_after_the_commit_is_503_and_the_new_password_stands(
    stack: Stack, monkeypatch: pytest.MonkeyPatch
) -> None:
    uid, minted = _signed_in(stack, "zed")
    before = _hash(stack, uid)

    async def broken(*_a: Any, **_k: Any) -> Any:
        raise RuntimeError("store down")

    monkeypatch.setattr(stack.auth.sessions, "mint", broken)
    r = _change(stack, minted)
    assert (r.status_code, r.json()["detail"]) == (503, "password changed; sign in again")
    assert _hash(stack, uid) != before and not _session_works(stack, minted)
    last = stack.audit.records[-1]
    assert (last["action"], last["reason"]) == ("auth.password_change", "unrotated")
    assert last["outcome"] == "failure"
    assert last["after_state"]["committed"] is True
    assert "voids_session_created" in last["after_state"]


def test_a_revocation_that_fails_after_the_commit_is_503_and_voids_the_revoked_records(
    stack: Stack, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The intent rows said every session was revoked; an outcome row voids them (C-2.9)."""
    uid, minted = _signed_in(stack, "zed")
    before = _hash(stack, uid)

    async def broken(*_a: Any, **_k: Any) -> Any:
        raise RuntimeError("store down")

    monkeypatch.setattr(stack.auth.sessions, "revoke_all", broken)
    r = _change(stack, minted)
    assert (r.status_code, r.json()["detail"]) == (503, "password changed; sign in again")
    assert _hash(stack, uid) != before
    last = stack.audit.records[-1]
    assert (last["action"], last["reason"]) == ("auth.password_change", "unrotated")
    assert last["outcome"] == "failure"
    assert last["after_state"]["voids_session_revoked"] == [str(minted.session_id)]


def test_a_session_minted_after_the_plan_is_revoked_with_an_unplanned_row(
    stack: Stack, monkeypatch: pytest.MonkeyPatch
) -> None:
    """C-2.9: the records written ahead do not name it, so its revocation gets an outcome row."""
    _, minted = _signed_in(stack, "zed")
    sessions = stack.auth.sessions
    revoke_all = sessions.revoke_all
    late: list[MintedSession] = []

    async def racing(user_id: str, **kw: Any) -> Any:
        late.append(await sessions.mint(user_id))  # another sign-in lands after the plan
        return await revoke_all(user_id, **kw)

    monkeypatch.setattr(sessions, "revoke_all", racing)
    r = _change(stack, minted)
    assert r.status_code == 200, r.text
    assert not _session_works(stack, late[0])
    unplanned = [
        row
        for row in stack.audit.of("auth.session_revoked")
        if (row.get("after_state") or {}).get("unplanned")
    ]
    assert [row["session_id"] for row in unplanned] == [late[0].session_id]
    assert unplanned[0]["reason"] == "password_change"


def test_a_session_that_never_proved_a_second_factor_is_not_upgraded_by_the_rotation(
    stack: Stack,
) -> None:
    """BQ-221: the replacement keeps the caller's `mfa_satisfied_at` state (unset stays unset).
    Only a user without `mfa_required` (C-12.2 forbids one) holds such a full session."""
    uid, minted = _signed_in(stack, "zed", mfa_satisfied=False)
    user = stack.users.users[str(uid)]
    stack.users.users[str(uid)] = user.model_copy(update={"mfa_required": False})
    r = _change(stack, minted)
    assert r.status_code == 200, r.text
    row = stack.call(stack.auth.sessions.peek_access_token, r.json()["tokens"]["access_token"])
    assert row is not None and row.mfa_satisfied_at is None


# -- refusals of the guards (steps 1 to 3) --------------------------------------------------------


def test_an_ended_session_is_401_and_a_missing_csrf_token_is_403(stack: Stack) -> None:
    """Steps 1 and 2. A call bound to no session at all is refused by CSRF first, as every
    unsafe operation is (SR-041; the RBAC matrix counts it as the anonymous refusal)."""
    uid, minted = _signed_in(stack, "zed")
    body = {"current_password": PW, "new_password": NEW}
    anonymous = stack.client.put(_PATH, json=body)
    assert (anonymous.status_code, anonymous.json()["code"]) == (403, "csrf_token_invalid")
    bare = {"Authorization": f"Bearer {minted.access_token}"}
    r = stack.client.put(_PATH, headers=bare, json=body)
    assert (r.status_code, r.json()["code"]) == (403, "csrf_token_invalid")
    _, ended = _signed_in(stack, "yon")
    stack.call(stack.auth.sessions.revoke, str(ended.session_id), reason="logout")
    assert _change(stack, ended).status_code == 401
    assert stack.users.users[str(uid)].failed_login_count == 0


def test_an_idle_locked_session_is_401_session_idle_locked(stack: Stack) -> None:
    uid, minted = _signed_in(stack, "zed", idle_timeout_s=300)
    stack.clock.now += timedelta(seconds=301)
    r = _change(stack, minted)
    assert (r.status_code, r.json()["code"]) == (401, "session_idle_locked")
    assert stack.users.users[str(uid)].failed_login_count == 0


def test_a_read_only_session_is_403_session_read_only(stack: Stack) -> None:
    until = stack.clock.now + timedelta(minutes=5)
    uid, minted = _signed_in(stack, "zed", readonly_until=until)
    before = _hash(stack, uid)
    r = _change(stack, minted)
    assert (r.status_code, r.json()["code"]) == (403, "session_read_only")
    assert _hash(stack, uid) == before


def test_an_enrolment_only_session_is_403_mfa_enrollment_required(stack: Stack) -> None:
    uid, _ = stack.add_user("zed")
    minted = stack.call(stack.auth.sessions.mint_enrolment_only, str(uid), session_id=uuid.uuid4())
    before = _hash(stack, uid)
    r = _change(stack, minted)
    assert (r.status_code, r.json()["code"]) == (403, "mfa_enrollment_required")
    assert _hash(stack, uid) == before


def test_a_viewing_session_is_403_view_as_read_only_and_the_target_is_untouched(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """IDOR through view-as: the viewer acts as itself, read-only; the target never changes."""

    async def may_view(_self: Any, _user_id: str) -> dict[str, Any]:
        return {"permissions": [Permission.USERS_WRITE.value], "account_scope": []}

    monkeypatch.setattr(_stack.Identity, "session_info", may_view)
    with _stack.open_stack(monkeypatch) as s:
        uid, minted = _signed_in(s, "zed")
        target, _ = s.add_user("bo")
        mine, theirs = _hash(s, uid), _hash(s, target)
        store = cast(FakeSessionRepository, s.auth.view_as_store)
        record = store.sessions[str(minted.session_id)]
        state = ViewAsState.start(uuid.uuid4(), target, now=datetime.now(UTC))
        store.sessions[str(record.id)] = record.model_copy(update={"view_as": state})
        r = _change(s, minted)
        assert (r.status_code, r.json()["code"]) == (403, "view_as_read_only")
        assert _hash(s, uid) == mine and _hash(s, target) == theirs

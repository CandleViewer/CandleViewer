"""Enrolment-only session endpoints on the composed app (#2295 slice 3/3, #2344; contract #2661).

Real `create_app()` over the in-memory auth stack of `_stack.py`, with a user store that derives
each user's confirmed methods from the MFA store on every read, as the SQL does
(`users_sqlalchemy._FIND_SQL`), so a reset, an enrolment or a confirmation shows at once. Covers
the sign-in that mints the session (Q6), enrol and confirm with the rotation, the method
revocation and the code replacement (Q8), the owner reset setting `mfa_required` (Q9), the
409 while a method exists (Q10) and the recovery sign-in that mints the session too (#2344).
Each endpoint has a forbidden case (a session that may not enrol) and a cross-user case, and its
audit records are written before anything changes.
"""

from __future__ import annotations

import base64
import json
import logging
import uuid
from collections.abc import Iterator
from datetime import timedelta
from typing import Any
from urllib.parse import parse_qs, urlparse

import pytest
import structlog
from prometheus_client import REGISTRY

from candleviewer.audit.errors import AuditError
from candleviewer.audit.models import AuditOutcome, Severity
from candleviewer.auth.mfa_service import CHALLENGE_ATTEMPT_CAP
from candleviewer.auth.models import UserRecord
from candleviewer.auth.recovery_codes import normalize_recovery_code
from tests.csrf_helpers import csrf_headers
from tests.unit.auth.auth_fakes import FakeUserRepository
from tests.unit.auth.mfa_fakes import FakeMfaRepository

from . import _stack
from ._stack import PW, Stack, open_stack

_GRANTS: dict[str, Any] = {
    "permissions": ["orders:read"],
    "account_scope": ["acc-1"],
    "kill_switch": {"engaged": False},
}
#: The confirm's write-ahead records, for a user with two live sessions (C-2.9).
_ROTATION = [
    "auth.mfa_enrolled",
    "auth.recovery_codes_regenerated",
    "auth.session_revoked",
    "auth.session_revoked",
    "auth.session_created",
]
#: A recovery sign-in's write-ahead records, for a user with two live sessions (C-2.9, #2344).
_RECOVERY = [
    "auth.recovery_code_used",
    "auth.session_revoked",
    "auth.session_revoked",
    "auth.session_created",
]
#: The one answer every refused recovery gets (PR #1618 review finding 4: no oracle).
_RECOVERY_REFUSED = (401, "invalid or expired code")


class _Users(FakeUserRepository):
    """`mfa_methods` derived on every read: the user's confirmed, unrevoked methods."""

    def __init__(self, mfa: FakeMfaRepository) -> None:
        super().__init__()
        self.mfa = mfa

    def _derive(self, user: UserRecord | None) -> UserRecord | None:
        if user is None:
            return None
        kinds = {
            m.kind
            for m in self.mfa.methods.values()
            if m.user_id == user.id and m.confirmed_at is not None and m.revoked_at is None
        }
        return user.model_copy(update={"mfa_methods": tuple(sorted(kinds))})

    async def find_by_identifier(self, identifier: str) -> UserRecord | None:
        return self._derive(await super().find_by_identifier(identifier))

    async def find_by_id(self, user_id: str) -> UserRecord | None:
        return self._derive(await super().find_by_id(user_id))


class _Identity(_stack.Identity):
    async def session_info(self, user_id: str) -> dict[str, Any]:
        return dict(_GRANTS)


@pytest.fixture
def stack(monkeypatch: pytest.MonkeyPatch) -> Iterator[Stack]:
    mfa = FakeMfaRepository()
    monkeypatch.setattr(_stack, "FakeMfaRepository", lambda: mfa)
    monkeypatch.setattr(_stack, "FakeUserRepository", lambda: _Users(mfa))
    monkeypatch.setattr(_stack, "Identity", _Identity)
    with open_stack(monkeypatch) as s:
        yield s


def _store(stack: Stack) -> FakeMfaRepository:
    assert isinstance(stack.users, _Users)
    return stack.users.mfa


def _must_enrol(stack: Stack, username: str) -> uuid.UUID:
    """A user with `PW` whose every method is revoked, as an owner reset leaves them."""
    uid, _ = stack.add_user(username)
    store = _store(stack)
    for mid, m in list(store.methods.items()):
        if m.user_id == uid:
            store.methods[mid] = m.model_copy(update={"revoked_at": stack.clock.now})
    return uid


def _sign_in(stack: Stack, username: str) -> Any:
    stack.client.cookies.clear()
    return stack.client.post("/auth/login", json={"identifier": username, "password": PW})


def _auth(stack: Stack, access_token: str) -> dict[str, str]:
    """The bearer and an SR-041 pair bound to its session, as the client echoes its cookie."""
    record = stack.call(stack.auth.sessions.peek_access_token, access_token)
    stack.client.cookies.clear()
    csrf = csrf_headers(stack.state.csrf_codec, record.id)
    return {"Authorization": f"Bearer {access_token}", **csrf}


def _enrolment_only(stack: Stack, username: str) -> dict[str, str]:
    resp = _sign_in(stack, username)
    assert resp.status_code == 200, resp.text
    return _auth(stack, resp.json()["tokens"]["access_token"])


def _enrol(stack: Stack, headers: dict[str, str]) -> tuple[str, bytes]:
    """`POST /auth/mfa/enroll`: the method id and the seed from the provisioning URI."""
    body = {"method": "totp", "label": "Phone"}
    resp = stack.client.post("/auth/mfa/enroll", headers=headers, json=body)
    assert resp.status_code == 201, resp.text
    secret = parse_qs(urlparse(resp.json()["otpauth_uri"]).query)["secret"][0]
    return resp.json()["method_id"], base64.b32decode(secret + "=" * (-len(secret) % 8))


def _confirm(stack: Stack, headers: dict[str, str], method_id: str, code: str) -> Any:
    body = {"method_id": method_id, "code": code}
    return stack.client.post("/auth/mfa/enroll/confirm", headers=headers, json=body)


def _wrong_code(stack: Stack, seed: bytes) -> str:
    """Six digits no step of *seed*'s accepted window (+/-1) produces: a wrong guess, never a
    lucky one."""
    window = {stack.code(seed, offset) for offset in (-1, 0, 1)}
    return next(code for code in ("000000", "000001", "000002", "000003") if code not in window)


def _revocations(reason: str) -> float:
    """`auth_session_revocations_total{reason}` on the process-default registry."""
    sample = REGISTRY.get_sample_value("auth_session_revocations_total", {"reason": reason})
    return float(sample or 0.0)


def _code_hashes(stack: Stack, uid: uuid.UUID) -> set[str | None]:
    rows = _store(stack).recovery_codes.values()
    return {row["code_hash"] for row in rows if row["user_id"] == str(uid)}


async def _accept(methods: int, sessions: int, /) -> None:
    """The owner reset's write-ahead audit hook, accepting."""


def _codes(stack: Stack, uid: uuid.UUID) -> tuple[str, ...]:
    """A new set of 10 recovery codes for *uid*, in plaintext (the earlier set stops working)."""
    return tuple(stack.call(stack.auth.mfa.regenerate_recovery_codes, str(uid)).recovery_codes)


def _challenge(stack: Stack, username: str) -> str:
    """The password step of a user with a confirmed TOTP: the `mfa_token` of its challenge."""
    resp = _sign_in(stack, username)
    assert resp.json()["status"] == "mfa_required", resp.text
    return str(resp.json()["mfa_token"])


def _recover(stack: Stack, mfa_token: str, code: str, **kwargs: Any) -> Any:
    body = {"mfa_token": mfa_token, "recovery_code": code}
    return stack.client.post("/auth/mfa/recovery", json=body, **kwargs)


def _unused(stack: Stack, uid: uuid.UUID) -> int:
    return int(stack.call(_store(stack).count_unused_recovery_codes, str(uid)))


def _live(stack: Stack, uid: uuid.UUID) -> set[uuid.UUID]:
    return {view.id for view in stack.call(stack.auth.sessions.list_sessions, str(uid))}


# -- POST /auth/login (Q6, Q7, Q9) ---------------------------------------------------------------


def test_regression_sign_in_after_an_owner_reset_is_enrolment_only_not_501(stack: Stack) -> None:
    """The live lockout on #2295: after an owner TOTP reset, sign-in answered 501 and no route
    could add a method. The reset also sets `mfa_required` (Q9), so a user the owner had
    exempted signs in to enrol too, and the new TOTP then signs in normally."""
    owner, owner_seed = stack.add_user("owner")
    target, _ = stack.add_user("target")
    stack.users.add(stack.users.users[str(target)].model_copy(update={"mfa_required": False}))
    sid = str(stack.call(stack.auth.sessions.mint, str(owner)).session_id)
    stack.call(stack.auth.step_up.step_up, str(owner), sid, "users", stack.code(owner_seed), PW)
    stack.call(
        stack.auth.step_up.reset_totp,
        actor_session_id=sid,
        actor_user_id=str(owner),
        target_user_id=str(target),
        audit=_accept,
    )

    resp = _sign_in(stack, "target")

    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "authenticated"
    headers = _auth(stack, resp.json()["tokens"]["access_token"])
    method_id, seed = _enrol(stack, headers)
    assert _confirm(stack, headers, method_id, stack.code(seed)).status_code == 200
    stack.clock.now += timedelta(seconds=30)  # the confirming code is spent
    stack.sign_in("target", seed)  # asserts 200 for the password and the TOTP step


def test_sign_in_mints_a_fifteen_minute_session_audited_before_it_exists(stack: Stack) -> None:
    uid = _must_enrol(stack, "alice")

    resp = _sign_in(stack, "alice")

    assert (resp.status_code, resp.json()["tokens"]["refresh_expires_in"]) == (200, 900)
    assert "Max-Age=900" in resp.headers["set-cookie"]
    record = stack.call(
        stack.auth.sessions.peek_access_token, resp.json()["tokens"]["access_token"]
    )
    assert record.mfa_satisfied_at is None
    assert record.expires_at - record.issued_at == timedelta(minutes=15)
    (created,) = stack.audit.of("auth.session_created")
    assert (created["session_id"], created["actor_user_id"]) == (record.id, uid)
    assert created["after_state"] == {"enrolment_only": True, "mfa_satisfied": False}


def test_sign_in_mints_nothing_when_its_audit_record_cannot_be_written(
    stack: Stack, monkeypatch: pytest.MonkeyPatch
) -> None:
    uid = _must_enrol(stack, "alice")
    _fail_on(stack, monkeypatch, "auth.session_created")

    assert _sign_in(stack, "alice").status_code == 503
    assert stack.call(stack.auth.sessions.list_sessions, str(uid)) == ()


def test_sign_in_without_mfa_required_and_without_a_method_still_fails_closed(
    stack: Stack,
) -> None:
    uid = _must_enrol(stack, "alice")
    stack.users.add(stack.users.users[str(uid)].model_copy(update={"mfa_required": False}))

    assert _sign_in(stack, "alice").status_code == 501
    assert stack.call(stack.auth.sessions.list_sessions, str(uid)) == ()


def test_an_owners_enrolment_only_sign_in_moves_the_series_an_alert_pages_on(
    stack: Stack, monkeypatch: pytest.MonkeyPatch
) -> None:
    """U33 (RR-15): an Owner's password-only session is counted under `role="owner"`."""
    _must_enrol(stack, "boss")

    async def owner(self: _Identity, user_id: str) -> dict[str, Any]:
        return {"id": user_id, "username": "boss", "roles": ["owner"], "status": "active"}

    monkeypatch.setattr(_Identity, "user", owner)
    before = stack.scraped("auth_enrolment_only_sessions_total", role="owner")

    assert _sign_in(stack, "boss").status_code == 200
    assert stack.scraped("auth_enrolment_only_sessions_total", role="owner") == before + 1


# -- POST /auth/mfa/enroll (Q10) -----------------------------------------------------------------


def test_enrol_supersedes_the_earlier_pending_method_and_returns_no_codes(stack: Stack) -> None:
    _must_enrol(stack, "alice")
    headers = _enrolment_only(stack, "alice")
    first, first_seed = _enrol(stack, headers)

    resp = stack.client.post("/auth/mfa/enroll", headers=headers, json={"method": "totp"})

    assert resp.status_code == 201 and "recovery_codes" not in resp.json()
    assert _store(stack).methods[first].revoked_at is not None
    refused = _confirm(stack, headers, first, stack.code(first_seed))
    assert (refused.status_code, refused.json()["code"]) == (422, "validation_failed")
    webauthn = stack.client.post("/auth/mfa/enroll", headers=headers, json={"method": "webauthn"})
    assert webauthn.status_code == 422
    assert len(stack.audit.of("auth.mfa_enroll")) == 2  # one record per enrolment, written first


def test_enrol_creates_nothing_without_its_audit_record_or_a_live_token(
    stack: Stack, monkeypatch: pytest.MonkeyPatch
) -> None:
    _must_enrol(stack, "alice")
    headers = _enrolment_only(stack, "alice")
    before = dict(_store(stack).methods)
    _fail_on(stack, monkeypatch, "auth.mfa_enroll")

    unaudited = stack.client.post("/auth/mfa/enroll", headers=headers, json={"method": "totp"})
    stack.clock.now += timedelta(minutes=13)  # past the 12-minute access token
    expired = stack.client.post("/auth/mfa/enroll", headers=headers, json={"method": "totp"})

    assert (unaudited.status_code, expired.status_code) == (503, 401)
    assert _store(stack).methods == before


def test_forbidden_a_user_with_a_confirmed_method_gets_409_and_nothing_changes(
    stack: Stack,
) -> None:
    """Q10: voluntary re-enrolment is a follow-up; no role is refused otherwise (viewer here)."""
    _, seed = stack.add_user("member")
    headers = _auth(stack, stack.sign_in("member", seed).json()["tokens"]["access_token"])
    before = dict(_store(stack).methods)

    enrol = stack.client.post("/auth/mfa/enroll", headers=headers, json={"method": "totp"})
    confirm = _confirm(stack, headers, next(iter(before)), stack.code(seed))

    assert [(r.status_code, r.json()["code"]) for r in (enrol, confirm)] == [(409, "conflict")] * 2
    assert _store(stack).methods == before
    assert stack.audit.of("auth.mfa_enroll") == []


def test_cross_user_no_header_or_query_parameter_can_name_another_user(stack: Stack) -> None:
    victim = _must_enrol(stack, "victim")
    alice = _must_enrol(stack, "alice")
    headers = _enrolment_only(stack, "alice")
    before = dict(_store(stack).methods)

    by_query = stack.client.post(
        f"/auth/mfa/enroll?user_id={victim}", headers=headers, json={"method": "totp"}
    )
    unchanged = dict(_store(stack).methods)
    by_header = stack.client.post(
        "/auth/mfa/enroll", headers={**headers, "X-User-Id": str(victim)}, json={"method": "totp"}
    )

    assert (by_query.status_code, by_query.json()["code"], unchanged) == (
        422,
        "validation_failed",
        before,
    )
    assert by_header.status_code == 201  # the header is ignored: the bearer names the user
    assert _store(stack).methods[by_header.json()["method_id"]].user_id == alice
    assert all(m == before.get(k) for k, m in _store(stack).methods.items() if m.user_id == victim)


# -- POST /auth/mfa/enroll/confirm (Q8) ----------------------------------------------------------


def test_confirm_rotates_to_a_full_session_and_replaces_every_old_credential(stack: Stack) -> None:
    uid = _must_enrol(stack, "alice")
    old_codes = _code_hashes(stack, uid)
    parallel = _enrolment_only(stack, "alice")
    first = _sign_in(stack, "alice")
    old_refresh = first.cookies["cv_refresh"]
    headers = _auth(stack, first.json()["tokens"]["access_token"])
    method_id, seed = _enrol(stack, headers)
    mark = len(stack.audit.records)

    resp = _confirm(stack, headers, method_id, stack.code(seed))

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert (body["mfa_method"]["id"], body["mfa_method"]["active"]) == (method_id, True)
    assert len(set(body["recovery_codes"])) == 10 == len(_code_hashes(stack, uid))
    assert not _code_hashes(stack, uid) & old_codes
    full = _auth(stack, body["tokens"]["access_token"])
    written = stack.audit.records[mark:]  # all before the response: write-ahead (C-2.9)
    assert [r["action"] for r in written] == _ROTATION
    assert (
        written[-1]["session_id"]
        == stack.call(stack.auth.sessions.peek_access_token, body["tokens"]["access_token"]).id
    )
    for dead in (headers, parallel):  # SR-013: the old tokens and every other session end
        assert stack.client.get("/auth/session", headers=dead).status_code == 401
    old_sid = stack.call(stack.auth.sessions.peek_refresh, old_refresh).id
    refresh = stack.client.post(
        "/auth/refresh",
        headers=csrf_headers(stack.state.csrf_codec, old_sid),
        json={"refresh_token": old_refresh},
    )
    assert refresh.status_code == 401
    assert stack.client.get("/auth/sessions", headers=full).status_code == 200


@pytest.mark.parametrize("failing", sorted(set(_ROTATION)))
def test_confirm_changes_nothing_when_an_audit_record_cannot_be_written(
    stack: Stack, monkeypatch: pytest.MonkeyPatch, failing: str
) -> None:
    uid = _must_enrol(stack, "alice")
    old_codes = _code_hashes(stack, uid)
    headers = _enrolment_only(stack, "alice")
    method_id, seed = _enrol(stack, headers)
    _fail_on(stack, monkeypatch, failing)

    resp = _confirm(stack, headers, method_id, stack.code(seed))

    assert resp.status_code == 503
    assert stack.call(_store(stack).find_pending_method, method_id, str(uid)) is not None
    assert _code_hashes(stack, uid) == old_codes
    assert stack.client.get("/auth/session", headers=headers).status_code == 200


def test_cross_user_confirming_another_users_pending_method_is_refused(stack: Stack) -> None:
    _must_enrol(stack, "victim")
    _must_enrol(stack, "alice")
    victim_method, victim_seed = _enrol(stack, _enrolment_only(stack, "victim"))
    headers = _enrolment_only(stack, "alice")

    resp = _confirm(stack, headers, victim_method, stack.code(victim_seed))

    assert (resp.status_code, resp.json()["code"]) == (422, "validation_failed")
    assert _store(stack).methods[victim_method].confirmed_at is None
    assert len(stack.audit.of("auth.mfa_failed")) == 1


def test_confirm_with_a_wrong_code_writes_only_its_failure_and_changes_nothing(
    stack: Stack,
) -> None:
    """The code is checked before any write-ahead record (C-2.9): a wrong guess appends only
    `auth.mfa_failed`, never a false enrolment, code swap or session record, and the session,
    the pending method and the old codes survive it, so the right code still completes."""
    uid = _must_enrol(stack, "alice")
    old_codes = _code_hashes(stack, uid)
    headers = _enrolment_only(stack, "alice")
    method_id, seed = _enrol(stack, headers)
    methods = dict(_store(stack).methods)
    refused = stack.scraped("auth_enrolments_total", outcome="refused")
    mark = len(stack.audit.records)

    resp = _confirm(stack, headers, method_id, _wrong_code(stack, seed))

    assert (resp.status_code, resp.json()["code"]) == (422, "validation_failed")
    assert [r["action"] for r in stack.audit.records[mark:]] == ["auth.mfa_failed"]
    assert stack.call(_store(stack).find_pending_method, method_id, str(uid)) is not None
    assert (_store(stack).methods, _code_hashes(stack, uid)) == (methods, old_codes)
    assert stack.client.get("/auth/session", headers=headers).status_code == 200
    assert stack.scraped("auth_enrolments_total", outcome="refused") == refused + 1
    assert _confirm(stack, headers, method_id, stack.code(seed)).status_code == 200


def test_confirm_reads_the_user_before_anything_is_written_or_changed(
    stack: Stack, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The user the response shows is read before the audit records and the transaction, so a
    failing identity store cannot leave a committed enrolment without its reply."""
    uid = _must_enrol(stack, "alice")
    old_codes = _code_hashes(stack, uid)
    headers = _enrolment_only(stack, "alice")
    method_id, seed = _enrol(stack, headers)
    mark = len(stack.audit.records)

    async def unavailable(self: _Identity, user_id: str) -> dict[str, Any]:
        raise OSError("identity store unavailable")

    monkeypatch.setattr(_Identity, "user", unavailable)
    resp = _confirm(stack, headers, method_id, stack.code(seed))

    assert resp.status_code == 500
    assert stack.audit.records[mark:] == []
    assert stack.call(_store(stack).find_pending_method, method_id, str(uid)) is not None
    assert _code_hashes(stack, uid) == old_codes


@pytest.mark.parametrize("step", ["revoke_all", "mint"])
def test_confirm_whose_rotation_fails_keeps_the_enrolment_and_answers_503(
    stack: Stack, monkeypatch: pytest.MonkeyPatch, step: str
) -> None:
    """Nothing undoes the commit: a failing revoke-all or mint answers a 503 telling the client to
    sign in again (never a 500), an error log names the user and the sessions, and the new TOTP
    signs in."""
    uid = _must_enrol(stack, "alice")
    token = _sign_in(stack, "alice").json()["tokens"]["access_token"]
    sid = stack.call(stack.auth.sessions.peek_access_token, token).id
    headers = _auth(stack, token)
    method_id, seed = _enrol(stack, headers)
    real = getattr(stack.auth.sessions, step)

    async def unavailable(*_args: Any, **_kwargs: Any) -> Any:
        raise OSError("session store unavailable")

    monkeypatch.setattr(stack.auth.sessions, step, unavailable)
    with structlog.testing.capture_logs() as logs:
        resp = _confirm(stack, headers, method_id, stack.code(seed))
    monkeypatch.setattr(stack.auth.sessions, step, real)

    assert resp.status_code == 503 and "sign in again" in resp.json()["detail"]
    (event,) = [e for e in logs if e["event"] == "auth.enrolment.completed_unrotated"]
    assert (event["log_level"], event["user_id"], event["error"]) == ("error", str(uid), "OSError")
    assert (event["session_id"], event["revoked_session_ids"]) == (str(sid), [str(sid)])
    assert _store(stack).methods[method_id].confirmed_at is not None
    stack.clock.now += timedelta(seconds=30)  # the confirming code is spent
    stack.sign_in("alice", seed)  # asserts 200 for the password and the TOTP step


def test_a_completed_enrolment_is_counted_and_its_revocations_keep_their_reason(
    stack: Stack,
) -> None:
    _must_enrol(stack, "alice")
    headers = _enrolment_only(stack, "alice")
    method_id, seed = _enrol(stack, headers)
    completed = stack.scraped("auth_enrolments_total", outcome="completed")
    revoked = _revocations("mfa_enrolled")

    assert _confirm(stack, headers, method_id, stack.code(seed)).status_code == 200
    assert stack.scraped("auth_enrolments_total", outcome="completed") == completed + 1
    assert _revocations("mfa_enrolled") == revoked + 1  # the caller's own: rotated


def test_after_a_recovery_sign_in_the_old_method_can_never_be_confirmed_again(
    stack: Stack,
) -> None:
    """The #2295 DoR finding: the recovery sign-in revokes the old method for good (#2344), so
    its seed (the lost device) never satisfies the forced re-enrolment."""
    uid, old_seed = stack.add_user("alice")
    (old_id,) = [k for k, m in _store(stack).methods.items() if m.user_id == uid]
    signed_in = _recover(stack, _challenge(stack, "alice"), _codes(stack, uid)[0])
    headers = _auth(stack, signed_in.json()["tokens"]["access_token"])

    resp = _confirm(stack, headers, old_id, stack.code(old_seed))

    assert (resp.status_code, resp.json()["code"]) == (422, "validation_failed")
    assert _store(stack).methods[old_id].revoked_at is not None


# -- POST /auth/mfa/recovery (#2344) -------------------------------------------------------------


def test_regression_a_recovery_sign_in_mints_an_enrolment_only_session_that_re_enrols(
    stack: Stack,
) -> None:
    """The lockout on #2344: the recovery answered 200 with no session, token or cookie, yet it
    spent the code and dropped the TOTP. It now mints the enrolment-only session (15 minutes,
    never a full one), which enrols and confirms a new TOTP that then signs in."""
    uid, _ = stack.add_user("alice")
    codes = _codes(stack, uid)

    resp = _recover(stack, _challenge(stack, "alice"), codes[0])

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert (body["status"], set(body)) == ("authenticated", {"status", "tokens", "user"})
    assert (body["user"]["mfa_required"], body["user"]["mfa_enabled"]) == (True, False)
    assert (body["tokens"]["refresh_expires_in"], body["tokens"]["refresh_token"]) == (900, None)
    cookies = resp.headers.get_list("set-cookie")
    for name in ("cv_refresh=", "__Host-cv_csrf="):
        assert [c for c in cookies if c.startswith(name) and "Max-Age=900" in c], name
    record = stack.call(stack.auth.sessions.peek_access_token, body["tokens"]["access_token"])
    assert (record.user_id, record.mfa_satisfied_at) == (uid, None)
    assert record.expires_at - record.issued_at == timedelta(minutes=15)
    headers = _auth(stack, body["tokens"]["access_token"])
    method_id, seed = _enrol(stack, headers)
    assert _confirm(stack, headers, method_id, stack.code(seed)).status_code == 200
    stack.clock.now += timedelta(seconds=30)  # the confirming code is spent
    stack.sign_in("alice", seed)  # asserts 200 for the password and the TOTP step


def test_recovery_revokes_every_method_and_session_audited_before_any_change(
    stack: Stack,
) -> None:
    """Contract `authMfaRecovery`: the code is spent, every MFA method is revoked for good and
    every other session ends (reason `mfa_recovery`), each named by a record written first."""
    uid, seed = stack.add_user("alice")
    codes = _codes(stack, uid)
    before = [_auth(stack, stack.sign_in("alice", seed).json()["tokens"]["access_token"])]
    before.append(_auth(stack, stack.sign_in("alice", seed).json()["tokens"]["access_token"]))
    old_sessions = _live(stack, uid)
    revoked = _revocations("mfa_recovery")
    token = _challenge(stack, "alice")
    mark = len(stack.audit.records)

    resp = _recover(stack, token, codes[0])

    assert resp.status_code == 200, resp.text
    written = stack.audit.records[mark:]
    assert [r["action"] for r in written] == _RECOVERY
    used, *ended, created = written
    assert (used["actor_user_id"], used["severity"]) == (uid, Severity.WARNING)
    assert {r["session_id"] for r in ended} == old_sessions
    assert {r["reason"] for r in ended} == {"mfa_recovery"}
    access = resp.json()["tokens"]["access_token"]
    minted = stack.call(stack.auth.sessions.peek_access_token, access)
    assert created["session_id"] == used["session_id"] == minted.id
    assert created["after_state"] == {
        "enrolment_only": True,
        "mfa_method": "recovery_code",
        "mfa_satisfied": False,
    }
    assert _live(stack, uid) == {minted.id}
    for dead in before:
        assert stack.client.get("/auth/session", headers=dead).status_code == 401
    assert all(m.revoked_at is not None for m in _store(stack).methods.values())
    assert _unused(stack, uid) == len(codes) - 1
    assert _revocations("mfa_recovery") == revoked + 2


@pytest.mark.parametrize("failing", sorted(set(_RECOVERY)))
def test_recovery_changes_nothing_when_an_audit_record_cannot_be_written(
    stack: Stack, monkeypatch: pytest.MonkeyPatch, failing: str
) -> None:
    """Write-ahead (C-2.9): a record that cannot be written spends no code, revokes nothing and
    mints nothing, so the same challenge and code still sign in once the sink is back."""
    uid, seed = stack.add_user("alice")
    codes = _codes(stack, uid)
    live = _auth(stack, stack.sign_in("alice", seed).json()["tokens"]["access_token"])
    methods, sessions = dict(_store(stack).methods), _live(stack, uid)
    token = _challenge(stack, "alice")
    emit = stack.audit.emit
    _fail_on(stack, monkeypatch, failing)

    resp = _recover(stack, token, codes[0])

    assert (resp.status_code, resp.json()["detail"]) == (401, "audit sink not active")
    assert (_unused(stack, uid), _store(stack).methods) == (len(codes), methods)
    assert _live(stack, uid) == sessions
    assert stack.client.get("/auth/session", headers=live).status_code == 200
    monkeypatch.setattr(stack.audit, "emit", emit)
    assert _recover(stack, token, codes[0]).status_code == 200


def test_replaying_a_spent_code_or_challenge_is_refused_and_changes_nothing(
    stack: Stack,
) -> None:
    """Single use: once a code signed in, neither its challenge nor another open challenge of the
    user accepts it again, and the session it minted is untouched."""
    uid, _ = stack.add_user("alice")
    codes = _codes(stack, uid)
    first, second = _challenge(stack, "alice"), _challenge(stack, "alice")
    signed_in = _recover(stack, first, codes[0])
    assert signed_in.status_code == 200, signed_in.text
    headers = _auth(stack, signed_in.json()["tokens"]["access_token"])
    sessions, mark = _live(stack, uid), len(stack.audit.records)

    replays = [_recover(stack, first, codes[0]), _recover(stack, second, codes[0])]

    assert [(r.status_code, r.json()["detail"]) for r in replays] == [_RECOVERY_REFUSED] * 2
    assert [r["action"] for r in stack.audit.records[mark:]] == ["auth.mfa_failed"] * 2
    assert (_unused(stack, uid), _live(stack, uid)) == (len(codes) - 1, sessions)
    assert stack.client.get("/auth/session", headers=headers).status_code == 200


def test_wrong_codes_are_throttled_and_past_the_cap_even_the_right_one_is_refused(
    stack: Stack,
) -> None:
    """Each wrong code counts toward the challenge's cap (the login lockout's 5), so guessing
    costs a password sign-in per five tries; past the cap the right code is refused unspent."""
    uid, _ = stack.add_user("alice")
    codes = _codes(stack, uid)
    token, mark = _challenge(stack, "alice"), len(stack.audit.records)

    wrong = [_recover(stack, token, "0000-0000-0000-0000") for _ in range(CHALLENGE_ATTEMPT_CAP)]
    locked = _recover(stack, token, codes[0])

    answers = {(r.status_code, r.json()["detail"]) for r in (*wrong, locked)}
    assert answers == {_RECOVERY_REFUSED}
    assert [r["action"] for r in stack.audit.records[mark:]] == ["auth.mfa_failed"] * 6
    assert (_unused(stack, uid), _live(stack, uid)) == (len(codes), set())
    assert _recover(stack, _challenge(stack, "alice"), codes[0]).status_code == 200


def test_forbidden_an_owners_recovery_session_may_only_enrol(
    stack: Stack, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Every role may recover, and no role's recovery session escapes the allow-list."""
    uid, _ = stack.add_user("boss")

    async def owner(self: _Identity, user_id: str) -> dict[str, Any]:
        return {"id": user_id, "username": "boss", "roles": ["owner"], "status": "active"}

    monkeypatch.setattr(_Identity, "user", owner)
    resp = _recover(stack, _challenge(stack, "boss"), _codes(stack, uid)[0])
    headers = _auth(stack, resp.json()["tokens"]["access_token"])

    sessions = stack.client.get("/auth/sessions", headers=headers)
    info = stack.client.get("/auth/session", headers=headers)

    assert (resp.status_code, resp.json()["user"]["roles"]) == (200, ["owner"])
    assert (sessions.status_code, sessions.json()["code"]) == (403, "mfa_enrollment_required")
    assert (info.status_code, info.json()["permissions"]) == (200, [])
    assert len(stack.audit.of("auth.mfa_enrollment_required")) == 1


def test_forbidden_a_user_without_mfa_required_spends_and_mints_nothing(stack: Stack) -> None:
    """C-12.2 forbids the state, so the contract fails it closed: a valid code is refused like a
    wrong one, unspent, and no method or session changes."""
    uid, _ = stack.add_user("alice")
    codes = _codes(stack, uid)
    token = _challenge(stack, "alice")  # issued while MFA was required
    stack.users.add(stack.users.users[str(uid)].model_copy(update={"mfa_required": False}))
    methods, mark = dict(_store(stack).methods), len(stack.audit.records)

    resp = _recover(stack, token, codes[0])

    assert (resp.status_code, resp.json()["detail"]) == _RECOVERY_REFUSED
    outcomes = [(r["action"], r["outcome"]) for r in stack.audit.records[mark:]]
    assert outcomes == [("auth.mfa_failed", AuditOutcome.DENIED)]
    unchanged = (_unused(stack, uid), _store(stack).methods, _live(stack, uid))
    assert unchanged == (len(codes), methods, set())


def test_cross_user_another_users_code_is_refused_and_only_the_callers_sessions_end(
    stack: Stack,
) -> None:
    """A code is checked against the challenge's own user only, and a session credential of
    another user carried into the recovery is audited, never adopted and never revoked."""
    alice, _ = stack.add_user("alice")
    bob, bob_seed = stack.add_user("bob")
    alice_codes, bob_codes = _codes(stack, alice), _codes(stack, bob)
    bob_token = stack.sign_in("bob", bob_seed).json()["tokens"]["access_token"]
    bob_methods = {k: m for k, m in _store(stack).methods.items() if m.user_id == bob}
    token = _challenge(stack, "alice")

    crossed = _recover(stack, token, bob_codes[0])
    carried = _recover(
        stack, token, alice_codes[0], headers={"Authorization": f"Bearer {bob_token}"}
    )

    assert (crossed.status_code, crossed.json()["detail"]) == _RECOVERY_REFUSED
    assert carried.status_code == 200, carried.text
    minted = stack.call(
        stack.auth.sessions.peek_access_token, carried.json()["tokens"]["access_token"]
    )
    assert minted.user_id == alice
    (attempt,) = stack.audit.of("auth.session_fixation_attempt")
    assert (attempt["reason"], attempt["after_state"]["stage"]) == (
        "foreign_session",
        "mfa_recovery",
    )
    assert (_unused(stack, alice), _unused(stack, bob)) == (len(alice_codes) - 1, len(bob_codes))
    assert stack.client.get("/auth/session", headers=_auth(stack, bob_token)).status_code == 200
    assert {k: m for k, m in _store(stack).methods.items() if m.user_id == bob} == bob_methods


def test_cross_user_a_carried_session_that_cannot_be_audited_spends_and_mints_nothing(
    stack: Stack, monkeypatch: pytest.MonkeyPatch
) -> None:
    """U6/SR-013, write-ahead: the fixation record comes before anything changes."""
    alice, _ = stack.add_user("alice")
    _, bob_seed = stack.add_user("bob")
    codes = _codes(stack, alice)
    bob_token = stack.sign_in("bob", bob_seed).json()["tokens"]["access_token"]
    token = _challenge(stack, "alice")
    _fail_on(stack, monkeypatch, "auth.session_fixation_attempt")

    resp = _recover(stack, token, codes[0], headers={"Authorization": f"Bearer {bob_token}"})

    assert (resp.status_code, resp.json()["detail"]) == (401, "audit sink not active")
    assert (_unused(stack, alice), _live(stack, alice)) == (len(codes), set())
    assert stack.audit.of("auth.recovery_code_used") == []


def test_a_recovery_that_loses_the_race_for_its_code_changes_nothing(
    stack: Stack, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A concurrent request spent the code or satisfied the challenge after the check: the
    transaction rolls back, the answer is the uniform 401 and `auth.mfa_failed` follows the
    write-ahead records, naming the session and the revocations they announced and it voids
    (C-2.9); the user keeps every method, session and code."""
    uid, seed = stack.add_user("alice")
    codes = _codes(stack, uid)
    live = _auth(stack, stack.sign_in("alice", seed).json()["tokens"]["access_token"])
    methods, token = dict(_store(stack).methods), _challenge(stack, "alice")

    async def lost(user_id: str, *, challenge_id: str, code_id: str, now: Any) -> bool:
        return False  # what the conditional updates answer once another request won

    monkeypatch.setattr(_store(stack), "complete_recovery", lost)
    mark = len(stack.audit.records)

    resp = _recover(stack, token, codes[0])

    assert (resp.status_code, resp.json()["detail"]) == _RECOVERY_REFUSED
    written = stack.audit.records[mark:]
    assert [r["action"] for r in written] == [
        "auth.recovery_code_used",
        "auth.session_revoked",
        "auth.session_created",
        "auth.mfa_failed",
    ]
    _, revoked, created, failed = written
    assert (failed["actor_user_id"], failed["session_id"]) == (uid, created["session_id"])
    assert (failed["outcome"], failed["reason"]) == (AuditOutcome.FAILURE, "lost_race")
    assert failed["after_state"] == {
        "voids_session_created": str(created["session_id"]),
        "voids_session_revoked": [str(revoked["session_id"])],
    }
    assert (_unused(stack, uid), _store(stack).methods) == (len(codes), methods)
    assert stack.client.get("/auth/session", headers=live).status_code == 200


def test_recovery_reads_the_user_before_anything_is_written_or_spent(
    stack: Stack, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The user the response shows is read before the audit records and the transaction, so a
    failing identity store writes nothing and spends nothing: the same challenge and code then
    sign in."""
    uid, _ = stack.add_user("alice")
    codes = _codes(stack, uid)
    methods, token = dict(_store(stack).methods), _challenge(stack, "alice")
    real, mark = _Identity.user, len(stack.audit.records)

    async def unavailable(self: _Identity, user_id: str) -> dict[str, Any]:
        raise OSError("identity store unavailable")

    monkeypatch.setattr(_Identity, "user", unavailable)
    resp = _recover(stack, token, codes[0])
    monkeypatch.setattr(_Identity, "user", real)

    assert resp.status_code == 500
    assert stack.audit.records[mark:] == []
    assert (_unused(stack, uid), _store(stack).methods) == (len(codes), methods)
    assert _recover(stack, token, codes[0]).status_code == 200


@pytest.mark.parametrize("step", ["revoke_all", "mint_enrolment_only"])
def test_recovery_whose_session_step_fails_keeps_the_commit_and_says_sign_in_again(
    stack: Stack, monkeypatch: pytest.MonkeyPatch, step: str
) -> None:
    """Nothing undoes the commit: a failing revoke-all or mint answers the documented 401 telling
    the client to sign in again with the password (never a bare 500), and an error log names the
    user and the sessions. The code stays spent and every method revoked, so the password alone
    then signs in, enrolment-only."""
    uid, seed = stack.add_user("alice")
    codes = _codes(stack, uid)
    live = stack.sign_in("alice", seed).json()["tokens"]["access_token"]
    live_id = stack.call(stack.auth.sessions.peek_access_token, live).id
    token, mark = _challenge(stack, "alice"), len(stack.audit.records)
    real = getattr(stack.auth.sessions, step)

    async def unavailable(*_args: Any, **_kwargs: Any) -> Any:
        raise OSError("session store unavailable")

    monkeypatch.setattr(stack.auth.sessions, step, unavailable)
    with structlog.testing.capture_logs() as logs:
        resp = _recover(stack, token, codes[0])
    monkeypatch.setattr(stack.auth.sessions, step, real)

    assert resp.status_code == 401
    assert "sign in again with your password" in resp.json()["detail"]
    (event,) = [e for e in logs if e["event"] == "auth.recovery.completed_unminted"]
    assert (event["log_level"], event["user_id"], event["error"]) == ("error", str(uid), "OSError")
    created = stack.audit.records[mark:][-1]
    assert (event["new_session_id"], event["revoked_session_ids"]) == (
        str(created["session_id"]),
        [str(live_id)],
    )
    assert _unused(stack, uid) == len(codes) - 1
    assert all(m.revoked_at is not None for m in _store(stack).methods.values())
    replayed = _recover(stack, token, codes[0])
    assert (replayed.status_code, replayed.json()["detail"]) == _RECOVERY_REFUSED
    signed_in = _sign_in(stack, "alice")
    assert (signed_in.status_code, signed_in.json()["tokens"]["refresh_expires_in"]) == (200, 900)


def test_a_session_the_plan_missed_is_revoked_with_its_own_record(
    stack: Stack, monkeypatch: pytest.MonkeyPatch
) -> None:
    """C-2.9: a session the write-ahead records could not name (minted between the plan and the
    revoke-all, by a concurrent sign-in) ends with the others and gets its own
    `auth.session_revoked`, marked unplanned."""
    uid, seed = stack.add_user("alice")
    codes = _codes(stack, uid)
    first, second = (
        stack.sign_in("alice", seed).json()["tokens"]["access_token"] for _ in range(2)
    )
    planned, late = (
        stack.call(stack.auth.sessions.peek_access_token, t).id for t in (first, second)
    )
    token, listed = _challenge(stack, "alice"), stack.auth.sessions.list_sessions

    async def without_the_late_one(user_id: str, **kwargs: Any) -> tuple[Any, ...]:
        return tuple(view for view in await listed(user_id, **kwargs) if view.id != late)

    monkeypatch.setattr(stack.auth.sessions, "list_sessions", without_the_late_one)
    mark = len(stack.audit.records)
    resp = _recover(stack, token, codes[0])
    monkeypatch.setattr(stack.auth.sessions, "list_sessions", listed)

    assert resp.status_code == 200, resp.text
    written = stack.audit.records[mark:]
    assert [r["action"] for r in written] == [
        "auth.recovery_code_used",
        "auth.session_revoked",
        "auth.session_created",
        "auth.session_revoked",
    ]
    assert (written[1]["session_id"], written[1]["after_state"]) == (planned, None)
    unplanned = written[-1]
    assert (unplanned["session_id"], unplanned["actor_user_id"]) == (late, uid)
    assert (unplanned["reason"], unplanned["after_state"]) == ("mfa_recovery", {"unplanned": True})
    assert _live(stack, uid) == {written[2]["session_id"]}


def test_an_owners_recovery_sign_in_moves_the_series_an_alert_pages_on(
    stack: Stack, monkeypatch: pytest.MonkeyPatch
) -> None:
    """U33 (RR-15): the enrolment-only session a recovery mints is counted under `role="owner"`,
    like the password-only sign-in's, so the series the runbook watches sees it."""
    uid, _ = stack.add_user("boss")
    codes, token = _codes(stack, uid), _challenge(stack, "boss")

    async def owner(self: _Identity, user_id: str) -> dict[str, Any]:
        return {"id": user_id, "username": "boss", "roles": ["owner"], "status": "active"}

    monkeypatch.setattr(_Identity, "user", owner)
    before = stack.scraped("auth_enrolment_only_sessions_total", role="owner")

    assert _recover(stack, token, codes[0]).status_code == 200
    assert stack.scraped("auth_enrolment_only_sessions_total", role="owner") == before + 1


def test_recovery_never_logs_or_echoes_the_code_or_tokens(
    stack: Stack, caplog: pytest.LogCaptureFixture
) -> None:
    """C-12.6: no recovery code (as typed, normalised, wrong or truncated), challenge token or
    minted credential reaches a log event, on success, a wrong code, a locked challenge or a
    malformed request, nor any refusal body."""
    uid, _ = stack.add_user("alice")
    codes, locked = _codes(stack, uid), _challenge(stack, "alice")
    wrong, short = "WRNG-LEAK-CANARY-7Q", codes[0][:7]
    caplog.set_level(logging.DEBUG)

    with structlog.testing.capture_logs() as logs:
        refusals = [_recover(stack, locked, wrong) for _ in range(CHALLENGE_ATTEMPT_CAP)]
        refusals += [_recover(stack, locked, codes[0]), _recover(stack, locked, short)]
        token = _challenge(stack, "alice")
        signed_in = _recover(stack, token, codes[0])

    assert [r.status_code for r in refusals] == [401] * (CHALLENGE_ATTEMPT_CAP + 1) + [422]
    assert signed_in.status_code == 200, signed_in.text
    secrets = {
        "code": codes[0],
        "normalised_code": normalize_recovery_code(codes[0]),
        "wrong_code": wrong,
        "truncated_code": short,
        "locked_mfa_token": locked,
        "mfa_token": token,
        "access_token": signed_in.json()["tokens"]["access_token"],
        "refresh_cookie": signed_in.cookies["cv_refresh"],
        "csrf_cookie": signed_in.cookies["__Host-cv_csrf"],
    }
    texts = [json.dumps(logs, default=str), caplog.text, *(r.text for r in refusals)]
    assert [name for name, value in secrets.items() if any(value in t for t in texts)] == []


# -- the enrolment-only session's own operations -------------------------------------------------


def test_session_info_grants_nothing_and_refresh_counts_down(stack: Stack) -> None:
    _must_enrol(stack, "alice")
    resp = _sign_in(stack, "alice")
    raw_refresh = resp.cookies["cv_refresh"]
    access = resp.json()["tokens"]["access_token"]
    info = stack.client.get("/auth/session", headers=_auth(stack, access))
    stack.clock.now += timedelta(minutes=5)
    stack.client.cookies.clear()  # no SR-041 cookie: the session read re-issues it
    reissued = stack.client.get("/auth/session", headers={"Authorization": f"Bearer {access}"})
    sid = stack.call(stack.auth.sessions.peek_refresh, raw_refresh).id

    refreshed = stack.client.post(
        "/auth/refresh",
        headers=csrf_headers(stack.state.csrf_codec, sid),
        json={"refresh_token": raw_refresh},
    )

    grants = ("permissions", "account_scope", "allowed_environments")
    assert [info.json()[k] for k in grants] == [[], [], []]
    assert "kill_switch" not in info.json()
    assert "__Host-cv_csrf=" in reissued.headers["set-cookie"]
    assert "Max-Age=600" in reissued.headers["set-cookie"]  # Q7: never the 12 h of a full one
    assert refreshed.json()["tokens"]["refresh_expires_in"] == 600
    assert "Max-Age=600" in refreshed.headers["set-cookie"]


def _fail_on(stack: Stack, monkeypatch: pytest.MonkeyPatch, action: str) -> None:
    """The audit sink refuses *action*, as `AuditWriter.emit` does when it cannot append."""
    emit = stack.audit.emit

    async def failing(name: str, **kw: Any) -> None:
        if name == action:
            raise AuditError(f"{name}: sink unavailable")
        await emit(name, **kw)

    monkeypatch.setattr(stack.audit, "emit", failing)

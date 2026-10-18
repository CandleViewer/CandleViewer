"""Enrolment-only session endpoints on the composed app (#2295; contract #2661).

Real `create_app()` over the in-memory auth stack of `_stack.py`, with a user store that derives
each user's confirmed methods from the MFA store on every read, as the SQL does
(`users_sqlalchemy._FIND_SQL`), so a reset shows at once. Covers the sign-in that mints the
session (Q6), its audit records written before it exists, and what the session itself may read:
no grants, and a refresh that counts down to its unchanged expiry (Q7).
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from datetime import timedelta
from typing import Any

import pytest

from candleviewer.audit.errors import AuditError
from candleviewer.auth.errors import UserDisabled
from candleviewer.auth.models import UserRecord
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


# -- POST /auth/login (Q6, Q7) ------------------------------------------------------------------


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


def test_sign_in_of_a_user_disabled_since_the_password_check_mints_nothing_and_is_403(
    stack: Stack, monkeypatch: pytest.MonkeyPatch
) -> None:
    """#2911: the mint refuses a user disabled after the password check. Login's answer for a
    disabled account, never a 500; nothing is minted, and the refusal is audited and counted
    (SR-125) like login's."""
    uid = _must_enrol(stack, "alice")
    fails = stack.scraped("auth_login_failures_total", method="password")

    async def disabled(*_args: Any, **_kwargs: Any) -> Any:
        raise UserDisabled("disabled")

    monkeypatch.setattr(stack.auth.sessions, "mint", disabled)
    resp = _sign_in(stack, "alice")

    assert (resp.status_code, resp.json()["title"]) == (403, "Account disabled")
    assert "set-cookie" not in resp.headers
    assert stack.call(stack.auth.sessions.list_sessions, str(uid)) == ()
    (refused,) = stack.audit.of("auth.login_failed")
    assert (refused["reason"], refused["actor_user_id"]) == ("user_disabled", uid)
    assert stack.scraped("auth_login_failures_total", method="password") == fails + 1


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
    """U34 (RR-15): an Owner's password-only session is counted under `role="owner"`."""
    _must_enrol(stack, "boss")

    async def owner(self: _Identity, user_id: str) -> dict[str, Any]:
        return {"id": user_id, "username": "boss", "roles": ["owner"], "status": "active"}

    monkeypatch.setattr(_Identity, "user", owner)
    before = stack.scraped("auth_enrolment_only_sessions_total", role="owner")

    assert _sign_in(stack, "boss").status_code == 200
    assert stack.scraped("auth_enrolment_only_sessions_total", role="owner") == before + 1


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


def test_session_info_by_cookie_alone_refuses_a_session_not_minted_enrolment_only(
    stack: Stack,
) -> None:
    """#3214: `GET /auth/session` also finds its session by the `cv_refresh` cookie alone, past
    the enrolment guard. A full session whose user then lost every method was not minted
    enrolment-only: it gets the expired 401 there too, as its bearer does, and no user data."""
    uid, seed = stack.add_user("alice")
    refresh = stack.sign_in("alice", seed).cookies["cv_refresh"]
    store = _store(stack)
    for mid, m in list(store.methods.items()):  # a recovery sign-in or a reset since
        if m.user_id == uid:
            store.methods[mid] = m.model_copy(update={"revoked_at": stack.clock.now})
    stack.client.cookies.clear()

    resp = stack.client.get("/auth/session", headers={"Cookie": f"cv_refresh={refresh}"})

    assert resp.status_code == 401 and "user" not in resp.json()


def _fail_on(stack: Stack, monkeypatch: pytest.MonkeyPatch, action: str) -> None:
    """The audit sink refuses *action*, as `AuditWriter.emit` does when it cannot append."""
    emit = stack.audit.emit

    async def failing(name: str, **kw: Any) -> None:
        if name == action:
            raise AuditError(f"{name}: sink unavailable")
        await emit(name, **kw)

    monkeypatch.setattr(stack.audit, "emit", failing)

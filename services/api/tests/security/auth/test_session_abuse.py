"""E09-X02 session abuse cases (AC-SES-*): fixation, rotation, refresh reuse, expiry."""

from __future__ import annotations

import os
import uuid
from collections.abc import Iterator
from datetime import timedelta

import pytest

from candleviewer.api.sessions import REFRESH_COOKIE
from candleviewer.audit.models import AuditOutcome, Severity
from candleviewer.auth.errors import (
    RefreshReuseDetected,
    SessionNotFound,
    SessionRevoked,
)
from candleviewer.auth.hashing import Hasher
from candleviewer.auth.session_service import ACCESS_TOKEN_TTL, SessionService
from tests.unit.auth.session_fakes import FakeSessionRepository

from ._kit import Clock
from ._stack import ORIGIN, PW, Stack, open_stack

_FIXATION = "auth.session_fixation_attempt"


def _svc() -> tuple[SessionService, FakeSessionRepository, Clock]:
    repo, clock = FakeSessionRepository(), Clock()
    return SessionService(repo, Hasher(pepper=os.urandom(8).hex()), clock=clock), repo, clock


@pytest.fixture
def stack(monkeypatch: pytest.MonkeyPatch) -> Iterator[Stack]:
    with open_stack(monkeypatch) as s:
        yield s


def _present(stack: Stack, token: str) -> tuple[int, int]:
    """Present *token* as the bearer and as the `cv_refresh` cookie (allowed Origin)."""
    stack.client.cookies.clear()
    bearer = stack.client.get("/auth/session", headers={"Authorization": f"Bearer {token}"})
    cookie = {"Cookie": f"{REFRESH_COOKIE}={token}", "Origin": ORIGIN}
    return bearer.status_code, stack.client.post("/auth/refresh", headers=cookie).status_code


def _session_id(stack: Stack, access_token: str) -> str:
    stack.client.cookies.clear()
    r = stack.client.get("/auth/session", headers={"Authorization": f"Bearer {access_token}"})
    assert r.status_code == 200, r.text
    return str(r.json()["session"]["id"])


def test_ac_ses_01_planted_session_refused_after_password_and_mfa_and_audited(
    stack: Stack,
) -> None:  # U6 / SR-013, X02 AC2
    _, seed = stack.add_user("victim")
    planted = "attacker-planted-" + "p" * 40  # chosen by the attacker, never issued here
    carried = {"Cookie": f"{REFRESH_COOKIE}={planted}"}
    before = stack.scraped("auth_session_fixation_attempts_total", reason="unknown_token")
    stack.client.cookies.clear()
    pw = stack.client.post(
        "/auth/login", headers=carried, json={"identifier": "victim", "password": PW}
    )
    assert pw.status_code == 200, pw.text
    assert REFRESH_COOKIE not in pw.cookies  # the password step mints no session
    challenge = str(pw.json()["mfa_token"])
    assert _present(stack, planted) == (401, 401)  # after the password step
    body = {"mfa_token": challenge, "method": "totp", "code": stack.code(seed)}
    mfa = stack.client.post("/auth/mfa/verify", headers=carried, json=body)
    assert mfa.status_code == 200, mfa.text
    assert _present(stack, planted) == (401, 401)  # after the MFA step
    issued = str(mfa.json()["tokens"]["access_token"])
    sid = _session_id(stack, issued)
    assert len({sid, challenge, planted, issued}) == 4  # a new id, never the planted one
    assert mfa.cookies.get(REFRESH_COOKIE) not in (None, planted)
    assert stack.call(stack.auth.sessions.peek_refresh, planted) is None  # never adopted
    rows = stack.audit.of(_FIXATION)
    assert [(r["after_state"]["vector"], r["after_state"].get("stage")) for r in rows] == [
        ("bearer", None),
        ("refresh_cookie", None),
        ("refresh_cookie", "mfa_verify"),
        ("bearer", None),
        ("refresh_cookie", None),
    ]
    assert {(r["reason"], r["outcome"], r["severity"]) for r in rows} == {
        ("unknown_token", AuditOutcome.DENIED, Severity.WARNING)
    }
    assert planted not in repr(stack.audit.records)  # the token itself is never recorded
    after = stack.scraped("auth_session_fixation_attempts_total", reason="unknown_token")
    assert after - before == len(rows)


def test_ac_ses_01b_relogin_gets_new_id_and_own_carried_session_is_not_an_attempt(
    stack: Stack,
) -> None:  # SR-013: a new id on every authentication
    _, seed = stack.add_user("owner1")
    first = stack.sign_in("owner1", seed)
    access = str(first.json()["tokens"]["access_token"])
    own = {
        "Cookie": f"{REFRESH_COOKIE}={first.cookies.get(REFRESH_COOKIE)}",
        "Authorization": f"Bearer {access}",
    }
    second = stack.sign_in("owner1", seed, own)
    again = str(second.json()["tokens"]["access_token"])
    assert again != access and _session_id(stack, again) != _session_id(stack, access)
    assert stack.audit.of(_FIXATION) == []


def test_ac_ses_01c_attackers_own_session_carried_into_victims_mfa_is_audited(
    stack: Stack,
) -> None:  # session donation: a foreign session is never adopted
    _, attacker_seed = stack.add_user("mallory")
    victim, victim_seed = stack.add_user("victim")
    donor = stack.sign_in("mallory", attacker_seed)
    donated = {"Cookie": f"{REFRESH_COOKIE}={donor.cookies.get(REFRESH_COOKIE)}"}
    mine = stack.sign_in("victim", victim_seed, donated)
    donor_sid = _session_id(stack, str(donor.json()["tokens"]["access_token"]))
    assert _session_id(stack, str(mine.json()["tokens"]["access_token"])) != donor_sid
    (row,) = stack.audit.of(_FIXATION)
    assert (row["reason"], row["after_state"]["presented_session_id"]) == (
        "foreign_session",
        donor_sid,
    )
    assert row["actor_user_id"] == victim and row["after_state"]["stage"] == "mfa_verify"


async def test_ac_ses_02_every_refresh_issues_new_id_and_token() -> None:  # SR-013
    svc, _, _ = _svc()
    m = await svc.mint(str(uuid.uuid4()))
    nxt = await svc.refresh(m.refresh_token)
    assert nxt.minted.session_id != m.session_id
    assert nxt.minted.refresh_token != m.refresh_token
    assert nxt.minted.access_token != m.access_token


async def test_ac_ses_03_refresh_reuse_revokes_family_and_access_tokens() -> None:
    svc, _, _ = _svc()
    m = await svc.mint(str(uuid.uuid4()))
    live = (await svc.refresh(m.refresh_token)).minted
    with pytest.raises(RefreshReuseDetected):
        await svc.refresh(m.refresh_token)
    with pytest.raises(SessionRevoked):  # the victim's successor is now dead too
        await svc.authenticate_access_token(live.access_token)
    with pytest.raises(SessionRevoked):
        await svc.refresh(live.refresh_token)


async def test_ac_ses_04_refresh_cannot_extend_absolute_lifetime() -> None:
    svc, _repo, _ = _svc()
    m = await svc.mint(str(uuid.uuid4()))
    nxt = await svc.refresh(m.refresh_token)
    assert nxt.minted.expires_at == m.expires_at


async def test_ac_ses_05_access_token_expires_and_revoked_session_refused() -> None:
    svc, _, clock = _svc()
    m = await svc.mint(str(uuid.uuid4()))
    await svc.authenticate_access_token(m.access_token)
    clock.advance(ACCESS_TOKEN_TTL + timedelta(seconds=1))
    with pytest.raises(SessionNotFound):
        await svc.authenticate_access_token(m.access_token)


async def test_ac_ses_06_cookie_replay_from_other_context_accepted_by_design() -> None:
    """DESIGN DECISION TO CONFIRM (not a bug): sessions are not bound to IP/UA, so a stolen
    access token replayed from another address is accepted; detection relies on refresh reuse."""
    svc, _, _ = _svc()
    m = await svc.mint(str(uuid.uuid4()), ip="10.0.0.1", user_agent="victim-ua")
    rec = await svc.authenticate_access_token(m.access_token)  # attacker, no ip/ua presented
    assert rec.id == m.session_id


async def test_ac_ses_07_forged_access_token_rejected() -> None:
    svc, _, _ = _svc()
    await svc.mint(str(uuid.uuid4()))
    for forged in ("", "A" * 43, "../../etc/passwd", "x" * 4096):
        with pytest.raises(SessionNotFound):
            await svc.authenticate_access_token(forged)

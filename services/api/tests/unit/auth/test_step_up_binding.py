"""#2304: a no-grace grant is bound to the challenged request (`StepUpService`): one live
challenge carries the refused request's SHA-256 fingerprint, a no-grace step-up must name it,
and only the identical request can use the 60-second grant it leaves."""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Awaitable, Callable
from datetime import timedelta

import pytest

from candleviewer.auth.errors import (
    SessionReadOnly,
    SessionRevoked,
    StepUpChallengeRefused,
    StepUpCodeInvalid,
    StepUpMismatch,
    StepUpRequired,
)
from candleviewer.auth.models import SessionRecord
from candleviewer.auth.step_up import (
    CHALLENGE_WINDOW,
    READONLY_WINDOW,
    SINGLE_USE_WINDOW,
    StepUpChallenge,
    StepUpGrant,
    StepUpService,
)
from tests.conftest import RecordingAuditSink

from .session_fakes import FakeSessionRepository
from .test_step_up import PASSWORD, _Clock, _code, _sample, _setup

#: Hex SHA-256 fingerprints: the challenged request, and another request of its class.
_A, _B = "a" * 64, "b" * 64


async def _granted(
    svc: StepUpService, clock: _Clock, seed: bytes, user: uuid.UUID, fingerprint: str = _A
) -> tuple[StepUpChallenge, StepUpGrant]:
    challenge = await svc.record_pending("s1", "killswitch", fingerprint=fingerprint)
    code = _code(seed, clock)
    grant = await svc.step_up(
        str(user), "s1", None, code, PASSWORD, challenge_id=challenge.challenge_id
    )
    return challenge, grant


def _grants(sessions: FakeSessionRepository, alias: str = "s1") -> list[str]:
    return sorted(k for k in sessions.sessions[alias].step_up_elevations if k.startswith("once:"))


Act = Callable[[], Awaitable[object]]


def _use_grant(svc: StepUpService) -> Act:
    """The held request (`_A`) executes: it uses its grant."""
    return lambda: svc.consume_single_use("s1", "killswitch", fingerprint=_A)


async def _three_strikes(svc: StepUpService, user: uuid.UUID) -> None:
    """Three wrong codes: the session turns read-only for 5 minutes."""
    for _ in range(2):
        with pytest.raises(StepUpCodeInvalid):
            await svc.step_up(str(user), "s1", "keys", "000000", PASSWORD)
    with pytest.raises(SessionReadOnly):
        await svc.step_up(str(user), "s1", "keys", "000000", PASSWORD)


def _after_next_read(
    monkeypatch: pytest.MonkeyPatch, sessions: FakeSessionRepository, act: Act
) -> None:
    """Run `act` (other requests of the session) right after the next read of the row, so the
    reader decides on a copy the row no longer matches (#2304 security review, round 3)."""
    read, armed = sessions.find_by_id, [True]

    async def read_then_act(session_id: str) -> SessionRecord | None:
        found = await read(session_id)
        if armed:
            armed.clear()
            await act()
        return found

    monkeypatch.setattr(sessions, "find_by_id", read_then_act)


def _before_password_check(monkeypatch: pytest.MonkeyPatch, svc: StepUpService, act: Act) -> None:
    """Run `act` inside the next step-up's Argon2id check, the widest gap between a step-up's
    read of the row and its write."""
    verify, armed = svc._hasher.verify, [True]

    async def act_then_verify(password_hash: str, password: str) -> bool:
        if armed:
            armed.clear()
            await act()
        return await verify(password_hash, password)

    monkeypatch.setattr(svc._hasher, "verify", act_then_verify)


@pytest.mark.parametrize(
    ("cls", "fingerprint"),
    [("killswitch", None), ("live_enablement", None), ("keys", "not-a-sha256")],
)
async def test_challenge_that_cannot_bind_its_request_is_never_issued(
    cls: str, fingerprint: str | None
) -> None:
    svc, *_, sessions = await _setup()
    with pytest.raises(ValueError, match=r"bind the refused request|hex SHA-256"):
        await svc.record_pending("s1", cls, fingerprint=fingerprint)
    assert sessions.sessions["s1"].step_up_elevations == {}


@pytest.mark.parametrize("live", [True, False], ids=["live-challenge", "action-class-only"])
async def test_no_grace_step_up_without_challenge_id_is_refused_before_any_factor(
    live: bool,
) -> None:
    svc, _clock, _seed, user, sessions = await _setup()
    if live:
        await svc.record_pending("s1", "killswitch", fingerprint=_A)
    failures = _sample("auth_stepup_failures_total")
    with pytest.raises(StepUpChallengeRefused) as refused:  # wrong factors: never checked
        await svc.step_up(str(user), "s1", "killswitch", "000000", "wrong password")
    assert (refused.value.field, refused.value.rule) == ("challenge_id", "challenge_required")
    assert sessions.sessions["s1"].step_up_failures == 0 and _grants(sessions) == []
    assert _sample("auth_stepup_failures_total") == failures
    assert svc._users.users[str(user)].failed_login_count == 0  # type: ignore[attr-defined]


async def test_bound_grant_is_used_once_by_the_identical_request() -> None:
    svc, clock, seed, user, sessions = await _setup()
    challenge, grant = await _granted(svc, clock, seed, user)
    assert grant.single_use and SINGLE_USE_WINDOW == timedelta(seconds=60)
    assert grant.elevated_until == clock.now + SINGLE_USE_WINDOW
    assert (grant.challenge_id, grant.fingerprint) == (challenge.challenge_id, _A)
    assert await svc.live_challenge("s1") is None  # the step-up used it
    used = await svc.consume_single_use("s1", "killswitch", fingerprint=_A)
    assert used.challenge_id == challenge.challenge_id and _grants(sessions) == []
    with pytest.raises(StepUpRequired) as again:
        await svc.consume_single_use("s1", "killswitch", fingerprint=_A)
    assert not isinstance(again.value, StepUpMismatch)


async def test_identical_requests_racing_inside_the_window_use_the_grant_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Both re-sends read the row before either writes; one conditional write consumes the
    grant, so exactly one executes and the other is refused as if it had no grant."""
    svc, clock, seed, user, sessions = await _setup()
    await _granted(svc, clock, seed, user)
    read = sessions.find_by_id

    async def interleaved(session_id: str) -> SessionRecord | None:
        found = await read(session_id)
        await asyncio.sleep(0)  # yield to the other request, which reads the same row
        return found

    monkeypatch.setattr(sessions, "find_by_id", interleaved)
    consumers = (svc.consume_single_use("s1", "killswitch", fingerprint=_A) for _ in range(2))
    results = await asyncio.gather(*consumers, return_exceptions=True)
    used = [r for r in results if isinstance(r, StepUpChallenge)]
    refused = [r for r in results if type(r) is StepUpRequired]
    assert (len(used), len(refused)) == (1, 1) and _grants(sessions) == []


async def test_challenge_issued_after_the_grant_is_used_never_restores_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Security review round 3: a request refused while the held one executes writes its
    challenge onto the row as it is, so the grant used meanwhile stays used and the identical
    request cannot execute a second time inside the 60 s."""
    svc, clock, seed, user, sessions = await _setup()
    await _granted(svc, clock, seed, user)
    _after_next_read(monkeypatch, sessions, _use_grant(svc))

    challenge = await svc.record_pending("s1", "killswitch", fingerprint=_B)

    assert _grants(sessions) == [] and await svc.live_challenge("s1") == challenge
    with pytest.raises(StepUpRequired):
        await svc.consume_single_use("s1", "killswitch", fingerprint=_A)


async def test_refused_step_up_while_the_grant_is_used_never_restores_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A wrong password needs no factor: the failure is counted on the row as it is after the
    password check, never on the copy read before it."""
    svc, clock, seed, user, sessions = await _setup()
    await _granted(svc, clock, seed, user)
    _before_password_check(monkeypatch, svc, _use_grant(svc))

    with pytest.raises(StepUpCodeInvalid):
        await svc.step_up(str(user), "s1", "keys", "000000", "wrong password")

    assert _grants(sessions) == [] and sessions.sessions["s1"].step_up_failures == 1
    with pytest.raises(StepUpRequired):
        await svc.consume_single_use("s1", "killswitch", fingerprint=_A)


async def test_step_up_of_another_class_while_the_grant_is_used_never_restores_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    svc, clock, seed, user, sessions = await _setup()
    await _granted(svc, clock, seed, user)
    clock.now += timedelta(seconds=31)  # a fresh TOTP step, inside the grant's 60 s
    _before_password_check(monkeypatch, svc, _use_grant(svc))

    grant = await svc.step_up(str(user), "s1", "keys", _code(seed, clock), PASSWORD)

    assert grant.action_class == "keys" and _grants(sessions) == []
    with pytest.raises(StepUpRequired):
        await svc.consume_single_use("s1", "killswitch", fingerprint=_A)


async def test_step_up_of_a_session_downgraded_during_its_check_opens_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Three wrong step-ups land while a correct one is in its password check: the read-only
    downgrade stands, so the correct one is refused and opens no window."""
    svc, clock, seed, user, sessions = await _setup()
    _before_password_check(monkeypatch, svc, lambda: _three_strikes(svc, user))

    with pytest.raises(SessionReadOnly) as refused:
        await svc.step_up(str(user), "s1", "keys", _code(seed, clock), PASSWORD)

    row = sessions.sessions["s1"]
    assert refused.value.until == clock.now + READONLY_WINDOW == row.readonly_until
    assert (row.step_up_elevations, row.step_up_failures) == ({}, 3)


async def test_lifting_a_lapsed_downgrade_keeps_a_challenge_issued_since_its_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    svc, clock, _seed, user, sessions = await _setup()
    await _three_strikes(svc, user)
    clock.now += READONLY_WINDOW
    issued: list[StepUpChallenge] = []

    async def refuse_another_request() -> None:
        issued.append(await svc.record_pending("s1", "users"))

    _after_next_read(monkeypatch, sessions, refuse_another_request)

    await svc.assert_writable("s1")

    row = sessions.sessions["s1"]
    assert (row.step_up_failures, row.readonly_until) == (0, None)
    assert await svc.live_challenge("s1") == issued[0]


async def test_lifting_a_downgrade_renewed_since_its_read_keeps_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Three new strikes land between the read of a lapsed downgrade and its lift: the renewed
    downgrade stands and the request is refused."""
    svc, clock, _seed, user, sessions = await _setup()
    await _three_strikes(svc, user)
    clock.now += READONLY_WINDOW
    _after_next_read(monkeypatch, sessions, lambda: _three_strikes(svc, user))

    with pytest.raises(SessionReadOnly) as refused:
        await svc.assert_writable("s1")

    renewed = sessions.sessions["s1"].readonly_until
    assert refused.value.until == clock.now + READONLY_WINDOW == renewed


async def test_bound_grant_refuses_a_swapped_payload() -> None:
    """AC "Bound single-use grant refuses a swapped payload"; the grant is not used up."""
    svc, clock, seed, user, _ = await _setup()
    challenge, _grant = await _granted(svc, clock, seed, user)
    with pytest.raises(StepUpMismatch) as swapped:
        await svc.consume_single_use("s1", "killswitch", fingerprint=_B)
    mismatch = swapped.value
    assert (mismatch.bound, mismatch.refused, mismatch.action_class) == (_A, _B, "killswitch")
    assert (mismatch.challenge_id, mismatch.user_id) == (str(challenge.challenge_id), str(user))
    await svc.consume_single_use("s1", "killswitch", fingerprint=_A)


async def test_bound_grant_expires_sixty_seconds_after_the_step_up() -> None:
    svc, clock, seed, user, _ = await _setup()
    await _granted(svc, clock, seed, user)
    clock.now += timedelta(seconds=60)
    with pytest.raises(StepUpRequired):
        await svc.consume_single_use("s1", "killswitch", fingerprint=_A)


async def test_newer_step_up_replaces_the_class_grant() -> None:
    svc, clock, seed, user, sessions = await _setup()
    await _granted(svc, clock, seed, user)
    clock.now += timedelta(seconds=31)  # a fresh TOTP step
    challenge, _grant = await _granted(svc, clock, seed, user, _B)
    assert _grants(sessions) == [challenge.key("once:")]  # one grant per no-grace class
    with pytest.raises(StepUpMismatch):
        await svc.consume_single_use("s1", "killswitch", fingerprint=_A)
    await svc.consume_single_use("s1", "killswitch", fingerprint=_B)


async def test_read_only_downgrade_ends_the_grant() -> None:
    svc, clock, seed, user, sessions = await _setup()
    await _granted(svc, clock, seed, user)
    await svc.record_pending("s1", "keys")
    for _ in range(2):
        with pytest.raises(StepUpCodeInvalid):
            await svc.step_up(str(user), "s1", None, "000000", PASSWORD)
    with pytest.raises(SessionReadOnly):
        await svc.step_up(str(user), "s1", None, "000000", PASSWORD)
    assert sessions.sessions["s1"].step_up_elevations == {}
    clock.now += timedelta(minutes=5)
    with pytest.raises(StepUpRequired):
        await svc.consume_single_use("s1", "killswitch", fingerprint=_A)


async def test_bound_grant_is_used_only_by_its_own_session() -> None:
    svc, clock, seed, user, sessions = await _setup()
    await _granted(svc, clock, seed, user)
    with pytest.raises(StepUpRequired) as other:
        await svc.consume_single_use("s2", "killswitch", fingerprint=_A)
    assert not isinstance(other.value, StepUpMismatch)
    await sessions.revoke("s1", reason="logout", now=clock.now)
    with pytest.raises(SessionRevoked):  # logout ends the grant: 401, never a challenge
        await svc.consume_single_use("s1", "killswitch", fingerprint=_A)


@pytest.mark.parametrize(
    "stored",
    ["once:killswitch", f"once:killswitch:{uuid.UUID(int=1)}", "pending:killswitch"],
    ids=["class-only-grant", "grant-without-fingerprint", "class-only-challenge"],
)
async def test_entries_that_bind_no_request_never_elevate(stored: str) -> None:
    svc, clock, _seed, user, sessions = await _setup()
    sessions.sessions["s1"] = sessions.sessions["s1"].model_copy(
        update={"step_up_elevations": {stored: clock.now + timedelta(minutes=1)}}
    )
    with pytest.raises(StepUpRequired):
        await svc.consume_single_use("s1", "killswitch", fingerprint=_A)
    with pytest.raises(StepUpChallengeRefused):
        await svc.step_up(str(user), "s1", "killswitch", "000000", PASSWORD)


async def test_no_grace_challenge_that_binds_nothing_never_elevates() -> None:
    svc, clock, seed, user, sessions = await _setup()
    cid = uuid.uuid4()
    sessions.sessions["s1"] = sessions.sessions["s1"].model_copy(
        update={"step_up_elevations": {f"pending:killswitch:{cid}": clock.now + CHALLENGE_WINDOW}}
    )
    with pytest.raises(StepUpChallengeRefused) as refused:
        await svc.step_up(str(user), "s1", None, _code(seed, clock), PASSWORD, challenge_id=cid)
    assert refused.value.rule == "challenge_required" and _grants(sessions) == []


async def test_granted_audit_names_the_bound_request(b16_audit: RecordingAuditSink) -> None:
    svc, clock, seed, user, _ = await _setup()
    challenge, _grant = await _granted(svc, clock, seed, user)
    required, granted = b16_audit.calls
    assert "bound_request_sha256" not in required["after_state"]
    assert granted["object_id"] == str(challenge.challenge_id)
    assert granted["after_state"]["bound_request_sha256"] == _A

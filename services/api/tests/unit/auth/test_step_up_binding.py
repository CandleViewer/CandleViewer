"""#2304: a no-grace grant is bound to the challenged request (`StepUpService`): one live
challenge carries the refused request's SHA-256 fingerprint, a no-grace step-up must name it,
and only the identical request can use the 60-second grant it leaves."""

from __future__ import annotations

import uuid
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
from candleviewer.auth.step_up import (
    CHALLENGE_WINDOW,
    NO_GRACE_ACTION_CLASSES,
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


@pytest.mark.parametrize("cls", sorted(NO_GRACE_ACTION_CLASSES))
async def test_challenge_that_cannot_bind_its_request_is_never_issued(cls: str) -> None:
    svc, *_, sessions = await _setup()
    with pytest.raises(ValueError, match="bind the refused request"):
        await svc.record_pending("s1", cls)
    assert sessions.sessions["s1"].step_up_elevations == {}


@pytest.mark.parametrize("cls", sorted(NO_GRACE_ACTION_CLASSES))
@pytest.mark.parametrize("live", [True, False], ids=["live-challenge", "action-class-only"])
async def test_no_grace_step_up_without_challenge_id_is_refused_before_any_factor(
    live: bool, cls: str
) -> None:
    svc, _clock, _seed, user, sessions = await _setup()
    if live:
        await svc.record_pending("s1", cls, fingerprint=_A)
    failures = _sample("auth_stepup_failures_total")
    with pytest.raises(StepUpChallengeRefused) as refused:  # wrong factors: never checked
        await svc.step_up(str(user), "s1", cls, "000000", "wrong password")
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
    with pytest.raises(StepUpRequired) as unbound:
        await svc.consume_single_use("s1", "killswitch", fingerprint=_A)
    assert type(unbound.value) is StepUpRequired  # no grant at all, never a mismatch
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

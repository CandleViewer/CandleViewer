"""#2304: every refusal issues a challenge for the request it refused, and `POST /auth/step-up`
answers the live one (`StepUpService`; names follow the ticket's Gherkin and the contract)."""

from __future__ import annotations

import uuid
from datetime import timedelta

import pytest

from candleviewer.auth.errors import (
    SelfResetRefused,
    SessionRevoked,
    StepUpChallengeRefused,
    UnknownActionClass,
)
from candleviewer.auth.step_up import CHALLENGE_WINDOW, StepUpChallenge
from tests.conftest import RecordingAuditSink

from .session_fakes import FakeSessionRepository
from .test_step_up import _T0, PASSWORD, _code, _noop, _sample, _session, _setup


def _keys(sessions: FakeSessionRepository, alias: str = "s1") -> list[str]:
    return sorted(sessions.sessions[alias].step_up_elevations)


async def test_refusal_issues_a_random_session_scoped_challenge_for_five_minutes() -> None:
    svc, clock, *_ = await _setup()
    challenge = await svc.record_pending("s1", "keys")
    assert challenge.challenge_id.version == 4 and challenge.action_class == "keys"
    assert CHALLENGE_WINDOW == timedelta(minutes=5)
    assert challenge.expires_at == clock.now + CHALLENGE_WINDOW
    assert await svc.live_challenge("s1") == challenge
    assert await svc.live_challenge("s2") is None  # scoped to the issuing session


async def test_newer_refusal_supersedes_the_live_challenge() -> None:
    svc, clock, seed, user, sessions = await _setup()
    first = await svc.record_pending("s1", "keys")
    second = await svc.record_pending("s1", "users")
    assert await svc.live_challenge("s1") == second
    assert _keys(sessions) == [second.key()]  # at most one live challenge per session
    with pytest.raises(StepUpChallengeRefused) as refused:
        await svc.step_up(
            str(user), "s1", None, _code(seed, clock), PASSWORD, challenge_id=first.challenge_id
        )
    assert (refused.value.field, refused.value.rule) == ("challenge_id", "challenge_expired")


@pytest.mark.parametrize("stale", ["unknown", "expired", "used", "other-session", "other-user"])
async def test_stale_challenge_id_is_refused_before_any_factor(stale: str) -> None:
    """AC "Challenge expiry": a challenge issued more than 5 minutes ago (or used, unknown, or
    another session's or user's) is refused and counts no failure."""
    svc, clock, seed, user, sessions = await _setup()
    sessions.sessions["t1"] = _session(uuid.uuid4())
    challenge = await svc.record_pending("s1", "keys")
    if stale == "expired":
        clock.now += timedelta(minutes=5, seconds=1)
    if stale == "used":
        code = _code(seed, clock)
        await svc.step_up(
            str(user), "s1", None, code, PASSWORD, challenge_id=challenge.challenge_id
        )
    alias = {"other-session": "s2", "other-user": "t1"}.get(stale, "s1")
    sent = uuid.uuid4() if stale == "unknown" else challenge.challenge_id
    failures = _sample("auth_stepup_failures_total")
    with pytest.raises(StepUpChallengeRefused) as refused:  # wrong code: never checked
        await svc.step_up(str(user), alias, None, "000000", PASSWORD, challenge_id=sent)
    assert (refused.value.field, refused.value.rule) == ("challenge_id", "challenge_expired")
    assert sessions.sessions[alias].step_up_failures == 0
    assert _sample("auth_stepup_failures_total") == failures


@pytest.mark.parametrize("answer", ["challenge-id", "live-challenge", "action-class-only"])
async def test_grace_class_step_up_with_or_without_challenge_id(answer: str) -> None:
    svc, clock, seed, user, sessions = await _setup()
    challenge = None if answer == "action-class-only" else await svc.record_pending("s1", "keys")
    grant = await svc.step_up(
        str(user),
        "s1",
        "keys" if challenge is None else None,
        _code(seed, clock),
        PASSWORD,
        challenge_id=challenge.challenge_id if answer == "challenge-id" and challenge else None,
    )
    assert not grant.single_use and grant.elevated_until == clock.now + timedelta(minutes=5)
    assert grant.challenge_id == (None if challenge is None else challenge.challenge_id)
    assert _keys(sessions) == ["keys"]  # an unbound window; the challenge is used up
    await svc.require_elevation("s1", "keys")


@pytest.mark.parametrize(
    ("live", "sent", "field", "rule"),
    [
        ("keys", "users", "action_class", "challenge_mismatch"),
        ("users", "risk_caps", "action_class", "challenge_mismatch"),
        (None, None, "action_class", "required"),
    ],
)
async def test_action_class_is_only_a_cross_check_of_the_live_challenge(
    live: str | None, sent: str | None, field: str, rule: str
) -> None:
    svc, _clock, _seed, user, sessions = await _setup()
    if live is not None:
        await svc.record_pending("s1", live)
    with pytest.raises(StepUpChallengeRefused) as refused:
        await svc.step_up(str(user), "s1", sent, "000000", PASSWORD)
    assert (refused.value.field, refused.value.rule) == (field, rule)
    assert sessions.sessions["s1"].step_up_failures == 0


async def test_unknown_action_class_fails_closed_without_a_challenge() -> None:
    svc, *_, sessions = await _setup()
    with pytest.raises(UnknownActionClass):
        await svc.require_elevation("s1", "bogus")
    with pytest.raises(UnknownActionClass):
        await svc.record_pending("s1", "bogus")
    assert _keys(sessions) == []


async def test_revoked_session_is_refused_as_revoked_never_challenged() -> None:
    svc, clock, seed, user, sessions = await _setup()
    await sessions.revoke("s1", reason="logout", now=clock.now)
    with pytest.raises(SessionRevoked):
        await svc.record_pending("s1", "keys")
    with pytest.raises(SessionRevoked):
        await svc.step_up(str(user), "s1", "keys", _code(seed, clock), PASSWORD)


async def test_owner_self_reset_is_refused_before_the_elevation_check() -> None:
    svc, _clock, _seed, owner, _ = await _setup()
    with pytest.raises(SelfResetRefused):  # no elevation held: still not a challenge
        await svc.reset_totp(
            actor_session_id="o1", actor_user_id=str(owner), target_user_id=str(owner), audit=_noop
        )


async def test_challenge_written_before_challenge_ids_is_not_live() -> None:
    svc, clock, _seed, user, sessions = await _setup()
    sessions.sessions["s1"] = sessions.sessions["s1"].model_copy(
        update={"step_up_elevations": {"pending:keys": clock.now + timedelta(minutes=1)}}
    )
    assert await svc.live_challenge("s1") is None
    with pytest.raises(StepUpChallengeRefused):
        await svc.step_up(str(user), "s1", None, "000000", PASSWORD)


@pytest.mark.parametrize(
    "key",
    [
        "pending:keys:not-a-uuid",
        f"pending:bogus:{uuid.UUID(int=7)}",
        f"pending:keys:{uuid.UUID(int=7)}:extra",
    ],
    ids=["malformed-id", "unregistered-class", "extra-part"],
)
async def test_malformed_challenge_key_is_not_live_and_never_raises(key: str) -> None:
    svc, clock, _seed, user, sessions = await _setup()
    sessions.sessions["s1"] = sessions.sessions["s1"].model_copy(
        update={"step_up_elevations": {key: clock.now + timedelta(minutes=1)}}
    )
    assert await svc.live_challenge("s1") is None
    with pytest.raises(StepUpChallengeRefused) as refused:  # nothing to answer, no class named
        await svc.step_up(str(user), "s1", None, "000000", PASSWORD)
    assert (refused.value.field, refused.value.rule) == ("action_class", "required")


async def test_challenge_audits_name_the_challenge_never_a_factor(
    b16_audit: RecordingAuditSink,
) -> None:
    svc, clock, seed, user, _ = await _setup()
    challenge = await svc.record_pending("s1", "keys")
    code = _code(seed, clock)
    await svc.step_up(str(user), "s1", None, code, PASSWORD, challenge_id=challenge.challenge_id)
    required, granted = b16_audit.calls
    assert (required["action"], granted["action"]) == (
        "auth.step_up_required",
        "auth.step_up_granted",
    )
    for call in (required, granted):
        assert call["object_kind"] == "step_up_challenge"
        assert call["object_id"] == str(challenge.challenge_id)
    clock.now += timedelta(seconds=31)  # a fresh TOTP step
    await svc.step_up(str(user), "s1", "keys", _code(seed, clock), PASSWORD)  # no challenge
    assert b16_audit.calls[-1]["object_id"] is None
    assert PASSWORD not in repr(b16_audit.calls) and f"'{code}'" not in repr(b16_audit.calls)


async def test_challenge_fingerprint_must_be_a_hex_sha256() -> None:
    svc, *_, sessions = await _setup()
    with pytest.raises(ValueError, match="hex SHA-256"):
        await svc.record_pending("s1", "keys", fingerprint="not-a-sha256")
    assert sessions.sessions["s1"].step_up_elevations == {}


_ID, _SHA = uuid.UUID(int=2), "a" * 64


@pytest.mark.parametrize(
    ("key", "prefix", "parsed"),
    [
        (f"once:killswitch:{_ID}:{_SHA}", "once:", ("killswitch", _SHA)),
        (f"once:killswitch:{_ID}", "once:", None),  # a grant always names its request
        (f"once:keys:{_ID}:{_SHA}", "once:", None),  # a grace class has a window, no grant
        (f"once:killswitch:{_ID}:{'A' * 64}", "once:", None),  # lower-case hex only
        (f"pending:keys:{_ID}", "pending:", ("keys", None)),
        (f"pending:killswitch:{_ID}:{_SHA}", "pending:", ("killswitch", _SHA)),
        (f"pending:bogus:{_ID}", "pending:", None),
        (f"pending:keys:{_ID}", "once:", None),
    ],
)
def test_stored_entry_is_parsed_by_its_key_grammar(
    key: str, prefix: str, parsed: tuple[str, str | None] | None
) -> None:
    until = _T0 + CHALLENGE_WINDOW
    entry = StepUpChallenge.parse(key, until, prefix)
    got = None if entry is None else (entry.action_class, entry.fingerprint)
    assert got == parsed
    assert entry is None or (entry.challenge_id, entry.key(prefix)) == (_ID, key)

"""#2754: the step-up instant the session row still records (`last_step_up_at`).

`StepUpService` stores a grace class's window (`now + GRACE_WINDOW`) under the action class, and
a no-grace class's one-shot grant (`now + SINGLE_USE_WINDOW`) under its bound key (#2304).
`last_step_up_at` reads the instant back out of that record, so the verified principal can carry
it with no further query. These tests drive the real `StepUpService`, `SessionService` and B16
chart over the in-memory session fake."""

from __future__ import annotations

from datetime import timedelta

import pytest

from candleviewer.auth.errors import SessionReadOnly, StepUpCodeInvalid, StepUpRequired
from candleviewer.auth.session_chart import to_us
from candleviewer.auth.session_service import SessionService
from candleviewer.auth.step_up import (
    ACTION_CLASSES,
    GRACE_WINDOW,
    NO_GRACE_ACTION_CLASSES,
    last_step_up_at,
)
from candleviewer.statechart.bindings import b16_session

from .test_step_up import _HASHER, _T0, PASSWORD, _code, _pw_hash, _setup

#: #2304: the SHA-256 of the request a no-grace challenge refused; its grant is bound to it.
_HELD = "a" * 64


async def test_last_step_up_at_is_none_before_any_step_up() -> None:
    _svc, _clock, _seed, _user, sessions = await _setup()
    assert last_step_up_at(sessions.sessions["s1"].step_up_elevations) is None


async def test_last_step_up_at_is_the_step_up_instant_not_the_window_expiry() -> None:
    svc, clock, seed, user, sessions = await _setup()
    clock.now = _T0 + timedelta(seconds=90)
    grant = await svc.step_up(str(user), "s1", "keys", _code(seed, clock), PASSWORD)
    assert grant.elevated_until == clock.now + GRACE_WINDOW  # what the row stores
    assert last_step_up_at(sessions.sessions["s1"].step_up_elevations) == clock.now


async def test_last_step_up_at_follows_the_latest_step_up_of_any_class() -> None:
    svc, clock, seed, user, sessions = await _setup()
    await svc.step_up(str(user), "s1", "keys", _code(seed, clock), PASSWORD)
    clock.now += timedelta(seconds=60)
    await svc.step_up(str(user), "s1", "risk_caps", _code(seed, clock), PASSWORD)
    assert last_step_up_at(sessions.sessions["s1"].step_up_elevations) == clock.now


@pytest.mark.parametrize("action_class", sorted(ACTION_CLASSES))
async def test_last_step_up_at_reads_every_action_class_however_the_row_keys_it(
    action_class: str,
) -> None:
    """Grace classes sit under their name, no-grace classes under their bound `once:` key; a
    class added to `ACTION_CLASSES` is covered here the day it lands."""
    svc, clock, seed, user, sessions = await _setup()
    clock.now = _T0 + timedelta(seconds=40)
    challenge = None
    if action_class in NO_GRACE_ACTION_CLASSES:  # #2304: a fresh code bound to one request
        challenge = await svc.record_pending("s1", action_class, fingerprint=_HELD)
    cid = None if challenge is None else challenge.challenge_id
    await svc.step_up(str(user), "s1", action_class, _code(seed, clock), PASSWORD, challenge_id=cid)
    assert last_step_up_at(sessions.sessions["s1"].step_up_elevations) == clock.now


async def test_a_spent_one_shot_grant_leaves_no_step_up_record_on_the_row() -> None:
    """The row keeps a one-shot grant only until its action spends it, so an age derived from
    the row is `None` from then on (the limit of reading existing state, #2754)."""
    svc, clock, seed, user, sessions = await _setup()
    held = await svc.record_pending("s1", "killswitch", fingerprint=_HELD)
    code = _code(seed, clock)
    await svc.step_up(str(user), "s1", None, code, PASSWORD, challenge_id=held.challenge_id)
    assert last_step_up_at(sessions.sessions["s1"].step_up_elevations) == clock.now
    await svc.consume_single_use("s1", "killswitch", fingerprint=_HELD)
    assert last_step_up_at(sessions.sessions["s1"].step_up_elevations) is None


async def test_a_token_refresh_starts_the_successor_row_without_a_step_up_record() -> None:
    """`refresh()` mints a new session row and does not carry `step_up_elevations` over, so the
    value is `None` again until the next step-up (the limit of reading existing state, #2754)."""
    svc, clock, seed, user, sessions = await _setup()
    session_service = SessionService(sessions, _HASHER, clock=clock)
    minted = await session_service.mint(str(user))
    sid = str(minted.session_id)
    await svc.step_up(str(user), sid, "keys", _code(seed, clock), PASSWORD)
    assert last_step_up_at(sessions.sessions[sid].step_up_elevations) == clock.now
    clock.now += timedelta(minutes=1)
    outcome = await session_service.refresh(minted.refresh_token)
    successor = sessions.sessions[str(outcome.minted.session_id)]
    assert last_step_up_at(successor.step_up_elevations) is None


async def test_a_pending_challenge_is_not_a_step_up() -> None:
    """A 403 challenge is stored with the same `now + GRACE_WINDOW` expiry as a grant."""
    svc, clock, seed, user, sessions = await _setup()
    challenge = await svc.record_pending("s1", "keys")
    assert challenge.key() in sessions.sessions["s1"].step_up_elevations
    assert last_step_up_at(sessions.sessions["s1"].step_up_elevations) is None
    await svc.step_up(str(user), "s1", "keys", _code(seed, clock), PASSWORD)
    stepped = clock.now
    clock.now += timedelta(seconds=60)
    await svc.record_pending("s1", "users")  # a later challenge must not look like a later step-up
    assert last_step_up_at(sessions.sessions["s1"].step_up_elevations) == stepped


async def test_a_failed_step_up_does_not_move_the_instant() -> None:
    svc, clock, seed, user, sessions = await _setup()
    await svc.step_up(str(user), "s1", "keys", _code(seed, clock), PASSWORD)
    stepped = clock.now
    clock.now += timedelta(seconds=30)
    with pytest.raises(StepUpCodeInvalid):
        await svc.step_up(str(user), "s1", "keys", "000000", PASSWORD)
    assert last_step_up_at(sessions.sessions["s1"].step_up_elevations) == stepped


async def test_last_step_up_at_keeps_the_instant_after_the_grace_window_lapses() -> None:
    """Past its window the step-up no longer elevates, but it still happened: the age keeps
    counting from the same instant instead of resetting or stopping at the window."""
    svc, clock, seed, user, sessions = await _setup()
    await svc.step_up(str(user), "s1", "keys", _code(seed, clock), PASSWORD)
    stepped = clock.now
    for past_the_window in (GRACE_WINDOW, GRACE_WINDOW + timedelta(seconds=1), timedelta(hours=1)):
        clock.now = stepped + past_the_window
        with pytest.raises(StepUpRequired):
            await svc.require_elevation("s1", "keys")
        assert last_step_up_at(sessions.sessions["s1"].step_up_elevations) == stepped


async def test_a_later_challenge_prunes_the_lapsed_window_and_the_record_with_it() -> None:
    """A write after the window lapsed drops the expired grant, so the instant lasts only until
    the next write that touches the row (the limit of reading existing state, #2754)."""
    svc, clock, seed, user, sessions = await _setup()
    await svc.step_up(str(user), "s1", "keys", _code(seed, clock), PASSWORD)
    clock.now += GRACE_WINDOW + timedelta(seconds=1)
    await svc.record_pending("s1", "users")  # the next 403 challenge writes the row
    assert last_step_up_at(sessions.sessions["s1"].step_up_elevations) is None


async def test_last_step_up_at_restarts_at_the_next_step_up_after_an_idle_lock_unlock() -> None:
    """B16.7: an unlock clears every elevation, so it never inherits a step-up taken before the
    lock; the instant restarts from the next step-up, not from the one before the lock."""
    svc, clock, seed, user, sessions = await _setup()
    await svc.step_up(str(user), "s1", "keys", _code(seed, clock), PASSWORD)
    clock.now += timedelta(minutes=16)  # past the default 15-minute idle timeout
    assert sessions.sessions["s1"].is_idle_locked(now=clock.now)
    await SessionService(sessions, _HASHER, clock=clock).unlock(
        "s1", password=PASSWORD, password_hash=await _pw_hash()
    )
    assert last_step_up_at(sessions.sessions["s1"].step_up_elevations) is None
    await svc.step_up(str(user), "s1", "users", _code(seed, clock), PASSWORD)
    assert last_step_up_at(sessions.sessions["s1"].step_up_elevations) == clock.now


async def test_last_step_up_at_is_none_after_the_readonly_downgrade_drops_the_elevations() -> None:
    svc, clock, seed, user, sessions = await _setup()
    await svc.step_up(str(user), "s1", "keys", _code(seed, clock), PASSWORD)
    for _ in range(2):
        with pytest.raises(StepUpCodeInvalid):
            await svc.step_up(str(user), "s1", "keys", "000000", PASSWORD)
    with pytest.raises(SessionReadOnly):
        await svc.step_up(str(user), "s1", "keys", "000000", PASSWORD)
    assert sessions.sessions["s1"].step_up_elevations == {}
    assert last_step_up_at(sessions.sessions["s1"].step_up_elevations) is None


async def test_last_step_up_at_matches_the_b16_elevation_record() -> None:
    svc, clock, seed, user, sessions = await _setup()
    clock.now = _T0 + timedelta(seconds=17)
    await svc.step_up(str(user), "s1", "keys", _code(seed, clock), PASSWORD)
    interpreter = svc.chart.interpreter(str(sessions.sessions["s1"].id))
    assert interpreter is not None
    elevated_until_us = dict(interpreter.context)["elevated_until_us"]
    stepped = last_step_up_at(sessions.sessions["s1"].step_up_elevations)
    assert stepped is not None
    assert elevated_until_us - b16_session.STEP_UP_GRACE_US == to_us(stepped)


def test_last_step_up_at_ignores_keys_that_are_not_step_ups() -> None:
    until = _T0 + GRACE_WINDOW
    junk = {"pending:keys": until, "bogus": until, "once:bogus": until, "once:": until, "": until}
    assert last_step_up_at({}) is None
    assert last_step_up_at(junk) is None
    with_a_grant = {**junk, "pending:users": until + timedelta(minutes=1), "keys": until}
    assert last_step_up_at(with_a_grant) == _T0

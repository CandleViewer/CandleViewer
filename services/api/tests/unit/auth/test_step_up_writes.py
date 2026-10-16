"""#2304 (security review round 3) and #2798: every write of a session's step-up columns is a
pure change applied to the row as it is when written (`SessionRepository.update_step_up_state`),
never to a copy read before it, and a one-shot grant is used by one conditional write
(`consume_step_up_key`). A grant used while another request of the session is in flight stays
used, whichever writer races it, and a downgrade that lands meanwhile stands.

Each race runs the other request inside the writer's gap between its read of the row and its
write. The fakes apply a change or a use with no await inside, as Postgres does under the row
lock."""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Awaitable, Callable
from datetime import timedelta

import pytest

from candleviewer.auth.errors import SessionReadOnly, StepUpCodeInvalid, StepUpRequired
from candleviewer.auth.models import SessionRecord
from candleviewer.auth.step_up import READONLY_WINDOW, StepUpService

from .session_fakes import FakeSessionRepository
from .test_step_up import PASSWORD, _Clock, _code, _setup

#: The request a no-grace grant is bound to, and the grant a no-grace step-up left on the row.
_BOUND = "a" * 64
_GRANT = f"once:killswitch:{uuid.UUID(int=1)}:{_BOUND}"

Act = Callable[[], Awaitable[object]]
#: A request of the session that writes the step-up columns.
Writer = Callable[[StepUpService, uuid.UUID, bytes, _Clock], Awaitable[None]]


async def _holding_a_grant(
    failures: int = 0, readonly_for: timedelta | None = None
) -> tuple[StepUpService, _Clock, bytes, uuid.UUID, FakeSessionRepository]:
    """`s1` holds a live grant, `failures` strikes and a downgrade ending in `readonly_for`."""
    svc, clock, seed, user, sessions = await _setup()
    sessions.sessions["s1"] = sessions.sessions["s1"].model_copy(
        update={
            "step_up_elevations": {_GRANT: clock.now + timedelta(seconds=60)},
            "step_up_failures": failures,
            "readonly_until": None if readonly_for is None else clock.now + readonly_for,
        }
    )
    return svc, clock, seed, user, sessions


def _used(sessions: FakeSessionRepository, clock: _Clock) -> Act:
    """The held request executes: it uses its grant."""
    return lambda: sessions.consume_step_up_key("s1", key=_GRANT, now=clock.now)


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
    """Run `act` right after the next read of the row: the reader decides on a copy the row no
    longer matches when it writes."""
    read, armed = sessions.find_by_id, [True]

    async def read_then_act(session_id: str) -> SessionRecord | None:
        found = await read(session_id)
        if armed:
            armed.clear()
            await act()
        return found

    monkeypatch.setattr(sessions, "find_by_id", read_then_act)


def _in_password_check(monkeypatch: pytest.MonkeyPatch, svc: StepUpService, act: Act) -> None:
    """Run `act` inside the next step-up's Argon2id check, the widest gap between a step-up's
    read of the row and its write."""
    verify, armed = svc._hasher.verify, [True]

    async def act_then_verify(password_hash: str, password: str) -> bool:
        if armed:
            armed.clear()
            await act()
        return await verify(password_hash, password)

    monkeypatch.setattr(svc._hasher, "verify", act_then_verify)


async def _challenge(svc: StepUpService, user: uuid.UUID, seed: bytes, clock: _Clock) -> None:
    await svc.record_pending("s1", "keys")  # a refused request of another class


async def _grant(svc: StepUpService, user: uuid.UUID, seed: bytes, clock: _Clock) -> None:
    await svc.step_up(str(user), "s1", "keys", _code(seed, clock), PASSWORD)


async def _strike(svc: StepUpService, user: uuid.UUID, seed: bytes, clock: _Clock) -> None:
    with pytest.raises(StepUpCodeInvalid):
        await svc.step_up(str(user), "s1", "keys", "000000", "wrong password")


async def _third_strike(svc: StepUpService, user: uuid.UUID, seed: bytes, clock: _Clock) -> None:
    with pytest.raises(SessionReadOnly):
        await svc.step_up(str(user), "s1", "keys", "000000", "wrong password")


async def _lift(svc: StepUpService, user: uuid.UUID, seed: bytes, clock: _Clock) -> None:
    await svc.assert_writable("s1")  # a write after the downgrade ran out lifts it


@pytest.mark.parametrize(
    ("writer", "gap", "failures", "readonly_for"),
    [
        (_challenge, "read", 0, None),
        (_grant, "check", 0, None),
        (_strike, "check", 0, None),
        (_third_strike, "check", 2, None),
        (_lift, "read", 3, -timedelta(seconds=1)),
    ],
    ids=["challenge", "grant", "strike", "third-strike", "lift-downgrade"],
)
async def test_write_racing_the_use_of_a_grant_never_restores_it(
    monkeypatch: pytest.MonkeyPatch,
    writer: Writer,
    gap: str,
    failures: int,
    readonly_for: timedelta | None,
) -> None:
    """Security review round 3: rewriting the copy read before the use would put the grant back,
    and the identical request could execute a second time inside the 60 s."""
    svc, clock, seed, user, sessions = await _holding_a_grant(failures, readonly_for)
    if gap == "read":
        _after_next_read(monkeypatch, sessions, _used(sessions, clock))
    else:
        _in_password_check(monkeypatch, svc, _used(sessions, clock))

    await writer(svc, user, seed, clock)

    assert _GRANT not in sessions.sessions["s1"].step_up_elevations
    assert await _used(sessions, clock)() is None  # the grant is used up


def _yielding_reads(monkeypatch: pytest.MonkeyPatch, sessions: FakeSessionRepository) -> None:
    """Every read of the row yields once, so concurrent requests all read it before either
    writes."""
    read = sessions.find_by_id

    async def interleaved(session_id: str) -> SessionRecord | None:
        found = await read(session_id)
        await asyncio.sleep(0)
        return found

    monkeypatch.setattr(sessions, "find_by_id", interleaved)


async def test_concurrent_strikes_are_each_counted(monkeypatch: pytest.MonkeyPatch) -> None:
    """A strike is counted on the row's own count, never on the copy read before it."""
    svc, _clock, _seed, user, sessions = await _setup()
    _yielding_reads(monkeypatch, sessions)
    refused = (svc.step_up(str(user), "s1", "keys", "000000", PASSWORD) for _ in range(2))
    results = await asyncio.gather(*refused, return_exceptions=True)

    assert [type(r) for r in results] == [StepUpCodeInvalid, StepUpCodeInvalid]
    assert sessions.sessions["s1"].step_up_failures == 2  # both counted, none lost


async def test_step_up_of_a_session_downgraded_during_its_check_opens_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Three wrong step-ups land while a correct one is in its password check: the read-only
    downgrade stands, so the correct one is refused and opens no window."""
    svc, clock, seed, user, sessions = await _setup()
    _in_password_check(monkeypatch, svc, lambda: _three_strikes(svc, user))

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
    _after_next_read(monkeypatch, sessions, lambda: svc.record_pending("s1", "users"))

    await svc.assert_writable("s1")

    row = sessions.sessions["s1"]
    assert (row.step_up_failures, row.readonly_until) == (0, None)
    assert await svc.pending_action_class("s1") == "users"


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


async def test_identical_requests_racing_inside_the_window_use_the_grant_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """#2798: both re-sends read the row before either writes; one conditional write uses the
    grant, so exactly one executes and the other is refused as if it had no grant."""
    svc, clock, _seed, _user, sessions = await _setup()
    sessions.sessions["s1"] = sessions.sessions["s1"].model_copy(
        update={"step_up_elevations": {"once:killswitch": clock.now + timedelta(minutes=5)}}
    )
    _yielding_reads(monkeypatch, sessions)
    consumers = (svc.consume_single_use("s1", "killswitch") for _ in range(2))
    results = await asyncio.gather(*consumers, return_exceptions=True)

    refused = [r for r in results if type(r) is StepUpRequired]
    assert (results.count(None), len(refused)) == (1, 1)
    assert sessions.sessions["s1"].step_up_elevations == {}

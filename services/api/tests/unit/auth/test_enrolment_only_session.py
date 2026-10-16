"""Enrolment-only session: classification, wiring and lifetime (#2295 slice 2/3, enforcement).

Decisions on #2295 and the contract of #2661: the class is derived from the user's state on
every call, never from a session flag. `mfa_required` with no confirmed MFA method makes every
session of the user enrolment-only; such a session lives at most 15 minutes from sign-in and
refresh never extends it (Q7), so one whose expiry lies further ahead is refused.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any, cast

import pytest
from hypothesis import given
from hypothesis import strategies as st

from candleviewer.auth.errors import AuthServiceUnavailable, SessionRevoked
from candleviewer.auth.hashing import Hasher
from candleviewer.auth.models import MfaMethodKind, SessionRecord, UserRecord
from candleviewer.auth.service import AuthService
from candleviewer.auth.session_service import (
    ENROLMENT_ONLY_LIFETIME,
    SessionClass,
    SessionService,
    classify_session,
)
from tests.unit.auth.auth_fakes import FakeUserRepository, make_user
from tests.unit.auth.session_fakes import FakeSessionRepository

T0 = datetime(2026, 10, 16, 9, 0, tzinfo=UTC)
_TOTP = (MfaMethodKind.TOTP,)
_FULL, _ONLY, _EXPIRED = (
    SessionClass.FULL,
    SessionClass.ENROLMENT_ONLY,
    SessionClass.ENROLMENT_ONLY_EXPIRED,
)


class _Clock:
    def __init__(self) -> None:
        self.now = T0

    def __call__(self) -> datetime:
        return self.now


def _user(*, mfa_required: bool = True, methods: tuple[MfaMethodKind, ...] = ()) -> UserRecord:
    return make_user(password_hash="unused", mfa_required=mfa_required, mfa_methods=methods)


def _session(user_id: uuid.UUID, *, expires_in: timedelta) -> SessionRecord:
    """Only `user_id` and `expires_at` are read by the classification."""
    return SessionRecord.model_construct(user_id=user_id, issued_at=T0, expires_at=T0 + expires_in)


# -- the one classification ------------------------------------------------------------------


@pytest.mark.parametrize(
    ("user", "expires_in", "expected"),
    [
        (_user(methods=_TOTP), timedelta(hours=12), _FULL),
        (_user(), timedelta(0), _ONLY),
        (_user(), timedelta(minutes=15), _ONLY),  # Q7: exactly the window
        (_user(), timedelta(minutes=15, microseconds=1), _EXPIRED),
        (_user(), timedelta(hours=12), _EXPIRED),  # never minted as one
        (_user(mfa_required=False), timedelta(hours=12), _FULL),  # the decided rule; C-12.2
        (None, timedelta(minutes=5), _ONLY),  # fail closed: no proven second factor
        (None, timedelta(hours=12), _EXPIRED),
    ],
)
def test_classify_session_truth_table(
    user: UserRecord | None, expires_in: timedelta, expected: SessionClass
) -> None:
    session = _session(uuid.uuid4(), expires_in=expires_in)

    assert classify_session(session, user, now=T0) is expected


@given(
    mfa_required=st.booleans(),
    methods=st.lists(st.sampled_from(list(MfaMethodKind)), max_size=3, unique=True),
    known=st.booleans(),
    seconds_left=st.integers(min_value=-3600, max_value=13 * 3600),
)
def test_classify_session_is_full_exactly_when_a_second_factor_is_proven_or_not_required(
    mfa_required: bool, methods: list[MfaMethodKind], known: bool, seconds_left: int
) -> None:
    user = _user(mfa_required=mfa_required, methods=tuple(methods)) if known else None
    session = _session(uuid.uuid4(), expires_in=timedelta(seconds=seconds_left))

    verdict = classify_session(session, user, now=T0)

    full = user is not None and (bool(user.mfa_methods) or not user.mfa_required)
    assert (verdict is _FULL) is full
    if not full:
        assert (verdict is _EXPIRED) is (timedelta(seconds=seconds_left) > ENROLMENT_ONLY_LIFETIME)


# -- AuthService: the one place both HTTP and WS ask -------------------------------------------


async def _auth(users: FakeUserRepository | None, *, clock: _Clock | None = None) -> AuthService:
    auth = AuthService(
        users, pepper="p", session_repository=FakeSessionRepository(), clock=clock or _Clock()
    )
    await auth.start(cast(Any, None))  # no MFA repository: the context is never read
    return auth


@pytest.mark.parametrize(
    ("users", "sessions", "active"), [(1, 1, True), (0, 1, False), (1, 0, False)]
)
async def test_enrolment_gate_needs_the_session_and_the_user_store(
    users: int, sessions: int, active: bool
) -> None:
    auth = AuthService(
        FakeUserRepository() if users else None,
        session_repository=FakeSessionRepository() if sessions else None,
    )
    await auth.start(cast(Any, None))

    assert auth.enrolment_gate_is_active is active


async def test_classify_reads_the_sessions_own_user_on_every_call() -> None:
    users = FakeUserRepository()
    enrolling, other = _user(), _user(methods=_TOTP)
    users.add(enrolling)
    users.add(other)
    auth = await _auth(users)
    session = _session(enrolling.id, expires_in=timedelta(minutes=10))

    assert await auth.classify(session) is _ONLY
    assert await auth.classify(_session(other.id, expires_in=timedelta(minutes=10))) is _FULL
    users.add(enrolling.model_copy(update={"mfa_methods": _TOTP}))  # confirmed elsewhere
    assert await auth.classify(session) is _FULL
    users.add(enrolling.model_copy(update={"mfa_methods": ()}))  # e.g. a recovery sign-in
    assert await auth.classify(session) is _ONLY


async def test_classify_uses_the_injected_clock() -> None:
    users, clock = FakeUserRepository(), _Clock()
    user = _user()
    users.add(user)
    auth = await _auth(users, clock=clock)
    session = _session(user.id, expires_in=timedelta(minutes=20))

    assert await auth.classify(session) is _EXPIRED
    clock.now = T0 + timedelta(minutes=5)  # 15 minutes left now
    assert await auth.classify(session) is _ONLY


class _BrokenUsers(FakeUserRepository):
    async def find_by_id(self, user_id: str) -> UserRecord | None:
        raise OSError("user store unreachable")


@pytest.mark.parametrize(
    ("users", "error"), [(None, AuthServiceUnavailable), (_BrokenUsers(), OSError)]
)
async def test_classify_fails_closed_without_a_readable_user_store(
    users: FakeUserRepository | None, error: type[Exception]
) -> None:
    auth = await _auth(users)

    with pytest.raises(error):
        await auth.classify(_session(uuid.uuid4(), expires_in=timedelta(minutes=5)))


# -- lifetime and refresh (Q7): refresh never extends it ---------------------------------------


def _service(clock: _Clock) -> SessionService:
    return SessionService(FakeSessionRepository(), Hasher(pepper="p"), clock=clock)


async def test_refresh_keeps_the_deadline_and_the_session_dies_at_fifteen_minutes() -> None:
    clock = _Clock()
    service = _service(clock)
    deadline = T0 + ENROLMENT_ONLY_LIFETIME
    minted = await service.mint(str(uuid.uuid4()), mfa_satisfied=False, expires_at=deadline)
    clock.now = T0 + timedelta(minutes=10)
    successor = (await service.refresh(minted.refresh_token)).minted

    assert successor.expires_at == deadline
    clock.now = deadline - timedelta(microseconds=1)
    record = await service.authenticate_access_token(successor.access_token)
    assert classify_session(record, _user(), now=clock.now) is _ONLY
    clock.now = deadline
    with pytest.raises(SessionRevoked, match="expired"):
        await service.authenticate_access_token(successor.access_token)
    with pytest.raises(SessionRevoked, match="expired"):
        await service.refresh(successor.refresh_token)


@given(steps=st.lists(st.integers(min_value=1, max_value=600), min_size=1, max_size=6))
def test_no_sequence_of_refreshes_extends_an_enrolment_only_session(steps: list[int]) -> None:
    async def run() -> None:
        clock = _Clock()
        service = _service(clock)
        deadline = T0 + ENROLMENT_ONLY_LIFETIME
        current = await service.mint(str(uuid.uuid4()), mfa_satisfied=False, expires_at=deadline)
        for step in steps:
            clock.now += timedelta(seconds=step)
            if clock.now >= deadline:
                with pytest.raises(SessionRevoked):
                    await service.refresh(current.refresh_token)
                return
            current = (await service.refresh(current.refresh_token)).minted
            assert current.expires_at == deadline

    asyncio.run(run())

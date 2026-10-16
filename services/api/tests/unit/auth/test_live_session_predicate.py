"""#2264: `is_live_session` and `SessionService.authenticate_access_token` agree.

The CSRF guard picks the audit budget of a refusal with `is_live_session`, a read-only twin of
the strict acceptance rule of `authenticate_access_token`. They state one
rule twice, so this pins them together: for any record and clock the twin says "live" exactly
when the strict path accepts. If either changes alone, this fails.
"""

from __future__ import annotations

import asyncio
import os
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from hypothesis import example, given, settings
from hypothesis import strategies as st

from candleviewer.auth.errors import SessionIdleLocked, SessionNotFound, SessionRevoked
from candleviewer.auth.hashing import Hasher
from candleviewer.auth.models import SessionRecord
from candleviewer.auth.session_service import ACCESS_TOKEN_TTL, SessionService, is_live_session

from .session_fakes import FakeSessionRepository

_NOW = datetime(2026, 10, 16, 9, 0, tzinfo=UTC)
_US = timedelta(microseconds=1)
_SEC = 1_000_000  # microseconds
_TTL = ACCESS_TOKEN_TTL // _US
_IDLE = 900 * _SEC  # the default idle timeout
_FAR = 10**12  # an absolute deadline far in the future


@dataclass(frozen=True)
class _State:
    """Issued `age_us` ago, last seen `idle_gap_us` ago, expiring `absolute_left_us` from now."""

    age_us: int
    idle_gap_us: int
    idle_timeout_s: int
    absolute_left_us: int
    revoked: bool


async def _session_in(wanted: _State) -> tuple[SessionService, SessionRecord, str]:
    """A really minted session, moved to the wanted state: (service, record, token)."""
    repository = FakeSessionRepository()
    service = SessionService(repository, Hasher(pepper=os.urandom(8).hex()), clock=lambda: _NOW)
    minted = await service.mint(str(uuid.uuid4()), idle_timeout_s=wanted.idle_timeout_s)
    record = repository.sessions[str(minted.session_id)].model_copy(
        update={
            "issued_at": _NOW - wanted.age_us * _US,
            "last_seen_at": _NOW - wanted.idle_gap_us * _US,
            "expires_at": _NOW + wanted.absolute_left_us * _US,
            "revoked_at": _NOW if wanted.revoked else None,
            "revoked_reason": "logout" if wanted.revoked else None,
        }
    )
    repository.sessions[str(record.id)] = record
    return service, record, minted.access_token


async def _agree(state: _State) -> None:
    service, record, token = await _session_in(state)
    try:
        await service.authenticate_access_token(token)  # never activity (#2300)
        accepted = True
    except (SessionNotFound, SessionRevoked, SessionIdleLocked):
        accepted = False
    assert accepted is is_live_session(record, now=_NOW)


@settings(max_examples=300, deadline=None)
# Each boundary on its own: the access TTL, the idle deadline, the absolute deadline, revocation.
@example(age_us=_TTL, idle_gap_us=0, idle_timeout_s=900, absolute_left_us=_FAR, revoked=False)
@example(age_us=_TTL - 1, idle_gap_us=0, idle_timeout_s=900, absolute_left_us=_FAR, revoked=False)
@example(age_us=_SEC, idle_gap_us=_IDLE, idle_timeout_s=900, absolute_left_us=_FAR, revoked=False)
@example(
    age_us=_SEC, idle_gap_us=_IDLE - 1, idle_timeout_s=900, absolute_left_us=_FAR, revoked=False
)
@example(age_us=_SEC, idle_gap_us=0, idle_timeout_s=900, absolute_left_us=0, revoked=False)
@example(age_us=_SEC, idle_gap_us=0, idle_timeout_s=900, absolute_left_us=1, revoked=False)
@example(age_us=_SEC, idle_gap_us=0, idle_timeout_s=900, absolute_left_us=_FAR, revoked=True)
@given(
    age_us=st.integers(min_value=0, max_value=_TTL + 120 * _SEC),
    idle_gap_us=st.integers(min_value=0, max_value=2 * _IDLE),
    idle_timeout_s=st.sampled_from([300, 900, 3600]),
    absolute_left_us=st.one_of(
        st.integers(min_value=-120 * _SEC, max_value=120 * _SEC), st.just(_FAR)
    ),
    revoked=st.booleans(),
)
def test_is_live_session_holds_exactly_when_the_strict_path_accepts(
    age_us: int, idle_gap_us: int, idle_timeout_s: int, absolute_left_us: int, revoked: bool
) -> None:
    state = _State(age_us, idle_gap_us, idle_timeout_s, absolute_left_us, revoked)
    asyncio.run(_agree(state))


async def test_a_logout_finds_an_idle_locked_session_the_predicate_rejects() -> None:
    """A bearer logout finds its session with `peek_access_token`, idle-locked or not (#2300),
    so a refusal there is not "live" for the CSRF audit budget although the route serves it."""
    service, record, token = await _session_in(_State(_SEC, 2 * _IDLE, 900, _FAR, False))
    assert is_live_session(record, now=_NOW) is False
    found = await service.peek_access_token(token)
    assert found is not None and found.id == record.id

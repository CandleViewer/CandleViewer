"""#2259: `access_token_expires_at` is exactly the first instant at which
`SessionService.authenticate_access_token` refuses the token. That is the
access TTL, capped by the session's absolute expiry. The WS gateway closes the
socket at this instant, so it must never be later than the service's refusal.
"""

from __future__ import annotations

import asyncio
import os
import uuid
from datetime import UTC, datetime, timedelta

from hypothesis import example, given, settings
from hypothesis import strategies as st

from candleviewer.auth.errors import SessionNotFound, SessionRevoked
from candleviewer.auth.hashing import Hasher
from candleviewer.auth.session_service import (
    ACCESS_TOKEN_TTL,
    SessionService,
    access_token_expires_at,
)

from .session_fakes import FakeSessionRepository

_NOW = datetime(2026, 10, 12, 9, 0, tzinfo=UTC)
_US = timedelta(microseconds=1)
_TTL_US = ACCESS_TOKEN_TTL // _US
_FIVE_MIN_US = timedelta(minutes=5) // _US
_TWELVE_H_US = timedelta(hours=12) // _US
_TWO_MIN_US = timedelta(minutes=2) // _US


class _Clock:
    def __init__(self) -> None:
        self.now = _NOW

    def __call__(self) -> datetime:
        return self.now


async def _accepted(absolute_after: timedelta, delta: timedelta) -> tuple[bool, datetime]:
    """Mint at `_NOW` with absolute expiry `_NOW + absolute_after`, then probe
    `authenticate_access_token` at `access_token_expires_at(record) + delta`."""
    clock, repo = _Clock(), FakeSessionRepository()
    svc = SessionService(repo, Hasher(pepper=os.urandom(8).hex()), clock=clock)
    minted = await svc.mint(str(uuid.uuid4()), expires_at=_NOW + absolute_after)
    expiry = access_token_expires_at(repo.sessions[str(minted.session_id)])
    clock.now = expiry + delta
    try:
        await svc.authenticate_access_token(minted.access_token)
    except (SessionNotFound, SessionRevoked):
        return False, expiry
    return True, expiry


@settings(max_examples=150, deadline=None)
@example(absolute_after_us=_TWELVE_H_US, delta_us=0)  # TTL-bound: refused at the expiry
@example(absolute_after_us=_TWELVE_H_US, delta_us=-1)  # ...and accepted 1 us before it
@example(absolute_after_us=_TTL_US, delta_us=0)  # both deadlines coincide
@example(absolute_after_us=_FIVE_MIN_US, delta_us=0)  # absolute-bound: refused at the cap
@example(absolute_after_us=_FIVE_MIN_US, delta_us=-1)
@given(
    absolute_after_us=st.integers(min_value=1, max_value=_TWELVE_H_US),
    delta_us=st.integers(min_value=-_TWO_MIN_US, max_value=_TWO_MIN_US),
)
def test_access_token_expires_at_is_the_first_instant_the_service_refuses(
    absolute_after_us: int, delta_us: int
) -> None:
    absolute_after = absolute_after_us * _US
    accepted, expiry = asyncio.run(_accepted(absolute_after, delta_us * _US))
    assert expiry == min(_NOW + ACCESS_TOKEN_TTL, _NOW + absolute_after)
    assert accepted is (delta_us < 0)

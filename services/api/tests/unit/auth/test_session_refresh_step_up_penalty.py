"""#4051: a token refresh keeps the session's step-up penalty (SR-025).

Three wrong step-up codes make a session read-only for five minutes (`FAILURE_CAP`,
`READONLY_WINDOW`). `refresh()` mints the successor with the claimed row's `step_up_failures` and
`readonly_until`, as it carries `last_seen_at` (#4012), so a rotation never lifts the brake. Grants
are not carried: a rotation still drops every step-up elevation. No DB, no network, fixed clock.
"""

from __future__ import annotations

import asyncio
import os
from datetime import UTC, datetime, timedelta

import pytest

from candleviewer.auth.envelope import TotpEncryptor
from candleviewer.auth.errors import RefreshReuseDetected, SessionReadOnly
from candleviewer.auth.hashing import Hasher
from candleviewer.auth.models import MintedSession, SessionRecord
from candleviewer.auth.session_service import SessionService
from candleviewer.auth.step_up import FAILURE_CAP, READONLY_WINDOW, StepUpService
from tests.unit.auth.auth_fakes import no_wait

from .auth_fakes import FakeUserRepository
from .mfa_fakes import FakeMfaRepository
from .session_fakes import FakeSessionRepository, YieldingFindRepository

_T0 = datetime(2026, 10, 21, 9, 0, 0, tzinfo=UTC)
_USER = "00000000-0000-4000-8000-000000004051"


class _Clock:
    def __init__(self) -> None:
        self.now = _T0

    def __call__(self) -> datetime:
        return self.now


def _svc(repo: FakeSessionRepository | None = None) -> tuple[SessionService, FakeSessionRepository]:
    repo = repo if repo is not None else FakeSessionRepository()
    return SessionService(repo, Hasher(), clock=_Clock()), repo


async def _penalised(
    svc: SessionService, repo: FakeSessionRepository, failures: int, until: datetime | None
) -> MintedSession:
    minted = await svc.mint(_USER)
    grant = {"keys": _T0 + timedelta(minutes=5)}
    await repo.save_step_up_state(
        str(minted.session_id), elevations=grant, failures=failures, readonly_until=until
    )
    return minted


def _row(repo: FakeSessionRepository, minted: MintedSession) -> SessionRecord:
    return repo.sessions[str(minted.session_id)]


async def test_a_refresh_keeps_the_read_only_window_and_the_strike_count() -> None:
    svc, repo = _svc()
    until = _T0 + READONLY_WINDOW
    successor = await svc.refresh((await _penalised(svc, repo, FAILURE_CAP, until)).refresh_token)
    row = _row(repo, successor.minted)
    assert (row.step_up_failures, row.readonly_until) == (FAILURE_CAP, until)
    assert row.step_up_elevations == {}  # grants are never carried
    step_up = StepUpService(
        FakeMfaRepository(),
        repo,
        TotpEncryptor(os.urandom(32)),
        FakeUserRepository(),
        Hasher(),
        clock=lambda: _T0,
        sleep=no_wait,
    )
    try:
        with pytest.raises(SessionReadOnly):
            await step_up.assert_writable(str(successor.minted.session_id))
    finally:
        await step_up.stop()


@pytest.mark.parametrize(("failures", "until"), [(0, None), (2, None)])
async def test_a_refresh_carries_strikes_as_they_are_and_no_window_it_lacked(
    failures: int, until: datetime | None
) -> None:
    svc, repo = _svc()
    successor = await svc.refresh((await _penalised(svc, repo, failures, until)).refresh_token)
    row = _row(repo, successor.minted)
    assert (row.step_up_failures, row.readonly_until) == (failures, until)


class _StrikeBeforeClaim(FakeSessionRepository):
    """A third wrong code lands between refresh()'s read and its claim: the claim's row holds
    the downgrade, `presented` the clean state."""

    async def revoke(self, session_id: str, *, reason: str, now: datetime) -> SessionRecord | None:
        if reason == "rotated":
            await self.save_step_up_state(
                session_id,
                elevations={},
                failures=FAILURE_CAP,
                readonly_until=now + READONLY_WINDOW,
            )
        return await super().revoke(session_id, reason=reason, now=now)


async def test_the_successor_carries_the_claims_penalty_not_the_read_one() -> None:
    svc, repo = _svc(_StrikeBeforeClaim())
    minted = await svc.mint(_USER)
    successor = (await svc.refresh(minted.refresh_token)).minted
    row = _row(repo, successor)
    assert (row.step_up_failures, row.readonly_until) == (FAILURE_CAP, _T0 + READONLY_WINDOW)


async def test_of_two_concurrent_refreshes_one_mints_and_its_successor_carries_the_penalty() -> (
    None
):
    """Both read the row before either claims it (the repository yields after each read, as
    Postgres's read and revoke are two statements): one wins the claim and mints, the other loses
    it and is refused with no family revoked, and the one successor carries the penalty."""
    svc, repo = _svc(YieldingFindRepository())
    until = _T0 + READONLY_WINDOW
    minted = await _penalised(svc, repo, FAILURE_CAP, until)
    results = await asyncio.gather(
        svc.refresh(minted.refresh_token), svc.refresh(minted.refresh_token), return_exceptions=True
    )
    (lost,) = [r for r in results if isinstance(r, RefreshReuseDetected)]
    assert lost.revoked_session_ids == ()  # the lost claim, not reuse detection
    successors = [r for r in repo.sessions.values() if r.id != minted.session_id]
    assert [(r.is_revoked, r.step_up_failures, r.readonly_until) for r in successors] == [
        (False, FAILURE_CAP, until)
    ]

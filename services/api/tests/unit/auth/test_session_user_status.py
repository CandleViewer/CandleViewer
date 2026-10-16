"""#2911: no session is minted or rotated for a disabled (or deleted) user, and a disabled user's
live session is refused and revoked on its next use (SR-029, E42-T04's in-flight refresh window).
`locked` and `invited` users are not refused: login refuses `disabled` only, and the issue keeps
the other two as they are.

On the fakes: `FakeSessionRepository.user_statuses` plays `users.status`, read with the session
row and checked in the same step as the insert, like the real repository under the user-row
lock. The Postgres side is `tests/integration/auth/test_disabled_user_sessions_pg.py`; REST 401
is `tests/unit/api/test_sessions_router.py`, the socket's `bye user_disabled` + 4403 the SR-029
drill (`tests/security/auth/test_disable_user_drill.py`). The breach counter for a session that no
disable revoked is catalogued and served on the scraped registry (SR-125).
"""

from __future__ import annotations

import asyncio
import os
import uuid
from datetime import UTC, datetime

import pytest
from prometheus_client import REGISTRY, generate_latest
from structlog.testing import capture_logs

from candleviewer.app import create_app
from candleviewer.auth.errors import SessionRevoked, UserDisabled
from candleviewer.auth.hashing import Hasher
from candleviewer.auth.metrics import AUTH_EXPORTED_NAMES
from candleviewer.auth.models import SessionRecord, UserStatus
from candleviewer.auth.session_service import SessionService
from candleviewer.observability.metrics_catalogue import CATALOGUE
from candleviewer.settings import Environment, Settings

from .session_fakes import FakeSessionRepository, LostRaceRepository, YieldingFindRepository

_NOW = datetime(2026, 10, 16, 12, 0, tzinfo=UTC)
_WAIT_S = 5.0  # bounds every wait on the parked refresh: a regression fails instead of hanging
#: Refused: `disabled`, or the user row gone (absent or soft-deleted).
_REFUSED = [pytest.param(UserStatus.DISABLED, id="disabled"), pytest.param(None, id="gone")]
#: Not refused: `active`, and `locked` / `invited` as #2911 keeps them.
_KEPT = [UserStatus.ACTIVE, UserStatus.LOCKED, UserStatus.INVITED]


def _service(
    repo: FakeSessionRepository, published: list[tuple[str, str]] | None = None
) -> SessionService:
    async def publish(session_id: str, reason: str) -> None:
        if published is not None:
            published.append((session_id, reason))

    return SessionService(
        repo, Hasher(pepper=os.urandom(16).hex()), clock=lambda: _NOW, publish_revocation=publish
    )


def _sample(name: str, **labels: str) -> float:
    return REGISTRY.get_sample_value(name, labels) or 0.0


class _ParkedMint(FakeSessionRepository):
    """Parks the mint's insert once armed: the refresh has claimed the presented session and
    has not minted its successor, so a disable can run in between."""

    def __init__(self) -> None:
        super().__init__()
        self.armed = False
        self.parked = asyncio.Event()
        self.release = asyncio.Event()

    async def create_session(self, session: SessionRecord) -> SessionRecord | None:
        if self.armed:
            self.parked.set()
            await self.release.wait()
        return await super().create_session(session)


@pytest.mark.parametrize("status", _REFUSED)
async def test_mint_refuses_a_disabled_user(status: UserStatus | None) -> None:
    repo, user = FakeSessionRepository(), str(uuid.uuid4())
    repo.user_statuses[user] = status

    with pytest.raises(UserDisabled):
        await _service(repo).mint(user)

    assert repo.sessions == {}


@pytest.mark.parametrize("status", _KEPT)
async def test_mint_still_stores_the_session_of_a_user_who_is_not_disabled(
    status: UserStatus,
) -> None:
    repo, user = FakeSessionRepository(), str(uuid.uuid4())
    repo.user_statuses[user] = status

    minted = await _service(repo).mint(user)

    assert list(repo.sessions) == [str(minted.session_id)]


@pytest.mark.parametrize("status", _REFUSED)
async def test_refresh_refuses_a_disabled_user(status: UserStatus | None) -> None:
    """Refused before the claim: the presented session is untouched and nothing is minted."""
    repo, user = FakeSessionRepository(), str(uuid.uuid4())
    service = _service(repo)
    minted = await service.mint(user)
    repo.user_statuses[user] = status

    with pytest.raises(UserDisabled) as refused:
        await service.refresh(minted.refresh_token)

    assert refused.value.status == (None if status is None else status.value)
    presented = repo.sessions[str(minted.session_id)]
    assert presented.revoked_at is None  # not claimed: nothing changed
    assert list(repo.sessions) == [str(minted.session_id)] and repo.rotation_next == {}


@pytest.mark.parametrize("status", _KEPT)
async def test_refresh_still_rotates_for_a_user_who_is_not_disabled(status: UserStatus) -> None:
    repo, user = FakeSessionRepository(), str(uuid.uuid4())
    service = _service(repo)
    minted = await service.mint(user)
    repo.user_statuses[user] = status

    outcome = await service.refresh(minted.refresh_token)

    assert repo.sessions[str(minted.session_id)].revoked_reason == "rotated"
    assert repo.rotation_next == {str(minted.session_id): str(outcome.minted.session_id)}
    assert repo.sessions[str(outcome.minted.session_id)].revoked_at is None


async def test_refresh_parked_between_claim_and_mint_across_a_disable_mints_nothing() -> None:
    """The window of #2911: the refresh claims while the user is active; the disable (status,
    its own revoke and the post-commit sweep) lands before the mint; the mint is refused."""
    repo, user = _ParkedMint(), str(uuid.uuid4())
    service = _service(repo)
    minted = await service.mint(user)
    repo.armed = True

    refresh = asyncio.create_task(service.refresh(minted.refresh_token))
    await asyncio.wait_for(repo.parked.wait(), _WAIT_S)
    repo.user_statuses[user] = UserStatus.DISABLED
    swept = await service.revoke_all(user, reason="user_disabled")
    repo.release.set()

    with pytest.raises(UserDisabled):
        await asyncio.wait_for(refresh, _WAIT_S)
    assert swept == ()  # the claimed session was no longer live, and no successor existed yet
    assert await repo.find_live_by_user(user) == ()
    assert repo.rotation_next == {}


@pytest.mark.parametrize("status", _REFUSED)
async def test_require_active_refuses_a_disabled_users_live_session(
    status: UserStatus | None,
) -> None:
    """Fail closed: refused as revoked with `user_disabled`, the row revoked and the id
    published, so the hub ends its sockets with `bye user_disabled` + 4403 (§9.5). The breach
    signal is counted once, and the revocation under `user_disabled`, not `other`."""
    repo, published = FakeSessionRepository(), list[tuple[str, str]]()
    service = _service(repo, published)
    user, bystander = str(uuid.uuid4()), str(uuid.uuid4())
    minted, kept = await service.mint(user), await service.mint(bystander)
    repo.user_statuses[user] = status
    signals = _sample("auth_disabled_user_sessions_revoked_total")
    revocations = _sample("auth_session_revocations_total", reason="user_disabled")

    with pytest.raises(SessionRevoked) as refused:
        await service.authenticate_access_token(minted.access_token)

    sid = str(minted.session_id)
    assert refused.value.reason == "user_disabled"
    assert repo.sessions[sid].revoked_reason == "user_disabled"
    assert published == [(sid, "user_disabled")]
    assert _sample("auth_disabled_user_sessions_revoked_total") == signals + 1
    assert _sample("auth_session_revocations_total", reason="user_disabled") == revocations + 1
    assert (await service.require_active(str(kept.session_id))).id == kept.session_id


@pytest.mark.parametrize("status", _REFUSED)
async def test_require_active_logs_the_stray_session_for_the_operator(
    status: UserStatus | None,
) -> None:
    """The runbook (auth-rbac section 4) sends the operator to this line: a warning that names
    the session, the user and the status read (`None`: the row is gone), and holds no token."""
    repo = FakeSessionRepository()
    service = _service(repo)
    user = str(uuid.uuid4())
    minted = await service.mint(user)
    repo.user_statuses[user] = status

    with capture_logs() as logs, pytest.raises(SessionRevoked):
        await service.require_active(str(minted.session_id))

    (line,) = [e for e in logs if e["event"] == "auth.disabled_user_session_revoked"]
    assert (line["log_level"], line["session_id"], line["user_id"]) == (
        "warning",
        str(minted.session_id),
        user,
    )
    assert line["user_status"] == (None if status is None else status.value)
    assert minted.access_token not in str(line) and minted.refresh_token not in str(line)


@pytest.mark.parametrize("status", _KEPT)
async def test_require_active_keeps_the_live_session_of_a_user_who_is_not_disabled(
    status: UserStatus,
) -> None:
    """`active`, and `locked` / `invited` as the issue keeps them: nothing revoked or counted."""
    repo, published = FakeSessionRepository(), list[tuple[str, str]]()
    service = _service(repo, published)
    user = str(uuid.uuid4())
    minted = await service.mint(user)
    repo.user_statuses[user] = status
    signals = _sample("auth_disabled_user_sessions_revoked_total")

    assert (await service.require_active(str(minted.session_id))).id == minted.session_id
    assert published == [] and repo.sessions[str(minted.session_id)].revoked_at is None
    assert _sample("auth_disabled_user_sessions_revoked_total") == signals


async def test_require_active_counts_a_stray_session_once_when_requests_race() -> None:
    """#3029 item 1: three requests on one stray session each see it live, one wins the revoke.
    Only that call counts, logs and publishes: the breach counter, the revocation counter under
    `user_disabled` and the WARNING lines each move once. The other two are refused all the same."""
    repo, published = YieldingFindRepository(), list[tuple[str, str]]()
    service = _service(repo, published)
    user = str(uuid.uuid4())
    sid = str((await service.mint(user)).session_id)
    repo.user_statuses[user] = UserStatus.DISABLED
    signals = _sample("auth_disabled_user_sessions_revoked_total")
    revocations = _sample("auth_session_revocations_total", reason="user_disabled")

    with capture_logs() as logs:
        outcomes = await asyncio.gather(
            *(service.require_active(sid) for _ in range(3)), return_exceptions=True
        )

    assert [o.reason for o in outcomes if isinstance(o, SessionRevoked)] == ["user_disabled"] * 3
    assert _sample("auth_disabled_user_sessions_revoked_total") == signals + 1
    assert _sample("auth_session_revocations_total", reason="user_disabled") == revocations + 1
    assert [
        e["session_id"] for e in logs if e["event"] == "auth.disabled_user_session_revoked"
    ] == [sid]
    assert published == [(sid, "user_disabled")]


@pytest.mark.parametrize("status", _REFUSED)
async def test_require_active_counts_nothing_when_another_call_revoked_the_row(
    status: UserStatus | None,
) -> None:
    """The stale copy is still refused as `user_disabled`, but nothing is counted, logged or
    published: whoever revoked the row did that."""
    repo, published = LostRaceRepository(), list[tuple[str, str]]()
    service = _service(repo, published)
    user = str(uuid.uuid4())
    minted = await service.mint(user)
    repo.user_statuses[user] = status
    signals = _sample("auth_disabled_user_sessions_revoked_total")
    revocations = _sample("auth_session_revocations_total", reason="user_disabled")

    with capture_logs() as logs, pytest.raises(SessionRevoked) as refused:
        await service.require_active(str(minted.session_id))

    assert refused.value.reason == "user_disabled"
    assert _sample("auth_disabled_user_sessions_revoked_total") == signals
    assert _sample("auth_session_revocations_total", reason="user_disabled") == revocations
    assert [e for e in logs if e["event"] == "auth.disabled_user_session_revoked"] == []
    assert published == []


async def test_require_active_takes_the_revoked_session_off_the_active_gauge() -> None:
    """The backstop revokes through the row update `revoke` makes, so the gauge of live
    sessions falls with it, as it does for a logout."""
    repo = FakeSessionRepository()
    service = _service(repo)
    user = str(uuid.uuid4())
    sid = str((await service.mint(user)).session_id)
    repo.user_statuses[user] = UserStatus.DISABLED
    live = _sample("auth_sessions_active")

    with pytest.raises(SessionRevoked):
        await service.require_active(sid)

    assert _sample("auth_sessions_active") == live - 1


async def test_require_active_counts_the_stray_session_before_a_cancel_in_the_publish() -> None:
    """The publish is a suspension point, and a request cancelled in it leaves the row revoked
    and `auth_session_revocations_total{reason="user_disabled"}` moved. The breach counter and the
    WARNING have to move with them, before the publish: the retry finds the row revoked, refuses
    it with its stored reason and counts nothing, so a signal lost here is lost for good."""
    repo, parked, never = FakeSessionRepository(), asyncio.Event(), asyncio.Event()

    async def publish(session_id: str, reason: str) -> None:
        parked.set()
        await never.wait()

    service = SessionService(
        repo, Hasher(pepper=os.urandom(16).hex()), clock=lambda: _NOW, publish_revocation=publish
    )
    user = str(uuid.uuid4())
    sid = str((await service.mint(user)).session_id)
    repo.user_statuses[user] = UserStatus.DISABLED
    signals = _sample("auth_disabled_user_sessions_revoked_total")
    revocations = _sample("auth_session_revocations_total", reason="user_disabled")

    with capture_logs() as logs:
        request = asyncio.create_task(service.require_active(sid))
        await asyncio.wait_for(parked.wait(), _WAIT_S)
        request.cancel()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(request, _WAIT_S)

    assert repo.sessions[sid].revoked_reason == "user_disabled"
    assert _sample("auth_session_revocations_total", reason="user_disabled") == revocations + 1
    assert _sample("auth_disabled_user_sessions_revoked_total") == signals + 1
    assert [
        e["session_id"] for e in logs if e["event"] == "auth.disabled_user_session_revoked"
    ] == [sid]


_SIGNAL = "auth_disabled_user_sessions_revoked_total"


def test_the_breach_signal_is_catalogued_live_and_exported() -> None:
    spec = next(s for s in CATALOGUE if s.name == _SIGNAL)

    assert (spec.kind, spec.labels, spec.status, spec.exported) == ("counter", (), "live", True)
    assert _SIGNAL in AUTH_EXPORTED_NAMES


def test_the_breach_signal_exists_before_the_first_stray_session() -> None:
    """`increase()` needs a 0 sample before the first one, or that one is never seen."""
    assert REGISTRY.get_sample_value(_SIGNAL) is not None


def test_create_app_serves_the_breach_signal_on_the_scraped_registry() -> None:
    app = create_app(Settings(environment=Environment.DEMO))

    text = generate_latest(app.state.app_context.metrics).decode()

    assert f'{_SIGNAL}{{env="demo"}} ' in text

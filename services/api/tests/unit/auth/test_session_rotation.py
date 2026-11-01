"""SR-013 (#2101): `SessionService.rotate`, the step-up's session rotation, and the two pieces it
needs: `mint(step_up_elevations=...)` and `auth.step_up.carried_grants` (the ruling's C-5); plus
the role change's sign-out, `revoke_all(families=True)` (C-3), and its `role_changed` reason (C-7).
The real inserts are `tests/integration/auth/test_step_up_rotation_pg.py`'s."""

from __future__ import annotations

import os
import uuid
from datetime import UTC, datetime, timedelta

import pytest
import structlog

from candleviewer.auth.errors import RefreshReuseDetected, SessionRevoked, UserDisabled
from candleviewer.auth.hashing import Hasher
from candleviewer.auth.metrics import auth_sessions_active, normalise_reason
from candleviewer.auth.models import MintedSession, UserStatus
from candleviewer.auth.session_service import SessionService
from candleviewer.auth.step_up import carried_grants
from candleviewer.auth.view_as import ViewAsState

from .session_fakes import FakeSessionRepository

_NOW = datetime(2026, 10, 31, 12, 0, 0, tzinfo=UTC)
_FP = "ab" * 32  # a hex SHA-256: the fingerprint of the request a one-shot grant binds
_ONCE = f"once:killswitch:{uuid.UUID(int=7)}:{_FP}"
_PENDING = f"pending:users:{uuid.UUID(int=8)}"


class _Clock:
    def __init__(self) -> None:
        self.now = _NOW

    def __call__(self) -> datetime:
        return self.now


class _Sink:
    """The revocation sink: what each publish was given, in order."""

    def __init__(self) -> None:
        self.published: list[tuple[str, str]] = []

    async def __call__(self, session_id: str, reason: str) -> None:
        self.published.append((session_id, reason))


def _service(
    repo: FakeSessionRepository, clock: _Clock, sink: _Sink | None = None
) -> SessionService:
    return SessionService(
        repo, Hasher(pepper=os.urandom(16).hex()), clock=clock, publish_revocation=sink
    )


def _keep_all(elevations: dict[str, datetime], _now: datetime) -> dict[str, datetime]:
    return dict(elevations)


async def _grants(repo: FakeSessionRepository, minted: MintedSession) -> None:
    """The step-up columns as a step-up leaves them, before its rotation."""
    await repo.save_step_up_state(
        str(minted.session_id),
        elevations={
            "users": _NOW + timedelta(minutes=5),  # a grace window: carried
            _ONCE: _NOW + timedelta(seconds=60),  # the bound one-shot grant just made: carried
            "keys": _NOW - timedelta(seconds=1),  # a lapsed window: dropped
            _PENDING: _NOW + timedelta(minutes=5),  # a pending challenge: dropped
            "once:killswitch": _NOW + timedelta(minutes=5),  # binds nothing (pre-#2304): dropped
        },
        failures=1,
        readonly_until=None,
    )


async def test_rotate_claims_the_session_as_rotated_and_mints_the_drawn_successor() -> None:
    repo, clock = FakeSessionRepository(), _Clock()
    service = _service(repo, clock)
    old = await service.mint(str(uuid.uuid4()))
    successor = uuid.uuid4()

    outcome = await service.rotate(
        str(old.session_id), successor_id=successor, carry_grants=_keep_all
    )

    assert outcome.previous_session_id == old.session_id
    assert outcome.minted.session_id == successor
    assert repo.sessions[str(old.session_id)].revoked_reason == "rotated"
    assert repo.sessions[str(successor)].revoked_at is None
    assert outcome.minted.refresh_token != old.refresh_token
    assert outcome.minted.access_token != old.access_token


async def test_rotate_old_tokens_are_refused_and_the_new_ones_authenticate() -> None:
    repo, clock = FakeSessionRepository(), _Clock()
    service = _service(repo, clock)
    old = await service.mint(str(uuid.uuid4()))

    outcome = await service.rotate(
        str(old.session_id), successor_id=uuid.uuid4(), carry_grants=_keep_all
    )

    with pytest.raises(SessionRevoked):
        await service.authenticate_access_token(old.access_token)
    live = await service.authenticate_access_token(outcome.minted.access_token)
    assert live.id == outcome.minted.session_id


async def test_rotate_links_the_successor_so_a_replayed_old_refresh_kills_the_family() -> None:
    repo, clock, sink = FakeSessionRepository(), _Clock(), _Sink()
    service = _service(repo, clock, sink)
    old = await service.mint(str(uuid.uuid4()))
    outcome = await service.rotate(
        str(old.session_id), successor_id=uuid.uuid4(), carry_grants=_keep_all
    )

    with pytest.raises(RefreshReuseDetected):
        await service.refresh(old.refresh_token)

    successor = repo.sessions[str(outcome.minted.session_id)]
    assert successor.revoked_reason == "rotation_reuse"
    assert {sid for sid, _ in sink.published} == {str(old.session_id), str(successor.id)}


async def test_rotate_carries_refresh_list_from_the_claims_row() -> None:
    repo, clock = FakeSessionRepository(), _Clock()
    service = _service(repo, clock)
    owner, target = uuid.uuid4(), uuid.uuid4()
    view = ViewAsState(
        context_id=uuid.uuid4(),
        target_user_id=target,
        started_at=_NOW,
        expires_at=_NOW + timedelta(minutes=30),
    )
    old = await service.mint(
        str(owner),
        ip="100.64.0.7",
        user_agent="cv-test",
        device_label="desk",
        is_electron=True,
        idle_timeout_s=1200,
        expires_at=_NOW + timedelta(hours=3),
        view_as=view,
        last_seen_at=_NOW - timedelta(minutes=4),
        step_up_failures=2,
        readonly_until=_NOW + timedelta(minutes=2),
        locked_at=_NOW - timedelta(minutes=1),
    )
    clock.now = _NOW + timedelta(minutes=1)

    outcome = await service.rotate(
        str(old.session_id), successor_id=uuid.uuid4(), carry_grants=_keep_all
    )

    new = repo.sessions[str(outcome.minted.session_id)]
    assert (new.expires_at, new.idle_timeout_s) == (_NOW + timedelta(hours=3), 1200)
    assert new.last_seen_at == _NOW - timedelta(minutes=4)  # a rotation is no user activity
    assert new.view_as == view
    assert (new.step_up_failures, new.readonly_until) == (2, _NOW + timedelta(minutes=2))
    assert new.locked_at == _NOW - timedelta(minutes=1)  # a rotation never lifts a lock
    assert (new.ip, new.user_agent, new.device_label, new.is_electron) == (
        "100.64.0.7",
        "cv-test",
        "desk",
        True,
    )
    assert new.mfa_satisfied_at is not None


async def test_rotate_takes_the_request_address_and_agent_when_given() -> None:
    repo, clock = FakeSessionRepository(), _Clock()
    service = _service(repo, clock)
    old = await service.mint(str(uuid.uuid4()), ip="100.64.0.7", user_agent="old")

    outcome = await service.rotate(
        str(old.session_id),
        successor_id=uuid.uuid4(),
        carry_grants=_keep_all,
        ip="100.64.0.9",
        user_agent="new",
    )

    new = repo.sessions[str(outcome.minted.session_id)]
    assert (new.ip, new.user_agent) == ("100.64.0.9", "new")


async def test_rotate_carries_the_grants_the_step_up_keeps_and_drops_the_challenge() -> None:
    repo, clock = FakeSessionRepository(), _Clock()
    service = _service(repo, clock)
    old = await service.mint(str(uuid.uuid4()))
    await _grants(repo, old)

    outcome = await service.rotate(
        str(old.session_id), successor_id=uuid.uuid4(), carry_grants=carried_grants
    )

    new = repo.sessions[str(outcome.minted.session_id)]
    assert new.step_up_elevations == {
        "users": _NOW + timedelta(minutes=5),
        _ONCE: _NOW + timedelta(seconds=60),
    }
    assert new.step_up_failures == 1


async def test_rotate_reads_the_grants_from_the_claim_not_from_an_earlier_read() -> None:
    """A grant the session used before the claim (here: spent between a read and the rotation)
    is not carried, so it is used once at most (C-5)."""
    repo, clock = FakeSessionRepository(), _Clock()
    service = _service(repo, clock)
    old = await service.mint(str(uuid.uuid4()))
    await _grants(repo, old)
    spent = await repo.consume_step_up_key(str(old.session_id), key=_ONCE, now=_NOW)
    assert spent is not None

    outcome = await service.rotate(
        str(old.session_id), successor_id=uuid.uuid4(), carry_grants=carried_grants
    )

    assert _ONCE not in repo.sessions[str(outcome.minted.session_id)].step_up_elevations


async def test_rotate_publishes_nothing() -> None:
    """C-3: the step-up's sockets re-`auth` in place, as after a refresh (23 section 4.1)."""
    repo, clock, sink = FakeSessionRepository(), _Clock(), _Sink()
    service = _service(repo, clock, sink)
    old = await service.mint(str(uuid.uuid4()))

    await service.rotate(str(old.session_id), successor_id=uuid.uuid4(), carry_grants=_keep_all)

    assert sink.published == []


async def test_rotate_leaves_the_active_session_gauge_where_it_was() -> None:
    """The claim counts down what the mint counts up (refresh's claim does not: out of scope)."""
    repo, clock = FakeSessionRepository(), _Clock()
    service = _service(repo, clock)
    old = await service.mint(str(uuid.uuid4()))
    before = auth_sessions_active._value.get()

    await service.rotate(str(old.session_id), successor_id=uuid.uuid4(), carry_grants=_keep_all)

    assert auth_sessions_active._value.get() == before


async def test_rotate_loses_the_claim_to_a_refresh_and_mints_nothing() -> None:
    """C-8: of a rotation and a refresh of one session exactly one wins; no grace."""
    repo, clock = FakeSessionRepository(), _Clock()
    service = _service(repo, clock)
    old = await service.mint(str(uuid.uuid4()))
    refreshed = await service.refresh(old.refresh_token)
    successor = uuid.uuid4()
    before = auth_sessions_active._value.get()

    with pytest.raises(SessionRevoked):
        await service.rotate(str(old.session_id), successor_id=successor, carry_grants=_keep_all)

    assert str(successor) not in repo.sessions
    assert repo.sessions[str(refreshed.minted.session_id)].revoked_at is None
    assert auth_sessions_active._value.get() == before


async def test_rotate_of_a_revoked_session_claims_nothing() -> None:
    repo, clock = FakeSessionRepository(), _Clock()
    service = _service(repo, clock)
    old = await service.mint(str(uuid.uuid4()))
    await service.revoke(str(old.session_id), reason="logout")

    with pytest.raises(SessionRevoked):
        await service.rotate(str(old.session_id), successor_id=uuid.uuid4(), carry_grants=_keep_all)

    assert repo.sessions[str(old.session_id)].revoked_reason == "logout"


async def test_rotate_of_a_disabled_user_keeps_the_claim_and_mints_nothing() -> None:
    """A disable that commits after the claim: the mint refuses (#2911), the claim stands."""
    repo, clock = FakeSessionRepository(), _Clock()
    service = _service(repo, clock)
    user = uuid.uuid4()
    old = await service.mint(str(user))
    repo.user_statuses[str(user)] = UserStatus.DISABLED
    successor = uuid.uuid4()

    with pytest.raises(UserDisabled):
        await service.rotate(str(old.session_id), successor_id=successor, carry_grants=_keep_all)

    assert repo.sessions[str(old.session_id)].revoked_reason == "rotated"
    assert str(successor) not in repo.sessions
    assert repo.rotation_next == {}


async def test_mint_inserts_the_step_up_elevations_it_is_given() -> None:
    repo, clock = FakeSessionRepository(), _Clock()
    grants = {"users": _NOW + timedelta(minutes=5)}

    minted = await _service(repo, clock).mint(str(uuid.uuid4()), step_up_elevations=grants)

    assert repo.sessions[str(minted.session_id)].step_up_elevations == grants


async def test_mint_without_step_up_elevations_starts_with_none() -> None:
    repo, clock = FakeSessionRepository(), _Clock()

    minted = await _service(repo, clock).mint(str(uuid.uuid4()))

    assert repo.sessions[str(minted.session_id)].step_up_elevations == {}


def test_carried_grants_keeps_live_windows_and_bound_grants_only() -> None:
    elevations = {
        "users": _NOW + timedelta(minutes=5),
        _ONCE: _NOW + timedelta(seconds=60),
        "keys": _NOW,  # expires now: lapsed
        _PENDING: _NOW + timedelta(minutes=5),
        "once:killswitch": _NOW + timedelta(minutes=5),
        "once:users:" + str(uuid.UUID(int=9)) + ":" + _FP: _NOW + timedelta(seconds=60),
        "nonsense": _NOW + timedelta(minutes=5),
    }

    assert carried_grants(elevations, _NOW) == {
        "users": _NOW + timedelta(minutes=5),
        _ONCE: _NOW + timedelta(seconds=60),
    }


async def test_revoke_all_with_families_publishes_every_member_of_each_family() -> None:
    """C-3: a socket still on a session a refresh rotated out closes too (23 :472)."""
    repo, clock, sink = FakeSessionRepository(), _Clock(), _Sink()
    service = _service(repo, clock, sink)
    user = str(uuid.uuid4())
    first = await service.mint(user)
    refreshed = await service.refresh(first.refresh_token)
    other = await service.mint(user)

    revoked = await service.revoke_all(user, reason="role_changed", families=True)

    assert {r.id for r in revoked} == {refreshed.minted.session_id, other.session_id}
    assert sorted(sink.published) == sorted(
        (str(sid), "role_changed")
        for sid in (first.session_id, refreshed.minted.session_id, other.session_id)
    )


async def test_revoke_all_without_families_publishes_the_revoked_rows_only() -> None:
    repo, clock, sink = FakeSessionRepository(), _Clock(), _Sink()
    service = _service(repo, clock, sink)
    user = str(uuid.uuid4())
    first = await service.mint(user)
    refreshed = await service.refresh(first.refresh_token)

    await service.revoke_all(user, reason="logout_all")

    assert sink.published == [(str(refreshed.minted.session_id), "logout_all")]


async def test_revoke_all_publishes_the_rest_when_a_family_cannot_be_walked(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo, clock, sink = FakeSessionRepository(), _Clock(), _Sink()
    service = _service(repo, clock, sink)
    user = str(uuid.uuid4())
    first = await service.mint(user)
    refreshed = await service.refresh(first.refresh_token)

    async def broken(session_id: str) -> tuple[str, ...]:
        raise OSError("store down")

    monkeypatch.setattr(repo, "walk_rotation_family", broken)
    with structlog.testing.capture_logs() as logs:
        revoked = await service.revoke_all(user, reason="role_changed", families=True)

    assert [r.id for r in revoked] == [refreshed.minted.session_id]
    assert sink.published == [(str(refreshed.minted.session_id), "role_changed")]
    assert [e["event"] for e in logs] == ["auth.session_family_publish_failed"]
    assert logs[0]["error"] == "OSError"


async def test_live_sessions_lists_the_users_live_rows_only() -> None:
    repo, clock = FakeSessionRepository(), _Clock()
    service = _service(repo, clock)
    user = str(uuid.uuid4())
    kept = await service.mint(user)
    ended = await service.mint(user)
    await service.mint(str(uuid.uuid4()))
    await service.revoke(str(ended.session_id), reason="logout")

    assert [r.id for r in await service.live_sessions(user)] == [kept.session_id]


def test_a_role_change_is_its_own_revocation_reason_not_other() -> None:
    assert normalise_reason("role_changed") == "role_changed"

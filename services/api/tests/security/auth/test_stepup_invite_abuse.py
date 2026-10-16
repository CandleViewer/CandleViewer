"""E09-X02 step-up (SR-025/U18) and invite (U12/SR-027) abuse cases."""

from __future__ import annotations

import uuid
from datetime import timedelta

import pytest

from candleviewer.auth.errors import InviteRejected, StepUpCodeInvalid, StepUpRequired
from candleviewer.auth.invite_service import INVITE_TTL, InviteService
from tests.unit.auth.test_invite_service import (
    GOOD_PW,
    FakeHasher,
    FakeMfa,
    FakeRepo,
    _req,
    ok_audit,
)
from tests.unit.auth.test_invite_service import (
    Clock as InviteClock,
)
from tests.unit.auth.test_step_up import PASSWORD, _code, _setup


async def test_ac_stepup_01_elevation_not_transplantable_across_session_or_action() -> None:
    svc, clock, seed, user, _ = await _setup()
    await svc.step_up(str(user), "s1", "keys", _code(seed, clock), PASSWORD)
    with pytest.raises(StepUpRequired):  # other session of same user
        await svc.require_elevation("s2", "keys")
    with pytest.raises(StepUpRequired):  # other action class
        await svc.require_elevation("s1", "users")
    with pytest.raises(StepUpRequired):  # fabricated class names
        await svc.require_elevation("s1", "keys; admin")


async def test_ac_stepup_02_grace_cannot_be_extended_and_replay_refused() -> None:
    svc, clock, seed, user, _ = await _setup()
    code = _code(seed, clock)
    await svc.step_up(str(user), "s1", "keys", code, PASSWORD)
    clock.now += timedelta(minutes=4)
    await svc.require_elevation("s1", "keys")
    with pytest.raises(StepUpCodeInvalid):  # same code replayed to refresh the window
        await svc.step_up(str(user), "s1", "keys", code, PASSWORD)
    clock.now += timedelta(minutes=2)
    with pytest.raises(StepUpRequired):
        await svc.require_elevation("s1", "keys")


async def test_ac_stepup_03_other_users_totp_code_does_not_elevate() -> None:
    svc, clock, seed, _user, _ = await _setup()
    with pytest.raises(StepUpCodeInvalid):
        await svc.step_up(str(uuid.uuid4()), "s1", "keys", _code(seed, clock), PASSWORD)


async def test_ac_stepup_04_unknown_session_cannot_elevate() -> None:
    svc, clock, seed, user, _ = await _setup()
    with pytest.raises(StepUpRequired):
        await svc.step_up(str(user), "no-such-session", "keys", _code(seed, clock), PASSWORD)


def _svc() -> tuple[InviteService, FakeRepo, InviteClock]:
    repo, clock = FakeRepo(), InviteClock()
    return InviteService(repo, FakeHasher(), FakeMfa(), clock=clock), repo, clock  # type: ignore[arg-type]


async def test_ac_inv_01_token_guessing_all_rejected_uniformly() -> None:  # U12
    svc, _, _ = _svc()
    await svc.create(_req(), invited_by=uuid.uuid4(), audit=ok_audit)
    reasons = set()
    for i in range(50):
        with pytest.raises(InviteRejected) as e:
            await svc.inspect(f"guess-{i}".ljust(43, "A"), source_ip="7.7.7.7")
        reasons.add(e.value.reason)
    assert reasons == {"unknown"}


async def test_ac_inv_02_expired_invite_never_yields_redemption() -> None:
    svc, _, clock = _svc()
    inv = await svc.create(_req(), invited_by=uuid.uuid4(), audit=ok_audit)
    clock.now += INVITE_TTL + timedelta(seconds=1)
    with pytest.raises(InviteRejected):
        await svc.begin_redemption(inv.token, password=GOOD_PW, source_ip="1.1.1.1")


async def test_ac_inv_03_reuse_after_acceptance_rejected() -> None:
    svc, _, _ = _svc()
    inv = await svc.create(_req(), invited_by=uuid.uuid4(), audit=ok_audit)
    await svc.begin_redemption(inv.token, password=GOOD_PW, source_ip="1.1.1.1")
    with pytest.raises(InviteRejected):
        await svc.begin_redemption(inv.token, password=GOOD_PW, source_ip="2.2.2.2")


async def test_ac_inv_04_cannot_invite_pre_elevated_owner() -> None:  # SR-027
    with pytest.raises(ValueError):
        _req(role="owner")

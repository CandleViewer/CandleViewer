"""InviteService (E09-S05): single-use, expiry, role immutability, abandoned enrolment."""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any, get_args, get_type_hints

import pytest

from candleviewer.audit.writer import AuditUnavailable, AuditWriterStopped
from candleviewer.auth.errors import (
    InviteConflict,
    InviteNotFound,
    InviteRejected,
    MfaCodeInvalid,
    PasswordPolicyViolation,
)
from candleviewer.auth.invite_service import (
    ENROLL_WINDOW,
    INVITE_TTL,
    InviteService,
    check_password_policy,
    hash_token,
)
from candleviewer.auth.models import (
    EnrollmentStart,
    InviteCreateRequest,
    InviteRecord,
    UserStatus,
)

T0 = datetime(2026, 10, 1, 12, 0, tzinfo=UTC)
GOOD_PW = "correct horse battery"


class FakeRepo:
    def __init__(self) -> None:
        self.rows: dict[str, InviteRecord] = {}
        self.emails: set[str] = set()

    async def create_user_with_invite(self, **kw: Any) -> bool:
        if kw["email"] in self.emails:
            return False
        await kw["audit"](kw["user_id"], kw["role"])  # write-ahead: before any mutation
        self.emails.add(kw["email"])
        self.rows[kw["token_hash"]] = InviteRecord(
            id=kw["invite_id"],
            user_id=kw["user_id"],
            role=kw["role"],
            username=kw["username"],
            email=kw["email"],
            display_name=kw["display_name"],
            expires_at=kw["expires_at"],
            created_at=T0,
        )
        return True

    async def find_by_token_hash(self, token_hash: str) -> InviteRecord | None:
        return self.rows.get(token_hash)

    async def consume(
        self, token_hash: str, *, now: datetime, pending_password_hash: str
    ) -> InviteRecord | None:
        row = self.rows.get(token_hash)
        if row is None or row.consumed_at or row.revoked_at or row.expires_at <= now:
            return None
        new = row.model_copy(
            update={"consumed_at": now, "pending_password_hash": pending_password_hash}
        )
        self.rows[token_hash] = new
        return new

    async def find_consumed_for_user(self, user_id: uuid.UUID) -> InviteRecord | None:
        return None

    async def activate_user(self, user_id: uuid.UUID, **kw: Any) -> bool:
        for h, r in self.rows.items():
            if r.user_id == user_id and r.user_status is UserStatus.INVITED:
                self.rows[h] = r.model_copy(update={"user_status": UserStatus.ACTIVE})
                return True
        return False

    async def downgrade_to_viewer(self, user_id: uuid.UUID) -> None:
        for h, r in list(self.rows.items()):
            if r.user_id == user_id:
                self.rows[h] = r.model_copy(update={"role": "viewer"})

    def _open(self, user_id: uuid.UUID) -> list[str]:
        rows = self.rows.items()
        return [h for h, r in rows if r.user_id == user_id and not (r.consumed_at or r.revoked_at)]

    async def reissue(self, user_id: uuid.UUID, **kw: Any) -> InviteRecord | None:
        hits = self._open(user_id)
        if not hits:
            return None
        old = self.rows[hits[0]]
        await kw["audit"](user_id, old.role)  # write-ahead: before any mutation
        for h in hits:
            self.rows[h] = self.rows[h].model_copy(update={"revoked_at": kw["now"]})
        fresh = old.model_copy(update={"id": kw["invite_id"], "expires_at": kw["expires_at"]})
        self.rows[kw["token_hash"]] = fresh
        return fresh

    async def revoke_open(self, user_id: uuid.UUID, *, now: datetime, audit: Any) -> bool:
        hits = self._open(user_id)
        if hits:
            await audit(user_id, self.rows[hits[0]].role)  # write-ahead: before any mutation
        for h in hits:
            self.rows[h] = self.rows[h].model_copy(update={"revoked_at": now})
        return bool(hits)

    async def list_pending(self, *, now: datetime) -> tuple[InviteRecord, ...]:
        return tuple(r for r in self.rows.values() if not r.consumed_at and not r.revoked_at)


class FakeHasher:
    async def hash(self, password: str, params: Any) -> str:
        return "$argon2id$fake$" + password[:2]


class FakeMfa:
    async def enroll(self, user_id: str, request: Any, *, account_name: str) -> Any:
        return EnrollmentStart(
            method_id=uuid.uuid4(), otpauth_uri="otpauth://x", secret_base32="AAAA"
        )

    async def confirm_enrollment(
        self, user_id: str, *, method_id: str, code: str
    ) -> tuple[Any, tuple[str, ...]]:
        if code != "123456":
            raise MfaCodeInvalid("bad")
        return "totp", ("rc-1", "rc-2")


class Clock:
    def __init__(self) -> None:
        self.now = T0

    def __call__(self) -> datetime:
        return self.now


async def _noop_audit(rec: Any, stored_role: str) -> None:
    return None


async def ok_audit(user_id: uuid.UUID, role: str) -> None:
    """Accepting write-ahead audit hook of an owner invite action (#2510)."""


def _make() -> tuple[InviteService, FakeRepo, Clock]:
    repo, clock = FakeRepo(), Clock()
    svc = InviteService(repo, FakeHasher(), FakeMfa(), clock=clock)  # type: ignore[arg-type]  # fakes
    return svc, repo, clock


def _req(email: str = "ann@example.com", role: str = "viewer") -> InviteCreateRequest:
    return InviteCreateRequest.model_validate(
        {"email": email, "username": "annie", "roles": [role]}
    )


async def test_create_returns_high_entropy_token_stored_only_as_hash() -> None:
    svc, repo, _ = _make()
    inv = await svc.create(_req(), invited_by=uuid.uuid4(), audit=ok_audit)
    assert len(inv.token) >= 43
    assert inv.token not in repo.rows
    assert hash_token(inv.token) in repo.rows
    assert inv.expires_at == T0 + INVITE_TTL


async def test_create_duplicate_email_conflicts() -> None:
    svc, _, _ = _make()
    await svc.create(_req(), invited_by=uuid.uuid4(), audit=ok_audit)
    with pytest.raises(InviteConflict):
        await svc.create(_req(), invited_by=uuid.uuid4(), audit=ok_audit)


def test_owner_role_cannot_be_invited() -> None:
    with pytest.raises(ValueError):
        _req(role="owner")


def test_manager_invite_refused() -> None:
    with pytest.raises(ValueError):
        _req(role="manager")


def test_viewer_invite_accepted_by_model() -> None:
    assert _req(role="viewer").roles[0].value == "viewer"


async def test_legacy_manager_invite_is_accepted_as_viewer() -> None:
    svc, repo, _ = _make()
    inv = await svc.create(_req(), invited_by=uuid.uuid4(), audit=ok_audit)
    h = hash_token(inv.token)
    repo.rows[h] = repo.rows[h].model_copy(update={"role": "manager"})  # legacy row
    await svc.begin_redemption(inv.token, password=GOOD_PW, source_ip="1.1.1.1")
    rec, _ = await svc.complete_redemption(
        inv.token, method_id="m", code="123456", source_ip="1.1.1.1", audit_downgrade=_noop_audit
    )
    assert rec.role == "viewer" and rec.downgraded_from == "manager"
    assert repo.rows[h].role == "viewer"


async def test_viewer_invite_redemption_is_not_flagged_downgraded() -> None:
    svc, _, _ = _make()
    inv = await svc.create(_req(), invited_by=uuid.uuid4(), audit=ok_audit)
    await svc.begin_redemption(inv.token, password=GOOD_PW, source_ip="1.1.1.1")
    rec, _ = await svc.complete_redemption(
        inv.token, method_id="m", code="123456", source_ip="1.1.1.1", audit_downgrade=_noop_audit
    )
    assert rec.downgraded_from is None


async def test_invite_accepted_end_to_end_activates_user() -> None:
    svc, _, _ = _make()
    inv = await svc.create(_req(), invited_by=uuid.uuid4(), audit=ok_audit)
    await svc.begin_redemption(inv.token, password=GOOD_PW, source_ip="1.1.1.1")
    rec, codes = await svc.complete_redemption(
        inv.token, method_id="m", code="123456", source_ip="1.1.1.1", audit_downgrade=_noop_audit
    )
    assert rec.role == "viewer" and codes == ("rc-1", "rc-2")


async def test_expired_token_rejected_after_72h() -> None:
    svc, _, clock = _make()
    inv = await svc.create(_req(), invited_by=uuid.uuid4(), audit=ok_audit)
    clock.now = T0 + INVITE_TTL
    with pytest.raises(InviteRejected) as e:
        await svc.inspect(inv.token, source_ip="1.1.1.1")
    assert e.value.reason == "expired"


async def test_token_reuse_rejected() -> None:
    svc, _, _ = _make()
    inv = await svc.create(_req(), invited_by=uuid.uuid4(), audit=ok_audit)
    await svc.begin_redemption(inv.token, password=GOOD_PW, source_ip="1.1.1.1")
    with pytest.raises(InviteRejected) as e:
        await svc.begin_redemption(inv.token, password=GOOD_PW, source_ip="1.1.1.1")
    assert e.value.reason == "redeemed"


async def test_unknown_token_rejected() -> None:
    svc, _, _ = _make()
    with pytest.raises(InviteRejected) as e:
        await svc.inspect("x" * 40, source_ip="1.1.1.1")
    assert e.value.reason == "unknown"


async def test_abandoned_enrolment_leaves_user_invited() -> None:
    svc, repo, clock = _make()
    inv = await svc.create(_req(), invited_by=uuid.uuid4(), audit=ok_audit)
    await svc.begin_redemption(inv.token, password=GOOD_PW, source_ip="1.1.1.1")
    clock.now = T0 + ENROLL_WINDOW + timedelta(seconds=1)
    with pytest.raises(InviteRejected):
        await svc.complete_redemption(
            inv.token,
            method_id="m",
            code="123456",
            source_ip="1.1.1.1",
            audit_downgrade=_noop_audit,
        )
    assert repo.rows[hash_token(inv.token)].user_status is UserStatus.INVITED


async def test_wrong_totp_code_does_not_activate() -> None:
    svc, repo, _ = _make()
    inv = await svc.create(_req(), invited_by=uuid.uuid4(), audit=ok_audit)
    await svc.begin_redemption(inv.token, password=GOOD_PW, source_ip="1.1.1.1")
    with pytest.raises(InviteRejected) as e:
        await svc.complete_redemption(
            inv.token,
            method_id="m",
            code="000000",
            source_ip="1.1.1.1",
            audit_downgrade=_noop_audit,
        )
    assert e.value.reason == "enrollment_invalid"
    assert repo.rows[hash_token(inv.token)].user_status is UserStatus.INVITED


async def test_concurrent_redemptions_exactly_one_wins() -> None:
    svc, _, _ = _make()
    inv = await svc.create(_req(), invited_by=uuid.uuid4(), audit=ok_audit)
    res = await asyncio.gather(
        *(svc.begin_redemption(inv.token, password=GOOD_PW, source_ip="1.1.1.1") for _ in range(2)),
        return_exceptions=True,
    )
    assert sum(isinstance(r, EnrollmentStart) for r in res) == 1
    assert sum(isinstance(r, InviteRejected) for r in res) == 1


async def test_revoked_token_rejected_and_revoke_unknown_not_found() -> None:
    svc, _, _ = _make()
    inv = await svc.create(_req(), invited_by=uuid.uuid4(), audit=ok_audit)
    await svc.revoke(inv.user_id, audit=ok_audit)
    with pytest.raises(InviteRejected) as e:
        await svc.inspect(inv.token, source_ip="1.1.1.1")
    assert e.value.reason == "revoked"
    with pytest.raises(InviteNotFound):
        await svc.revoke(uuid.uuid4(), audit=ok_audit)


async def test_repeated_rejections_trip_ip_throttle() -> None:
    svc, _, _ = _make()
    for _ in range(10):
        with pytest.raises(InviteRejected):
            await svc.inspect("y" * 40, source_ip="9.9.9.9")
    assert svc.is_blocked("9.9.9.9")
    assert not svc.is_blocked("8.8.8.8")


@pytest.mark.parametrize("pw", ["short", "password1234", "aaaaaaaaaaaaaa", "annie-annie-annie"])
def test_password_policy_rejects_weak(pw: str) -> None:
    with pytest.raises(PasswordPolicyViolation):
        check_password_policy(pw, username="annie", email="ann@example.com")


def test_password_policy_accepts_good() -> None:
    check_password_policy(GOOD_PW, username="annie", email="ann@example.com")


async def test_abandoned_enrolment_cannot_sign_in_through_real_login() -> None:
    """AC: password set, TOTP abandoned -> a real LoginService.login is refused."""
    from candleviewer.auth.errors import InvalidCredentials
    from candleviewer.auth.hashing import Hasher
    from candleviewer.auth.login_service import LoginService
    from candleviewer.auth.models import LoginRequest, MfaMethodKind
    from candleviewer.auth.throttle import PerIpLoginThrottle
    from tests.unit.auth.auth_fakes import FakeUserRepository, make_user

    class _Capture(FakeRepo):
        placeholder = ""

        async def create_user_with_invite(self, **kw: Any) -> bool:
            self.placeholder = kw["placeholder_password_hash"]
            return await super().create_user_with_invite(**kw)

    repo, clock = _Capture(), Clock()
    svc = InviteService(repo, FakeHasher(), FakeMfa(), clock=clock)  # type: ignore[arg-type]  # fakes
    inv = await svc.create(_req(), invited_by=uuid.uuid4(), audit=ok_audit)
    await svc.begin_redemption(inv.token, password=GOOD_PW, source_ip="1.1.1.1")
    clock.now = T0 + ENROLL_WINDOW + timedelta(seconds=1)
    with pytest.raises(InviteRejected):
        await svc.complete_redemption(
            inv.token,
            method_id="m",
            code="123456",
            source_ip="1.1.1.1",
            audit_downgrade=_noop_audit,
        )
    row = repo.rows[hash_token(inv.token)]
    assert row.user_status is UserStatus.INVITED

    users = FakeUserRepository()
    users.add(
        make_user(
            username=row.username,
            email=row.email,
            password_hash=repo.placeholder,
            status=UserStatus.INVITED,
            mfa_methods=(MfaMethodKind.TOTP,),
        )
    )
    login = LoginService(
        users, Hasher(pepper="p"), per_ip_throttle=PerIpLoginThrottle(max_attempts=1000)
    )
    for pw in (GOOD_PW, ""):
        with pytest.raises(InvalidCredentials):
            await login.login(
                LoginRequest(identifier=row.username, password=pw or "x" * 12), source_ip="2.2.2.2"
            )


def _sample(metric: Any, **labels: str) -> float:
    return float(metric.labels(**labels)._value.get()) if labels else float(metric._value.get())


async def test_invite_metrics_count_created_redeemed_rejected() -> None:
    from candleviewer.auth import metrics as m

    created0 = _sample(m.users_invites_created_total, role="viewer")
    redeemed0 = _sample(m.users_invites_redeemed_total)
    rejected0 = _sample(m.users_invites_rejected_total, reason="unknown")
    svc, _, _ = _make()
    inv = await svc.create(_req(), invited_by=uuid.uuid4(), audit=ok_audit)
    assert _sample(m.users_invites_created_total, role="viewer") == created0 + 1
    await svc.begin_redemption(inv.token, password=GOOD_PW, source_ip="2.2.2.2")
    await svc.complete_redemption(
        inv.token, method_id="m", code="123456", source_ip="2.2.2.2", audit_downgrade=_noop_audit
    )
    assert _sample(m.users_invites_redeemed_total) == redeemed0 + 1
    with pytest.raises(InviteRejected):
        await svc.inspect("z" * 40, source_ip="2.2.2.2")
    assert _sample(m.users_invites_rejected_total, reason="unknown") == rejected0 + 1


def test_refuse_takes_only_the_two_tamper_reasons() -> None:
    # The reason is the `users_invites_rejected_total` label: a Literal keeps a caller from opening
    # its cardinality (#2319); mypy checks every caller against it.
    reason = get_type_hints(InviteService.refuse)["reason"]
    assert set(get_args(reason)) == {"role_tamper", "identity_tamper"}


@pytest.mark.parametrize("exc", [AuditUnavailable("wal full"), AuditWriterStopped()])
async def test_legacy_downgrade_aborted_when_audit_write_fails(exc: Exception) -> None:
    svc, repo, _ = _make()
    inv = await svc.create(_req(), invited_by=uuid.uuid4(), audit=ok_audit)
    h = hash_token(inv.token)
    repo.rows[h] = repo.rows[h].model_copy(update={"role": "manager"})
    await svc.begin_redemption(inv.token, password=GOOD_PW, source_ip="1.1.1.1")

    async def failing(rec: Any, stored_role: str) -> None:
        raise exc

    with pytest.raises(type(exc)):
        await svc.complete_redemption(
            inv.token, method_id="m", code="123456", source_ip="1.1.1.1", audit_downgrade=failing
        )
    assert repo.rows[h].role == "manager"  # no role change persisted
    assert repo.rows[h].user_status is UserStatus.INVITED  # not activated


async def test_legacy_downgrade_without_hook_fails_closed() -> None:
    svc, repo, _ = _make()
    inv = await svc.create(_req(), invited_by=uuid.uuid4(), audit=ok_audit)
    h = hash_token(inv.token)
    repo.rows[h] = repo.rows[h].model_copy(update={"role": "manager"})
    await svc.begin_redemption(inv.token, password=GOOD_PW, source_ip="1.1.1.1")
    with pytest.raises(InviteRejected):
        await svc.complete_redemption(
            inv.token,
            method_id="m",
            code="123456",
            source_ip="1.1.1.1",
            audit_downgrade=None,  # type: ignore[arg-type]  # proves runtime fail-closed
        )
    assert repo.rows[h].role == "manager"

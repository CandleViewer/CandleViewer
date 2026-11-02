"""Unit tests for `candleviewer.auth.service.AuthService` (E09-S01).

Regression for QA bug #1604 defect 1: `candleviewer/auth/*` was still in the
coverage omit list after the real `AuthService.start()`/`login` wiring
landed, so `service.py` (and the rest of the module) sat at 0% covered
without failing the 85% floor. This test exercises the lifecycle directly:
before `start()`, after `start()` with no repository (scaffold), after
`start()` with a real repository (wired), and `stop()`."""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from candleviewer.auth.service import AuthService
from candleviewer.observability.health import HealthStatus
from candleviewer.settings import Environment
from tests.unit.auth.auth_fakes import FakeUserRepository
from tests.unit.auth.mfa_fakes import FakeMfaKeyring, FakeMfaRepository
from tests.unit.auth.session_fakes import FakeSessionRepository


@dataclass
class _FakeSettings:
    environment: Environment


@dataclass
class _FakeAppContext:
    settings: _FakeSettings


def test_auth_service_before_start_is_inactive_and_stopped() -> None:
    service = AuthService()

    assert service.is_active is False
    report = service.health()
    assert report.status is HealthStatus.STOPPED
    assert report.module == "auth"


async def test_auth_service_start_without_repository_stays_scaffold() -> None:
    service = AuthService()

    await service.start(ctx=None)  # type: ignore[arg-type]

    assert service.is_active is False
    report = service.health()
    assert report.status is HealthStatus.OK
    assert "no repository wired" in report.detail
    with pytest.raises(RuntimeError, match="has not wired a real backend"):
        _ = service.login


async def test_auth_service_start_with_repository_wires_login_service() -> None:
    service = AuthService(repository=FakeUserRepository(), pepper="pepper")

    await service.start(ctx=None)  # type: ignore[arg-type]

    assert service.is_active is True
    report = service.health()
    assert report.status is HealthStatus.OK
    assert report.detail == ""
    assert service.login is not None


async def test_auth_service_stop_clears_login_and_marks_stopped() -> None:
    service = AuthService(repository=FakeUserRepository(), pepper="pepper")
    await service.start(ctx=None)  # type: ignore[arg-type]

    await service.stop(grace_s=1.0)

    assert service.is_active is False
    assert service.health().status is HealthStatus.STOPPED


async def test_auth_service_start_without_mfa_repository_stays_scaffold() -> None:
    service = AuthService()

    await service.start(ctx=None)  # type: ignore[arg-type]

    assert service.mfa_is_active is False
    with pytest.raises(RuntimeError, match="has not wired an MfaRepository"):
        _ = service.mfa


async def test_auth_service_start_with_mfa_repository_wires_mfa_service() -> None:
    service = AuthService(
        mfa_repository=FakeMfaRepository(), mfa_keyring=FakeMfaKeyring(b"0" * 32, b"1" * 32)
    )

    await service.start(ctx=None)  # type: ignore[arg-type]

    assert service.mfa_is_active is True
    assert service.mfa is not None


async def test_auth_service_stop_clears_mfa_and_marks_inactive() -> None:
    service = AuthService(
        mfa_repository=FakeMfaRepository(), mfa_keyring=FakeMfaKeyring(b"0" * 32, b"1" * 32)
    )
    await service.start(ctx=None)  # type: ignore[arg-type]

    await service.stop(grace_s=1.0)

    assert service.mfa_is_active is False


@pytest.mark.parametrize("environment", list(Environment))
async def test_auth_service_without_a_keyring_wires_no_mfa_in_any_environment(
    environment: Environment,
) -> None:
    """#2152 (ADR-0009 Amendment 4, "Dev, demo and CI"): there is no process-local fallback key
    left, so without M2's keyring MFA is not wired anywhere, and the start never fails over it."""
    service = AuthService(mfa_repository=FakeMfaRepository())
    ctx = _FakeAppContext(settings=_FakeSettings(environment=environment))

    await service.start(ctx=ctx)  # type: ignore[arg-type]

    assert service.mfa_is_active is False


async def test_auth_service_hands_mfa_the_injected_keyring_and_holds_no_key() -> None:
    """#2152 S5a: both keys sit behind the one keyring the composition root injects (PR #1618
    security review, blocking 1: the recovery-code HMAC key follows the TOTP key's custody)."""
    keyring = FakeMfaKeyring(b"0" * 32, b"1" * 32)
    service = AuthService(mfa_repository=FakeMfaRepository(), mfa_keyring=keyring)
    live = _FakeAppContext(settings=_FakeSettings(environment=Environment.LIVE))
    await service.start(ctx=live)  # type: ignore[arg-type]

    assert service.mfa._keyring is keyring
    assert not [n for n in vars(service) if "key" in n and n != "_mfa_keyring"]


async def test_auth_service_start_with_explicit_key_allows_live_environment() -> None:
    service = AuthService(
        mfa_repository=FakeMfaRepository(),
        mfa_keyring=FakeMfaKeyring(b"0" * 32, b"1" * 32),
    )
    ctx = _FakeAppContext(settings=_FakeSettings(environment=Environment.LIVE))

    await service.start(ctx=ctx)  # type: ignore[arg-type]

    assert service.mfa_is_active is True


def test_auth_service_exposes_its_session_repository_as_the_view_as_store() -> None:
    """#3085 S2b: the view-as service and its sweeper (S4, S5) write the store the session service
    writes, from construction on (no `start()` needed)."""
    repository = FakeSessionRepository()
    service = AuthService(session_repository=repository)

    assert service.view_as_store_is_active is True
    assert service.view_as_store is repository


def test_auth_service_without_a_session_repository_has_no_view_as_store() -> None:
    service = AuthService()

    assert service.view_as_store_is_active is False
    with pytest.raises(RuntimeError, match="without a session repository"):
        _ = service.view_as_store

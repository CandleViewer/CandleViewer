"""E27-T01 QA gap: AccountsService lifecycle (start / stop / health)."""

from __future__ import annotations

from typing import cast

from candleviewer.accounts.service import AccountsService
from candleviewer.app import AppContext
from candleviewer.observability.health import HealthStatus

_CTX = cast(AppContext, object())


def test_health_before_start_is_stopped() -> None:
    report = AccountsService().health()
    assert report.status is HealthStatus.STOPPED


async def test_start_then_health_is_ok() -> None:
    svc = AccountsService()
    await svc.start(_CTX)
    assert svc.health().status is HealthStatus.OK


async def test_stop_returns_health_to_stopped() -> None:
    svc = AccountsService()
    await svc.start(_CTX)
    await svc.stop(1.0)
    assert svc.health().status is HealthStatus.STOPPED


async def test_stop_without_start_is_safe_and_idempotent() -> None:
    svc = AccountsService()
    await svc.stop(0.0)
    await svc.stop(0.0)
    assert svc.health().status is HealthStatus.STOPPED

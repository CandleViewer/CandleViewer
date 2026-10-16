"""SR-016 / SR-125 (#2102): a lockout is audited and reaches the Owner alert path.

The Owner is not notified from inside the request. The notification is the `AuthLockouts` rule
(`infra/prometheus/alerts/system_ticket.yml`) reading the scraped `auth_lockouts_total`, which
Alertmanager routes to the Owner's `ticket` channel (SR-125, SR-126). The last point the
application owns is that series on the scraped registry, so that is where "the notification" is
asserted: it moves once for each lock applied, never for an attempt refused while locked, and
carries nothing but `env`. Delivery of the Alertmanager message itself is not exercised (no
network in tests).

In-process throughout: the real `/auth/login` router and `LoginService` over the in-memory user
repository, a fixed clock. The audit cardinality (one `auth.account_locked` per refused attempt,
none for the failure that trips the lock) is pinned in `test_lockout_audit_route.py`; it is asserted
here next to the notification so one lock event proves both halves of SR-016.
"""

from __future__ import annotations

import re
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from functools import cache
from pathlib import Path
from typing import Any

import httpx
import yaml
from fastapi import FastAPI
from prometheus_client import CollectorRegistry, generate_latest

from candleviewer.api.auth import make_auth_router
from candleviewer.audit.models import AuditOutcome, Severity
from candleviewer.auth.csrf import CsrfCodec
from candleviewer.auth.hashing import Hasher
from candleviewer.auth.login_service import LOCKOUT_DURATION, LOCKOUT_THRESHOLD, LoginService
from candleviewer.auth.metrics import AUTH_EXPORTED_NAMES, export_auth_metrics
from candleviewer.auth.throttle import PerIpLoginThrottle
from tests.unit.auth.auth_fakes import FakeUserRepository, make_user

_CSRF_CODEC = CsrfCodec(b"\x05" * 32)  # SR-041 (#2090): routers require a codec
_NOW = datetime(2026, 1, 1, tzinfo=UTC)
_ENV = "demo"
_IDENTIFIER = "basiltt"
_RIGHT = "correct-horse-battery-staple"
_GUESS = "s3cr3t-guess-9f2c"  # distinctive, so a leak is a plain substring check
_RULES = "infra/prometheus/alerts/system_ticket.yml"


@cache
def _alert_rule() -> dict[str, Any]:
    """The `AuthLockouts` rule as committed: the Owner-facing half of SR-016."""
    path = next(p / _RULES for p in Path(__file__).resolve().parents if (p / _RULES).is_file())
    rules = yaml.safe_load(path.read_text(encoding="utf-8"))["groups"]
    (rule,) = [r for g in rules for r in g["rules"] if r.get("alert") == "AuthLockouts"]
    assert isinstance(rule, dict)
    return rule


def _alert_series() -> str:
    """The one counter the rule reads, taken from its expression, never hard-coded here."""
    names: set[str] = set(re.findall(r"\b[a-z][a-z0-9_]*_total\b", str(_alert_rule()["expr"])))
    (name,) = names
    return name


class _Clock:
    def __init__(self) -> None:
        self.now = _NOW

    def __call__(self) -> datetime:
        return self.now


class _Audit:
    """Keeps every `emit()` call whole; the shared route test keeps only the action names."""

    is_active = True

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    @property
    def writer(self) -> _Audit:
        return self

    async def emit(self, action: str, **kwargs: Any) -> None:
        self.calls.append((action, kwargs))

    def actions(self) -> list[str]:
        return [action for action, _ in self.calls]


class _Auth:
    is_active = True

    def __init__(self, login: LoginService) -> None:
        self.login = login


class _World:
    def __init__(
        self, client: httpx.AsyncClient, audit: _Audit, clock: _Clock, registry: CollectorRegistry
    ) -> None:
        self.client, self.audit, self.clock, self._registry = client, audit, clock, registry

    async def fail(self, times: int) -> list[httpx.Response]:
        """`times` wrong passwords for the one account, one after another."""
        body = {"identifier": _IDENTIFIER, "password": _GUESS}
        return [await self.client.post("/auth/login", json=body) for _ in range(times)]

    def alerts(self) -> float:
        """The scraped value of the series the Owner alert rule reads."""
        return float(self._registry.get_sample_value(_alert_series(), {"env": _ENV}) or 0.0)

    def exposition(self) -> str:
        return generate_latest(self._registry).decode()

    def series_labels(self) -> list[dict[str, str]]:
        return [
            dict(sample.labels)
            for family in self._registry.collect()
            for sample in family.samples
            if sample.name == _alert_series()
        ]


@asynccontextmanager
async def _world() -> AsyncIterator[_World]:
    repo, hasher, clock = FakeUserRepository(), Hasher(pepper="p"), _Clock()
    repo.add(make_user(password_hash=await hasher.hash(_RIGHT)))
    login = LoginService(
        repo, hasher, per_ip_throttle=PerIpLoginThrottle(max_attempts=10_000), clock=clock
    )
    audit, auth, app = _Audit(), _Auth(login), FastAPI()
    app.include_router(make_auth_router(auth, audit, csrf=_CSRF_CODEC), prefix="")  # type: ignore[arg-type]
    registry = CollectorRegistry()
    collector = export_auth_metrics(registry, env=_ENV)
    try:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://t") as client:
            yield _World(client, audit, clock, registry)
    finally:
        collector.close()


async def test_lockout_alert_fires_on_every_lockout() -> None:
    """E09-X01 U27: the series moves once for each lock applied, including a re-lock."""
    async with _world() as world:
        start = world.alerts()
        await world.fail(LOCKOUT_THRESHOLD - 1)
        assert world.alerts() == start  # below the threshold nothing is signalled
        await world.fail(1)  # the failure that applies the lock; a 401 like any wrong password
        assert world.alerts() == start + 1
        world.clock.now += LOCKOUT_DURATION + timedelta(seconds=1)
        await world.fail(1)  # the count resets only on a success, so this failure locks again
        assert world.alerts() == start + 2


async def test_a_lock_is_signalled_when_applied_and_audited_on_each_refused_attempt() -> None:
    """SR-016: one lock event, both halves. The audit trail and the notification series agree."""
    async with _world() as world:
        start = world.alerts()
        burst = await world.fail(LOCKOUT_THRESHOLD)
        assert {r.status_code for r in burst} == {401}
        assert world.alerts() == start + 1
        assert world.audit.actions() == ["auth.login_failed"] * LOCKOUT_THRESHOLD  # no lock row yet

        refused = await world.fail(3)
        assert {r.status_code for r in refused} == {423}
        assert all(int(r.headers["Retry-After"]) > 0 for r in refused)
        locked = [kwargs for action, kwargs in world.audit.calls if action == "auth.account_locked"]
        assert len(locked) == 3
        assert {(k["outcome"], k["severity"]) for k in locked} == {
            (AuditOutcome.DENIED, Severity.WARNING)
        }
        assert world.alerts() == start + 1  # audited each time, but the Owner is not alerted again


async def test_neither_the_alert_series_nor_the_audit_rows_carry_a_credential() -> None:
    """C-12.6: no typed password, no raw identifier; the series has no label but `env`."""
    async with _world() as world:
        await world.fail(LOCKOUT_THRESHOLD + 1)  # a lock and one refusal
        everything = repr(world.audit.calls) + world.exposition()
        assert _GUESS not in everything and _RIGHT not in everything
        assert _IDENTIFIER not in repr(world.audit.calls)  # only the redacted label is audited
        assert world.series_labels() == [{"env": _ENV}]


def test_the_alert_rule_is_a_ticket_for_auth_and_reads_a_series_the_application_serves() -> None:
    rule = _alert_rule()
    assert rule["labels"] == {"severity": "ticket", "component": "auth"}
    assert _alert_series() in AUTH_EXPORTED_NAMES  # an unserved series is a rule that never fires

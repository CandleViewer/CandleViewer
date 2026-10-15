"""#2319 item 1: the session series that moved only on the process-default registry reach the
scraped one. Each is read from a registry that serves `export_auth_metrics` (what Prometheus
scrapes) and moves at its decision point. Before/after deltas: the counters are process-global."""

from __future__ import annotations

import uuid
from collections.abc import Callable, Iterator
from datetime import UTC, datetime

import pytest
from prometheus_client import CollectorRegistry

from candleviewer.audit.models import Severity
from candleviewer.auth.errors import RefreshReuseDetected
from candleviewer.auth.hashing import Hasher
from candleviewer.auth.metrics import export_auth_metrics
from candleviewer.auth.session_service import SessionService
from tests.unit.api.test_sessions_router import _Env
from tests.unit.auth.session_fakes import FakeSessionRepository

Scrape = Callable[..., float]


@pytest.fixture
def scrape() -> Iterator[Scrape]:
    registry = CollectorRegistry()
    collector = export_auth_metrics(registry, env="demo")

    def read(name: str, **labels: str) -> float:
        return float(registry.get_sample_value(name, {"env": "demo", **labels}) or 0.0)

    try:
        yield read
    finally:
        collector.close()


def _service() -> SessionService:
    now = datetime(2026, 9, 30, 12, 0, 0, tzinfo=UTC)
    return SessionService(FakeSessionRepository(), Hasher(pepper="p"), clock=lambda: now)


async def test_refresh_token_reuse_moves_the_scraped_counter(scrape: Scrape) -> None:
    service = _service()
    minted = await service.mint(str(uuid.uuid4()))
    await service.refresh(minted.refresh_token)
    before = scrape("auth_refresh_reuse_total")
    with pytest.raises(RefreshReuseDetected):
        await service.refresh(minted.refresh_token)  # the rotated-out token, replayed
    assert scrape("auth_refresh_reuse_total") == before + 1


async def test_a_replayed_refresh_token_is_scraped_and_still_writes_its_critical_row(
    scrape: Scrape,
) -> None:
    env = _Env()
    minted = await env.mint(uuid.uuid4())
    body = {"refresh_token": minted.refresh_token}
    assert env.client.post("/api/v1/auth/refresh", json=body).status_code == 200
    env.client.cookies.clear()  # the client would otherwise replay the rotated cookie
    before = scrape("auth_refresh_reuse_total")
    assert env.client.post("/api/v1/auth/refresh", json=body).status_code == 401
    assert scrape("auth_refresh_reuse_total") == before + 1
    row = env.audit.writer.events[-1]
    assert (row["action"], row["severity"]) == ("auth.refresh_reuse_detected", Severity.CRITICAL)


async def test_revocations_are_scraped_by_a_closed_reason_set(scrape: Scrape) -> None:
    service = _service()
    user = str(uuid.uuid4())
    first, second = await service.mint(user), await service.mint(user)
    logout, other = (
        scrape("auth_session_revocations_total", reason=r) for r in ("logout", "other")
    )
    await service.revoke(str(first.session_id), reason="logout")
    await service.revoke(str(second.session_id), reason="free-form-" + "x" * 200)  # clamped
    assert scrape("auth_session_revocations_total", reason="logout") == logout + 1
    assert scrape("auth_session_revocations_total", reason="other") == other + 1

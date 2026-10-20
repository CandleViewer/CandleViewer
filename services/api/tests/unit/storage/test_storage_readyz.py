"""#3874: `/readyz` carries one check per real storage tier, from `StorageService.tier_health()`;
the fake backend wires none, so its readiness body is unchanged."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any, cast

import httpx
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import SecretStr

from candleviewer.api.health import make_health_router
from candleviewer.app import create_app
from candleviewer.settings import Environment, Settings
from candleviewer.storage.models import StorageTier
from candleviewer.storage.real_tiers import RealTier, RealTiers
from candleviewer.storage.service import StorageService
from candleviewer.storage.testing import (
    FakeColdTierRepository,
    FakeMarketDataRepository,
    FakeRelationalRepository,
)

if TYPE_CHECKING:
    from candleviewer.app import AppContext

_CTX = cast("AppContext", SimpleNamespace(settings=None))


class _Down:
    """The tiers whose probe fails: a `set` the probes read when they run."""

    def __init__(self) -> None:
        self.tiers: set[str] = set()

    def build(self, _settings: Settings) -> RealTiers:
        def tier(name: StorageTier) -> RealTier:
            async def probe() -> None:
                if name in self.tiers:
                    raise ConnectionError

            async def close(_budget_s: float) -> None:
                return None

            return RealTier(name, probe, close)

        return RealTiers(
            market_data=FakeMarketDataRepository(),
            relational=FakeRelationalRepository(),
            cold=FakeColdTierRepository(),
            tiers=(tier("postgres"), tier("questdb"), tier("cold")),
        )


def _client(service: StorageService | None) -> TestClient:
    app = FastAPI()
    health = service.tier_health if service is not None else None
    app.include_router(make_health_router(Settings(), storage_health=health))
    return TestClient(app)


async def test_readyz_reports_each_real_tier_and_follows_its_probes() -> None:
    down = _Down()
    service = StorageService(backend="real", real_tiers=down.build)
    client = _client(service)
    assert client.get("/readyz").json()["checks"] == []  # before start: no tier yet
    await service.start(_CTX)
    try:
        body = client.get("/readyz").json()
        assert body["status"] == "ok"
        assert body["checks"] == [
            {"name": "storage_postgres", "ok": True, "detail": ""},
            {"name": "storage_questdb", "ok": True, "detail": ""},
            {"name": "storage_cold", "ok": True, "detail": ""},
        ]
        down.tiers |= {"postgres", "questdb"}
        await service.refresh()
        resp = client.get("/readyz")
        assert resp.status_code == 200
        assert resp.json()["status"] == "degraded"
        assert resp.json()["checks"] == [
            {"name": "storage_postgres", "ok": False, "detail": "down"},
            {"name": "storage_questdb", "ok": False, "detail": "degraded"},
            {"name": "storage_cold", "ok": True, "detail": ""},
        ]
        down.tiers.clear()
        await service.refresh()
        assert client.get("/readyz").json()["status"] == "ok"
    finally:
        await service.stop(grace_s=1.0)
    assert client.get("/readyz").json()["checks"] == []  # stopped: no tier


def test_readyz_without_a_storage_source_has_no_storage_check() -> None:
    body = _client(None).get("/readyz").json()
    assert body["status"] == "ok" and body["checks"] == []


def _real_app(tmp_path: Path) -> FastAPI:
    """`create_app` on the real storage backend, with test vectors for auth (no I/O at build)."""
    return create_app(
        Settings(
            environment=Environment.DEMO, storage_backend="real", metrics_enabled=False,
            parquet_root=str(tmp_path / "parquet"), bars_state_root=str(tmp_path / "bars"),
            auth_pepper=SecretStr("test-pepper"), auth_totp_key_hex=SecretStr("11" * 32),
            auth_recovery_hmac_key_hex=SecretStr("22" * 32), auth_csrf_key_hex=SecretStr("33" * 32),
        )
    )  # fmt: skip


async def _app_checks(app: FastAPI) -> list[dict[str, Any]]:
    """`/readyz`'s checks, asked from the loopback peer the app's network guard admits."""
    transport = httpx.ASGITransport(app=app, client=("127.0.0.1", 50000))
    async with httpx.AsyncClient(transport=transport, base_url="https://testserver") as c:
        resp = await c.get("/readyz")
    assert resp.status_code == 200, resp.text
    checks: list[dict[str, Any]] = resp.json()["checks"]
    return checks


async def test_create_app_on_the_real_backend_serves_the_storage_checks(tmp_path: Path) -> None:
    app = _real_app(tmp_path)
    ctx = app.state.app_context
    down = _Down()
    ctx.storage._build_real = down.build  # the tier clients, not the router, are faked
    await ctx.storage.start(ctx)
    try:
        down.tiers.add("cold")
        await ctx.storage.refresh()
        checks = await _app_checks(app)
        assert [c for c in checks if c["name"].startswith("storage_")] == [
            {"name": "storage_postgres", "ok": True, "detail": ""},
            {"name": "storage_questdb", "ok": True, "detail": ""},
            {"name": "storage_cold", "ok": False, "detail": "degraded"},
        ]
    finally:
        await ctx.storage.stop(grace_s=1.0)


async def test_create_app_on_the_fake_backend_serves_no_storage_check() -> None:
    app = create_app(Settings(metrics_enabled=False))
    ctx = app.state.app_context
    await ctx.storage.start(ctx)
    try:
        checks = await _app_checks(app)
        assert [c for c in checks if c["name"].startswith("storage_")] == []
    finally:
        await ctx.storage.stop(grace_s=1.0)

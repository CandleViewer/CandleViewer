"""Composition-root tests (E02-T05 acceptance criterion 3).

Given the composition root, when `create_app()` is called in a unit test
with fake storage clients, then it constructs without touching Postgres,
QuestDB or the network, and `GET /healthz` returns 200 with a build-info body
containing `gitSha`, `version` and `environment`.
"""

from __future__ import annotations

import asyncio
import builtins
import importlib
import socket
import time
from pathlib import Path
from typing import Any, NoReturn

import httpx
import pytest
from fastapi.testclient import TestClient

from candleviewer.app import Supervisor, build_app_context, create_app
from candleviewer.settings import Environment, Settings


def _fake_settings() -> Settings:
    return Settings(environment=Environment.DEMO, git_sha="deadbeef", version="9.9.9")


def test_create_app_touches_no_io(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Structural no-IO check (C-13.7): any socket/DB/HTTP/file access raises."""

    def _boom(*_a: object, **_k: object) -> NoReturn:
        raise AssertionError("create_app() performed I/O")

    create_app(_fake_settings())  # warm imports before patching open()
    monkeypatch.setattr(socket.socket, "connect", _boom)
    monkeypatch.setattr(httpx.Client, "send", _boom)
    monkeypatch.setattr(httpx.AsyncClient, "send", _boom)
    for mod_name in ("asyncpg", "psycopg"):
        try:
            mod = importlib.import_module(mod_name)
        except ImportError:
            continue
        monkeypatch.setattr(mod, "connect", _boom)

    real_open = builtins.open
    allowed = str(tmp_path)

    def _guarded_open(file: Any, *args: Any, **kwargs: Any) -> Any:
        if isinstance(file, int) or str(file).startswith(allowed):
            return real_open(file, *args, **kwargs)
        raise AssertionError(f"create_app() opened {file!r}")

    monkeypatch.setattr(builtins, "open", _guarded_open)
    assert create_app(_fake_settings()) is not None


@pytest.mark.perf
def test_create_app_under_200ms() -> None:
    # Warm up module imports first (import machinery dominates a cold call).
    create_app(_fake_settings())
    started = time.perf_counter()
    app = create_app(_fake_settings())
    elapsed_ms = (time.perf_counter() - started) * 1000
    assert app is not None
    # Ticket "Performance notes" budget (C-13.9): create_app() <=200 ms.
    assert elapsed_ms < 200


def test_healthz_returns_200_with_build_info() -> None:
    app = create_app(_fake_settings())
    client = TestClient(app, client=("127.0.0.1", 50000))
    response = client.get("/healthz")
    assert response.status_code == 200
    body = response.json()
    assert body["git_sha"] == "deadbeef"
    assert body["version"] == "9.9.9"
    assert body["environment"] == "demo"


def test_readyz_returns_200_with_empty_checks_array() -> None:
    app = create_app(_fake_settings())
    client = TestClient(app, client=("127.0.0.1", 50000))
    response = client.get("/readyz")
    assert response.status_code == 200
    body = response.json()
    assert body["checks"] == []


def test_healthz_does_not_leak_internal_hostnames_or_datastore_versions() -> None:
    app = create_app(_fake_settings())
    client = TestClient(app, client=("127.0.0.1", 50000))
    body = client.get("/healthz").json()
    assert set(body.keys()) == {"git_sha", "version", "environment", "status"}


def test_metrics_returns_200_prometheus_exposition_format() -> None:
    # E02-T08 acceptance: prometheus.yml scrapes api:8000/metrics — this
    # asserts the target this ticket wires prometheus.yml at actually exists
    # and returns the Prometheus text-exposition content type.
    app = create_app(_fake_settings())
    client = TestClient(app, client=("127.0.0.1", 50000))
    response = client.get("/metrics")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain")


async def test_supervisor_starts_storage_before_ws_and_stops_in_reverse() -> None:
    ctx = build_app_context(_fake_settings())
    supervisor = Supervisor(ctx)
    await supervisor.start_all()
    assert ctx.storage.health().status.value == "ok"
    assert ctx.ws.health().status.value == "ok"
    await supervisor.stop_all(grace_s=0.1)
    assert ctx.storage.health().status.value == "stopped"
    assert ctx.ws.health().status.value == "stopped"


def test_build_app_context_wires_the_mesh_guard(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    # E09-T04 AC1/AC3/AC5: the guard must exist on `AppContext`, not merely
    # in the `net` package unused — this is the "never wired in" regression.
    ctx = build_app_context(_fake_settings())

    assert ctx.oms_read_only_gate is not None
    assert ctx.oms_read_only_gate.is_read_only is False
    assert ctx.mesh_self_check is not None


def test_create_app_mounts_the_mesh_only_middleware() -> None:
    # E09-T04 AC1: a guard module built but never registered as ASGI
    # middleware provides zero protection — assert it is actually mounted.
    from candleviewer.net import MeshOnlyMiddleware

    app = create_app(_fake_settings())

    middleware_classes = [m.cls for m in app.user_middleware]
    assert MeshOnlyMiddleware in middleware_classes


async def test_oms_service_validator_is_bound_to_the_shared_read_only_gate() -> None:
    # E09-T04 AC3: the OMS validator must consult the *same* gate instance
    # the boot self-check trips, not a disconnected copy.
    ctx = build_app_context(_fake_settings())
    supervisor = Supervisor(ctx)
    await supervisor.start_all()
    try:
        assert ctx.oms.validator is not None
        ctx.oms.validator.assert_order_placement_allowed()  # not read-only yet

        ctx.oms_read_only_gate.trip(reason_code="net.test", reason_text="test")

        from candleviewer.oms.validator import OrderPlacementRefused

        try:
            ctx.oms.validator.assert_order_placement_allowed()
            raise AssertionError("expected OrderPlacementRefused")
        except OrderPlacementRefused:
            pass
    finally:
        await supervisor.stop_all(grace_s=0.1)


def test_readyz_exposes_mesh_binding_safe_from_the_shared_read_only_gate() -> None:
    # QA defect #1578 blocker 2: SCR-137/SCR-016 need the mesh self-check
    # result on a health payload; this is the "never wired in" regression.
    app = create_app(_fake_settings())
    client = TestClient(app, client=("127.0.0.1", 50000))

    body = client.get("/readyz").json()
    assert body["mesh_binding_safe"] is True
    assert body["mesh_reason_code"] is None

    ctx = app.state.app_context
    ctx.oms_read_only_gate.trip(reason_code="net.public_binding_detected", reason_text="bad")

    body = client.get("/readyz").json()
    assert body["mesh_binding_safe"] is False
    assert body["mesh_reason_code"] == "net.public_binding_detected"


async def test_build_app_context_wires_a_system_topic_publisher_to_the_gate() -> None:
    # QA defect #1578 blocker 1: the gate must have a production subscriber
    # publishing onto the `system` WS topic, not merely the mechanism to.
    from candleviewer.bus.models import QueuePolicy

    ctx = build_app_context(_fake_settings())
    assert ctx.mesh_system_topic_publisher is not None

    sub = ctx.bus.bus.subscribe("test", "demo.system", QueuePolicy.CONFLATE_LATEST)
    ctx.oms_read_only_gate.trip(reason_code="net.test", reason_text="test")
    await asyncio.sleep(0)

    payload = sub.get_nowait()
    assert payload["reason_code"] == "net.test"


def test_create_app_mounts_the_admin_audit_router() -> None:
    # QA defect #1596 blocker 1: `AuditQueryService`/`authorize()` existed
    # but no `APIRouter` mounted `/admin/audit*` onto `create_app()`'s
    # FastAPI instance.
    app = create_app(_fake_settings())
    paths: set[str | None] = set()
    for route in app.routes:
        original = getattr(route, "original_router", None)
        if original is not None:
            paths.update(getattr(r, "path", None) for r in original.routes)
        else:
            paths.add(getattr(route, "path", None))
    assert "/admin/audit" in paths
    assert "/admin/audit/verify" in paths
    assert "/admin/audit/export" in paths


def test_accounts_row_counts_store_exists_only_on_the_real_backend() -> None:
    # #2314: the fake backend has no Postgres, so the row gauges stay unset there.
    from candleviewer.app import _build_accounts_counts
    from candleviewer.storage.repositories.accounts_sqlalchemy import SqlAlchemyAccountsStore

    assert _build_accounts_counts(_fake_settings()) is None
    real = Settings(environment=Environment.DEMO, storage_backend="real")
    assert isinstance(_build_accounts_counts(real), SqlAlchemyAccountsStore)


async def test_create_app_wires_the_accounts_row_gauges_to_the_scraped_registry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # #2314: the catalogue gauges on `ctx.metrics` (what /metrics serves), env-scoped reads.
    import candleviewer.app as appmod

    envs: list[str] = []

    class _Counts:
        async def count_accounts_by_kind(self, env: str) -> dict[str, int]:
            envs.append(env)
            return {"sub": 2}

        async def count_api_keys_by_status(self, env: str) -> dict[str, int]:
            envs.append(env)
            return {"invalid": 1}

    monkeypatch.setattr(appmod, "_build_accounts_counts", lambda _settings: _Counts())
    ctx = create_app(_fake_settings()).state.app_context
    assert await ctx.accounts.refresh_once() is True
    sample = ctx.metrics.get_sample_value
    assert sample("cv_accounts_rows", {"env": "demo", "kind": "sub"}) == 2
    assert sample("cv_accounts_rows", {"env": "demo", "kind": "main"}) == 0
    assert sample("cv_api_keys_rows", {"env": "demo", "state": "invalid"}) == 1
    assert envs == ["demo", "demo"]

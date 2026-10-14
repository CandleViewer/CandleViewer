"""Slice-8 wiring, end to end through the real `create_app()` (C-13.7: each fix has a test that
fails without it). A KEK that cannot load latches the gate; `/readyz`, the health registry and
the WS `system` topic must all show it, using only schema-valid frames."""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any

import pytest
from fastapi.testclient import TestClient

from candleviewer.app import AppContext, Supervisor, create_app
from candleviewer.net.system_topic import client_notice
from candleviewer.secrets.errors import KekLoadError
from candleviewer.settings import Environment, Settings
from tests.unit.ws._seq_support import validate

USER = uuid.uuid4()
JSON = ["cv.v1.json"]
ORIGIN = "http://testserver"  # the TestClient's own origin
HDR = {"origin": ORIGIN}
#: Far-future token expiry: this module does not test expiry (test_token_expiry.py does).
_EXPIRES = datetime(2100, 1, 1, tzinfo=UTC)


async def _authenticate(token: str) -> tuple[str, uuid.UUID, datetime]:
    if token != "tok":  # noqa: S105 - test vector, not a credential
        raise PermissionError("bad token")
    return "sess-1", USER, _EXPIRES


def _settings() -> Settings:
    return Settings(environment=Environment.DEMO, ws_shutdown_grace_ms=0, allowed_origins=ORIGIN)


def _latch(ctx: AppContext) -> None:
    ctx.oms_read_only_gate.latch(reason_code="secrets.kek_unavailable", reason_text="internal")


@pytest.fixture
def client() -> Iterator[TestClient]:
    app = create_app(_settings(), ws_authenticate=_authenticate)
    with TestClient(app, client=("127.0.0.1", 50000)) as c:
        yield c


def _ctx(c: TestClient) -> AppContext:
    ctx: AppContext = c.app.state.app_context  # type: ignore[attr-defined]
    return ctx


def _open_and_auth(ws: Any) -> None:
    ws.send_json({"t": "hello", "id": "h", "p": {"clock_ms": 1}})
    ws.receive_json()
    ws.send_json({"t": "auth", "id": "a", "p": {"access_token": "tok"}})
    assert ws.receive_json()["t"] == "auth_ok"


def test_client_notice_is_schema_valid_and_role_neutral() -> None:
    for ro, code in ((True, "secrets.kek_unavailable"), (True, "net.public_binding_detected"),
                     (False, None)):  # fmt: skip
        body = client_notice(ro, code)
        validate({"t": "d", "ch": "system", "s": 1, "ts": 1, "e": "j", "p": body})
        assert ":8080" not in str(body) and "read_only" not in body


def test_ws_connect_after_latch_gets_schema_valid_notice(client: TestClient) -> None:
    _latch(_ctx(client))
    with client.websocket_connect("/ws", subprotocols=JSON, headers=HDR) as ws:
        _open_and_auth(ws)
        frame = ws.receive_json()
        validate(frame)
        assert frame["ch"] == "system" and frame["p"]["severity"] == "critical"
        assert frame["p"]["reason"] == "secrets.kek_unavailable"
        assert "internal" not in str(frame)  # remediation text stays server-side


def test_ws_authenticated_client_receives_broadcast_on_latch(client: TestClient) -> None:
    with client.websocket_connect("/ws", subprotocols=JSON, headers=HDR) as ws:
        _open_and_auth(ws)
        _latch(_ctx(client))
        frame = ws.receive_json()
        validate(frame)
        assert frame["p"]["reason"] == "secrets.kek_unavailable"


def test_ws_reauth_does_not_repeat_the_notice(client: TestClient) -> None:
    _latch(_ctx(client))
    with client.websocket_connect("/ws", subprotocols=JSON, headers=HDR) as ws:
        _open_and_auth(ws)
        assert ws.receive_json()["p"]["kind"] == "notice"
        ws.send_json({"t": "auth", "id": "b", "p": {"access_token": "tok"}})
        assert ws.receive_json()["t"] == "auth_ok"
        ws.send_json({"t": "ping", "id": "p"})
        assert ws.receive_json()["t"] == "pong"  # no second notice in between


def _failing_bundle() -> Any:
    from candleviewer.admin.wiring import SecretsBundle
    from candleviewer.secrets import (
        SecretsLifecycleFacade,
        SecretsMetadataFacade,
        SecretsService,
        mint_borrower,
    )
    from candleviewer.secrets._source import KekSources
    from candleviewer.secrets.store import InMemoryCredentialStore
    from tests.unit.credentials_m2._vectors import AuditLog

    class _Fail:
        def load(self) -> Any:
            raise KekLoadError("kek_unavailable")

    st = InMemoryCredentialStore()
    svc = SecretsService(store=st, kcv_store=st, audit=AuditLog(), harden=lambda: True,
                         sources=lambda s: KekSources(_Fail(), None, None))  # fmt: skip
    return SecretsBundle(
        SecretsLifecycleFacade(svc),
        SecretsMetadataFacade(svc),
        mint_borrower(svc, "exchange_adapter"),
    )


async def test_readyz_and_health_show_secrets_down_after_kek_failure() -> None:
    app = create_app(_settings(), ws_authenticate=_authenticate, secrets_bundle=_failing_bundle())
    with TestClient(app, client=("127.0.0.1", 50000)) as client:
        ctx = _ctx(client)
        await ctx.secrets.start(ctx)  # the supervisor's call for this module
        assert ctx.oms_read_only_gate.is_read_only
        body = client.get("/readyz").json()
        assert body["status"] == "degraded"
        secrets = [c for c in body["checks"] if c["name"] == "secrets"]
        assert secrets and secrets[0]["ok"] is False and secrets[0]["detail"] == "kek_unavailable"
        snap = await app.state.health_registry.refresh()
        assert {c.name: c for c in snap.components}["secrets"].state.value == "down"


def test_readyz_ok_when_secrets_not_deployed(client: TestClient) -> None:
    body = client.get("/readyz").json()
    assert not [c for c in body["checks"] if c["name"] == "secrets"]  # STOPPED → not listed


async def test_supervisor_unwinds_started_modules_when_one_fails() -> None:
    from candleviewer.app import _SUPERVISOR_ORDER, build_app_context

    ctx = build_app_context(_settings())
    order: list[str] = []
    victim = _SUPERVISOR_ORDER[2]

    class _Mod:
        def __init__(self, name: str) -> None:
            self.name = name

        async def start(self, c: Any) -> None:
            if self.name == victim:
                raise RuntimeError("boom")
            order.append(f"start:{self.name}")

        async def stop(self, grace_s: float) -> None:
            order.append(f"stop:{self.name}")

    for name in _SUPERVISOR_ORDER:
        object.__setattr__(ctx, name, _Mod(name))
    with pytest.raises(RuntimeError, match="boom"):
        await Supervisor(ctx).start_all()
    first, second = _SUPERVISOR_ORDER[0], _SUPERVISOR_ORDER[1]
    assert order == [f"start:{first}", f"start:{second}", f"stop:{second}", f"stop:{first}"]


@pytest.mark.parametrize("env", [Environment.DEMO, Environment.LIVE])
async def test_fake_storage_backend_wiring_fails_closed(env: Environment) -> None:
    """C-11.2: `storage_backend="fake"` is explicit and fail-closed: no borrow ever succeeds;
    in live the gate latches (`no_credential_store`), in demo M2 reports STOPPED."""
    from candleviewer.app import build_app_context
    from candleviewer.observability.health import HealthStatus
    from candleviewer.secrets import KEY_ID_SLOT, KekUnavailable

    s = Settings(environment=env, storage_backend="fake", kek_source="none")
    from candleviewer.app import _build_audit, _build_secrets

    bundle = _build_secrets(s, _build_audit(s))  # the real composition branch under test
    ctx = build_app_context(Settings(environment=Environment.DEMO), secrets_bundle=bundle)
    object.__setattr__(ctx, "settings", s)
    await ctx.secrets.start(ctx)
    borrower = ctx.exchange_bybit._credentials
    assert borrower is not None

    with pytest.raises(KekUnavailable):
        await borrower.sign(uuid.uuid4(), (KEY_ID_SLOT,), purpose="sign_rest")
    if env is Environment.LIVE:
        assert ctx.oms_read_only_gate.is_read_only
        assert ctx.secrets.health().status is HealthStatus.DEGRADED
        assert ctx.secrets.health().detail == "no_credential_store"
    else:
        assert not ctx.oms_read_only_gate.is_read_only
        assert ctx.secrets.health().status is HealthStatus.STOPPED


async def test_stop_all_isolates_a_raising_stop_so_secrets_still_zeroes() -> None:
    from candleviewer.app import _SUPERVISOR_ORDER, build_app_context

    ctx = build_app_context(_settings())
    stopped: list[str] = []

    class _Mod:
        def __init__(self, name: str) -> None:
            self.name = name

        async def start(self, c: Any) -> None:
            return None

        async def stop(self, grace_s: float) -> None:
            stopped.append(self.name)
            if self.name == "ws":
                raise RuntimeError("ws stop failed")

    for name in _SUPERVISOR_ORDER:
        object.__setattr__(ctx, name, _Mod(name))
    await Supervisor(ctx).stop_all(0.1)
    assert stopped == list(reversed(_SUPERVISOR_ORDER))  # every module, incl. secrets


async def test_stop_all_bounds_a_hanging_stop() -> None:
    import asyncio

    from candleviewer.app import _SUPERVISOR_ORDER, build_app_context

    ctx = build_app_context(_settings())
    stopped: list[str] = []

    class _Mod:
        def __init__(self, name: str) -> None:
            self.name = name

        async def start(self, c: Any) -> None:
            return None

        async def stop(self, grace_s: float) -> None:
            stopped.append(self.name)
            if self.name == "ws":
                await asyncio.Event().wait()  # hangs

    for name in _SUPERVISOR_ORDER:
        object.__setattr__(ctx, name, _Mod(name))
    await asyncio.wait_for(Supervisor(ctx).stop_all(0.01), timeout=10)
    assert stopped == list(reversed(_SUPERVISOR_ORDER))

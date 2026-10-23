"""#913 slice 3E (20 Sec.6.2): the lifespan starts the OMS runtime once `start_all` and the account
health runtime are up, and on shutdown stops it right after the gateway, before every other step,
the account health runtime and `Supervisor.stop_all` (SEC-S3B1-02); `create_app` composes it on
the real backend only. Its stop's isolation is #3403's, with every other step's
(`test_main_lifespan_teardown_isolation`), and a boot that fails at its start stops it
(`test_main_lifespan_boot_failure`)."""

from __future__ import annotations

from fastapi.testclient import TestClient
from pydantic import SecretStr

from candleviewer.app import create_app
from candleviewer.main import _lifespan
from candleviewer.oms_wiring import OmsRuntime
from candleviewer.settings import Settings
from tests.unit.test_main_lifespan_stop_order import _MODULES, _app, _Stops


class _Runtime:
    """The OMS runtime: its start awaited, its stop recorded."""

    def __init__(self, stops: _Stops) -> None:
        self.stops = stops

    async def start(self) -> None:
        self.stops.started.append("oms_runtime")

    async def stop(self) -> None:
        self.stops.order.append("oms_runtime")


async def test_the_oms_runtime_starts_after_account_health_and_stops_right_after_the_gateway() -> (
    None
):
    stops = _Stops()
    app = _app(stops)
    app.state.oms_runtime = _Runtime(stops)
    async with _lifespan(app):
        modules = [stops.started.index(f"module:{name}") for name in _MODULES]
        assert max(modules) < stops.started.index("account_health")
        assert stops.started.index("account_health") < stops.started.index("oms_runtime")
    assert stops.order[:2] == ["ws_runtime", "oms_runtime"]
    stopped = [stops.order.index(f"module:{name}") for name in _MODULES]
    assert stops.order.index("account_health") < min(stopped)
    assert stops.started.count("oms_runtime") == stops.order.count("oms_runtime") == 1


def test_create_app_composes_the_oms_runtime_on_the_real_backend_only() -> None:
    """The real backend's runtime takes the shared profile cache (finding 6), and `/readyz`
    carries no `oms` check until the lifespan starts it."""
    assert create_app(Settings()).state.oms_runtime is None  # the fake backend: 501
    real = Settings(
        storage_backend="real",
        auth_pepper=SecretStr("test-pepper"),
        auth_totp_key_hex=SecretStr("11" * 32),
        auth_recovery_hmac_key_hex=SecretStr("22" * 32),
        auth_csrf_key_hex=SecretStr("33" * 32),
    )
    app = create_app(real)
    runtime = app.state.oms_runtime
    assert isinstance(runtime, OmsRuntime) and runtime.profiles is app.state.profiles.effective
    body = TestClient(app, client=("127.0.0.1", 50000)).get("/readyz").json()
    assert "oms" not in [check["name"] for check in body["checks"]]

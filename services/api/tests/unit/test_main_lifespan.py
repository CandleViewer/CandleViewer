"""ASGI lifespan wiring (E09-T04 AC1/AC3/AC5).

`main.py` docstring says the module supervisor "is not exercised by unit
tests" (true for `Supervisor.start_all`/`stop_all`, covered via
`test_app.py`'s direct calls) — but the boot self-check and the hourly
scheduler are wired *only* here, so this is the one place that must assert
`run_once()` runs before serving and `start()`/`stop()` bracket the
lifespan, or the regression this bug ticket describes (guard built but
never wired in) reappears silently.
"""

from __future__ import annotations

from types import SimpleNamespace

from fastapi import FastAPI

from candleviewer.main import _lifespan


class _FakeGate:
    def __init__(self) -> None:
        self.is_read_only = False
        self.reason_code: str | None = None
        self.reason_text: str | None = None


class _FakeSelfCheck:
    def __init__(self) -> None:
        self.run_once_calls = 0
        self.start_calls = 0
        self.stop_calls = 0

    async def run_once(self) -> None:
        self.run_once_calls += 1

    def start(self) -> None:
        self.start_calls += 1

    async def stop(self) -> None:
        self.stop_calls += 1


class _FakeModule:
    def __init__(self) -> None:
        self.started = False
        self.stopped = False

    async def start(self, ctx: object) -> None:
        self.started = True

    async def stop(self, grace_s: float) -> None:
        self.stopped = True


def _fake_ctx() -> SimpleNamespace:
    module_names = [
        "storage",
        "secrets",
        "auth",
        "admin",
        "bus",
        "exchange_base",
        "exchange_bybit",
        "ingestion",
        "book",
        "bars",
        "orderflow",
        "recorder",
        "accounts",
        "risk",
        "audit",
        "oms",
        "paper",
        "rules",
        "alerts",
        "journal",
        "replay",
        "observability",
        "ws",
    ]
    modules = {name: _FakeModule() for name in module_names}
    return SimpleNamespace(
        settings=SimpleNamespace(metrics_enabled=False),
        mesh_self_check=_FakeSelfCheck(),
        oms_read_only_gate=_FakeGate(),
        **modules,
    )


async def test_lifespan_runs_boot_check_before_yielding_and_starts_the_scheduler() -> None:
    app = FastAPI()
    ctx = _fake_ctx()
    app.state.app_context = ctx

    async with _lifespan(app):
        assert ctx.mesh_self_check.run_once_calls == 1
        assert ctx.mesh_self_check.start_calls == 1
        assert ctx.mesh_self_check.stop_calls == 0

    assert ctx.mesh_self_check.stop_calls == 1


async def test_lifespan_starts_and_stops_every_supervised_module() -> None:
    app = FastAPI()
    ctx = _fake_ctx()
    app.state.app_context = ctx

    async with _lifespan(app):
        assert ctx.storage.started is True
        assert ctx.ws.started is True

    assert ctx.storage.stopped is True
    assert ctx.ws.stopped is True


async def test_lifespan_leaves_read_only_mode_on_when_boot_check_trips_the_gate() -> None:
    app = FastAPI()
    ctx = _fake_ctx()
    ctx.oms_read_only_gate.is_read_only = True
    ctx.oms_read_only_gate.reason_code = "net.public_binding_detected"
    ctx.oms_read_only_gate.reason_text = "off-mesh binding detected"
    app.state.app_context = ctx

    async with _lifespan(app):
        assert ctx.oms_read_only_gate.is_read_only is True


async def test_lifespan_runs_the_audit_budget_flush_and_drains_it_before_audit_stops() -> None:
    app = FastAPI()
    ctx = _fake_ctx()
    app.state.app_context = ctx
    seen: list[str] = []

    class _Flush:
        def start(self) -> None:
            seen.append("start")

        async def stop(self) -> int:
            seen.append(f"stop, audit stopped={ctx.audit.stopped}")
            return 0

    app.state.audit_budget_flush = _Flush()
    async with _lifespan(app):
        assert seen == ["start"]
    assert seen == ["start", "stop, audit stopped=False"] and ctx.audit.stopped

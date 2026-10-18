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

import asyncio
import os
import re
from collections.abc import Sequence
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi import FastAPI
from structlog.testing import capture_logs

from candleviewer.account_fixture_wiring import ACCOUNT_FIXTURE_AUDIT_ACTION, AccountFixtureRefused
from candleviewer.audit.service import AuditService
from candleviewer.main import _lifespan
from candleviewer.settings import Environment, FeedMode, Settings
from cvdev.account_fixture import boot
from cvdev.account_fixture.boot import StoredKey
from tests._account_fixtures import PACK_ROOT


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


class _FakeAudit(_FakeModule):
    """The audit module with a writer (real backend): `is_active`, then `writer.emit`."""

    def __init__(self, failure: BaseException | None = None) -> None:
        super().__init__()
        self.is_active = True
        self.writer = self
        self.actions: list[str] = []
        self._failure = failure

    async def emit(self, action: str, **_fields: object) -> None:
        if self._failure is not None:
            raise self._failure
        self.actions.append(action)


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
        settings=SimpleNamespace(metrics_enabled=False, test_clock=False, account_fixture=None),
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


async def test_lifespan_starts_and_stops_the_drawings_purge_task() -> None:
    app = FastAPI()
    app.state.app_context = _fake_ctx()
    app.state.drawings_purge_task = task = SimpleNamespace(start=Mock(), stop=AsyncMock())

    async with _lifespan(app):
        task.start.assert_called_once_with()

    task.stop.assert_awaited_once_with()


async def test_lifespan_starts_and_stops_the_incidents_purge_task() -> None:
    app = FastAPI()
    app.state.app_context = _fake_ctx()
    app.state.incidents_purge_task = task = SimpleNamespace(start=Mock(), stop=AsyncMock())

    async with _lifespan(app):
        task.start.assert_called_once_with()

    task.stop.assert_awaited_once_with()


async def test_lifespan_leaves_read_only_mode_on_when_boot_check_trips_the_gate() -> None:
    app = FastAPI()
    ctx = _fake_ctx()
    ctx.oms_read_only_gate.is_read_only = True
    ctx.oms_read_only_gate.reason_code = "net.public_binding_detected"
    ctx.oms_read_only_gate.reason_text = "off-mesh binding detected"
    app.state.app_context = ctx

    async with _lifespan(app):
        assert ctx.oms_read_only_gate.is_read_only is True


def _test_clock_ctx(audit: _FakeAudit) -> SimpleNamespace:
    ctx = _fake_ctx()
    ctx.settings = SimpleNamespace(
        metrics_enabled=False,
        test_clock=True,
        test_clock_file="/run/cv-test-clock/offset",
        environment=Environment.TESTNET,
        account_fixture=None,
    )
    ctx.audit = audit
    return ctx


async def test_lifespan_audits_the_test_clock_before_serving() -> None:
    """#2728 (E16 R-E3 "config audit"): the record is written before the app serves."""
    app = FastAPI()
    ctx = _test_clock_ctx(_FakeAudit())
    app.state.app_context = ctx

    async with _lifespan(app):
        assert ctx.audit.actions == ["system.config.test_clock_enabled"]


async def test_lifespan_stops_every_module_when_the_test_clock_audit_fails() -> None:
    """#2728: a failed boot record fails boot, and no started module is left running."""
    app = FastAPI()
    ctx = _test_clock_ctx(_FakeAudit(failure=RuntimeError("audit unavailable")))
    app.state.app_context = ctx

    with pytest.raises(RuntimeError, match="audit unavailable"):
        await _lifespan(app).__aenter__()

    assert (ctx.storage.stopped, ctx.audit.stopped, ctx.ws.stopped) == (True, True, True)
    assert ctx.mesh_self_check.run_once_calls == 0


async def test_lifespan_stops_every_module_when_the_test_clock_audit_is_cancelled() -> None:
    """#2728: a cancellation during the boot record also stops every started module before it
    propagates; since #3446 through the lifespan's teardown, which never swallows it."""
    app = FastAPI()
    ctx = _test_clock_ctx(_FakeAudit(failure=asyncio.CancelledError()))
    app.state.app_context = ctx

    with pytest.raises(asyncio.CancelledError):
        await _lifespan(app).__aenter__()

    assert (ctx.storage.stopped, ctx.audit.stopped, ctx.ws.stopped) == (True, True, True)


def _fixture_app(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, audit: object
) -> tuple[FastAPI, SimpleNamespace]:
    """The harness with the fixture on (#2893 S8) and the checkout's pack."""
    for name in [n for n in os.environ if n.upper().startswith("CV_")]:
        monkeypatch.delenv(name)
    monkeypatch.setattr(boot, "PACK_ROOT", PACK_ROOT)
    app, ctx = FastAPI(), _fake_ctx()
    ctx.settings = Settings(
        environment=Environment.DEMO,
        feed=FeedMode.SYNTHETIC,
        account_fixture="compliant",
        account_fixture_dir=str(tmp_path / "state"),
        metrics_enabled=False,
    )
    ctx.audit = audit
    app.state.app_context = ctx
    return app, ctx


def _modules(ctx: SimpleNamespace) -> list[_FakeModule]:
    return [m for m in vars(ctx).values() if isinstance(m, _FakeModule)]


class _AuditAfterStart(_FakeAudit):
    async def emit(self, action: str, **fields: object) -> None:
        assert self.started, "the boot record was written before the audit module started"
        await super().emit(action, **fields)


async def test_a_refused_boot_starts_no_module(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def _a_live_key(settings: Settings) -> Sequence[StoredKey]:
        return [StoredKey(env="live", key_id_last4="Ab12")]

    monkeypatch.setattr(boot, "read_stored_keys", _a_live_key)
    app, ctx = _fixture_app(tmp_path, monkeypatch, _FakeAudit())

    with pytest.raises(AccountFixtureRefused, match=re.escape("1 outside demo (live 1)")):
        await _lifespan(app).__aenter__()

    assert not [m for m in _modules(ctx) if m.started]
    assert (ctx.mesh_self_check.run_once_calls, ctx.audit.actions) == (0, [])


async def test_the_lifespan_decides_before_any_module_starts_and_records_after(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """With an audit writer, as on the real backend (the read is faked): the guard reads before
    any module starts, and its record is written once they run, before serving."""
    app, ctx = _fixture_app(tmp_path, monkeypatch, _AuditAfterStart())
    started_at_read: list[bool] = []

    async def _read(settings: Settings) -> Sequence[StoredKey]:
        started_at_read.append(any(m.started for m in _modules(ctx)))
        return [StoredKey(env="demo", key_id_last4="0001")]

    monkeypatch.setattr(boot, "read_stored_keys", _read)

    async with _lifespan(app):
        assert (started_at_read, ctx.audit.actions) == ([False], [ACCOUNT_FIXTURE_AUDIT_ACTION])


async def test_on_the_fake_backend_the_warning_is_the_only_record(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The real fake-backend path: no key is stored and `AuditService` has no writer (`is_active`
    is False and `writer` raises), so the guard passes with its warning and nothing is written."""
    app, ctx = _fixture_app(tmp_path, monkeypatch, AuditService())

    with capture_logs() as logs:
        async with _lifespan(app):
            assert ctx.audit.is_active is False

    passed = [e for e in logs if e["event"] == "exchange.account_fixture_boot_guard_passed"]
    assert [(e["log_level"], e["storage_backend"], e["fixture_keys"]) for e in passed] == [
        ("warning", "fake", 0)
    ]


async def test_a_failed_boot_record_stops_every_module_and_raises(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    app, ctx = _fixture_app(tmp_path, monkeypatch, _FakeAudit(failure=RuntimeError("audit down")))

    with pytest.raises(RuntimeError, match="audit down"):
        await _lifespan(app).__aenter__()

    assert not [m for m in _modules(ctx) if not m.stopped]


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

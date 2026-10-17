"""#2893 S8: the boot guard refuses a stored key the fixture must never answer for (FX-S01).

Fakes stand in for the store and the audit sink; `test_account_fixture_boot_guard_pg.py` runs the
read on Postgres. A refusal names counts and environments, never a key character.
"""

from __future__ import annotations

import json
import os
import re
import sys
import uuid
from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Final

import pytest
from fastapi import FastAPI
from structlog.testing import capture_logs

from candleviewer.account_fixture_wiring import (
    ACCOUNT_FIXTURE_AUDIT_ACTION,
    NO_FIXTURE_TRANSPORT,
    AccountFixtureRefused,
    account_fixture_boot,
)
from candleviewer.audit.actions import AUDIT_ACTIONS
from candleviewer.audit.models import AuditEmission, Severity
from candleviewer.main import _lifespan
from candleviewer.settings import Environment, FeedMode, Settings
from cvdev.account_fixture import boot
from cvdev.account_fixture.boot import MAX_STORED_KEYS, StoredKey
from cvdev.account_fixture.pack import Pack
from tests._account_fixtures import PACK, PACK_ROOT
from tests.unit.test_main_lifespan import _fake_ctx, _FakeAudit

_T0: Final = datetime(2026, 10, 16, 9, 0, tzinfo=UTC)
_FOREIGN: Final = "Zq9X"  # no pack key id ends with it


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in [n for n in os.environ if n.upper().startswith("CV_")]:
        monkeypatch.delenv(name)


def _dev(tmp_path: Path, **fields: Any) -> Settings:
    return Settings(
        environment=Environment.DEMO,
        feed=FeedMode.SYNTHETIC,
        account_fixture="compliant",
        account_fixture_dir=str(tmp_path / "state"),
        **fields,
    )


def _key(env: str, last4: str, *, revoked: bool = False) -> StoredKey:
    return StoredKey(env=env, key_id_last4=last4, revoked=revoked)


class _Keys:
    def __init__(self, *rows: StoredKey) -> None:
        self.rows = rows

    async def stored_keys(self) -> Sequence[StoredKey]:
        return self.rows


class _Audit:
    def __init__(self) -> None:
        self.records: list[tuple[str, dict[str, Any]]] = []

    async def emit(self, action: str, **fields: Any) -> None:
        self.records.append((action, fields))


async def test_boot_refuses_a_non_fixture_key_tail(tmp_path: Path) -> None:
    audit = _Audit()
    keys = _Keys(_key("demo", "0001"), _key("demo", _FOREIGN))

    with capture_logs() as logs, pytest.raises(AccountFixtureRefused) as refused:
        await boot.run(_dev(tmp_path), audit, keys=keys, pack=PACK)

    assert "1 on demo whose key id is not a fixture key id" in str(refused.value)
    assert [(e["event"], e["log_level"]) for e in logs] == [
        ("exchange.account_fixture_boot_refused", "error")
    ]
    assert _FOREIGN not in f"{refused.value} {logs}"
    assert audit.records == []  # a refused boot writes no "enabled" record


@pytest.mark.parametrize("env", ["live", "testnet"])
async def test_boot_refuses_any_unrevoked_key_outside_demo(tmp_path: Path, env: str) -> None:
    """A pack tail does not help outside demo: every such key refuses."""
    keys = _Keys(_key(env, "0001"), _key(env, "0002"), _key("demo", "0003"))

    with pytest.raises(AccountFixtureRefused, match=re.escape(f"2 outside demo ({env} 2)")) as e:
        await boot.run(_dev(tmp_path), None, keys=keys, pack=PACK)

    assert "0001" not in str(e.value) and "0002" not in str(e.value)


async def test_revoked_rows_do_not_block(tmp_path: Path) -> None:
    keys = _Keys(
        _key("live", "Ab12", revoked=True),
        _key("demo", _FOREIGN, revoked=True),
        _key("demo", "0001"),
    )
    audit = _Audit()

    await boot.run(_dev(tmp_path), audit, keys=keys, pack=PACK)

    assert [action for action, _ in audit.records] == [ACCOUNT_FIXTURE_AUDIT_ACTION]


async def test_boot_passes_with_fixture_keys_only(tmp_path: Path) -> None:
    keys = _Keys(_key("demo", "0001"), _key("demo", "0002"))

    with capture_logs() as logs:
        await boot.run(_dev(tmp_path), None, keys=keys, pack=PACK)

    assert [(e["event"], e["fixture_keys"], e["revoked_keys"]) for e in logs] == [
        ("exchange.account_fixture_boot_guard_passed", 2, 0)
    ]


async def test_boot_writes_audit_and_warning(tmp_path: Path) -> None:
    audit = _Audit()

    with capture_logs() as logs:
        await boot.run(_dev(tmp_path), audit, keys=_Keys(_key("demo", "0001")), pack=PACK)

    assert [(e["event"], e["log_level"], e["scenario"]) for e in logs] == [
        ("exchange.account_fixture_boot_guard_passed", "warning", "compliant")
    ]
    assert audit.records == [
        (
            "system.config.account_fixture_enabled",
            {
                "actor_label": "system:account-fixture",
                "object_kind": "settings",
                "object_id": "CV_ACCOUNT_FIXTURE",
                "severity": "warning",
                "env": "demo",
                "after_state": {"scenario": "compliant", "fixture_dir": str(tmp_path / "state")},
            },
        )
    ]
    ((action, fields),) = audit.records
    emission = AuditEmission(record_id=uuid.uuid4(), action=action, event_ts=_T0, **fields)
    assert action in AUDIT_ACTIONS and emission.severity is Severity.WARNING


async def test_boot_failure_stops_the_supervisor_and_raises(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def _a_live_key(settings: Settings) -> Sequence[StoredKey]:
        return [_key("live", "Ab12")]

    monkeypatch.setattr(boot, "read_stored_keys", _a_live_key)
    monkeypatch.setattr(boot, "PACK_ROOT", PACK_ROOT)
    app, ctx = FastAPI(), _fake_ctx()
    ctx.settings, ctx.audit = _dev(tmp_path, metrics_enabled=False), _FakeAudit()
    app.state.app_context = ctx

    with pytest.raises(AccountFixtureRefused, match=re.escape("1 outside demo (live 1)")):
        await _lifespan(app).__aenter__()

    assert (ctx.storage.stopped, ctx.audit.stopped, ctx.ws.stopped) == (True, True, True)
    assert (ctx.mesh_self_check.run_once_calls, ctx.audit.actions) == (0, [])


async def test_the_lifespan_guards_and_audits_before_serving(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """On the fake backend (no stored key) it passes with its log line, then writes the record."""
    monkeypatch.setattr(boot, "PACK_ROOT", PACK_ROOT)
    app, ctx = FastAPI(), _fake_ctx()
    ctx.settings, ctx.audit = _dev(tmp_path, metrics_enabled=False), _FakeAudit()
    app.state.app_context = ctx

    with capture_logs() as logs:
        async with _lifespan(app):
            assert ctx.audit.actions == [ACCOUNT_FIXTURE_AUDIT_ACTION]

    passed = [e for e in logs if e["event"] == "exchange.account_fixture_boot_guard_passed"]
    assert [(e["storage_backend"], e["fixture_keys"]) for e in passed] == [("fake", 0)]


def _forget_the_dev_package(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in [n for n in sys.modules if n == "cvdev" or n.startswith("cvdev.")]:
        monkeypatch.delitem(sys.modules, name)


async def test_unset_does_nothing_and_imports_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    _forget_the_dev_package(monkeypatch)
    audit = _FakeAudit()

    await account_fixture_boot(SimpleNamespace(settings=Settings(), audit=audit))

    assert audit.actions == []
    assert not [n for n in sys.modules if n == "cvdev" or n.startswith("cvdev.")]


async def test_a_build_without_the_dev_package_refuses_boot(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _forget_the_dev_package(monkeypatch)
    monkeypatch.setitem(sys.modules, "cvdev", None)  # the import system's "no such module"
    ctx = SimpleNamespace(settings=_dev(tmp_path), audit=_FakeAudit())

    with pytest.raises(AccountFixtureRefused, match=re.escape(NO_FIXTURE_TRANSPORT)):
        await account_fixture_boot(ctx)


async def test_the_guard_rechecks_settings_that_skipped_validation() -> None:
    settings = Settings.model_construct(account_fixture="compliant", environment=Environment.LIVE)

    with pytest.raises(AccountFixtureRefused, match="unless CV_ENVIRONMENT=demo"):
        await boot.run(settings, None, keys=_Keys(), pack=PACK)


async def test_a_pack_without_a_fixture_key_id_refuses_boot(tmp_path: Path) -> None:
    """Only fixture-shaped ids count, so a key-shaped id in a manifest adds no tail."""
    scenario = tmp_path / "fixtures" / "accounts" / "planted"
    scenario.mkdir(parents=True)
    body = {"tester_inputs": {"key_id": "AbCdEfGhIjKlMnOp0001"}}
    (scenario / "manifest.json").write_text(json.dumps(body), encoding="utf-8")
    keys = _Keys(_key("demo", "0001"))

    with pytest.raises(AccountFixtureRefused, match="names no fixture key id"):
        await boot.run(_dev(tmp_path), None, keys=keys, pack=Pack(scenario.parent))


async def test_more_stored_keys_than_the_guard_reads_refuses_boot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(boot, "MAX_STORED_KEYS", 1)
    keys = _Keys(_key("demo", "0001"), _key("demo", "0002"))

    with pytest.raises(AccountFixtureRefused, match="more than 1 exchange key"):
        await boot.run(_dev(tmp_path), None, keys=keys, pack=PACK)


class _Session:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.rows = rows
        self.statements: list[tuple[str, Any]] = []

    async def execute(self, statement: Any, params: Any = None) -> Any:
        self.statements.append((str(statement), params))
        return SimpleNamespace(mappings=lambda: SimpleNamespace(all=lambda: self.rows))


class _Relational:
    def __init__(self, dsn: str, name: str) -> None:
        self.name, self.disposed = name, False
        self.session = _Session([{"env": "demo", "key_id_last4": "0001", "revoked": True}])

    @asynccontextmanager
    async def unit_of_work(self) -> AsyncIterator[Any]:
        yield SimpleNamespace(session=self.session)

    async def dispose(self) -> None:
        self.disposed = True


async def test_the_postgres_read_is_read_only_bounded_and_disposed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    built: list[_Relational] = []

    def _build(dsn: str, name: str) -> _Relational:
        built.append(_Relational(dsn, name))
        return built[-1]

    monkeypatch.setattr(boot, "SqlAlchemyRelationalRepository", _build)

    stored = await boot.read_stored_keys(_dev(tmp_path, storage_backend="real"))

    assert stored == [_key("demo", "0001", revoked=True)]
    (relational,) = built
    (read_only, _), (select, params) = relational.session.statements
    assert read_only == "SET TRANSACTION READ ONLY"
    assert select.startswith("SELECT ea.env::text AS env, k.key_id_last4 AS key_id_last4")
    assert params == {"limit": MAX_STORED_KEYS + 1}
    assert (relational.name, relational.disposed) == ("account-fixture-boot", True)

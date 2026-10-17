"""#2893 S8: the boot guard refuses a stored key the fixture must never answer for (FX-S01).

Fakes stand in for the store and the audit sink; `test_account_fixture_boot_guard_pg.py` runs the
read on Postgres, and `tests/unit/test_main_lifespan.py` the lifespan wiring (kept out of this
module: importing `candleviewer.main` configures logging, #2519). A refusal names counts and
environments, never a key character.
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
from structlog.testing import capture_logs

from candleviewer.account_fixture_wiring import (
    NO_FIXTURE_TRANSPORT,
    AccountFixtureRefused,
    account_fixture_guard,
    account_fixture_record,
)
from candleviewer.audit.actions import AUDIT_ACTIONS
from candleviewer.audit.models import AuditEmission, Severity
from candleviewer.settings import Environment, FeedMode, Settings
from cvdev.account_fixture import boot
from cvdev.account_fixture.boot import MAX_STORED_KEYS, StoredKey
from cvdev.account_fixture.pack import Pack
from tests._account_fixtures import PACK

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


def _key(env: str, last4: str) -> StoredKey:
    return StoredKey(env=env, key_id_last4=last4)


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
    keys = _Keys(_key("demo", "0001"), _key("demo", _FOREIGN))

    with capture_logs() as logs, pytest.raises(AccountFixtureRefused) as refused:
        await boot.run(_dev(tmp_path), keys=keys, pack=PACK)

    assert "1 on demo whose key id is not a fixture key id" in str(refused.value)
    assert [(e["event"], e["log_level"]) for e in logs] == [
        ("exchange.account_fixture_boot_refused", "error")
    ]
    assert _FOREIGN not in f"{refused.value} {logs}"


@pytest.mark.parametrize("env", ["live", "testnet"])
async def test_boot_refuses_any_unrevoked_key_outside_demo(tmp_path: Path, env: str) -> None:
    """A pack tail does not help outside demo: every such key refuses."""
    keys = _Keys(_key(env, "0001"), _key(env, "0002"), _key("demo", "0003"))

    with pytest.raises(AccountFixtureRefused, match=re.escape(f"2 outside demo ({env} 2)")) as e:
        await boot.run(_dev(tmp_path), keys=keys, pack=PACK)

    assert "0001" not in str(e.value) and "0002" not in str(e.value)


async def test_boot_passes_with_fixture_keys_only(tmp_path: Path) -> None:
    keys = _Keys(_key("demo", "0001"), _key("demo", "0002"))

    with capture_logs() as logs:
        await boot.run(_dev(tmp_path), keys=keys, pack=PACK)

    assert [(e["event"], e["fixture_keys"]) for e in logs] == [
        ("exchange.account_fixture_boot_guard_passed", 2)
    ]


async def test_boot_writes_audit_and_warning(tmp_path: Path) -> None:
    """A pass logs the warning; its record, written once the modules run, goes to the writer."""
    audit = _Audit()

    with capture_logs() as logs:
        passed = await boot.run(_dev(tmp_path), keys=_Keys(_key("demo", "0001")), pack=PACK)
    await passed.record(audit)

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


def _forget_the_dev_package(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in [n for n in sys.modules if n == "cvdev" or n.startswith("cvdev.")]:
        monkeypatch.delitem(sys.modules, name)


async def test_unset_does_nothing_and_imports_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    _forget_the_dev_package(monkeypatch)
    audit = _Audit()

    passed = await account_fixture_guard(Settings())
    await account_fixture_record(passed, audit)

    assert (passed, audit.records) == (None, [])
    assert not [n for n in sys.modules if n == "cvdev" or n.startswith("cvdev.")]


async def test_a_build_without_the_dev_package_refuses_boot(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _forget_the_dev_package(monkeypatch)
    monkeypatch.setitem(sys.modules, "cvdev", None)  # the import system's "no such module"

    with pytest.raises(AccountFixtureRefused, match=re.escape(NO_FIXTURE_TRANSPORT)):
        await account_fixture_guard(_dev(tmp_path))


async def test_the_guard_rechecks_settings_that_skipped_validation() -> None:
    settings = Settings.model_construct(account_fixture="compliant", environment=Environment.LIVE)

    with pytest.raises(AccountFixtureRefused, match="unless CV_ENVIRONMENT=demo"):
        await boot.run(settings, keys=_Keys(), pack=PACK)


@pytest.mark.parametrize("key_id", ["AbCdEfGhIjKlMnOp0001", "fixture-a-0001XYZ"])
async def test_a_pack_without_a_fixture_key_id_refuses_boot(tmp_path: Path, key_id: str) -> None:
    """Only whole fixture-shaped ids count: a key-shaped id, or one that only starts like a pack
    key id, adds no tail."""
    scenario = tmp_path / "fixtures" / "accounts" / "planted"
    scenario.mkdir(parents=True)
    body = {"tester_inputs": {"key_id": key_id}}
    (scenario / "manifest.json").write_text(json.dumps(body), encoding="utf-8")
    keys = _Keys(_key("demo", "0001"))

    with pytest.raises(AccountFixtureRefused, match="names no fixture key id"):
        await boot.run(_dev(tmp_path), keys=keys, pack=Pack(scenario.parent))


async def test_more_stored_keys_than_the_guard_reads_refuses_boot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Exactly `MAX_STORED_KEYS` keys pass; one more refuses."""
    keys = _Keys(_key("demo", "0001"), _key("demo", "0002"))
    monkeypatch.setattr(boot, "MAX_STORED_KEYS", 2)
    await boot.run(_dev(tmp_path), keys=keys, pack=PACK)

    monkeypatch.setattr(boot, "MAX_STORED_KEYS", 1)
    with pytest.raises(AccountFixtureRefused, match="more than 1 unrevoked exchange keys"):
        await boot.run(_dev(tmp_path), keys=keys, pack=PACK)


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
        self.session = _Session([{"env": "demo", "key_id_last4": "0001"}])

    @asynccontextmanager
    async def unit_of_work(self) -> AsyncIterator[Any]:
        yield SimpleNamespace(session=self.session)

    async def dispose(self) -> None:
        self.disposed = True


async def test_the_postgres_read_skips_revoked_rows_and_is_read_only_bounded_disposed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Revoked rows are never read (ADR-0036 decision 4), so they never block boot or count
    toward the cap; `test_account_fixture_boot_guard_pg.py` runs the predicate on Postgres."""
    built: list[_Relational] = []

    def _build(dsn: str, name: str) -> _Relational:
        built.append(_Relational(dsn, name))
        return built[-1]

    monkeypatch.setattr(boot, "SqlAlchemyRelationalRepository", _build)

    stored = await boot.read_stored_keys(_dev(tmp_path, storage_backend="real"))

    assert stored == [_key("demo", "0001")]
    (relational,) = built
    (read_only, _), (select, params) = relational.session.statements
    assert read_only == "SET TRANSACTION READ ONLY"
    assert select.startswith("SELECT ea.env::text AS env, k.key_id_last4 AS key_id_last4 FROM")
    assert select.endswith(" WHERE k.revoked_at IS NULL LIMIT :limit")
    assert params == {"limit": MAX_STORED_KEYS + 1}
    assert (relational.name, relational.disposed) == ("account-fixture-boot", True)

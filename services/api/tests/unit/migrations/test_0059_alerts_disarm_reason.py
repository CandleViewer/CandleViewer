"""The alerts disarm-reason revision (E40-S01, CC-3): its statements and the model mirror.
Real Postgres round trip: the `migrations` CI job (alembic upgrade/downgrade/upgrade)."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest

from candleviewer.db import models

_FILE = next(
    (Path(__file__).resolve().parents[3] / "candleviewer" / "migrations" / "versions").glob(
        "*_alerts_disarm_reason.py"
    )
)


def _module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("rev_alerts_disarm_reason", _FILE)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _run(monkeypatch: pytest.MonkeyPatch, fn: str) -> list[str]:
    mod = _module()
    sql: list[str] = []
    monkeypatch.setattr(mod.op, "execute", sql.append)
    getattr(mod, fn)()
    return sql


def test_upgrade_adds_one_nullable_column_and_a_null_safe_check(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sql = _run(monkeypatch, "upgrade")
    assert sql[0] == "SET LOCAL lock_timeout = '5s';" and sql[-1].startswith(
        "SET LOCAL lock_timeout"
    )
    assert "ALTER TABLE alerts ADD COLUMN disarm_reason text;" in sql
    check = next(s for s in sql if "al_disarm_reason" in s)
    assert "disarm_reason IS NULL OR" in check and "'source_unavailable'" in check


def test_downgrade_drops_the_check_then_the_column(monkeypatch: pytest.MonkeyPatch) -> None:
    sql = [s for s in _run(monkeypatch, "downgrade") if s.startswith("ALTER")]
    assert sql == [
        "ALTER TABLE alerts DROP CONSTRAINT al_disarm_reason;",
        "ALTER TABLE alerts DROP COLUMN disarm_reason;",
    ]


def test_model_mirrors_the_revision() -> None:
    col = models.alerts.c.disarm_reason
    assert col.nullable and col.server_default is None
    assert any(str(c.name).endswith("al_disarm_reason") for c in models.alerts.constraints)


def test_revision_chain_follows_0058() -> None:
    mod = _module()
    assert mod.down_revision == "0058_oms_handovers"

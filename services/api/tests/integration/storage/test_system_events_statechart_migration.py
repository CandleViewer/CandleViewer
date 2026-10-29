"""Integration: `0057_se_component_statechart` on real Postgres 16 (E42-T07 #1025).

The widened `se_component` (validated, `statechart` admitted, an unknown component refused) and
the round trip on a seeded table: a `statechart` row refuses the downgrade; without one, the
downgrade restores 0008's list, keeps every other row, and `upgrade head` widens it again.
`testcontainers`; CI's `integration` job.
"""

from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import psycopg
import pytest
from psycopg import errors as pgerr
from testcontainers.postgres import PostgresContainer

pytestmark = pytest.mark.integration

_ROOT = Path(__file__).resolve().parents[3]
_REVISION_FILE = (
    _ROOT / "candleviewer" / "migrations" / "versions"
    / "0057_se_component_statechart.py"
)  # fmt: skip

Conn = psycopg.Connection[tuple[Any, ...]]


def _down_revision() -> str:
    spec = importlib.util.spec_from_file_location("rev_0057_it", _REVISION_FILE)
    assert spec is not None and spec.loader is not None
    revision = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(revision)
    return str(revision.down_revision)


def _alembic(dsn: str, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603 -- fixed argv, literal alembic subcommands, no shell (#1025)
        [sys.executable, "-m", "alembic", *args],
        cwd=_ROOT,
        env={**os.environ, "CV_PG_DSN": dsn.replace("postgresql+asyncpg", "postgresql+psycopg")},
        capture_output=True, text=True, check=False, timeout=120,
    )  # fmt: skip


@pytest.fixture(scope="module")
def pg_dsn() -> Iterator[str]:
    with PostgresContainer("postgres:16-alpine") as container:
        dsn = container.get_connection_url().replace("postgresql+psycopg2", "postgresql+asyncpg")
        yield dsn


def _conn(dsn: str) -> Conn:
    return psycopg.connect(dsn.replace("postgresql+asyncpg", "postgresql"), autocommit=True)


def _event(c: Conn, component: str) -> None:
    c.execute(
        "INSERT INTO system_events (component, kind, severity, message) "
        "VALUES (%s, 'k', 'critical', 'fixed')",
        (component,),
    )


def _check(c: Conn) -> tuple[Any, ...] | None:
    return c.execute(
        "SELECT pg_get_constraintdef(oid), convalidated FROM pg_constraint "
        "WHERE conname = 'se_component'"
    ).fetchone()


def test_round_trip_on_an_empty_then_a_seeded_table(pg_dsn: str) -> None:
    """C-5.5: up, down, up on the empty table; then seeded, a `statechart` row refuses the
    downgrade (C-5.2), and without one the round trip keeps every other row."""
    prev = _down_revision()
    for step in (("upgrade", "head"), ("downgrade", "-1"), ("upgrade", "head")):
        done = _alembic(pg_dsn, *step)
        assert done.returncode == 0, done.stderr
    with _conn(pg_dsn) as c:
        found = _check(c)
        assert found is not None and "'statechart'::text" in found[0] and found[1] is True
        _event(c, "statechart")
        _event(c, "backup")
        with pytest.raises(pgerr.CheckViolation):
            _event(c, "nope")
        refused = _alembic(pg_dsn, "downgrade", prev)
        assert refused.returncode != 0
        assert "downgrade refused: system_events holds statechart rows" in refused.stderr
        assert "'statechart'::text" in (_check(c) or ("",))[0]
        c.execute("DELETE FROM system_events WHERE component = 'statechart'")
        done = _alembic(pg_dsn, "downgrade", prev)
        assert done.returncode == 0, done.stderr
        narrowed = _check(c)
        assert narrowed is not None and "statechart" not in narrowed[0] and narrowed[1] is True
        with pytest.raises(pgerr.CheckViolation):
            _event(c, "statechart")
        assert c.execute("SELECT count(*) FROM system_events WHERE component = 'backup'"
                         ).fetchone() == (1,)  # fmt: skip
        done = _alembic(pg_dsn, "upgrade", "head")
        assert done.returncode == 0, done.stderr
        _event(c, "statechart")

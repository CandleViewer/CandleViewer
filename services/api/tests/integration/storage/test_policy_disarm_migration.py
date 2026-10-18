"""Integration: `0031_policy_disarm` on real Postgres 16 (#836 slice 2d).

Each CHECK refuses by its name; the downgrade refuses while a disarm's record is owed, and once it
is marked the revision goes down and up again with the seeded row kept. `testcontainers`, CI-only
(no docker socket here); run before the PR on a scratch Postgres 16 through a local stand-in.
"""

from __future__ import annotations

import os
import subprocess
import sys
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import psycopg
import pytest
from psycopg import errors as pgerr
from testcontainers.postgres import PostgresContainer

pytestmark = pytest.mark.integration

_ROOT = Path(__file__).resolve().parents[3]
_PREV = "0030_auth_keys"
_AT = datetime(2026, 10, 18, 9, tzinfo=UTC)
_SET = (
    "UPDATE exchange_accounts SET (policy_disarm_code, policy_disarmed_at, "
    "policy_disarm_audited_at) = (%s, %s, %s) WHERE id = %s"
)
_READ = (
    "SELECT trading_enabled, policy_disarm_code, policy_disarmed_at, policy_disarm_audited_at "
    "FROM exchange_accounts WHERE id = %s"
)

Conn = psycopg.Connection[tuple[Any, ...]]


def _alembic(dsn: str, *args: str) -> subprocess.CompletedProcess[str]:
    """Bounded, so a lost `lock_timeout` fails the test instead of hanging it."""
    return subprocess.run(  # noqa: S603 -- fixed argv, literal alembic subcommands, no shell (#836)
        [sys.executable, "-m", "alembic", *args],
        cwd=_ROOT, env={**os.environ, "CV_PG_DSN": dsn}, capture_output=True, text=True,
        check=False, timeout=120,
    )  # fmt: skip


@pytest.fixture(scope="module")
def pg_dsn() -> Iterator[str]:
    with PostgresContainer("postgres:16-alpine") as container:
        dsn = container.get_connection_url().replace("postgresql+psycopg2", "postgresql+psycopg")
        assert _alembic(dsn, "upgrade", "head").returncode == 0
        yield dsn


def _conn(dsn: str) -> Conn:
    return psycopg.connect(dsn.replace("postgresql+psycopg", "postgresql"), autocommit=True)


def _account(c: Conn) -> uuid.UUID:
    acct = uuid.uuid4()
    c.execute(
        "INSERT INTO exchange_accounts (id, exchange, env, kind, exchange_uid, label) "
        "VALUES (%s, 'bybit', 'demo', 'main', %s, %s)",
        (acct, str(acct.int % 10**15), f"L{acct.hex[:8]}"),
    )
    return acct


@pytest.mark.parametrize(
    ("values", "constraint"),
    [
        (("A failing key: Wallet holds Withdraw", _AT, None), "ea_disarm_code_fmt"),
        (("key_withdraw_permission", None, None), "ea_disarm_shape"),
        ((None, _AT, None), "ea_disarm_shape"),
        ((None, None, _AT), "ea_disarm_shape"),
    ],
    ids=["message-text", "code-without-time", "time-without-code", "mark-without-disarm"],
)
def test_each_check_refuses_by_its_name(
    pg_dsn: str, values: tuple[object, ...], constraint: str
) -> None:
    with _conn(pg_dsn) as c:
        acct = _account(c)
        with pytest.raises(pgerr.CheckViolation) as refused:
            c.execute(_SET, (*values, acct))
    assert refused.value.diag.constraint_name == constraint


def test_the_downgrade_refuses_while_a_record_is_owed_and_round_trips_once_it_is_marked(
    pg_dsn: str,
) -> None:
    with _conn(pg_dsn) as c:
        acct = _account(c)  # `trading_enabled` defaults to false, as after a disarm
        c.execute(_SET, ("key_withdraw_permission", _AT, None, acct))
        head = c.execute("SELECT version_num FROM alembic_version").fetchone()
    refused = _alembic(pg_dsn, "downgrade", _PREV)
    assert refused.returncode != 0 and "0031_policy_disarm downgrade refused" in refused.stderr
    with _conn(pg_dsn) as c:
        assert c.execute("SELECT version_num FROM alembic_version").fetchone() == head
        c.execute(_SET, ("key_withdraw_permission", _AT, _AT, acct))
    for step in (("downgrade", _PREV), ("upgrade", "head")):
        assert _alembic(pg_dsn, *step).returncode == 0
    with _conn(pg_dsn) as c:
        row = c.execute(_READ, (acct,)).fetchone()
    assert row == (False, None, None, None)  # the row stays; the dropped values do not come back

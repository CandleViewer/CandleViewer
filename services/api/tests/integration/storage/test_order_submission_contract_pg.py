"""Integration: the order-submission stores' contract on real Postgres 16 (E29-T04 #913).

`tests/unit/oms/submission_contract.py` runs here on the Postgres adapters, as `cv_app` on a
database set up like production (`pg_bootstrap.sql`'s roles, then the migrations as `cv_owner`),
and on the in-memory stores in `test_submission_fake.py`, so the fakes the OMS's unit suites use
take only what Postgres takes, by the names Postgres gives (C-13.3). The races, the rollbacks and
the share-locked re-check are real here; `test_order_submission_pg.py` keeps the cases only a
database can stage (lock waits, the sweep over every account). The pairing reads' contract
(`store_reads_contract.py`, E29-T05) runs here too, beside it, with the exit routes' scoped reads
(E29-T04 slice 4) over real grants, owner roles and accounts of two environments.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import uuid
from collections.abc import AsyncIterator, Iterator
from pathlib import Path
from typing import Any, Final

import psycopg
import pytest
import pytest_asyncio
from testcontainers.postgres import PostgresContainer

from candleviewer.storage.repositories.executions_sqlalchemy import SqlAlchemyExecutionStore
from candleviewer.storage.repositories.idempotency_anchors_sqlalchemy import (
    SqlAlchemyIdempotencyAnchorStore,
)
from candleviewer.storage.repositories.orders import NewOrder
from candleviewer.storage.repositories.orders_sqlalchemy import SqlAlchemyOrderStore
from candleviewer.storage.repositories.recorded_stops_sqlalchemy import (
    SqlAlchemyRecordedStopStore,
)
from candleviewer.storage.repositories.relational_sqlalchemy import (
    SqlAlchemyRelationalRepository,
)
from candleviewer.storage.repositories.submissions import FirstPersist, SubmissionRefusal
from candleviewer.storage.repositories.submissions_sqlalchemy import SqlAlchemySubmissionStore
from tests.unit.oms.store_reads_contract import StoreReadsContract
from tests.unit.oms.submission_contract import Bounded, Harness, SubmissionContract

pytestmark = pytest.mark.integration

_ROOT = Path(__file__).resolve().parents[3]
_BOOTSTRAP = _ROOT.parents[1] / "infra" / "scripts" / "pg_bootstrap.sql"


def _login(dsn: str, role: str) -> str:
    return re.sub(r"://[^@]+@", f"://{role}:{role}_test_pw@", dsn)


@pytest.fixture(scope="module")
def pg_dsn() -> Iterator[str]:
    """Superuser DSN of a database set up like production (test_order_submission_pg.py)."""
    with PostgresContainer("postgres:16-alpine", dbname="candleviewer") as container:
        dsn = container.get_connection_url().replace("postgresql+psycopg2", "postgresql+asyncpg")
        info = psycopg.conninfo.conninfo_to_dict(dsn.replace("postgresql+asyncpg", "postgresql"))
        psql = shutil.which("psql")
        assert psql is not None, "the CI integration and migrations jobs have postgresql-client"
        bootstrap = subprocess.run(  # noqa: S603 -- resolved absolute path, fixed argv, no shell
            [psql, "-h", str(info["host"]), "-p", str(info["port"]), "-U", str(info["user"]),
             "-d", "candleviewer", "-v", "ON_ERROR_STOP=1", "-v", "owner_pw=cv_owner_test_pw",
             "-v", "app_pw=cv_app_test_pw", "-v", "ro_pw=cv_ro_test_pw", "-f", str(_BOOTSTRAP)],
            check=False, capture_output=True, text=True, timeout=120,
            env={**os.environ, "PGPASSWORD": str(info["password"])},
        )  # fmt: skip
        assert bootstrap.returncode == 0, bootstrap.stderr
        owner = _login(dsn, "cv_owner").replace("postgresql+asyncpg", "postgresql+psycopg")
        subprocess.run(
            [sys.executable, "-m", "alembic", "upgrade", "head"],
            cwd=_ROOT, env={**os.environ, "CV_PG_DSN": owner}, check=True, timeout=300,
        )  # fmt: skip
        yield dsn


def _sql(dsn: str, query: str, *args: object) -> list[tuple[Any, ...]]:
    with psycopg.connect(dsn.replace("postgresql+asyncpg", "postgresql"), autocommit=True) as c:
        cursor = c.execute(query, args)
        return cursor.fetchall() if cursor.description else []


def _user(dsn: str) -> uuid.UUID:
    uid = uuid.uuid4()
    _sql(
        dsn,
        "INSERT INTO users (id, email, username, password_hash, status) "
        "VALUES (%s, %s, %s, '$argon2id$x', 'active')",
        uid, f"{uid}@example.test", f"u{uid.hex[:12]}",
    )  # fmt: skip
    return uid


def _account(dsn: str, env: str = "demo") -> tuple[uuid.UUID, uuid.UUID]:
    """An account of `env` and its bootstrap profile (`trg_ea_default_profile`, version 1)."""
    account = uuid.uuid4()
    _sql(
        dsn,
        "INSERT INTO exchange_accounts (id, exchange, env, kind, exchange_uid, label) "
        "VALUES (%s, 'bybit', %s, 'main', %s, %s)",
        account, env, str(account.int % 10**15), f"acct {account.hex[:8]}",
    )  # fmt: skip
    [(profile,)] = _sql(
        dsn,
        "SELECT id FROM account_profiles WHERE exchange_account_id = %s AND is_default",
        account,
    )
    return account, uuid.UUID(str(profile))


def _grant(dsn: str, user: uuid.UUID, account: uuid.UUID, trade: bool, frozen: bool) -> None:
    """A viewing grant, trading for `trade`, frozen with its time (`uaa_frozen_consistency`)."""
    _sql(
        dsn,
        "INSERT INTO user_account_access (user_id, exchange_account_id, can_view, can_trade, "
        "frozen, frozen_at) VALUES (%s, %s, true, %s, %s, CASE WHEN %s THEN now() END)",
        user, account, trade, frozen, frozen,
    )  # fmt: skip


def _owner(dsn: str, user: uuid.UUID) -> None:
    sql = "INSERT INTO user_roles (user_id, role_id) SELECT %s, id FROM roles WHERE name = 'owner'"
    _sql(dsn, sql, user)


def _refuse(dsn: str, account: uuid.UUID, reason: SubmissionRefusal) -> None:
    """The account soft-deleted, or its profile moved past version 1 by an edit."""
    if reason == "account_not_live":
        _sql(dsn, "UPDATE exchange_accounts SET deleted_at = now() WHERE id = %s", account)
        return
    moved = "UPDATE account_profiles SET leverage = 3 WHERE exchange_account_id = %s AND is_default"
    _sql(dsn, moved, account)


def _held(dsn: str, first: FirstPersist, order: NewOrder) -> tuple[int, ...]:
    """How many of the persist's anchor, group, leg, order and stop rows exist."""
    [counts] = _sql(
        dsn,
        "SELECT (SELECT count(*) FROM idempotency_anchors WHERE id = %s), "
        "(SELECT count(*) FROM trade_groups WHERE id = %s), "
        "(SELECT count(*) FROM trade_group_legs WHERE id = ANY(%s)), "
        "(SELECT count(*) FROM orders WHERE id = %s), "
        "(SELECT count(*) FROM recorded_stops WHERE id = ANY(%s))",
        first.anchor.id, first.group.id if first.group else None,
        [leg.id for leg in first.legs], order.id, [s.id for s in first.recorded_stops],
    )  # fmt: skip
    return tuple(int(n) for n in counts)


#: A lifecycle move no store writes yet, as `trg_rs_guard` and `rs_times` admit it (fixed SQL).
_MOVES: Final = {
    "in_force": "UPDATE recorded_stops SET status = 'in_force', in_force_at = now(), "
                "answered_at = coalesce(answered_at, now()) WHERE id = %s",
    "replaced": "UPDATE recorded_stops SET status = 'replaced', closed_at = now() WHERE id = %s",
    "ended": "UPDATE recorded_stops SET status = 'ended', closed_at = now() WHERE id = %s",
}  # fmt: skip


def _move_stop(dsn: str, record_id: uuid.UUID, status: str) -> None:
    _sql(dsn, _MOVES[status], record_id)


def _bind_stop(dsn: str, record_id: uuid.UUID, exchange_order_id: str) -> None:
    sql = "UPDATE recorded_stops SET exchange_order_id = %s WHERE id = %s"
    _sql(dsn, sql, exchange_order_id, record_id)


def _twin_stop(dsn: str, record_id: uuid.UUID, twin_id: uuid.UUID) -> None:
    sql = (
        "INSERT INTO recorded_stops SELECT (jsonb_populate_record(NULL::recorded_stops, "
        "to_jsonb(r) || jsonb_build_object('id', %s::text, 'exchange_order_id', NULL))).* "
        "FROM recorded_stops r WHERE r.id = %s"
    )
    _sql(dsn, sql, twin_id, record_id)


@pytest_asyncio.fixture
async def h(pg_dsn: str) -> AsyncIterator[Harness]:
    """The stores on one pool, as `cv_app`; every user, account and profile a new row."""
    rel = SqlAlchemyRelationalRepository(_login(pg_dsn, "cv_app"), "submission-contract-it")

    def bounded(seconds: float) -> Bounded:
        return Bounded(
            SqlAlchemySubmissionStore(rel, audit_timeout_s=seconds),
            SqlAlchemyRecordedStopStore(rel, audit_timeout_s=seconds),
        )

    try:
        yield Harness(
            submissions=SqlAlchemySubmissionStore(rel),
            anchors=SqlAlchemyIdempotencyAnchorStore(rel),
            stops=SqlAlchemyRecordedStopStore(rel),
            orders=SqlAlchemyOrderStore(rel),
            executions=SqlAlchemyExecutionStore(rel),
            new_user=lambda: _user(pg_dsn),
            new_account=lambda: _account(pg_dsn),
            refuse=lambda account, reason: _refuse(pg_dsn, account, reason),
            bounded=bounded,
            held=lambda first, order: _held(pg_dsn, first, order),
            move_stop=lambda record_id, status: _move_stop(pg_dsn, record_id, status),
            bind_stop=lambda record_id, xid: _bind_stop(pg_dsn, record_id, xid),
            twin_stop=lambda record_id, twin_id: _twin_stop(pg_dsn, record_id, twin_id),
            tick=lambda: None,
            grant=lambda user, account, trade, frozen: _grant(pg_dsn, user, account, trade, frozen),
            owner=lambda user: _owner(pg_dsn, user),
            elsewhere=lambda: _account(pg_dsn, "live"),
        )
    finally:
        await rel.dispose()


class TestSubmissionContractOnPostgres(SubmissionContract, StoreReadsContract):
    """E29-T04's submission contract on real row locks and real rollbacks, and E29-T05's reads."""

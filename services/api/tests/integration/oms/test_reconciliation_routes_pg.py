"""Integration (E29-T06 #914): the reconciliation routes' records on a migrated Postgres 16
(testcontainers, `alembic upgrade head`). The two routes on their audited admin router, over the
real accounts store (`SqlAlchemyAccountsStore`: the Owner's live-owner scope read in SQL) and a
real `AuditWriter` over `audit_log`; the OMS is the unit rig's stand-in, which runs the route's
write-ahead before it tells B19, as the driver does (`test_admin_reconciliation_driver.py` runs the
routes over the driver itself), and the step-up a stand-in that grants the `accounts` request
(`test_admin_reconciliation.py` holds the real gate). One loop serves the requests, the writer and
the pools. Needs Docker; CI `integration` runs it.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import httpx
import psycopg
import pytest
from fastapi import FastAPI, Request

from candleviewer.accounts.repository import AccountsRepository
from candleviewer.admin.http import AdminAreaRefused, admin_area_refused_handler
from candleviewer.api.admin_reconciliation import make_admin_reconciliation_router
from candleviewer.audit.access import AuditPrincipal
from candleviewer.audit.query import AuditQueryService
from candleviewer.audit.writer import AuditWriter
from candleviewer.auth.step_up import StepUpChallenge
from candleviewer.storage.repositories.accounts_sqlalchemy import SqlAlchemyAccountsStore
from candleviewer.storage.repositories.audit_sqlalchemy import SqlAlchemyAuditRepository
from candleviewer.storage.repositories.relational_sqlalchemy import SqlAlchemyRelationalRepository
from tests.integration import _refused
from tests.unit.api.test_admin_reconciliation import Runtime, Service
from tests.unit.api.test_admin_reconciliation_driver import Granting

pytestmark = pytest.mark.integration

pg_dsn = _refused.pg_dsn  # the module-scoped Postgres 16, migrated; its database is named `test`
SESSION, REQUEST = uuid.UUID(int=0x5E55), uuid.UUID(int=0x9E9)
BODY = {"reason": "Exchange reachable again; positions checked by hand."}


def _sql(dsn: str, query: str, *args: object) -> list[tuple[Any, ...]]:
    with psycopg.connect(dsn.replace("postgresql+asyncpg", "postgresql"), autocommit=True) as c:
        cursor = c.execute(query, args)
        return cursor.fetchall() if cursor.description else []


@pytest.fixture(scope="module")
def owner(pg_dsn: str) -> uuid.UUID:
    """A live user holding the owner role: the store's scope reads both, and each record's
    actor is a user row (`audit_log.actor_user_id`)."""
    uid = uuid.uuid4()
    _sql(
        pg_dsn,
        "INSERT INTO users (id, email, username, password_hash, status) "
        "VALUES (%s, 'recon-owner@example.test', 'recon-owner', '$argon2id$x', 'active')",
        uid,
    )
    _sql(pg_dsn, "INSERT INTO user_roles (user_id, role_id) SELECT %s, id FROM roles "
                 "WHERE name = 'owner'", uid)  # fmt: skip
    return uid


def _account(dsn: str, env: str) -> uuid.UUID:
    account = uuid.uuid4()
    _sql(
        dsn,
        "INSERT INTO exchange_accounts (id, exchange, env, kind, exchange_uid, label) "
        "VALUES (%s, 'bybit', %s, 'main', %s, %s)",
        account, env, str(account.int % 10**15), f"recon {account.hex[:8]}",
    )  # fmt: skip
    return account


class _Granted(Granting):
    """The stand-in step-up, noting each grant it lets a request spend."""

    def __init__(self) -> None:
        super().__init__()
        self.spent: list[StepUpChallenge] = []

    async def consume_single_use(
        self, session_id: str, action_class: str, *, fingerprint: str
    ) -> StepUpChallenge:
        grant = await super().consume_single_use(session_id, action_class, fingerprint=fingerprint)
        self.spent.append(grant)
        return grant


class _Owner:
    def __init__(self, user: uuid.UUID) -> None:
        self._user = user

    async def resolve(self, request: Request) -> AuditPrincipal:
        perms = frozenset({"admin:read", "admin:write"})
        return AuditPrincipal(self._user, "recon-owner", perms, SESSION, "10.0.0.9", REQUEST, True)


@pytest.fixture
async def served(pg_dsn: str, owner: uuid.UUID, tmp_path: Path) -> AsyncIterator[SimpleNamespace]:
    relational = SqlAlchemyRelationalRepository(pg_dsn, "recon-routes-audit")
    stored = SqlAlchemyRelationalRepository(pg_dsn, "recon-routes-accounts")
    writer = AuditWriter(SqlAlchemyAuditRepository(relational), str(tmp_path / "audit.wal"))
    await writer.start()
    service, granted = Service(), _Granted()
    app = FastAPI()
    app.add_exception_handler(AdminAreaRefused, admin_area_refused_handler)
    app.include_router(
        make_admin_reconciliation_router(
            AccountsRepository(SqlAlchemyAccountsStore(stored)), lambda: Runtime(service),
            environment="demo", auth=cast(Any, granted), resolver=_Owner(owner),
            audit=cast(Any, writer),  # its `emit` names its keywords; the route's takes any
        )
    )  # fmt: skip
    transport = httpx.ASGITransport(app=app)
    query = AuditQueryService(SqlAlchemyAuditRepository(relational))
    try:
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            yield SimpleNamespace(
                client=client, service=service, writer=writer, query=query, granted=granted
            )
    finally:
        await writer.stop(5.0)
        await relational.dispose()
        await stored.dispose()


async def test_the_routes_records_land_in_audit_log_ahead_of_their_effects_and_chained(
    pg_dsn: str, owner: uuid.UUID, served: SimpleNamespace
) -> None:
    """The resolve of a locked job, then a manual pass, then that pass's key replayed: two
    `oms.reconcile` records (`resolved` with the state, the reason and the spent grant's
    `challenge_id`; `requested` with the pass), each as the Owner on the account, beside the
    guard's three `admin.area_entered`; the replay writes no second record, and the chain
    verifies."""
    s, account = served, _account(pg_dsn, "demo")
    s.service.states[account] = "stale_lockout"
    resolve, run = f"/admin/reconciliation/{account}/resolve", f"/admin/reconciliation/{account}"
    keys = [{"Idempotency-Key": str(uuid.uuid4())} for _ in range(2)]
    resolved = await s.client.post(resolve, json=BODY, headers=keys[0])
    started = await s.client.post(run, headers=keys[1])
    again = await s.client.post(run, headers=keys[1])
    await s.writer.flush(60.0)
    chain = await s.query.verify()
    assert [r.status_code for r in (resolved, started, again)] == [200, 202, 202]
    assert again.headers["idempotency-replayed"] == "true" and again.content == started.content
    assert [event for event, *_ in s.service.told] == ["OPERATOR_RESOLVED", "SWEEP_DUE"]
    rows = _sql(
        pg_dsn,
        "SELECT actor_user_id, actor_label, session_id, object_kind, outcome::text, "
        "severity::text, reason, after_state FROM audit_log WHERE action = 'oms.reconcile' "
        "AND object_id = %s ORDER BY id",
        str(account),
    )
    assert [row[:7] for row in rows] == [
        (owner, "recon-owner", SESSION, "exchange_account", "success", "warning", "resolved"),
        (owner, "recon-owner", SESSION, "exchange_account", "success", "info", "requested"),
    ]
    (grant,) = s.granted.spent
    assert [row[7] for row in rows] == [
        {"stage": "resolved", "state": "stale_lockout", "reason": BODY["reason"],
         "challenge_id": str(grant.challenge_id)},
        {"stage": "requested", "trigger": "manual", "pass_id": started.json()["pass_id"],
         "joined": False},
    ]  # fmt: skip
    entered = _sql(
        pg_dsn,
        "SELECT object_id, outcome::text FROM audit_log WHERE action = 'admin.area_entered' "
        "AND actor_user_id = %s ORDER BY id",
        owner,
    )
    assert entered == [
        ("/admin/reconciliation/{accountId}/resolve", "success"),
        ("/admin/reconciliation/{accountId}", "success"),
        ("/admin/reconciliation/{accountId}", "success"),
    ]
    assert chain.verified


async def test_an_account_of_another_environment_is_404_and_records_no_decision(
    pg_dsn: str, served: SimpleNamespace
) -> None:
    """C-2.11 in SQL: the store reads the live account; the route answers another environment's
    as absent, and nothing reaches B19 or `oms.reconcile`."""
    s, live, absent = served, _account(pg_dsn, "live"), uuid.uuid4()
    other = await s.client.post(
        f"/admin/reconciliation/{live}", headers={"Idempotency-Key": str(uuid.uuid4())}
    )
    missing = await s.client.post(
        f"/admin/reconciliation/{absent}", headers={"Idempotency-Key": str(uuid.uuid4())}
    )
    await s.writer.flush(60.0)
    assert (other.status_code, other.content) == (404, missing.content)
    assert s.service.told == []
    rows = _sql(
        pg_dsn,
        "SELECT count(*) FROM audit_log WHERE action = 'oms.reconcile' AND object_id IN (%s, %s)",
        str(live),
        str(absent),
    )
    assert rows == [(0,)]

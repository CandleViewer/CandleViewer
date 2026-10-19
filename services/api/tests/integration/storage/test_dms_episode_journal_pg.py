"""Integration: the dead-man's-switch episode journal on Postgres 16 (E27-T04 W5, #837): the row,
the resolve (its account's older open rows only), the replay read (open, latest per account, newest
first, bounded) and the environment fence (C-2.11). Each test makes its own accounts."""

from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa
from testcontainers.postgres import PostgresContainer

from candleviewer.storage.repositories.accounts import AccountsStoreError
from candleviewer.storage.repositories.dms_episodes_sqlalchemy import SqlAlchemyDmsEpisodeJournal
from candleviewer.storage.repositories.relational_sqlalchemy import SqlAlchemyRelationalRepository

pytestmark = pytest.mark.integration

_ROOT = Path(__file__).resolve().parents[3]
T = datetime(2026, 10, 18, 12, tzinfo=UTC)
_OLDER = [("exchange", "rate_limit"), ("ws", "dms_hook_owed")]  # neither is the journal's
_ACCOUNT = sa.text(
    "INSERT INTO exchange_accounts (id, exchange, env, kind, exchange_uid, label) "
    "VALUES (CAST(:id AS uuid), 'bybit', CAST(:env AS exchange_env), 'main', :uid, :label)"
)
_ROWS = sa.text(
    "SELECT id, component, kind, severity::text AS severity, details, event_ts, resolved_at "
    "FROM system_events WHERE exchange_account_id = CAST(:account AS uuid) ORDER BY id"
)
_EVENT = sa.text(  # another open event of the account's, which the journal must never touch
    "INSERT INTO system_events (component, kind, severity, exchange_account_id, message) VALUES "
    "(:component, :kind, CAST('error' AS severity), CAST(:account AS uuid), 'other') RETURNING id"
)
_SETTLE = sa.text("UPDATE system_events SET resolved_at = :at WHERE id = :id RETURNING id")
_DELETE = sa.text("UPDATE exchange_accounts SET deleted_at = now() WHERE id = :id RETURNING id")


@pytest.fixture(scope="module")
def pg_dsn() -> Iterator[str]:
    with PostgresContainer("postgres:16-alpine") as container:
        url = container.get_connection_url()
        env = {**os.environ, "CV_PG_DSN": url.replace("postgresql+psycopg2", "postgresql+psycopg")}
        subprocess.run(  # bounded, so a stuck migration fails the module instead of hanging it
            [sys.executable, "-m", "alembic", "upgrade", "head"],
            cwd=_ROOT,
            env=env,
            check=True,
            timeout=120,
        )
        yield url.replace("postgresql+psycopg2", "postgresql+asyncpg")


@pytest.fixture
async def rel(pg_dsn: str) -> AsyncIterator[SqlAlchemyRelationalRepository]:
    repository = SqlAlchemyRelationalRepository(pg_dsn, "test")
    yield repository
    await repository.dispose()


async def _account(rel: SqlAlchemyRelationalRepository, env: str = "demo") -> UUID:
    account = uuid4()
    params = {"id": str(account), "env": env, "uid": str(account.int % 10**12)}
    async with rel.unit_of_work() as uow:
        await uow.session.execute(_ACCOUNT, {**params, "label": f"acct-{account.hex[:12]}"})
        await uow.commit()
    return account


async def _rows(rel: SqlAlchemyRelationalRepository, account: UUID) -> list[dict[str, Any]]:
    async with rel.unit_of_work() as uow:
        res = await uow.session.execute(_ROWS, {"account": str(account)})
        return [dict(m) for m in res.mappings()]


async def _execute(rel: SqlAlchemyRelationalRepository, statement: Any, **params: Any) -> int:
    async with rel.unit_of_work() as uow:  # the one row it wrote, or it raises
        found = int((await uow.session.execute(statement, params)).scalar_one())
        await uow.commit()
    return found


async def _episode(journal: SqlAlchemyDmsEpisodeJournal, account: UUID, minute: int = 0) -> int:
    at = T + timedelta(minutes=minute)
    return await journal.record(account, from_state="degraded", reason="no_success", at=at)


async def test_a_record_writes_one_open_warning_row_for_its_account(
    rel: SqlAlchemyRelationalRepository,
) -> None:
    account = await _account(rel)
    row = await _episode(SqlAlchemyDmsEpisodeJournal(rel, env="demo"), account)
    [written] = await _rows(rel, account)
    assert written == {
        "id": row, "component": "exchange", "kind": "dms_hook_owed", "severity": "warning",
        "details": {"from_state": "degraded", "reason": "no_success"}, "event_ts": T,
        "resolved_at": None,
    }  # fmt: skip


async def test_a_resolve_closes_the_row_and_its_accounts_older_open_rows_only(
    rel: SqlAlchemyRelationalRepository,
) -> None:
    journal = SqlAlchemyDmsEpisodeJournal(rel, env="demo")
    account, other = await _account(rel), await _account(rel)
    first, second, third = [await _episode(journal, account, m) for m in range(3)]
    await _episode(journal, other)
    await journal.resolve(account, second)
    closed = [(r["id"], r["resolved_at"] is not None) for r in await _rows(rel, account)]
    assert closed == [(first, True), (second, True), (third, False)]
    assert [r["resolved_at"] for r in await _rows(rel, other)] == [None]


async def test_the_replay_reads_the_latest_open_row_per_account_newest_first_and_bounded(
    rel: SqlAlchemyRelationalRepository,
) -> None:
    journal = SqlAlchemyDmsEpisodeJournal(rel, env="testnet")
    a, b, settled = [await _account(rel, "testnet") for _ in range(3)]
    await _episode(journal, a, 1)
    a_latest = await _episode(journal, a, 2)
    b_row = await _episode(journal, b, 3)
    await journal.resolve(settled, await _episode(journal, settled, 4))  # resolved: never replayed
    mine = {a, b, settled}
    rows = [r for r in await journal.open_episodes(10) if r.account_id in mine]
    assert [(r.row, r.account_id, r.from_state, r.reason) for r in rows] == [
        (b_row, b, "degraded", "no_success"),
        (a_latest, a, "degraded", "no_success"),
    ]
    assert rows[0].at == T + timedelta(minutes=3)
    assert [r.row for r in await journal.open_episodes(1)] == [b_row]  # the newest open one


async def test_another_environments_episode_is_never_recorded_resolved_nor_replayed(
    rel: SqlAlchemyRelationalRepository,
) -> None:
    live, demo = await _account(rel, "live"), SqlAlchemyDmsEpisodeJournal(rel, env="demo")
    with pytest.raises(AccountsStoreError):
        await _episode(demo, live)
    row = await _episode(SqlAlchemyDmsEpisodeJournal(rel, env="live"), live)
    await demo.resolve(live, row)
    assert live not in {r.account_id for r in await demo.open_episodes(1000)}
    assert [(r["id"], r["resolved_at"]) for r in await _rows(rel, live)] == [(row, None)]


async def test_the_journal_never_reads_nor_resolves_another_event_of_its_account(
    rel: SqlAlchemyRelationalRepository,
) -> None:
    journal, account = SqlAlchemyDmsEpisodeJournal(rel, env="demo"), await _account(rel)
    settled, past, ids = await _episode(journal, account), T - timedelta(days=1), str(account)
    older = [await _execute(rel, _EVENT, account=ids, component=c, kind=k) for c, k in _OLDER]
    row = await _episode(journal, account, 1)
    newer = await _execute(rel, _EVENT, account=ids, component="exchange", kind="clock_drift")
    await _execute(rel, _SETTLE, at=past, id=settled)  # an older episode, settled before
    assert [r.row for r in await journal.open_episodes(1000) if r.account_id == account] == [row]
    await journal.resolve(account, row)
    resolved = {r["id"]: r["resolved_at"] for r in await _rows(rel, account)}
    assert [resolved[n] for n in [*older, newer]] == [None] * 3 and resolved[settled] == past


async def test_a_soft_deleted_accounts_open_episode_is_still_replayed(
    rel: SqlAlchemyRelationalRepository,
) -> None:
    journal, account = SqlAlchemyDmsEpisodeJournal(rel, env="demo"), await _account(rel)
    row = await _episode(journal, account)
    await _execute(rel, _DELETE, id=account)  # a soft delete; on purpose: the policy decides
    assert row in {r.row for r in await journal.open_episodes(1000)}

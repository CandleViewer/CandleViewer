"""Integration (E42-T04 S7, #965): AC1 end to end on the deployed app over real Postgres 16.

The scenario and checks of `tests/security/auth/test_disable_user_e2e.py` with every store of
`create_app()` on the database; only the audit writer is a stand-in and the clock is the test's.
Needs Docker (testcontainers); CI `integration` runs it.
"""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
import sqlalchemy as sa
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import create_async_engine
from testcontainers.postgres import PostgresContainer

from candleviewer.auth.models import SessionRecord
from candleviewer.settings import Settings
from candleviewer.storage.repositories.relational_sqlalchemy import (
    SqlAlchemyRelationalRepository,
)
from candleviewer.storage.repositories.sessions_sqlalchemy import SqlAlchemySessionRepository
from tests.integration.admin.test_user_lifecycle_pg import _ACCOUNT, _FREEZE, _GRANT, _ROLE, _USER
from tests.security.auth.test_disable_user_drill import _Clock
from tests.security.auth.test_disable_user_e2e import (
    _settings,
    deployed,
    rule_disarmed,
    scenario,
    sessions_ended,
)

pytestmark = pytest.mark.integration

_ROOT = Path(__file__).resolve().parents[3]
_OWNER, _M, _EXCHANGE = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
_KEPT = sa.text(
    "SELECT u.status::text, (SELECT count(*) FROM user_roles r WHERE r.user_id = u.id), "
    "g.can_view, g.can_trade, g.frozen, g.frozen_reason, g.max_daily_loss_usd "
    "FROM users u JOIN user_account_access g ON g.user_id = u.id WHERE u.id = CAST(:id AS uuid)"
)
_SESSIONS = sa.text(
    "SELECT revoked_reason FROM sessions WHERE user_id = CAST(:id AS uuid) ORDER BY 1"
)


@pytest.fixture(scope="module")
def pg_dsn() -> Iterator[str]:
    with PostgresContainer("postgres:16-alpine") as container:
        dsn = container.get_connection_url().replace("postgresql+psycopg2", "postgresql+asyncpg")
        subprocess.run(
            [sys.executable, "-m", "alembic", "upgrade", "head"],
            cwd=_ROOT,
            env={
                **os.environ,
                "CV_PG_DSN": dsn.replace("postgresql+asyncpg", "postgresql+psycopg"),
            },
            check=True,
        )
        yield dsn


class _Parked(SqlAlchemySessionRepository):
    """Once `park` is set, a mint waits for it: a refresh has claimed its session and has not
    minted the successor yet (as #2911's test parks it)."""

    def __init__(self, relational: SqlAlchemyRelationalRepository) -> None:
        super().__init__(relational, lambda **fields: SessionRecord.model_validate(fields))
        self.park: asyncio.Event | None = None
        self.parked = asyncio.Event()

    async def create_session(self, session: Any) -> Any:
        if self.park is not None:
            self.parked.set()
            await self.park.wait()
        return await super().create_session(session)


async def _seed(dsn: str) -> None:
    """Owner O, and manager M with a grant on one account, frozen with a cap (O4)."""
    engine = create_async_engine(dsn)
    try:
        async with engine.begin() as conn:
            for uid, role in ((_OWNER, "owner"), (_M, "manager")):
                name = f"s7{uid.hex[:12]}"
                await conn.execute(
                    _USER, {"id": str(uid), "email": f"{name}@x.invalid", "name": name}
                )
                await conn.execute(_ROLE, {"id": str(uid), "role": role})
            await conn.execute(_ACCOUNT, {"id": str(_EXCHANGE), "uid": "5702", "label": "s7"})
            grant = {"user": str(_M), "account": str(_EXCHANGE), "view": True, "trade": True}
            await conn.execute(_GRANT, grant)
            await conn.execute(_FREEZE, {"id": str(_M), "by": str(_OWNER)})
    finally:
        await engine.dispose()


async def _kept(dsn: str) -> tuple[Any, list[Any]]:
    engine = create_async_engine(dsn)
    try:
        async with engine.connect() as conn:
            kept = (await conn.execute(_KEPT, {"id": str(_M)})).one()
            sessions = [r[0] for r in await conn.execute(_SESSIONS, {"id": str(_M)})]
    finally:
        await engine.dispose()
    return tuple(kept), sessions


def test_delete_route_two_sessions_one_rule(pg_dsn: str) -> None:
    """AC1, SR-029, O4 on Postgres: two sessions and one armed rule of manager M; the Owner's
    DELETE ends both sessions (REST 401) and both sockets (`bye user_disabled`, 4403) within 5 s
    on the test clock, the refresh in flight mints no successor (#2911), the rule is disarmed
    through B9 and audited, and every row of M stays: the user (disabled, with its role), the
    grant (soft-revoked, freeze state and cap kept) and the three session rows."""
    asyncio.run(_seed(pg_dsn))
    w = SimpleNamespace(clock=_Clock())
    w.clock.now = datetime.now(UTC).replace(microsecond=0)  # one time base with the database's
    settings: Settings = _settings().model_copy(update={"pg_dsn": SecretStr(pg_dsn)})
    relational = SqlAlchemyRelationalRepository(pg_dsn, "it-s7")
    w.repo = _Parked(relational)
    with pytest.MonkeyPatch.context() as mp, deployed(mp, settings, w) as (app, client):
        w.rules = app.state.app_context.rules._store  # the `PostgresRuleStore` it is bound to
        scenario(app, client, w, str(_OWNER), str(_M))
        assert client.portal is not None
        client.portal.call(relational.dispose)
    sessions_ended(w)
    rule_disarmed(w, _OWNER, _M)
    kept, sessions = asyncio.run(_kept(pg_dsn))
    assert kept == ("disabled", 1, False, False, True, "drawdown", Decimal(250))
    assert sessions == ["rotated", "user_disabled", "user_disabled"]
    assert not w.rule_row.deleted and len(w.rule_row.versions) == 1

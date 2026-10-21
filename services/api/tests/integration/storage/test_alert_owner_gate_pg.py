"""Integration (#3349, E42-X01 UL-F8): the identity read path of the alerts owner gate, on real
Postgres 16. `SqlAlchemyIdentityProvider.active_users` answers with the permission readers' test,
so a user who is disabled, locked, invited or deleted is not an active owner exactly when the
readers give them no permission. Not run on a laptop without docker; exercised by CI `integration`.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
import sqlalchemy as sa

from candleviewer.storage.repositories.identity_sqlalchemy import SqlAlchemyIdentityProvider
from candleviewer.storage.repositories.relational_sqlalchemy import (
    SqlAlchemyRelationalRepository,
)
from tests.integration.storage import test_rule_perms_status_pg as _perms

pytestmark = pytest.mark.integration
pg_dsn, db = _perms.pg_dsn, _perms.db  # the module-scoped Postgres 16, one active owner standing


@pytest.mark.parametrize("change", list(_perms._CHANGES))
async def test_active_users_agrees_with_the_permission_readers(
    pg_dsn: str, db: Any, change: str
) -> None:
    engine, readers = db
    rel = SqlAlchemyRelationalRepository(pg_dsn, "owner-gate-it")
    try:
        user = await _perms._user(engine, "manager")
        ids = [str(user), str(uuid.uuid4())]  # and an id no user row has
        directory = SqlAlchemyIdentityProvider(rel)
        assert await directory.active_users(ids) == {str(user)}
        assert await readers["session_info"](user)
        async with engine.begin() as conn:
            await conn.execute(sa.text(_perms._CHANGES[change]), {"id": str(user)})
        assert await directory.active_users(ids) == frozenset()
        assert await readers["session_info"](user) == frozenset()
    finally:
        await rel.dispose()

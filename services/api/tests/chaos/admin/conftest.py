"""Fixtures of the E42-Q03 admin chaos suite (#1216; catalogue in SCENARIOS.md).

The scenarios run on a migrated Postgres 16 in a loopback-only testcontainer, one per module, its
database named `test` (`tests.integration._refused.pg_dsn`, as the Q01 integration tests use):
AUDIT-CORRUPT's module gets a database no load set ever shares. Without Docker the fixture
errors: a run without the database is a failure, never a silent pass.
"""

from __future__ import annotations

import inspect
import uuid
from collections.abc import AsyncIterator, Iterator

import pytest

from candleviewer.audit.access import AuditPrincipal
from tests.chaos.admin._relay import Relay, upstream_of
from tests.chaos.admin._server import owner_principal, require_test_database
from tests.integration import _refused

# The Q01 container fixture (module-scoped, migrated to head), registered under another name so
# `pg_dsn` below can wrap it: every consumer of the DSN is then guarded, whatever the fixture order.
_unguarded_pg_dsn = pytest.fixture(scope="module", name="_unguarded_pg_dsn")(
    inspect.unwrap(_refused.pg_dsn)
)


@pytest.fixture(scope="module")
def pg_dsn(_unguarded_pg_dsn: str) -> Iterator[str]:
    """The module's Postgres DSN, refused unless it is a loopback `test` database."""
    require_test_database(_unguarded_pg_dsn)
    yield _unguarded_pg_dsn


@pytest.fixture
async def relay(pg_dsn: str) -> AsyncIterator[Relay]:
    """A relay in front of the module's Postgres. Teardown heals it and asserts it passes again,
    so a scenario that failed mid-fault leaves no fault behind."""
    require_test_database(pg_dsn)
    async with Relay(upstream_of(pg_dsn)) as opened:
        try:
            yield opened
        finally:
            await opened.heal()
            await opened.ensure_up()


@pytest.fixture
def owner(pg_dsn: str) -> AuditPrincipal:
    """An Owner who is a `users` row (`audit_log.actor_user_id` references `users`)."""
    return owner_principal(uuid.UUID(_refused.seed_user(pg_dsn)))

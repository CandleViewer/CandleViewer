"""`statement_timeout` actually fires on the audit read path (CI-only, testcontainers)."""

from __future__ import annotations

import pytest
import sqlalchemy as sa

from candleviewer.storage.repositories import audit_sqlalchemy as mod

pytestmark = pytest.mark.integration


def test_set_config_timeout_cancels_slow_query_with_sqlstate_57014() -> None:
    pytest.importorskip("testcontainers")
    from testcontainers.postgres import PostgresContainer

    with PostgresContainer("postgres:16.4", driver="psycopg") as pg:
        engine = sa.create_engine(pg.get_connection_url())
        with engine.begin() as conn:
            conn.execute(mod._SET_TIMEOUT_SQL, {"v": "50ms"})
            with pytest.raises(sa.exc.DBAPIError) as err:
                conn.execute(sa.text("SELECT count(*) FROM generate_series(1, 2000000000)"))
        assert mod._sqlstate(err.value) == mod._QUERY_CANCELED

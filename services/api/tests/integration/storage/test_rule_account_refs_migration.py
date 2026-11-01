"""Integration (#2291, SR-051): `0063_rule_version_account_refs` on real Postgres 16.

The revision adds one nullable `text[]` column and drops it on the downgrade: up, down and up again
on an empty database and on one holding a version saved before it (C-5.2, C-5.5). A version saved
before the revision holds no set (NULL), which the store fills. The revision below it is this
file's `_PREV`: whoever merges second renames and re-parents the revision (C-5.3) and moves it.
Not run on a laptop without docker; exercised by CI `integration`.
"""

from __future__ import annotations

from typing import Any

import pytest

from tests.integration.storage import test_rules_migration as _mig

pytestmark = pytest.mark.integration
pg_dsn = _mig.pg_dsn  # a module-scoped Postgres 16 container, upgraded to head

#: The revision `0063_rule_version_account_refs` sits on (its `down_revision`).
_PREV = "0061_password_history"
_COLUMN = (
    "SELECT data_type, udt_name, is_nullable, column_default FROM information_schema.columns "
    "WHERE table_name = 'rule_versions' AND column_name = 'account_refs'"
)


def _column(dsn: str) -> Any:
    with _mig._conn(dsn) as c:
        return c.execute(_COLUMN).fetchone()


def test_the_column_is_added_nullable_and_dropped_on_downgrade(pg_dsn: str) -> None:
    added = ("ARRAY", "_text", "YES", None)  # nullable, no default: no table rewrite
    assert _column(pg_dsn) == added
    _mig._alembic(pg_dsn, "downgrade", _PREV)
    try:
        assert _column(pg_dsn) is None
    finally:
        _mig._alembic(pg_dsn, "upgrade", "head")
    assert _column(pg_dsn) == added


def test_versions_stored_before_the_revision_hold_no_set_after_it(pg_dsn: str) -> None:
    _mig._alembic(pg_dsn, "downgrade", _PREV)
    try:
        with _mig._conn(pg_dsn) as c:
            rule = _mig._rule(c, _mig._user(c))
            version = _mig._version(c, rule, 1, "c" * 64)
    finally:
        _mig._alembic(pg_dsn, "upgrade", "head")
    with _mig._conn(pg_dsn) as c:
        held = c.execute("SELECT account_refs FROM rule_versions WHERE id = %s", (version,))
        assert held.fetchone() == (None,)
        c.execute("UPDATE rule_versions SET account_refs = '{}' WHERE id = %s", (version,))
    _mig._alembic(pg_dsn, "downgrade", _PREV)  # derived data: dropped, the version kept
    try:
        with _mig._conn(pg_dsn) as c:
            kept = c.execute("SELECT version FROM rule_versions WHERE id = %s", (version,))
            assert kept.fetchone() == (1,)
    finally:
        _mig._alembic(pg_dsn, "upgrade", "head")
    assert _column(pg_dsn) == ("ARRAY", "_text", "YES", None)

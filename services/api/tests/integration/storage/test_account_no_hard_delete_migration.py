"""Integration: `0044_account_no_hard_delete` (#2758 item 1) on real Postgres 16.

`cv_app`, the role every request handler runs as, cannot hard-delete an account, so it cannot delete
one and insert its id again, in another environment (`trg_ea_env_write_once`, 0041) or with an older
key row (`trg_api_keys_write_once`, 0024), neither of which fires on DELETE or INSERT. It cannot
TRUNCATE either, and `cv_ro` can do neither. Rewriting the id (`UPDATE ... SET id`) is the other way
to free one: since #3968 `trg_ea_identity_write_once` refuses it (SQLSTATE 23514), and the foreign
keys of the account's default profile and keys still would (SQLSTATE 23503). The owner's delete, the
purge path, still removes the account and cascades to its keys and profiles. The downgrade lets
`cv_app` delete again and the upgrade refuses it again, with the ACL as it was. Bootstrapped with
the shipped `infra/scripts/pg_bootstrap.sql` and migrated as `cv_owner` (the CI `migrations` order),
so every write runs as the real role. `testcontainers` in CI; the offline render is
`tests/unit/migrations/test_0044_account_no_hard_delete.py`.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import psycopg
import pytest
from psycopg import errors as pgerr
from psycopg import sql
from testcontainers.postgres import PostgresContainer

pytestmark = pytest.mark.integration

_ROOT = Path(__file__).resolve().parents[3]
_BOOTSTRAP = _ROOT.parents[1] / "infra" / "scripts" / "pg_bootstrap.sql"
_REV, _PREV = "0044_account_no_hard_delete", "0042_sessions_view_as"
_TEMPLATE = "no_hard_delete_template"
_SNAPSHOT: dict[str, Any] = {"uid": "1", "permissions": {"ContractTrade": ["Order"], "Wallet": []}}
_DELETE = "DELETE FROM exchange_accounts WHERE id = %s"
#: The rows an account holds: itself, its key and its default profile (`trg_ea_default_profile`).
_HELD = (
    "SELECT (SELECT count(*) FROM exchange_accounts WHERE id = %(a)s), "
    "(SELECT count(*) FROM api_keys WHERE exchange_account_id = %(a)s), "
    "(SELECT count(*) FROM account_profiles WHERE exchange_account_id = %(a)s)"
)
_PRIVILEGES = (
    "SELECT string_agg(p, ' ' ORDER BY p) FROM unnest(ARRAY['SELECT', 'INSERT', 'UPDATE', "
    "'DELETE', 'TRUNCATE', 'REFERENCES', 'TRIGGER']) AS p "
    "WHERE has_table_privilege(%s, 'exchange_accounts', p)"
)

Conn = psycopg.Connection[tuple[Any, ...]]


def _as(dsn: str, role: str, driver: str = "postgresql") -> str:
    """`dsn` logged in as a bootstrap role (test-only password `<role>_test_pw`)."""
    return re.sub(r"^postgresql://[^@]+@", f"{driver}://{role}:{role}_test_pw@", dsn)


def _alembic(dsn: str, *args: str) -> subprocess.CompletedProcess[str]:
    """As `cv_owner`, like CI; bounded, so a hung lock fails instead of waiting."""
    return subprocess.run(  # noqa: S603 -- fixed argv, literal alembic subcommands, no shell
        [sys.executable, "-m", "alembic", *args],
        cwd=_ROOT, env={**os.environ, "CV_PG_DSN": _as(dsn, "cv_owner", "postgresql+psycopg")},
        capture_output=True, text=True, check=False, timeout=120,
    )  # fmt: skip


def _conn(dsn: str) -> Conn:
    return psycopg.connect(dsn, autocommit=True)


def _database(dsn: str, name: str) -> str:
    return f"{dsn.rsplit('/', 1)[0]}/{name}"


@pytest.fixture(scope="module")
def pg_dsn() -> Iterator[str]:
    """Superuser DSN of a cluster with the bootstrap roles and a database migrated to head as
    `cv_owner`, plus an untouched copy of it that `_fresh` clones per test.
    `pg_bootstrap.sql` connects to `candleviewer`, so the container's database has that name."""
    with PostgresContainer("postgres:16-alpine", dbname="candleviewer") as container:
        dsn = container.get_connection_url().replace("postgresql+psycopg2", "postgresql")
        info = psycopg.conninfo.conninfo_to_dict(dsn)
        psql = shutil.which("psql")
        assert psql is not None, "the migrations CI job installs postgresql-client"
        bootstrap = subprocess.run(  # noqa: S603 -- resolved psql path, fixed argv, no shell
            [psql, "-h", str(info["host"]), "-p", str(info["port"]), "-U", str(info["user"]),
             "-d", "candleviewer", "-v", "ON_ERROR_STOP=1", "-v", "owner_pw=cv_owner_test_pw",
             "-v", "app_pw=cv_app_test_pw", "-v", "ro_pw=cv_ro_test_pw", "-f", str(_BOOTSTRAP)],
            check=False, capture_output=True, text=True, timeout=120,
            env={**os.environ, "PGPASSWORD": str(info["password"])},
        )  # fmt: skip
        assert bootstrap.returncode == 0, bootstrap.stderr
        migrated = _alembic(dsn, "upgrade", "head")
        assert migrated.returncode == 0, migrated.stderr
        with _conn(_database(dsn, "postgres")) as c:
            c.execute(
                sql.SQL("CREATE DATABASE {} TEMPLATE {}").format(
                    sql.Identifier(_TEMPLATE), sql.Identifier("candleviewer")
                )
            )
        yield dsn


def _fresh(dsn: str) -> str:
    """Its own database, cloned from the migrated template; the roles are the cluster's."""
    name = f"nhd_{uuid.uuid4().hex[:12]}"
    with _conn(_database(dsn, "postgres")) as c:
        c.execute(
            sql.SQL("CREATE DATABASE {} TEMPLATE {}").format(
                sql.Identifier(name), sql.Identifier(_TEMPLATE)
            )
        )
    return _database(dsn, name)


def _account(dsn: str, *, keyed: bool = True) -> str:
    """A demo account and, unless `keyed` is false, one key, written as the runtime role (the
    default profile comes from `trg_ea_default_profile`): the account's id."""
    account, key = str(uuid.uuid4()), str(uuid.uuid4())
    sealed = (key, account, b"sealed-key-id", b"sealed-secret", bytes(12), json.dumps(_SNAPSHOT))
    with _conn(_as(dsn, "cv_app")) as c:
        c.execute(
            "INSERT INTO exchange_accounts (id, exchange, env, kind, exchange_uid, label) "
            "VALUES (%s, 'bybit', 'demo', 'main', %s, %s)",
            (account, str(uuid.uuid4().int % 10**15), f"acct {account[:8]}"),
        )
        if keyed:
            c.execute(
                "INSERT INTO api_keys (id, exchange_account_id, label, key_id_enc, key_id_last4, "
                "secret_enc, enc_nonce, dek_ref, permission_snapshot) "
                "VALUES (%s, %s, 'k', %s, 'WXYZ', %s, %s, 'v1:00', %s::jsonb)",
                sealed,
            )
    return account


def _held(dsn: str, account: str) -> tuple[int, int, int]:
    """`(accounts, keys, profiles)` that exist for `account`, counted as the superuser."""
    with _conn(dsn) as c:
        row = c.execute(_HELD, {"a": account}).fetchone()
    assert row is not None
    return int(row[0]), int(row[1]), int(row[2])


def _privileges(dsn: str, role: str) -> str:
    """What `role` holds on `exchange_accounts`, sorted and space-separated."""
    with _conn(dsn) as c:
        row = c.execute(_PRIVILEGES, (role,)).fetchone()
    assert row is not None
    return str(row[0])


def _acl(dsn: str) -> str:
    with _conn(dsn) as c:
        row = c.execute(
            "SELECT relacl::text FROM pg_class WHERE oid = 'exchange_accounts'::regclass"
        ).fetchone()
    assert row is not None
    return str(row[0])


def test_cv_app_cannot_delete_an_account_so_its_id_stays_taken(pg_dsn: str) -> None:
    """The hole 0024 and 0041 named: a delete that the UPDATE guards never see, then the id
    inserted again (another environment, an older key row). At head the DELETE is refused with
    SQLSTATE 42501, the account, its key and its profile stay, and the id cannot be taken again."""
    dsn = _fresh(pg_dsn)
    account = _account(dsn)
    with _conn(_as(dsn, "cv_app")) as c:
        with pytest.raises(pgerr.InsufficientPrivilege) as refused:
            c.execute(_DELETE, (account,))
        assert refused.value.sqlstate == "42501"
        with pytest.raises(pgerr.UniqueViolation):
            c.execute(
                "INSERT INTO exchange_accounts (id, exchange, env, kind, exchange_uid, label) "
                "VALUES (%s, 'bybit', 'live', 'main', %s, 'again')",
                (account, str(uuid.uuid4().int % 10**15)),
            )
    assert _held(dsn, account) == (1, 1, 1)
    with _conn(dsn) as c:
        cur = c.execute("SELECT env::text FROM exchange_accounts WHERE id = %s", (account,))
        assert cur.fetchone() == ("demo",)  # still the environment it was created in


@pytest.mark.parametrize("keyed", [True, False], ids=["profile-and-key", "profile-only"])
def test_cv_app_cannot_free_an_account_id_by_updating_it(pg_dsn: str, keyed: bool) -> None:
    """The other way to free an id: rewrite it, then insert the old one again. Since #3968
    `trg_ea_identity_write_once` guards `exchange_accounts.id` itself, so the UPDATE fails first
    with SQLSTATE 23514 naming the guard. The children still hold the id under it: every foreign
    key into the table is ON UPDATE NO ACTION, the account's Default profile (and its keys) still
    reference the old id, and `cv_app` can neither re-point them (the write-once guards) nor delete
    them (no DELETE). With the guard disabled in this test's own database, the same UPDATE fails
    with SQLSTATE 23503, so the transitive pin stays meaningful. Either way the row is as it was
    and the new id was never written. The profile alone pins the id, so an account with no key is
    refused too."""
    dsn = _fresh(pg_dsn)
    account, freed = _account(dsn, keyed=keyed), str(uuid.uuid4())
    statement = "UPDATE exchange_accounts SET id = %s WHERE id = %s"
    with _conn(_as(dsn, "cv_app")) as c, pytest.raises(pgerr.CheckViolation) as guarded:
        c.execute(statement, (freed, account))
    assert guarded.value.sqlstate == "23514"
    assert guarded.value.diag.constraint_name == "trg_ea_identity_write_once"
    with _conn(dsn) as c:
        c.execute("ALTER TABLE exchange_accounts DISABLE TRIGGER trg_ea_identity_write_once")
    pins = {"account_profiles_exchange_account_id_fkey"}  # the key's FK may fire first, if any
    if keyed:
        pins.add("api_keys_exchange_account_id_fkey")
    with _conn(_as(dsn, "cv_app")) as c, pytest.raises(pgerr.ForeignKeyViolation) as refused:
        c.execute(statement, (freed, account))
    assert refused.value.sqlstate == "23503"
    assert refused.value.diag.constraint_name in pins
    assert _held(dsn, account) == (1, int(keyed), 1)
    with _conn(dsn) as c:
        rows = c.execute(
            "SELECT id::text, env::text FROM exchange_accounts WHERE id IN (%s, %s)",
            (account, freed),
        ).fetchall()
    assert rows == [(account, "demo")]


@pytest.mark.parametrize(
    ("role", "statement"),
    [
        pytest.param("cv_app", _DELETE, id="cv_app-delete"),
        pytest.param("cv_app", "TRUNCATE exchange_accounts", id="cv_app-truncate"),
        pytest.param("cv_app", "TRUNCATE exchange_accounts CASCADE", id="cv_app-truncate-cascade"),
        pytest.param("cv_ro", _DELETE, id="cv_ro-delete"),
        pytest.param("cv_ro", "TRUNCATE exchange_accounts", id="cv_ro-truncate"),
    ],
)
def test_no_runtime_role_can_delete_or_truncate_an_account(
    pg_dsn: str, role: str, statement: str
) -> None:
    """TRUNCATE was never granted (the bootstrap's defaults are SELECT, INSERT, UPDATE and
    DELETE), so the revision revokes DELETE alone; `cv_ro` holds SELECT only."""
    dsn = _fresh(pg_dsn)
    account = _account(dsn)
    with _conn(_as(dsn, role)) as c, pytest.raises(pgerr.InsufficientPrivilege) as refused:
        c.execute(statement, (account,) if "%s" in statement else None)
    assert refused.value.sqlstate == "42501"
    assert _held(dsn, account) == (1, 1, 1)
    assert (_privileges(dsn, "cv_app"), _privileges(dsn, "cv_ro")) == (
        "INSERT SELECT UPDATE",
        "SELECT",
    )


def test_cv_app_still_inserts_patches_and_soft_deletes_an_account(pg_dsn: str) -> None:
    """What the accounts store does as `cv_app` (insert, patch, soft delete) and what the
    environment guards do (`FOR SHARE` takes the UPDATE grant) is untouched."""
    dsn = _fresh(pg_dsn)
    account = _account(dsn)
    with _conn(_as(dsn, "cv_app")) as c:
        c.execute("UPDATE exchange_accounts SET label = 'renamed' WHERE id = %s", (account,))
        c.execute("SELECT 1 FROM exchange_accounts WHERE id = %s FOR SHARE", (account,))
        c.execute(
            "UPDATE exchange_accounts SET deleted_at = now(), trading_enabled = false "
            "WHERE id = %s",
            (account,),
        )
    with _conn(dsn) as c:
        cur = c.execute(
            "SELECT label, deleted_at IS NOT NULL FROM exchange_accounts WHERE id = %s",
            (account,),
        )
        assert cur.fetchone() == ("renamed", True)
    assert _held(dsn, account) == (1, 1, 1)


def test_the_owner_still_deletes_an_account_and_its_children_cascade(pg_dsn: str) -> None:
    """The purge path: referential actions run as the table owner, so `cv_owner`'s delete removes
    the account with its key and its profile (`cv_app` holds no DELETE on either child)."""
    dsn = _fresh(pg_dsn)
    account = _account(dsn)
    with _conn(_as(dsn, "cv_owner")) as c:
        c.execute(_DELETE, (account,))
    assert _held(dsn, account) == (0, 0, 0)


def test_the_round_trip_lets_cv_app_delete_again_then_refuses_it(pg_dsn: str) -> None:
    """C-5.5, on a seeded database: the downgrade (rollback only) grants DELETE back, so at 0042
    the hole is open and `cv_app` deletes an account with its key and profile; the upgrade closes
    it again, with the ACL as it was at head, byte for byte."""
    dsn = _fresh(pg_dsn)
    at_head = _acl(dsn)
    kept = _account(dsn)
    downgraded = _alembic(dsn, "downgrade", _PREV)
    assert downgraded.returncode == 0, downgraded.stderr
    assert _privileges(dsn, "cv_app") == "DELETE INSERT SELECT UPDATE"
    deleted = _account(dsn)
    with _conn(_as(dsn, "cv_app")) as c:
        c.execute(_DELETE, (deleted,))
    assert (_held(dsn, deleted), _held(dsn, kept)) == ((0, 0, 0), (1, 1, 1))
    upgraded = _alembic(dsn, "upgrade", _REV)
    assert upgraded.returncode == 0, upgraded.stderr
    assert (_acl(dsn), _privileges(dsn, "cv_app")) == (at_head, "INSERT SELECT UPDATE")
    with _conn(_as(dsn, "cv_app")) as c, pytest.raises(pgerr.InsufficientPrivilege):
        c.execute(_DELETE, (kept,))
    assert _held(dsn, kept) == (1, 1, 1)

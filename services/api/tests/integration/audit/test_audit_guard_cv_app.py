"""Integration: the audit guard against the real runtime role (#298 AC5; U14, SR-066, C-5.7).

`cv_app` is the role the API connects as. Here it is created by the shipped
`infra/scripts/pg_bootstrap.sql` and the schema is migrated as `cv_owner`, in that order, exactly
as the CI `migrations` job and a deploy do. What is attacked is therefore the privilege set those
two files produce, not a hand-built stand-in that could drift from them (the pattern of
`tests/integration/storage/test_cv_app_role_privileges.py`): a change to the bootstrap's default
privileges, to the `0003_audit_log` revocations or to who owns the guard fails a case here.

The guard is the three triggers on `audit_log` and the two on `audit_checkpoints` (the anchors a
truncated tail is detected against), all from migration 0003, the three functions they run and
`audit_field(text)`, which `audit_chain()` hashes every field with. The role owns none of it and
holds only SELECT and INSERT on the two tables, so every attempt below must end in
`insufficient_privilege`, and for the reason that makes the guard safe (a missing owner check, a
missing TRIGGER privilege), not for an unrelated one such as a lost schema USAGE.

Each attempt logs in as `cv_app` on a connection of its own and runs in a transaction that is
never committed, so an attack that gets through fails its own case and cannot change what the next
case sees. The owner connection only reads the catalogues and proves the triggers still fire:
nothing but a trigger stops the owner or a superuser from an UPDATE.

Evidence: CI's integration lane (`pytest tests/integration -m integration`, a `postgres:16-alpine`
container through `PostgresContainer`) is the proof of this module; it needs `psql`, like the other
bootstrap-based modules. The runs recorded in `docs/security/abuse-cases/e09-auth.md` were made on
a laptop without docker, on a native PostgreSQL 16.2 reached through an out-of-repo stand-in for
`PostgresContainer`: they show the cases pass and which ones fail when a shipped control is
broken, and say nothing about the image CI pulls.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from collections.abc import Iterator, Sequence
from pathlib import Path
from typing import Any

import psycopg
import pytest
from psycopg.conninfo import conninfo_to_dict
from psycopg.errors import InsufficientPrivilege, RaiseException
from testcontainers.postgres import PostgresContainer

pytestmark = pytest.mark.integration

_API = Path(__file__).resolve().parents[3]
_BOOTSTRAP = _API.parents[1] / "infra" / "scripts" / "pg_bootstrap.sql"
_BOOTSTRAP_ROLES = (("owner_pw", "cv_owner"), ("app_pw", "cv_app"), ("ro_pw", "cv_ro"))

_TABLES = ("audit_log", "audit_checkpoints")
#: (table, trigger, tgenabled, function) of every non-internal trigger on the two tables, in the
#: order `_GUARD_SQL` returns them. The attacks on a trigger are built from these names.
_GUARD = [
    ("audit_checkpoints", "trg_audit_ckpt_append", "O", "forbid_mutation"),
    ("audit_checkpoints", "trg_audit_ckpt_no_truncate", "O", "audit_refuse_truncate"),
    ("audit_log", "trg_audit_append", "O", "forbid_mutation"),
    ("audit_log", "trg_audit_chain", "O", "audit_chain"),
    ("audit_log", "trg_audit_no_truncate", "O", "audit_refuse_truncate"),
]
#: The same triggers plus what would change if one were swapped out: the md5 of the function
#: body, the function's owner and the table's owner.
_GUARD_SQL = (
    "SELECT c.relname::text, t.tgname::text, t.tgenabled::text, p.proname::text, md5(p.prosrc), "
    "pg_get_userbyid(p.proowner)::text, pg_get_userbyid(c.relowner)::text "
    "FROM pg_trigger t JOIN pg_class c ON c.oid = t.tgrelid JOIN pg_proc p ON p.oid = t.tgfoid "
    "WHERE t.tgrelid IN ('audit_log'::regclass, 'audit_checkpoints'::regclass) "
    'AND NOT t.tgisinternal ORDER BY c.relname COLLATE "C", t.tgname COLLATE "C"'
)
#: `audit_chain()` hashes every field through `audit_field(text)`, which is not a trigger function
#: and so is not in `_GUARD_SQL`: a body that encodes fields differently weakens every entry hash.
_FIELD_SQL = (
    "SELECT p.proname::text, pg_get_function_identity_arguments(p.oid), md5(p.prosrc), "
    "pg_get_userbyid(p.proowner)::text FROM pg_proc p WHERE p.proname = 'audit_field'"
)
#: A row appended the way the audit writer and the checkpoint job do it.
_PROBE = (
    "INSERT INTO audit_log (record_id, actor_label, action) "
    "VALUES (gen_random_uuid(), 'guard-probe', 'auth.guard_probe') "
    "RETURNING id, prev_hash, entry_hash"
)
_CHECKPOINT_PROBE = (
    "INSERT INTO audit_checkpoints (id, head_id, head_hash, row_count) "
    "SELECT gen_random_uuid(), coalesce(max(head_id), 0) + 1, repeat('0', 64), 0 "
    "FROM audit_checkpoints RETURNING id, head_hash"
)
_APPEND = {"audit_log": _PROBE, "audit_checkpoints": _CHECKPOINT_PROBE}
#: Every row of a table as text: what an attack on the history must leave exactly as it was.
_ROWS = {
    "audit_log": "SELECT t::text FROM audit_log t ORDER BY t.id",
    "audit_checkpoints": "SELECT t::text FROM audit_checkpoints t ORDER BY t.id",
}
#: What a competing BEFORE INSERT trigger would run to swallow rows: a trigger function that
#: returns NULL. Created by the owner, so the only thing between `cv_app` and the attack is the
#: TRIGGER privilege on the table.
_SWALLOW_ROWS_FUNCTION = (
    "CREATE FUNCTION swallow_audit_rows() RETURNS trigger LANGUAGE plpgsql "
    "AS $$ BEGIN RETURN NULL; END $$"
)

#: The refusal each attempt must get, matched whole against `diag.message_primary`. SQLSTATE 42501
#: alone cannot tell the owner check or the missing TRIGGER privilege, which is what protects the
#: guard, from some unrelated privilege error that would also end the statement.
_NO_SCHEMA_CREATE = r"permission denied for schema public"
_NO_REPLICA_MODE = r'permission denied to set parameter "session_replication_role"'


def _not_table_owner(table: str) -> str:
    return rf"must be owner of (table|relation) {table}"


def _no_table_privilege(table: str) -> str:
    return rf"permission denied for table {table}"


def _not_function_owner(function: str) -> str:
    return rf"must be owner of function {function}"


#: Attacks on one trigger, from the names in `_GUARD`. They are refused for the missing ownership
#: of the table, and PostgreSQL checks that before it looks an ALTER TABLE ... TRIGGER name up: a
#: misspelt name is refused the same way, so the test first checks, as the owner, that it exists.
_TRIGGER_ATTACKS = {
    "drop": "DROP TRIGGER {trigger} ON {table}",
    "disable": "ALTER TABLE {table} DISABLE TRIGGER {trigger}",
    # Still there, but fires only in replica mode: never for an ordinary session.
    "enable-for-replicas-only": "ALTER TABLE {table} ENABLE REPLICA TRIGGER {trigger}",
}
#: Attacks on a whole table, (statement, refusal for that table); `{hash}` is the column that
#: carries each row's hash.
_TABLE_ATTACKS = {
    "disable-user-triggers": ("ALTER TABLE {table} DISABLE TRIGGER USER", _not_table_owner),
    "disable-all-triggers": ("ALTER TABLE {table} DISABLE TRIGGER ALL", _not_table_owner),
    "take-table-ownership": ("ALTER TABLE {table} OWNER TO CURRENT_USER", _not_table_owner),
    "rename-table": ("ALTER TABLE {table} RENAME TO {table}_unguarded", _not_table_owner),
    "drop-hash-not-null": (
        "ALTER TABLE {table} ALTER COLUMN {hash} DROP NOT NULL",
        _not_table_owner,
    ),
    "drop-table": ("DROP TABLE {table}", _not_table_owner),
    # Needs the TRIGGER privilege: a trigger sorting before the guard's own swallows the row.
    "add-competing-trigger": (
        "CREATE TRIGGER aa_swallow_rows BEFORE INSERT ON {table} FOR EACH ROW "
        "EXECUTE FUNCTION swallow_audit_rows()",
        _no_table_privilege,
    ),
}
_HASH_COLUMN = {"audit_log": "entry_hash", "audit_checkpoints": "head_hash"}
#: Replace a guard function by one that lets everything through: (function, statement). For
#: `audit_field` that is one that drops the length prefix, so two rows can share a hash input.
_REPLACE_GUARD_FUNCTION = {
    "replace-chain-function": (
        "audit_chain",
        "CREATE OR REPLACE FUNCTION audit_chain() RETURNS trigger LANGUAGE plpgsql "
        "AS $$ BEGIN RETURN NEW; END $$",
    ),
    "replace-append-only-function": (
        "forbid_mutation",
        "CREATE OR REPLACE FUNCTION forbid_mutation() RETURNS trigger LANGUAGE plpgsql "
        "AS $$ BEGIN RETURN NEW; END $$",
    ),
    "replace-truncate-function": (
        "audit_refuse_truncate",
        "CREATE OR REPLACE FUNCTION audit_refuse_truncate() RETURNS trigger LANGUAGE plpgsql "
        "AS $$ BEGIN RETURN NULL; END $$",
    ),
    "replace-field-function": (
        "audit_field",
        "CREATE OR REPLACE FUNCTION audit_field(v text) RETURNS text LANGUAGE sql IMMUTABLE "
        "AS $$ SELECT coalesce(v, '-') $$",
    ),
}
#: Attacks that name no table: (statement, refusal). Replacing a function is refused for the
#: missing CREATE on the schema; `test_cv_app_with_schema_create_...` takes that away to reach
#: the ownership check behind it.
_FUNCTION_ATTACKS = {
    # Replica mode skips every trigger that is not ENABLE ALWAYS, the chain among them.
    "replica-mode-session": ("SET session_replication_role = replica", _NO_REPLICA_MODE),
    "drop-chain-function": ("DROP FUNCTION audit_chain()", _not_function_owner("audit_chain")),
    "drop-chain-function-cascade": (
        "DROP FUNCTION audit_chain() CASCADE",
        _not_function_owner("audit_chain"),
    ),
    "drop-append-only-function-cascade": (
        "DROP FUNCTION forbid_mutation() CASCADE",
        _not_function_owner("forbid_mutation"),
    ),
    "drop-truncate-function-cascade": (
        "DROP FUNCTION audit_refuse_truncate() CASCADE",
        _not_function_owner("audit_refuse_truncate"),
    ),
    "drop-field-function": ("DROP FUNCTION audit_field(text)", _not_function_owner("audit_field")),
    **{
        name: (statement, _NO_SCHEMA_CREATE)
        for name, (_, statement) in _REPLACE_GUARD_FUNCTION.items()
    },
    "take-chain-function-ownership": (
        "ALTER FUNCTION audit_chain() OWNER TO CURRENT_USER",
        _not_function_owner("audit_chain"),
    ),
}
#: AC-AUD-02, by id: (statement, refusal). Each table is attacked the same way.
_GUARD_ATTACKS = {
    **{
        f"{name}-{table}": (
            statement.format(table=table, hash=_HASH_COLUMN[table]),
            refusal(table),
        )
        for name, (statement, refusal) in _TABLE_ATTACKS.items()
        for table in _TABLES
    },
    **_FUNCTION_ATTACKS,
}
#: AC-AUD-01: changing history, as opposed to the guard that protects it.
_HISTORY_ATTACKS = {
    "audit_log": {
        "update": "UPDATE audit_log SET reason = 'forged'",
        "delete": "DELETE FROM audit_log",
        "truncate": "TRUNCATE audit_log",
    },
    "audit_checkpoints": {
        "update": "UPDATE audit_checkpoints SET head_hash = repeat('f', 64)",
        "delete": "DELETE FROM audit_checkpoints",
        "truncate": "TRUNCATE audit_checkpoints",
    },
}


def _as(dsn: str, role: str, driver: str = "postgresql") -> str:
    """`dsn` logged in as a bootstrap role (test-only password `<role>_test_pw`)."""
    return re.sub(r"^postgresql://[^@]+@", f"{driver}://{role}:{role}_test_pw@", dsn)


def _exec(dsn: str, query: str, params: Sequence[Any] | None = None) -> list[tuple[Any, ...]]:
    with psycopg.connect(dsn, autocommit=True) as conn:
        cur = conn.execute(query, params)
        return cur.fetchall() if cur.description else []


def _bootstrap_roles(dsn: str) -> None:
    """Run the shipped `pg_bootstrap.sql` through `psql`, as the CI `migrations` job does."""
    info = conninfo_to_dict(dsn)
    psql = shutil.which("psql")
    assert psql is not None, "psql is needed to run pg_bootstrap.sql (CI runners ship it)"
    passwords = [arg for var, role in _BOOTSTRAP_ROLES for arg in ("-v", f"{var}={role}_test_pw")]
    subprocess.run(  # noqa: S603 -- resolved psql path, fixed argv, no shell
        [
            psql,
            *("-h", str(info["host"]), "-p", str(info["port"]), "-U", str(info["user"])),
            *("-d", "candleviewer", "-v", "ON_ERROR_STOP=1", *passwords, "-f", str(_BOOTSTRAP)),
        ],
        env={**os.environ, "PGPASSWORD": str(info["password"])},
        check=True,
        timeout=120,
    )


def _migrate_as_owner(dsn: str) -> None:
    subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=_API,
        env={**os.environ, "CV_PG_DSN": _as(dsn, "cv_owner", "postgresql+psycopg")},
        check=True,
        timeout=300,
    )


@pytest.fixture(scope="module")
def pg() -> Iterator[str]:
    """Superuser DSN of a database whose roles come from the shipped `pg_bootstrap.sql` (which
    needs the database to be named `candleviewer`) and whose schema is at head, migrated as
    `cv_owner`. The bootstrap goes first: its default privileges only reach tables created after
    it, so the other order would leave `cv_app` with no grants at all."""
    with PostgresContainer("postgres:16-alpine", dbname="candleviewer") as container:
        dsn = container.get_connection_url().replace("postgresql+psycopg2", "postgresql")
        _bootstrap_roles(dsn)
        _migrate_as_owner(dsn)
        _exec(_as(dsn, "cv_owner"), _SWALLOW_ROWS_FUNCTION)
        yield dsn


@pytest.fixture
def cv_app_may_create_in_public(pg: str) -> Iterator[None]:
    """`cv_app` also holds CREATE on schema `public`, which `pg_bootstrap.sql` withholds, for one
    case: the worst case if that were ever granted, where a refused CREATE OR REPLACE is about
    owning the function and nothing else."""
    _exec(pg, "GRANT CREATE ON SCHEMA public TO cv_app")
    try:
        yield
    finally:
        _exec(pg, "REVOKE CREATE ON SCHEMA public FROM cv_app")


def _guard(dsn: str) -> tuple[list[tuple[Any, ...]], list[tuple[Any, ...]]]:
    """(the triggers, `audit_field`) as `_GUARD_SQL` and `_FIELD_SQL` read them."""
    return _exec(dsn, _GUARD_SQL), _exec(dsn, _FIELD_SQL)


def _assert_guard_enforces(dsn: str) -> None:
    """As the owner, whom no privilege stops: a new audit_log row is still chained to the last
    one, and UPDATE, DELETE and TRUNCATE of both tables are still refused by the triggers, with a
    row of each there to be refused. Rolled back; leaves no row."""
    with psycopg.connect(dsn) as conn:
        tail = conn.execute("SELECT entry_hash FROM audit_log ORDER BY id DESC LIMIT 1").fetchone()
        probe = conn.execute(_PROBE).fetchone()
        assert probe is not None
        _, prev_hash, entry_hash = probe
        assert prev_hash == (tail[0] if tail else "0" * 64)
        assert re.fullmatch("[0-9a-f]{64}", entry_hash) and entry_hash != prev_hash
        conn.execute(_CHECKPOINT_PROBE)
        for attacks in _HISTORY_ATTACKS.values():
            for statement in attacks.values():
                with pytest.raises(RaiseException, match="append-only"), conn.transaction():
                    conn.execute(statement)
        conn.rollback()


def _attack(dsn: str, statement: str, refusal: str) -> None:
    """`statement` on a login of its own is refused with `insufficient_privilege` for `refusal`.
    Never committed: if it is not refused, this case fails alone and nothing is left behind."""
    with psycopg.connect(dsn) as conn:
        with pytest.raises(InsufficientPrivilege) as refused:
            conn.execute(statement)
        conn.rollback()
    message = refused.value.diag.message_primary or ""
    assert re.fullmatch(refusal, message), f"refused, but not for the expected reason: {message!r}"


def _assert_guard_survives(pg: str, statement: str, refusal: str) -> None:
    """`statement` as `cv_app` is refused, the guard is exactly as it was (same triggers, enabled,
    same function bodies and owners, same `audit_field`) and it still fires."""
    owner = _as(pg, "cv_owner")
    before = _guard(owner)
    assert [row[:4] for row in before[0]] == _GUARD
    _attack(_as(pg, "cv_app"), statement, refusal)
    assert _guard(owner) == before
    _assert_guard_enforces(owner)


def _append_as_cv_app(pg: str, table: str) -> tuple[Any, ...]:
    """One row appended as `cv_app`, the way the audit writer and the checkpoint job do it:
    (id, prev_hash, entry_hash) for `audit_log`, (id, head_hash) for `audit_checkpoints`."""
    (row,) = _exec(_as(pg, "cv_app"), _APPEND[table])
    return row


# --- the premise: cv_app is the role the claims below are about --------------------------------


@pytest.mark.parametrize("table", _TABLES)
def test_cv_app_holds_only_select_and_insert_on_the_audit_tables(pg: str, table: str) -> None:
    """A premise, so that the refusals below are not a side effect of some other missing
    privilege and cannot hold for a role that was granted more than the shipped files give it."""
    held = _exec(
        _as(pg, "cv_app"),
        "SELECT p FROM unnest(ARRAY['SELECT', 'INSERT', 'UPDATE', 'DELETE', 'TRUNCATE', "
        "'REFERENCES', 'TRIGGER']) AS p "
        "WHERE has_table_privilege(current_user, %s, p) ORDER BY p",
        (table,),
    )
    assert held == [("INSERT",), ("SELECT",)]


def test_cv_app_is_a_plain_role_that_owns_nothing_and_belongs_to_no_role(pg: str) -> None:
    """No superuser, CREATEROLE, CREATEDB or BYPASSRLS; no table or function of its own; and no
    membership, which would make it the owner (`cv_owner`) through inheritance."""
    profile = _exec(
        _as(pg, "cv_app"),
        "SELECT r.rolsuper, r.rolcreaterole, r.rolcreatedb, r.rolbypassrls, "
        "(SELECT count(*) FROM pg_class WHERE relowner = r.oid), "
        "(SELECT count(*) FROM pg_proc WHERE proowner = r.oid), "
        "(SELECT count(*) FROM pg_auth_members WHERE member = r.oid) "
        "FROM pg_roles r WHERE r.rolname = current_user",
    )
    assert profile == [(False, False, False, False, 0, 0, 0)]


def test_cv_app_may_use_schema_public_but_not_create_in_it(pg: str) -> None:
    """USAGE is what lets a name like `audit_log` resolve at all: without it every attack fails
    for a reason that has nothing to do with the guard. CREATE would let the role add objects."""
    privileges = _exec(
        _as(pg, "cv_app"),
        "SELECT has_schema_privilege('public', 'USAGE'), has_schema_privilege('public', 'CREATE')",
    )
    assert privileges == [(True, False)]


def test_the_tables_and_the_guard_functions_are_owned_by_cv_owner(pg: str) -> None:
    """Whoever owns a table or a function may drop or replace it; the migrations job and a
    deploy both run as `cv_owner` for that reason. `audit_field` is no trigger function, so it
    is read on its own."""
    triggers, field = _guard(pg)
    assert {(row[5], row[6]) for row in triggers} == {("cv_owner", "cv_owner")}
    assert [(row[0], row[3]) for row in field] == [("audit_field", "cv_owner")]


def test_every_trigger_the_attacks_name_exists_and_is_enabled(pg: str) -> None:
    """The attacks on a trigger are built from `_GUARD`. This is the owner's view that each of
    those triggers is there, enabled for ordinary sessions and running the function `_GUARD`
    says, and that no other trigger sits on the two tables."""
    triggers, _ = _guard(_as(pg, "cv_owner"))
    assert [row[:4] for row in triggers] == _GUARD


def test_cv_app_appends_a_row_chained_to_the_last_one(pg: str) -> None:
    """The role is not simply locked out: the append path the audit writer uses works, and the
    chain trigger computes the hashes."""
    tail = _exec(pg, "SELECT entry_hash FROM audit_log ORDER BY id DESC LIMIT 1")
    _, prev_hash, entry_hash = _append_as_cv_app(pg, "audit_log")
    assert prev_hash == (tail[0][0] if tail else "0" * 64)
    assert re.fullmatch("[0-9a-f]{64}", entry_hash) and entry_hash != prev_hash


# --- AC-AUD-01: history cannot be rewritten ----------------------------------------------------


@pytest.mark.parametrize(
    ("table", "statement"),
    [
        pytest.param(table, statement, id=f"{table}-{name}")
        for table, attacks in _HISTORY_ATTACKS.items()
        for name, statement in attacks.items()
    ],
)
def test_cv_app_cannot_rewrite_audit_history(pg: str, table: str, statement: str) -> None:
    _append_as_cv_app(pg, table)
    before = _exec(pg, _ROWS[table])
    assert before
    _attack(_as(pg, "cv_app"), statement, _no_table_privilege(table))
    assert _exec(pg, _ROWS[table]) == before


# --- AC-AUD-02: the guard cannot be defeated ---------------------------------------------------


@pytest.mark.parametrize(
    ("table", "trigger", "statement"),
    [
        pytest.param(
            table, trigger, template.format(table=table, trigger=trigger), id=f"{verb}-{trigger}"
        )
        for verb, template in _TRIGGER_ATTACKS.items()
        for table, trigger, *_ in _GUARD
    ],
)
def test_cv_app_cannot_remove_or_switch_off_a_guard_trigger(
    pg: str, table: str, trigger: str, statement: str
) -> None:
    named = _exec(
        _as(pg, "cv_owner"),
        "SELECT count(*) FROM pg_trigger WHERE tgrelid = %s::regclass AND tgname = %s",
        (table, trigger),
    )
    assert named == [(1,)], f"{trigger} is not a trigger of {table}"
    _assert_guard_survives(pg, statement, _not_table_owner(table))


@pytest.mark.parametrize(
    ("statement", "refusal"),
    [pytest.param(statement, why, id=name) for name, (statement, why) in _GUARD_ATTACKS.items()],
)
def test_cv_app_cannot_defeat_the_audit_guard(pg: str, statement: str, refusal: str) -> None:
    _assert_guard_survives(pg, statement, refusal)


@pytest.mark.parametrize(
    ("function", "statement"),
    list(_REPLACE_GUARD_FUNCTION.values()),
    ids=list(_REPLACE_GUARD_FUNCTION),
)
def test_cv_app_with_schema_create_cannot_replace_a_guard_function(
    pg: str, cv_app_may_create_in_public: None, function: str, statement: str
) -> None:
    may_create = _exec(pg, "SELECT has_schema_privilege('cv_app', 'public', 'CREATE')")
    assert may_create == [(True,)]
    _assert_guard_survives(pg, statement, _not_function_owner(function))

"""Integration: `0025_settings` against real Postgres 16 (E42-T01 #963).

The catalog equals 21-database-schema.md Sec.3.9's `settings` DDL; every invalid row is rejected by
its NAMED constraint (scope, scope/user shape, key format, value type) and the unique system key by
`ux_settings_sys`; the two user FKs, the `value` classification comment, the downgrade guard and the
5 s `lock_timeout` brackets (a held lock makes either direction give up) are exercised on the real
engine. Uses `testcontainers` like the other migration suites; CI-only (no docker socket in WSL) --
every statement was run on a scratch Postgres 16.4 first.
"""

from __future__ import annotations

import os
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
from psycopg.types.json import Jsonb
from testcontainers.postgres import PostgresContainer

pytestmark = pytest.mark.integration

_ROOT = Path(__file__).resolve().parents[3]
_DOC = _ROOT.parents[1] / "docs" / "plan" / "21-database-schema.md"
_REV, _PREV = "0025_settings", "0024_api_keys_write_once"

Conn = psycopg.Connection[tuple[Any, ...]]


def _alembic(dsn: str, *args: str) -> subprocess.CompletedProcess[str]:
    """Bounded, so a lost `lock_timeout` fails the test instead of hanging it."""
    return subprocess.run(  # noqa: S603 -- fixed argv, literal alembic subcommands, no shell
        [sys.executable, "-m", "alembic", *args],
        cwd=_ROOT,
        env={**os.environ, "CV_PG_DSN": dsn.replace("postgresql+asyncpg", "postgresql+psycopg")},
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )


@pytest.fixture(scope="module")
def pg_dsn() -> Iterator[str]:
    with PostgresContainer("postgres:16-alpine") as container:
        dsn = container.get_connection_url().replace("postgresql+psycopg2", "postgresql+asyncpg")
        assert _alembic(dsn, "upgrade", "head").returncode == 0
        yield dsn


def _conn(dsn: str) -> Conn:
    return psycopg.connect(dsn.replace("postgresql+asyncpg", "postgresql"), autocommit=True)


def _heal(dsn: str) -> None:
    """Back to head whatever a test did, so one failure cannot cascade into the others."""
    done = _alembic(dsn, "upgrade", "head")
    assert done.returncode == 0, done.stderr


def _user(c: Conn) -> str:
    uid = str(uuid.uuid4())
    c.execute(
        "INSERT INTO users (id, email, username, password_hash) VALUES (%s, %s, %s, '$argon2id$x')",
        (uid, f"{uid[:8]}@x.io", f"u{uid[:8]}"),
    )
    return uid


def _active_owner(c: Conn) -> None:
    """Keep one active owner so `trg_owner_floor_fn` allows deleting other users."""
    uid = str(uuid.uuid4())
    c.execute(
        "INSERT INTO users (id, email, username, display_name, password_hash, status) "
        "VALUES (%s, %s, %s, 'o', '$argon2id$x', 'active')",
        (uid, f"{uid}@example.test", f"o{uid[:12]}"),
    )
    c.execute(
        "INSERT INTO user_roles (user_id, role_id) SELECT %s, id FROM roles WHERE name = 'owner'",
        (uid,),
    )


def _key() -> str:
    """A valid, never-reused system key (`ux_settings_sys` is global across the module's DB)."""
    return f"t_{uuid.uuid4().hex[:12]}.k"


def _setting(c: Conn, **cols: object) -> str:
    row: dict[str, object] = {
        "id": str(uuid.uuid4()),
        "scope": "system",
        "key": _key(),
        "value": Jsonb("regular"),
        "value_type": "string",
        **cols,
    }
    stmt = sql.SQL("INSERT INTO settings ({}) VALUES ({})").format(
        sql.SQL(", ").join(sql.Identifier(k) for k in row),
        sql.SQL(", ").join([sql.Placeholder()] * len(row)),
    )
    c.execute(stmt, tuple(row.values()))
    return str(row["id"])


def _user_setting(c: Conn, user: str, key: str, **cols: object) -> str:
    return _setting(c, scope="user", user_id=user, key=key, **cols)


# --- The catalog equals the plan doc, and the round trip leaves nothing behind ----------------

_COLUMNS = (
    "SELECT a.attname, format_type(a.atttypid, a.atttypmod), a.attnotnull, "
    "pg_get_expr(d.adbin, d.adrelid) FROM pg_attribute a LEFT JOIN pg_attrdef d "
    "ON d.adrelid = a.attrelid AND d.adnum = a.attnum "
    "WHERE a.attrelid = %s::regclass AND a.attnum > 0 AND NOT a.attisdropped ORDER BY a.attnum"
)
_CONSTRAINTS = (
    "SELECT conname, contype, pg_get_constraintdef(oid) FROM pg_constraint "
    "WHERE conrelid = %s::regclass ORDER BY conname"
)
_INDEXES = (
    "SELECT i.relname, pg_get_indexdef(i.oid) FROM pg_index x "
    "JOIN pg_class i ON i.oid = x.indexrelid WHERE x.indrelid = %s::regclass ORDER BY i.relname"
)


def _doc_ddl() -> str:
    """Sec.3.9's `settings` table + both indexes, verbatim (the block also holds feature flags)."""
    text = _DOC.read_text(encoding="utf-8")
    block = text.split("### 3.9 Settings & feature flags", 1)[1].split("```sql", 1)[1]
    return block.split("CREATE TABLE feature_flags (", 1)[0]


def _catalog(c: Conn, schema: str) -> tuple[list[Any], list[Any], list[Any]]:
    table = f"{schema}.settings"
    cols = c.execute(_COLUMNS, (table,)).fetchall()
    cons = c.execute(_CONSTRAINTS, (table,)).fetchall()
    idx = [(n, d.replace(f" ON {schema}.", " ON ")) for n, d in c.execute(_INDEXES, (table,))]
    return cols, cons, idx


def _assert_matches_plan_doc(c: Conn) -> None:
    """Build the doc's DDL in a scratch schema (rolled back) and diff the two catalogs."""
    got: tuple[list[Any], list[Any], list[Any]] | None = None
    want: tuple[list[Any], list[Any], list[Any]] | None = None
    with c.transaction():
        c.execute("CREATE SCHEMA doc_ref")
        c.execute("SET LOCAL search_path = doc_ref, public")
        c.execute(_doc_ddl().encode())
        got, want = _catalog(c, "public"), _catalog(c, "doc_ref")
        raise psycopg.Rollback
    assert got is not None and want is not None
    assert got == want
    assert {name for name, *_ in got[2]} == {"settings_pkey", "ux_settings_sys", "ux_settings_user"}
    assert {name for name, *_ in got[1]} == {
        "settings_pkey",
        "settings_updated_by_fkey",
        "settings_user_id_fkey",
        "st_key_fmt",
        "st_scope",
        "st_shape",
        "st_vtype",
    }


def test_schema_matches_the_plan_doc_exactly(pg_dsn: str) -> None:
    with _conn(pg_dsn) as c:
        _assert_matches_plan_doc(c)


def test_only_value_carries_the_secret_classification_comment(pg_dsn: str) -> None:
    """C-5.9 / 21 Sec.12: `value` is class S when `is_secret`; no other column can hold one."""
    with _conn(pg_dsn) as c:
        rows = c.execute(
            "SELECT a.attname, col_description(a.attrelid, a.attnum) FROM pg_attribute a "
            "WHERE a.attrelid = 'settings'::regclass AND a.attnum > 0 AND NOT a.attisdropped "
            "AND col_description(a.attrelid, a.attnum) IS NOT NULL"
        ).fetchall()
        assert [r[0] for r in rows] == ["value"]
        assert str(rows[0][1]).startswith("SECRET:")


def test_round_trip_leaves_no_residue_and_restores_the_exact_schema(pg_dsn: str) -> None:
    with _conn(pg_dsn) as c:
        c.execute("DELETE FROM settings")
        try:
            assert _alembic(pg_dsn, "downgrade", _PREV).returncode == 0
            for obj in ("settings", "ux_settings_sys", "ux_settings_user", "settings_pkey"):
                assert c.execute("SELECT to_regclass(%s)", (obj,)).fetchone() == (None,)
        finally:
            _heal(pg_dsn)  # the upgrade half of the round trip, even when a check above failed
        _assert_matches_plan_doc(c)


def test_downgrade_refuses_while_settings_exist(pg_dsn: str) -> None:
    with _conn(pg_dsn) as c:
        sid = _setting(c)
        try:
            refused = _alembic(pg_dsn, "downgrade", _PREV)
            assert refused.returncode != 0
            assert "0025_settings downgrade refused" in refused.stderr
            assert c.execute("SELECT to_regclass('settings')").fetchone() == ("settings",)
        finally:
            _heal(pg_dsn)  # a regressed guard would have dropped the table; keep that local
            c.execute("DELETE FROM settings WHERE id = %s", (sid,))


def test_upgrade_gives_up_on_a_held_lock_instead_of_queueing(pg_dsn: str) -> None:
    """The two FKs need SHARE ROW EXCLUSIVE on `users`, which an open writer blocks; the 5 s
    `lock_timeout` bounds that wait and the failed upgrade leaves the database at 0024."""
    with _conn(pg_dsn) as c:
        c.execute("DELETE FROM settings")
        try:
            assert _alembic(pg_dsn, "downgrade", _PREV).returncode == 0
            with _conn(pg_dsn) as holder, holder.transaction():
                # What an open writer on `users` holds; it conflicts with the FK lock.
                holder.execute("LOCK TABLE users IN ROW EXCLUSIVE MODE")
                refused = _alembic(pg_dsn, "upgrade", _REV)
            assert refused.returncode != 0
            assert "lock timeout" in refused.stderr
            assert c.execute("SELECT version_num FROM alembic_version").fetchone() == (_PREV,)
            assert c.execute("SELECT to_regclass('settings')").fetchone() == (None,)
        finally:
            _heal(pg_dsn)


def test_downgrade_gives_up_on_a_reader_lock_instead_of_queueing(pg_dsn: str) -> None:
    """DROP TABLE needs ACCESS EXCLUSIVE on `users` (it removes the FK triggers there), so even an
    open reader blocks the rollback; `lock_timeout` bounds that wait too and nothing changes."""
    with _conn(pg_dsn) as c:
        c.execute("DELETE FROM settings")
        try:
            before = c.execute("SELECT version_num FROM alembic_version").fetchone()
            with _conn(pg_dsn) as holder, holder.transaction():
                # What an open reader of `users` holds; it conflicts with the DROP.
                holder.execute("LOCK TABLE users IN ACCESS SHARE MODE")
                refused = _alembic(pg_dsn, "downgrade", _PREV)
            assert refused.returncode != 0
            assert "lock timeout" in refused.stderr
            assert c.execute("SELECT version_num FROM alembic_version").fetchone() == before
            assert c.execute("SELECT to_regclass('settings')").fetchone() == ("settings",)
        finally:
            _heal(pg_dsn)


# --- Every invalid row is rejected by its NAMED constraint -------------------------------------


@pytest.mark.parametrize(
    ("cols", "constraint"),
    [
        pytest.param({"scope": "team"}, "st_scope", id="scope-not-in-enum"),
        pytest.param({"scope": "System"}, "st_scope", id="scope-is-case-sensitive"),
        pytest.param({"value_type": "integer"}, "st_vtype", id="vtype-not-in-enum"),
        pytest.param({"value_type": "null"}, "st_vtype", id="vtype-null-is-not-a-type"),
        pytest.param({"value_type": "String"}, "st_vtype", id="vtype-is-case-sensitive"),
        pytest.param({"value_type": ""}, "st_vtype", id="vtype-empty"),
        pytest.param({"key": ""}, "st_key_fmt", id="key-empty"),
        pytest.param({"key": "A"}, "st_key_fmt", id="key-uppercase"),
        pytest.param({"key": "Ui.density"}, "st_key_fmt", id="key-uppercase-segment"),
        pytest.param({"key": "a..b"}, "st_key_fmt", id="key-empty-segment"),
        pytest.param({"key": ".a"}, "st_key_fmt", id="key-leading-dot"),
        pytest.param({"key": "a."}, "st_key_fmt", id="key-trailing-dot"),
        pytest.param({"key": "a b"}, "st_key_fmt", id="key-space"),
        pytest.param({"key": "a-b"}, "st_key_fmt", id="key-dash"),
        pytest.param({"key": "a\n"}, "st_key_fmt", id="key-trailing-newline"),
        pytest.param({"key": "a.\nb"}, "st_key_fmt", id="key-newline-inside"),
        pytest.param({"key": "café"}, "st_key_fmt", id="key-non-ascii"),
        pytest.param({"key": "a.b.c.d.e.f"}, "st_key_fmt", id="key-six-segments"),
    ],
)
def test_invalid_setting_is_rejected_by_its_named_constraint(
    pg_dsn: str, cols: dict[str, object], constraint: str
) -> None:
    with _conn(pg_dsn) as c:
        with pytest.raises(pgerr.CheckViolation) as exc:
            _setting(c, **cols)
        assert exc.value.diag.constraint_name == constraint


def test_scope_and_user_must_agree_in_both_directions(pg_dsn: str) -> None:
    """`st_shape`: a user-scope row needs a user, a system-scope row must not name one."""
    with _conn(pg_dsn) as c:
        user = _user(c)
        with pytest.raises(pgerr.CheckViolation) as no_user:
            _setting(c, scope="user")
        assert no_user.value.diag.constraint_name == "st_shape"
        with pytest.raises(pgerr.CheckViolation) as stray_user:
            _setting(c, scope="system", user_id=user)
        assert stray_user.value.diag.constraint_name == "st_shape"
        assert _user_setting(c, user, "ui.density")


def test_value_is_not_null(pg_dsn: str) -> None:
    with _conn(pg_dsn) as c, pytest.raises(pgerr.NotNullViolation) as exc:
        _setting(c, value=None)
    assert exc.value.diag.column_name == "value"


@pytest.mark.parametrize(
    "key",
    [
        pytest.param("a", id="one-char"),
        pytest.param("ui.density", id="two-segments"),
        pytest.param("recorder.default_depth", id="underscore"),
        pytest.param("a.b.c.d.e", id="five-segments-is-the-maximum"),
        pytest.param("0.1", id="digits-only"),
        pytest.param("_", id="underscore-only"),
        pytest.param("9", id="single-digit"),
        pytest.param("a_b.c_d", id="underscores-in-both"),
    ],
)
def test_key_boundary_values_are_accepted(pg_dsn: str, key: str) -> None:
    with _conn(pg_dsn) as c:
        assert _user_setting(c, _user(c), key)


@pytest.mark.parametrize(
    ("value_type", "value"),
    [
        pytest.param("string", "regular", id="string"),
        pytest.param("number", 5, id="number"),
        pytest.param("boolean", True, id="boolean"),
        pytest.param("object", {"a": 1}, id="object"),
        pytest.param("array", [1, 2], id="array"),
    ],
)
def test_every_declared_value_type_is_accepted(pg_dsn: str, value_type: str, value: Any) -> None:
    with _conn(pg_dsn) as c:
        sid = _setting(c, value=Jsonb(value), value_type=value_type)
        row = c.execute("SELECT value, value_type FROM settings WHERE id = %s", (sid,)).fetchone()
        assert row == (value, value_type)


def test_defaults_match_the_plan(pg_dsn: str) -> None:
    with _conn(pg_dsn) as c:
        sid = _setting(c)
        row = c.execute(
            "SELECT is_secret, user_id, updated_by, created_at = updated_at, "
            "created_at <= now() FROM settings WHERE id = %s",
            (sid,),
        ).fetchone()
        assert row == (False, None, None, True, True)


# --- Uniqueness: one system value per key, one value per (user, key) ----------------------------


def test_system_key_is_unique_across_system_rows(pg_dsn: str) -> None:
    with _conn(pg_dsn) as c:
        key = _key()
        _setting(c, key=key)
        with pytest.raises(pgerr.UniqueViolation) as exc:
            _setting(c, key=key, value=Jsonb("business_kyc"))
        assert exc.value.diag.constraint_name == "ux_settings_sys"


def test_user_key_is_unique_per_user_but_free_across_users_and_scopes(pg_dsn: str) -> None:
    with _conn(pg_dsn) as c:
        a, b, key = _user(c), _user(c), _key()
        _user_setting(c, a, key)
        with pytest.raises(pgerr.UniqueViolation) as exc:
            _user_setting(c, a, key, value=Jsonb("compact"))
        assert exc.value.diag.constraint_name == "ux_settings_user"
        # The same key is a different row for another user, and for the system scope.
        assert _user_setting(c, b, key)
        assert _setting(c, key=key)


# --- Foreign keys ------------------------------------------------------------------------------


def test_user_scope_row_needs_an_existing_user(pg_dsn: str) -> None:
    with _conn(pg_dsn) as c:
        with pytest.raises(pgerr.ForeignKeyViolation) as no_owner:
            _user_setting(c, str(uuid.uuid4()), "ui.density")
        assert no_owner.value.diag.constraint_name == "settings_user_id_fkey"
        with pytest.raises(pgerr.ForeignKeyViolation) as no_editor:
            _setting(c, updated_by=str(uuid.uuid4()))
        assert no_editor.value.diag.constraint_name == "settings_updated_by_fkey"


def test_user_delete_cascades_their_settings(pg_dsn: str) -> None:
    with _conn(pg_dsn) as c:
        _active_owner(c)
        gone, kept = _user(c), _user(c)
        mine, theirs = _user_setting(c, gone, "ui.density"), _user_setting(c, kept, "ui.density")
        c.execute("DELETE FROM users WHERE id = %s", (gone,))
        assert c.execute("SELECT 1 FROM settings WHERE id = %s", (mine,)).fetchone() is None
        assert c.execute("SELECT 1 FROM settings WHERE id = %s", (theirs,)).fetchone() == (1,)


def test_editor_delete_detaches_updated_by_and_keeps_the_row(pg_dsn: str) -> None:
    with _conn(pg_dsn) as c:
        _active_owner(c)
        editor = _user(c)
        sid = _setting(c, updated_by=editor)
        c.execute("DELETE FROM users WHERE id = %s", (editor,))
        row = c.execute("SELECT updated_by FROM settings WHERE id = %s", (sid,)).fetchone()
        assert row == (None,)

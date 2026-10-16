"""Integration: `0027_feature_flags` against real Postgres 16 (E42-T03 #964).

The catalog equals 21-database-schema.md Sec.3.9's flag DDL and `flag_kind` its Sec.1.2 values;
every invalid row is rejected by its NAMED constraint (key format, rollout bounds, kind shape,
override target, the three uniques, the four FKs); the delete rules, defaults, the downgrade guard
and the 5 s `lock_timeout` brackets (a held lock makes either direction give up) are exercised on
the real engine. Uses `testcontainers` like the other migration suites; CI-only (no docker socket
in WSL) -- every statement was run on a scratch Postgres 16.4 first.
"""

from __future__ import annotations

import os
import re
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
_REV, _PREV = "0027_feature_flags", "0026_kek_versions_env"
_TABLES = ("feature_flags", "feature_flag_overrides")

Conn = psycopg.Connection[tuple[Any, ...]]


def _alembic(dsn: str, *args: str) -> subprocess.CompletedProcess[str]:
    """Bounded, so a lost `lock_timeout` fails the test instead of hanging it."""
    return subprocess.run(  # noqa: S603 -- fixed argv, literal alembic subcommands, no shell (#964)
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
        _ok(dsn, "upgrade", "head")
        yield dsn


def _conn(dsn: str) -> Conn:
    return psycopg.connect(dsn.replace("postgresql+asyncpg", "postgresql"), autocommit=True)


def _ok(dsn: str, *args: str) -> None:
    """Run alembic and fail with its stderr (the Postgres error), not a bare `assert 1 == 0`."""
    done = _alembic(dsn, *args)
    assert done.returncode == 0, done.stderr


def _heal(dsn: str) -> None:
    """Back to head whatever a test did, so one failure cannot cascade into the others."""
    _ok(dsn, "upgrade", "head")


def _insert(c: Conn, table: str, row: dict[str, object]) -> str:
    stmt = sql.SQL("INSERT INTO {} ({}) VALUES ({})").format(
        sql.Identifier(table),
        sql.SQL(", ").join(sql.Identifier(k) for k in row),
        sql.SQL(", ").join([sql.Placeholder()] * len(row)),
    )
    c.execute(stmt, tuple(row.values()))
    return str(row["id"])


def _flag(c: Conn, **cols: object) -> str:
    """A valid flag under a never-reused key (`feature_flags_key_key` is module-wide)."""
    return _insert(c, "feature_flags", {"id": str(uuid.uuid4()), "key": _key(), **cols})


def _override(c: Conn, flag: str, **cols: object) -> str:
    row = {"id": str(uuid.uuid4()), "feature_flag_id": flag, "value": Jsonb(True), **cols}
    return _insert(c, "feature_flag_overrides", row)


def _key() -> str:
    return f"t_{uuid.uuid4().hex[:12]}.k"


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


def _role(c: Conn, name: str) -> str:
    row = c.execute("SELECT id FROM roles WHERE name = %s", (name,)).fetchone()
    assert row is not None
    return str(row[0])


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
    """Sec.3.9's second ```sql block (both flag tables and their indexes), to its fence."""
    section = _DOC.read_text(encoding="utf-8").split("### 3.9 Settings & feature flags", 1)[1]
    return section.split("```sql", 2)[2].split("```", 1)[0]


def _catalog(c: Conn, schema: str) -> list[Any]:
    """Columns, constraints and indexes of both tables, schema qualifiers stripped."""
    unqualify = re.compile(r"\b(?:public|doc_ref)\.")
    out: list[Any] = []
    for table in _TABLES:
        for query in (_COLUMNS, _CONSTRAINTS, _INDEXES):
            rows = c.execute(query, (f"{schema}.{table}",)).fetchall()
            out.append([tuple(unqualify.sub("", str(v)) for v in row) for row in rows])
    return out


def _assert_matches_plan_doc(c: Conn) -> None:
    """Build the doc's DDL in a scratch schema (rolled back) and diff the two catalogs."""
    got: list[Any] = []
    want: list[Any] = []
    with c.transaction():
        c.execute("CREATE SCHEMA doc_ref")
        c.execute("SET LOCAL search_path = doc_ref, public")
        c.execute(_doc_ddl().encode())
        got, want = _catalog(c, "public"), _catalog(c, "doc_ref")
        raise psycopg.Rollback
    assert got == want and got
    names = {name for rows in got[1::3] + got[2::3] for name, *_ in rows}
    assert names == {
        "feature_flags_pkey",
        "feature_flags_key_key",
        "feature_flags_updated_by_fkey",
        "ff_key",
        "ff_pct",
        "ff_shape",
        "feature_flag_overrides_pkey",
        "feature_flag_overrides_feature_flag_id_fkey",
        "feature_flag_overrides_user_id_fkey",
        "feature_flag_overrides_role_id_fkey",
        "feature_flag_overrides_set_by_fkey",
        "ffo_target",
        "ux_ffo_user",
        "ux_ffo_role",
    }


def test_schema_matches_the_plan_doc_exactly(pg_dsn: str) -> None:
    with _conn(pg_dsn) as c:
        _assert_matches_plan_doc(c)
        kinds = c.execute("SELECT enum_range(NULL::flag_kind)::text[]").fetchone()
        assert kinds == (["boolean", "percentage", "variant"],)


def test_round_trip_leaves_no_residue_and_restores_the_exact_schema(pg_dsn: str) -> None:
    with _conn(pg_dsn) as c:
        _override(c, _flag(c), role_id=_role(c, "viewer"))  # so the step below must clear both
        c.execute("DELETE FROM feature_flags")  # the step the refusal names; it cascades
        try:
            _ok(pg_dsn, "downgrade", _PREV)
            for obj in (*_TABLES, "ux_ffo_user", "ux_ffo_role", "feature_flags_key_key"):
                found = c.execute("SELECT to_regclass(%s)", (obj,)).fetchone()
                assert found == (None,), f"{obj} must be gone after the downgrade"
            kind = c.execute("SELECT to_regtype('flag_kind')").fetchone()
            assert kind == (None,), "flag_kind must be dropped with the tables"
        finally:
            _heal(pg_dsn)  # the upgrade half of the round trip, even when a check above failed
        _assert_matches_plan_doc(c)


def test_downgrade_refuses_while_flags_exist(pg_dsn: str) -> None:
    with _conn(pg_dsn) as c:
        fid = _flag(c)
        try:
            refused = _alembic(pg_dsn, "downgrade", _PREV)
            assert refused.returncode != 0, "a downgrade over flag rows must be refused"
            assert "0027_feature_flags downgrade refused" in refused.stderr, refused.stderr
            assert "DELETE FROM feature_flags" in refused.stderr, "the refusal must say what to do"
            still = c.execute("SELECT to_regclass('feature_flags')").fetchone()
            assert still == ("feature_flags",), "a refused downgrade must leave the table in place"
        finally:
            _heal(pg_dsn)  # a regressed guard would have dropped the tables; keep that local
            c.execute("DELETE FROM feature_flags WHERE id = %s", (fid,))


def test_upgrade_gives_up_on_a_held_lock_instead_of_queueing(pg_dsn: str) -> None:
    """The `role_id` FK needs SHARE ROW EXCLUSIVE on `roles`, which an open writer blocks; the 5 s
    `lock_timeout` bounds that wait and the failed upgrade leaves the database at 0026."""
    with _conn(pg_dsn) as c:
        c.execute("DELETE FROM feature_flags")
        try:
            _ok(pg_dsn, "downgrade", _PREV)
            with _conn(pg_dsn) as holder, holder.transaction():
                holder.execute("LOCK TABLE roles IN ROW EXCLUSIVE MODE")
                refused = _alembic(pg_dsn, "upgrade", _REV)
            assert refused.returncode != 0, "a held roles lock must stop the upgrade"
            assert "lock timeout" in refused.stderr, refused.stderr
            version = c.execute("SELECT version_num FROM alembic_version").fetchone()
            assert version == (_PREV,), "the failed upgrade must leave the database at 0026"
            assert c.execute("SELECT to_regtype('flag_kind')").fetchone() == (None,), "type leaked"
        finally:
            _heal(pg_dsn)


def test_downgrade_gives_up_on_a_reader_lock_instead_of_queueing(pg_dsn: str) -> None:
    """Dropping the overrides removes their FK triggers on `users`, which needs a lock an open
    reader blocks; `lock_timeout` bounds that wait too and nothing changes."""
    with _conn(pg_dsn) as c:
        c.execute("DELETE FROM feature_flags")
        try:
            # Start at this revision, so a later head never takes the lock first.
            _ok(pg_dsn, "downgrade", _REV)
            with _conn(pg_dsn) as holder, holder.transaction():
                holder.execute("LOCK TABLE users IN ACCESS SHARE MODE")
                refused = _alembic(pg_dsn, "downgrade", _PREV)
            assert refused.returncode != 0, "a held users lock must stop the downgrade"
            assert "lock timeout" in refused.stderr, refused.stderr
            version = c.execute("SELECT version_num FROM alembic_version").fetchone()
            assert version == (_REV,), "the failed downgrade must leave the database at 0027"
        finally:
            _heal(pg_dsn)


# --- Every invalid row is rejected by its NAMED constraint -------------------------------------


@pytest.mark.parametrize(
    ("cols", "constraint"),
    [
        pytest.param({"key": ""}, "ff_key", id="key-empty"),
        pytest.param({"key": "Trading.live"}, "ff_key", id="key-uppercase"),
        pytest.param({"key": "a..b"}, "ff_key", id="key-empty-segment"),
        pytest.param({"key": ".a"}, "ff_key", id="key-leading-dot"),
        pytest.param({"key": "a-b"}, "ff_key", id="key-dash"),
        pytest.param({"key": "a\n"}, "ff_key", id="key-trailing-newline"),
        pytest.param({"key": "a.b.c.d.e"}, "ff_key", id="key-five-segments"),
        pytest.param({"kind": "percentage", "rollout_pct": -1}, "ff_pct", id="pct-below-0"),
        pytest.param({"kind": "percentage", "rollout_pct": 101}, "ff_pct", id="pct-above-100"),
        pytest.param({"kind": "percentage"}, "ff_shape", id="percentage-without-pct"),
        pytest.param({"kind": "variant"}, "ff_shape", id="variant-without-variants"),
    ],
)
def test_invalid_flag_is_rejected_by_its_named_constraint(
    pg_dsn: str, cols: dict[str, object], constraint: str
) -> None:
    with _conn(pg_dsn) as c, pytest.raises(pgerr.CheckViolation) as exc:
        _flag(c, **cols)
    assert exc.value.diag.constraint_name == constraint


def test_boundary_flags_are_accepted_with_the_plan_defaults(pg_dsn: str) -> None:
    with _conn(pg_dsn) as c:
        for cols in ({"kind": "percentage", "rollout_pct": 0}, {"rollout_pct": 100}):
            assert _flag(c, **cols)
        assert _flag(c, kind="variant", variants=Jsonb(["a", "b"]))
        fid = _flag(c, key=f"a.b.c.{uuid.uuid4().hex[:8]}")  # four segments is the maximum
        row = c.execute(
            "SELECT kind, description, default_value, is_killswitch, owner_team, expires_at, "
            "created_at = updated_at FROM feature_flags WHERE id = %s",
            (fid,),
        ).fetchone()
        assert row == ("boolean", "", False, False, "platform", None, True)


def test_flag_writer_must_exist(pg_dsn: str) -> None:
    with _conn(pg_dsn) as c, pytest.raises(pgerr.ForeignKeyViolation) as exc:
        _flag(c, updated_by=str(uuid.uuid4()))
    assert exc.value.diag.constraint_name == "feature_flags_updated_by_fkey"


def test_flag_key_is_unique(pg_dsn: str) -> None:
    with _conn(pg_dsn) as c:
        key = _key()
        _flag(c, key=key)
        with pytest.raises(pgerr.UniqueViolation) as exc:
            _flag(c, key=key)
        assert exc.value.diag.constraint_name == "feature_flags_key_key"


def test_an_override_targets_exactly_one_user_or_role(pg_dsn: str) -> None:
    with _conn(pg_dsn) as c:
        fid, user, role = _flag(c), _user(c), _role(c, "manager")
        for target in ({}, {"user_id": user, "role_id": role}):
            with pytest.raises(pgerr.CheckViolation) as exc:
                _override(c, fid, **target)
            assert exc.value.diag.constraint_name == "ffo_target"
        assert _override(c, fid, user_id=user) and _override(c, fid, role_id=role)


@pytest.mark.parametrize(
    ("target", "index"), [("user_id", "ux_ffo_user"), ("role_id", "ux_ffo_role")]
)
def test_one_override_per_flag_and_target(pg_dsn: str, target: str, index: str) -> None:
    with _conn(pg_dsn) as c:
        first, second = _flag(c), _flag(c)
        who = _user(c) if target == "user_id" else _role(c, "viewer")
        _override(c, first, **{target: who})
        assert _override(c, second, **{target: who})  # another flag, same target: allowed
        with pytest.raises(pgerr.UniqueViolation) as exc:
            _override(c, first, **{target: who}, value=Jsonb(False))
        assert exc.value.diag.constraint_name == index


@pytest.mark.parametrize("column", ["feature_flag_id", "user_id", "role_id", "set_by"])
def test_every_override_reference_must_exist(pg_dsn: str, column: str) -> None:
    with _conn(pg_dsn) as c:
        target = {"role_id": _role(c, "viewer")} if column == "role_id" else {"user_id": _user(c)}
        row: dict[str, object] = {"id": str(uuid.uuid4()), "feature_flag_id": _flag(c)}
        row |= {"value": Jsonb(True), **target, column: str(uuid.uuid4())}
        with pytest.raises(pgerr.ForeignKeyViolation) as exc:
            _insert(c, "feature_flag_overrides", row)
        assert exc.value.diag.constraint_name == f"feature_flag_overrides_{column}_fkey"


def _has_override(c: Conn, oid: str) -> bool:
    found = c.execute("SELECT 1 FROM feature_flag_overrides WHERE id = %s", (oid,)).fetchone()
    return found is not None


def test_deleting_a_user_cascades_their_overrides(pg_dsn: str) -> None:
    with _conn(pg_dsn) as c:
        _active_owner(c)
        gone = _user(c)
        mine = _override(c, _flag(c), user_id=gone)
        c.execute("DELETE FROM users WHERE id = %s", (gone,))
        assert not _has_override(c, mine), "an override must go with the user it targets"


def test_deleting_a_user_detaches_set_by_and_updated_by(pg_dsn: str) -> None:
    with _conn(pg_dsn) as c:
        _active_owner(c)
        setter = _user(c)
        fid = _flag(c, updated_by=setter)
        by_setter = _override(c, fid, user_id=_user(c), set_by=setter)
        c.execute("DELETE FROM users WHERE id = %s", (setter,))
        row = c.execute("SELECT set_by FROM feature_flag_overrides WHERE id = %s", (by_setter,))
        assert row.fetchone() == (None,), "the setter's override must survive, detached"
        writer = c.execute("SELECT updated_by FROM feature_flags WHERE id = %s", (fid,))
        assert writer.fetchone() == (None,), "the flag must survive its last writer, detached"


def test_deleting_a_flag_cascades_its_overrides(pg_dsn: str) -> None:
    with _conn(pg_dsn) as c:
        fid = _flag(c)
        by_role = _override(c, fid, role_id=_role(c, "owner"))
        c.execute("DELETE FROM feature_flags WHERE id = %s", (fid,))
        assert not _has_override(c, by_role), "overrides must be deleted with their flag"

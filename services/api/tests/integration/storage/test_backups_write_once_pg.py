"""Integration: `0032_backups_write_once` on real Postgres 16 (E42-T05 #966, BK-2).

The guard refuses a change to each write-once column with SQLSTATE 23514, naming the column and no
value, and leaves the row as it was; `checksum_sha256` and `deleted_at` go from NULL to a value
once and `deleted_by` only with the mark; the engine's columns stay writable; the guard fires under
`session_replication_role = replica` and ignores a session's shadowing operator; deleting a user
still detaches it; `cv_app` loses DELETE; a held writer lock makes either direction give up; the
downgrade refuses while an artefact is marked deleted and otherwise round-trips a seeded table.
`testcontainers`, CI-only (no docker socket here); run before the PR on a scratch Postgres 16.4
through a local stand-in.
"""

from __future__ import annotations

import os
import subprocess
import sys
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import psycopg
import pytest
from psycopg import errors as pgerr
from psycopg import sql
from testcontainers.postgres import PostgresContainer

pytestmark = pytest.mark.integration

_ROOT = Path(__file__).resolve().parents[3]
_REV, _PREV = "0032_backups_write_once", "0031_policy_disarm"
_AT = datetime(2026, 10, 18, 9, tzinfo=UTC)
_DIGEST, _OTHER_DIGEST = "a" * 64, "b" * 64
_SET_ONCE = ("checksum_sha256", "deleted_at", "deleted_by")
#: What `cv_app` may do to `backups`, as `has_table_privilege` reports it.
_PRIVILEGES = (
    "SELECT string_agg(p, ' ' ORDER BY p) FROM unnest(ARRAY['SELECT', 'INSERT', 'UPDATE', "
    "'DELETE']) AS p WHERE has_table_privilege('cv_app', 'backups', p)"
)
#: (trigger `tgenabled` or None, guard function exists, `deleted_at` exists).
_STATE = (
    "SELECT (SELECT tgenabled FROM pg_trigger WHERE tgname = 'trg_backups_write_once'), "
    "to_regprocedure('backups_write_once()') IS NOT NULL, EXISTS (SELECT FROM pg_attribute "
    "WHERE attrelid = 'backups'::regclass AND attname = 'deleted_at' AND NOT attisdropped)"
)

Conn = psycopg.Connection[tuple[Any, ...]]


def _alembic(dsn: str, *args: str) -> subprocess.CompletedProcess[str]:
    """Bounded, so a lost `lock_timeout` fails the test instead of hanging it."""
    return subprocess.run(  # noqa: S603 -- fixed argv, literal alembic subcommands, no shell (#966)
        [sys.executable, "-m", "alembic", *args],
        cwd=_ROOT, env={**os.environ, "CV_PG_DSN": dsn}, capture_output=True, text=True,
        check=False, timeout=120,
    )  # fmt: skip


@pytest.fixture(scope="module")
def pg_dsn() -> Iterator[str]:
    with PostgresContainer("postgres:16-alpine") as container:
        dsn = container.get_connection_url().replace("postgresql+psycopg2", "postgresql+psycopg")
        assert _alembic(dsn, "upgrade", "head").returncode == 0
        yield dsn


def _conn(dsn: str) -> Conn:
    return psycopg.connect(dsn.replace("postgresql+psycopg", "postgresql"), autocommit=True)


def _heal(dsn: str) -> None:
    """Back to head whatever a test did, so one failure cannot cascade into the others."""
    done = _alembic(dsn, "upgrade", "head")
    assert done.returncode == 0, done.stderr


def _backup(c: Conn, **cols: object) -> uuid.UUID:
    bid = uuid.uuid4()
    row = {"id": bid, "kind": "pg_dump", "target_path": f"/backups/{bid}.dump"}
    row |= {"encryption_ref": "age:main", "started_at": _AT} | cols
    c.execute(
        sql.SQL("INSERT INTO backups ({}) VALUES ({})").format(
            sql.SQL(", ").join(map(sql.Identifier, row)),
            sql.SQL(", ").join([sql.Placeholder()] * len(row)),
        ),
        tuple(row.values()),
    )
    return bid


def _user(c: Conn, *, owner: bool = False) -> uuid.UUID:
    """A user; an active owner keeps `trg_owner_floor_fn` allowing other users' deletion."""
    uid = uuid.uuid4()
    c.execute(
        "INSERT INTO users (id, email, username, password_hash, status) "
        "VALUES (%s, %s, %s, '$argon2id$x', 'active')",
        (uid, f"{uid}@example.test", f"u{uid.hex[:12]}"),
    )
    if owner:
        c.execute(
            "INSERT INTO user_roles (user_id, role_id) "
            "SELECT %s, id FROM roles WHERE name = 'owner'",
            (uid,),
        )
    return uid


def _row(c: Conn, bid: uuid.UUID) -> tuple[Any, ...] | None:
    return c.execute("SELECT b::text FROM backups b WHERE b.id = %s", (bid,)).fetchone()


def _set(c: Conn, bid: uuid.UUID, **cols: object) -> None:
    sets = sql.SQL(", ").join(sql.SQL("{} = %s").format(sql.Identifier(k)) for k in cols)
    c.execute(sql.SQL("UPDATE backups SET {} WHERE id = %s").format(sets), (*cols.values(), bid))


def _guard(column: str) -> str:
    """The refusal: the column and its rule, never a value."""
    rule = "set-once" if column in _SET_ONCE else "write-once"
    return f"trg_backups_write_once: backups.{column} is {rule} (SR-E42-05)"


def _refused(c: Conn, bid: uuid.UUID, **cols: object) -> str:
    """The guard's message for this UPDATE, which left the row as it was."""
    before = _row(c, bid)
    with pytest.raises(pgerr.CheckViolation) as refused:
        _set(c, bid, **cols)
    assert _row(c, bid) == before
    assert refused.value.diag.message_detail is None
    return str(refused.value.diag.message_primary)


def test_target_path_and_kind_are_write_once(pg_dsn: str) -> None:
    with _conn(pg_dsn) as c:
        bid = _backup(c, target_path="/backups/a.dump")
        assert _refused(c, bid, target_path="/backups/b.dump") == _guard("target_path")
        assert _refused(c, bid, kind="pg_basebackup") == _guard("kind")
        _set(c, bid, target_path="/backups/a.dump", kind="pg_dump")  # each over itself: passes


def test_the_refusal_names_the_rule_and_never_a_value(pg_dsn: str) -> None:
    """Distinctive old and new values of a write-once column, the class S one and a set-once one
    reach no part of the error: not the message, detail, hint or context, nor the row's id."""
    old = {"target_path": "/backups/OLD-7f3e.dump", "encryption_ref": "age:OLD-REF-7f3e"}
    new = {"target_path": "/backups/NEW-9c1d.dump", "encryption_ref": "age:NEW-REF-9c1d"}
    old["checksum_sha256"], new["checksum_sha256"] = "7f3e" * 16, "9c1d" * 16
    with _conn(pg_dsn) as c:
        bid = _backup(c, **old)
        for column, value in new.items():
            with pytest.raises(pgerr.CheckViolation) as refused:
                _set(c, bid, **{column: value})
            diag = refused.value.diag
            parts = (diag.message_primary, diag.message_detail, diag.message_hint, diag.context)
            text = " ".join(map(str, (refused.value, *parts)))
            assert diag.message_primary == _guard(column)
            assert [v for v in (*old.values(), *new.values(), str(bid)) if v in text] == []


@pytest.mark.parametrize(
    ("column", "value"),
    [
        ("id", uuid.UUID(int=0x32)),
        ("encryption_ref", "age:other"),
        ("encryption_ref", None),
        ("started_at", _AT + timedelta(seconds=1)),
        ("triggered_by", "pre_release"),
        ("triggered_by_user", "user"),  # from NULL to a live user's id
    ],
    ids=["id", "encryption_ref", "encryption_ref-cleared", "started_at", "triggered_by", "user"],
)
def test_each_other_identity_column_is_write_once(pg_dsn: str, column: str, value: object) -> None:
    with _conn(pg_dsn) as c:
        bid = _backup(c)
        value = _user(c) if value == "user" else value
        assert _refused(c, bid, **{column: value}) == _guard(column)


def test_a_user_reference_is_cleared_only_by_deleting_the_user(pg_dsn: str) -> None:
    """Both FKs are ON DELETE SET NULL, an UPDATE this guard sees: `triggered_by_user`, and
    `deleted_by` after the mark, go to NULL only once their user row is gone; the mark keeps its
    time (`bk_deleted`)."""
    with _conn(pg_dsn) as c:
        _user(c, owner=True)
        user = _user(c)
        bid = _backup(c, triggered_by="manual", triggered_by_user=user)
        for value in (None, _user(c)):
            assert _refused(c, bid, triggered_by_user=value) == _guard("triggered_by_user")
        _set(c, bid, deleted_at=_AT, deleted_by=user)
        c.execute("DELETE FROM users WHERE id = %s", (user,))
        detached = c.execute(
            "SELECT triggered_by_user, deleted_by, deleted_at FROM backups WHERE id = %s", (bid,)
        ).fetchone()
    assert detached == (None, None, _AT)


def test_checksum_is_set_once_from_null_then_frozen(pg_dsn: str) -> None:
    with _conn(pg_dsn) as c:
        bid = _backup(c)
        _set(c, bid, checksum_sha256=_DIGEST)  # NULL to a value: once
        _set(c, bid, checksum_sha256=_DIGEST)  # over itself: passes
        for value in (_OTHER_DIGEST, None):
            assert _refused(c, bid, checksum_sha256=value) == _guard("checksum_sha256")


def test_deleted_at_is_set_once(pg_dsn: str) -> None:
    with _conn(pg_dsn) as c:
        bid = _backup(c, status="ok")
        _set(c, bid, deleted_at=_AT)
        _set(c, bid, deleted_at=_AT)
        for value in (_AT + timedelta(seconds=1), None):
            assert _refused(c, bid, deleted_at=value) == _guard("deleted_at")


def test_deleted_by_is_set_with_the_mark_then_frozen(pg_dsn: str) -> None:
    """Set in the UPDATE that marks the row; afterwards another user, NULL while the user exists, or
    a deleter added to a mark that had none is refused (set-once); only its FK clears it."""
    with _conn(pg_dsn) as c:
        a, b = _user(c), _user(c)
        bid, unattributed = _backup(c), _backup(c)
        _set(c, bid, deleted_at=_AT, deleted_by=a)
        _set(c, unattributed, deleted_at=_AT)
        for row, value in ((bid, b), (bid, None), (unattributed, a)):
            assert _refused(c, row, deleted_by=value) == _guard("deleted_by")


def test_a_deleter_without_a_deletion_time_is_refused_by_bk_deleted(pg_dsn: str) -> None:
    with _conn(pg_dsn) as c:
        user, bid = _user(c), _backup(c)
        for write in (lambda: _backup(c, deleted_by=user), lambda: _set(c, bid, deleted_by=user)):
            with pytest.raises(pgerr.CheckViolation) as refused:
                write()
            assert refused.value.diag.constraint_name == "bk_deleted"


def test_status_verified_at_and_error_stay_writable(pg_dsn: str) -> None:
    """What the engine, verify and delete write (BK-3); `deleted_by` is set with the mark."""
    with _conn(pg_dsn) as c:
        user, bid = _user(c), _backup(c)
        _set(c, bid, status="ok", size_bytes=7, encrypted=False, covers_from=_AT, covers_to=_AT)
        _set(c, bid, wal_start_lsn="0/1", wal_end_lsn="0/2", duration_ms=5, finished_at=_AT)
        _set(c, bid, retention_until=_AT, checksum_sha256=_DIGEST)
        for status, error in (("verified", None), ("failed", "checksum_mismatch")):
            _set(c, bid, status=status, verified_at=_AT, verify_method="checksum")
            _set(c, bid, error_message=error, verified_at=_AT + timedelta(seconds=1))
        _set(c, bid, status="restored", restored_at=_AT, deleted_at=_AT, deleted_by=user)
        row = c.execute(
            "SELECT status::text, error_message, deleted_by FROM backups WHERE id = %s", (bid,)
        ).fetchone()
    assert row == ("restored", "checksum_mismatch", user)


def test_trigger_fires_under_replica_role(pg_dsn: str) -> None:
    """`ENABLE ALWAYS`: a `session_replication_role = replica` session is refused too. It is the
    only trigger on `backups`, so no later BEFORE UPDATE trigger can rewrite NEW after it."""
    with _conn(pg_dsn) as c:
        bid = _backup(c)
        c.execute("SET session_replication_role = replica")
        assert _refused(c, bid, target_path="/backups/z.dump") == _guard("target_path")
        triggers = c.execute(
            "SELECT tgname, tgenabled FROM pg_trigger "
            "WHERE tgrelid = 'backups'::regclass AND NOT tgisinternal"
        ).fetchall()
    assert triggers == [("trg_backups_write_once", "A")]


def test_a_shadowing_operator_never_reaches_the_guard(pg_dsn: str) -> None:
    """The guard pins `search_path = pg_catalog, pg_temp`, so a uuid `=` that a session puts ahead
    of pg_catalog (here one that never matches) cannot change its comparisons: the refusal still
    names the column that changed, not `id`."""
    with _conn(pg_dsn) as c:
        bid = _backup(c)
        c.execute("CREATE SCHEMA shadow")
        try:
            c.execute(
                "CREATE FUNCTION shadow.never(uuid, uuid) RETURNS boolean LANGUAGE sql "
                "IMMUTABLE AS 'SELECT false'"
            )
            c.execute(
                "CREATE OPERATOR shadow.= "
                "(LEFTARG = uuid, RIGHTARG = uuid, FUNCTION = shadow.never)"
            )
            c.execute("SET search_path = shadow, pg_catalog, public")
            with pytest.raises(pgerr.CheckViolation) as refused:
                c.execute(
                    "UPDATE backups SET target_path = '/backups/z.dump' "
                    "WHERE id OPERATOR(pg_catalog.=) %s",
                    (bid,),
                )
            assert refused.value.diag.message_primary == _guard("target_path")
        finally:
            c.execute("RESET search_path")
            c.execute("DROP SCHEMA shadow CASCADE")


def test_cv_app_cannot_delete_a_row_so_it_cannot_swap_one(pg_dsn: str) -> None:
    """With `pg_bootstrap.sql`'s default DML grant on `backups`, 0032 leaves `cv_app` SELECT,
    INSERT and UPDATE but not DELETE (42501), so the runtime role cannot delete a row and insert it
    again under the same id with another location or digest. The downgrade grants DELETE back."""
    with _conn(pg_dsn) as c:
        c.execute("DELETE FROM backups")  # marks would block the downgrade
        c.execute(
            "DO $$ BEGIN IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'cv_app') "
            "THEN CREATE ROLE cv_app; END IF; END $$"
        )
        c.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON backups TO cv_app")
        try:
            for step in (("downgrade", _PREV), ("upgrade", _REV)):
                assert _alembic(pg_dsn, *step).returncode == 0
            assert c.execute(_PRIVILEGES).fetchone() == ("INSERT SELECT UPDATE",)
            bid = _backup(c, checksum_sha256=_DIGEST)
            before = _row(c, bid)
            with _conn(pg_dsn) as app:
                app.execute("SET ROLE cv_app")
                with pytest.raises(pgerr.InsufficientPrivilege):
                    app.execute("DELETE FROM backups WHERE id = %s", (bid,))
                with pytest.raises(pgerr.UniqueViolation):
                    app.execute(
                        "INSERT INTO backups (id, kind, target_path, checksum_sha256) "
                        "VALUES (%s, 'pg_dump', '/backups/SWAPPED.dump', %s)",
                        (bid, _OTHER_DIGEST),
                    )
            assert _row(c, bid) == before
            assert _alembic(pg_dsn, "downgrade", _PREV).returncode == 0
            assert c.execute(_PRIVILEGES).fetchone() == ("DELETE INSERT SELECT UPDATE",)
        finally:
            _heal(pg_dsn)
        assert c.execute(_PRIVILEGES).fetchone() == ("INSERT SELECT UPDATE",)


@pytest.mark.parametrize(
    ("direction", "target", "lock"),
    [
        pytest.param("upgrade", _REV, "LOCK TABLE users IN ROW EXCLUSIVE MODE", id="up-users"),
        pytest.param("upgrade", _REV, "LOCK TABLE backups IN ROW EXCLUSIVE MODE", id="up-backups"),
        pytest.param("downgrade", _PREV, "LOCK TABLE backups IN ROW EXCLUSIVE MODE", id="down"),
    ],
)
def test_a_held_writer_lock_makes_either_direction_give_up(
    pg_dsn: str, direction: str, target: str, lock: str
) -> None:
    """C-5.6: an open writer on `users` blocks the FK's SHARE ROW EXCLUSIVE, and one on `backups`
    the ALTER TABLE's ACCESS EXCLUSIVE and the downgrade's SHARE lock. The 5 s `lock_timeout`
    bounds each wait, and the failed step leaves the revision where it was."""
    with _conn(pg_dsn) as c:
        c.execute("DELETE FROM backups")  # marks would block the downgrade to the start
        try:
            start = _PREV if direction == "upgrade" else _REV
            assert _alembic(pg_dsn, "downgrade", start).returncode == 0
            before = c.execute("SELECT version_num FROM alembic_version").fetchone()
            assert before == (start,)
            with _conn(pg_dsn) as holder, holder.transaction():
                holder.execute(lock)
                refused = _alembic(pg_dsn, direction, target)
            assert refused.returncode != 0 and "lock timeout" in refused.stderr
            assert c.execute("SELECT version_num FROM alembic_version").fetchone() == before
        finally:
            _heal(pg_dsn)


def test_round_trip_on_a_seeded_database(pg_dsn: str) -> None:
    """C-5.5: down to 0031 and up again with rows in the table. The rows stay; the guard, its
    function and the columns go and come back, and the guard holds again."""
    with _conn(pg_dsn) as c:
        c.execute("DELETE FROM backups")  # other tests' marks would block the downgrade
        seeded = [_backup(c), _backup(c, status="ok", checksum_sha256=_DIGEST, size_bytes=7)]
        before = [_row(c, bid) for bid in seeded]
        head = c.execute("SELECT version_num FROM alembic_version").fetchone()
        try:
            assert _alembic(pg_dsn, "downgrade", _PREV).returncode == 0
            assert c.execute(_STATE).fetchone() == (None, False, False)
            assert c.execute("SELECT count(*) FROM backups").fetchone() == (2,)
        finally:
            _heal(pg_dsn)
        assert c.execute("SELECT version_num FROM alembic_version").fetchone() == head
        assert c.execute(_STATE).fetchone() == ("A", True, True)
        assert [_row(c, bid) for bid in seeded] == before  # the re-added columns are NULL again
        assert _refused(c, seeded[1], checksum_sha256=None) == _guard("checksum_sha256")


def test_downgrade_refuses_while_an_artefact_is_marked_deleted(pg_dsn: str) -> None:
    with _conn(pg_dsn) as c:
        c.execute("DELETE FROM backups")  # only this test's mark may decide the refusal
        bid = _backup(c, status="ok")
        _set(c, bid, deleted_at=_AT)  # marked with no deleter: the guard reads deleted_at
        head = c.execute("SELECT version_num FROM alembic_version").fetchone()
        try:
            refused = _alembic(pg_dsn, "downgrade", _PREV)
            assert refused.returncode != 0
            assert "0032_backups_write_once downgrade refused" in refused.stderr
            assert "(C-5.2)" in refused.stderr
            assert c.execute("SELECT version_num FROM alembic_version").fetchone() == head
            assert c.execute(_STATE).fetchone() == ("A", True, True)
        finally:
            c.execute("DELETE FROM backups WHERE id = %s", (bid,))
            _heal(pg_dsn)

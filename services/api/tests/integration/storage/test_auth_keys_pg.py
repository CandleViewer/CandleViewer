"""Integration: `0030_auth_keys` and `SqlAlchemyAuthKeyStore` on real Postgres 16 (#2152 S2),
bootstrapped with `infra/scripts/pg_bootstrap.sql` and migrated as `cv_owner` like the CI
`migrations` job, so runtime writes run as `cv_app`. Placeholders only; needs docker (CI)."""

from __future__ import annotations

import asyncio
import logging
import os
import re
import shutil
import subprocess
import sys
from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import psycopg
import pytest
from psycopg import errors as pgerr
from psycopg import sql
from psycopg.abc import Params
from testcontainers.postgres import PostgresContainer

from candleviewer.storage.errors import StorageQueryFailed
from candleviewer.storage.repositories import auth_keys_sqlalchemy as keys
from candleviewer.storage.repositories.relational_sqlalchemy import (
    SqlAlchemyRelationalRepository,
)
from tests.unit.credentials_m2._vectors import KEK_V2, kek

pytestmark = pytest.mark.integration

Store = keys.SqlAlchemyAuthKeyStore

_ROOT = Path(__file__).resolve().parents[3]
_BOOTSTRAP = _ROOT.parents[1] / "infra" / "scripts" / "pg_bootstrap.sql"
_REV, _PREV = "0030_auth_keys", "0029_oms_core"
#: A value per write-once column that differs from `_key()` and passes every other check.
_CHANGES: dict[str, Any] = {
    "id": UUID(int=0xA1), "env": "live", "purpose": "recovery_hmac", "key_version": 2,
    "origin": "imported_env", "created_at": datetime(2020, 1, 1, tzinfo=UTC),
}  # fmt: skip
#: Wraps as S3's `LoadedKek.wrap_auth_key` writes them: what `_key()` stores, and a re-wrap.
_DEK_REF = kek().wrap_auth_key(bytearray(32), key_id=UUID(int=1), purpose="totp_seal")
_NEXT_REF = kek(KEK_V2, 2).wrap_auth_key(bytearray(32), key_id=UUID(int=1), purpose="totp_seal")
_RAW = bytes(range(32)).hex()  # a plaintext 32-byte key, as a buggy caller might store it
Rows = list[tuple[Any, ...]]


@pytest.fixture(scope="module")
def pg() -> Iterator[str]:
    """Superuser DSN of a container with the bootstrap roles (the database is `candleviewer`)."""
    with PostgresContainer("postgres:16-alpine", dbname="candleviewer") as container:
        dsn = container.get_connection_url().replace("postgresql+psycopg2", "postgresql")
        info = psycopg.conninfo.conninfo_to_dict(dsn)
        psql = shutil.which("psql")
        assert psql is not None, "psql is needed to run pg_bootstrap.sql (CI runners ship it)"
        subprocess.run(  # noqa: S603 -- resolved psql path, fixed argv, no shell (#2152)
            [psql, "-h", str(info["host"]), "-p", str(info["port"]), "-U", str(info["user"]),
             "-d", "candleviewer", "-v", "ON_ERROR_STOP=1",
             *[a for r in ("owner", "app", "ro") for a in ("-v", f"{r}_pw=cv_{r}_test_pw")],
             "-f", str(_BOOTSTRAP)],
            env={**os.environ, "PGPASSWORD": str(info["password"])}, check=True, timeout=120,
        )  # fmt: skip
        yield dsn


def _as(dsn: str, role: str, driver: str = "postgresql") -> str:
    """`dsn` logged in as a bootstrap role (test-only password `<role>_test_pw`)."""
    return re.sub(r"^postgresql://[^@]+@", f"{driver}://{role}:{role}_test_pw@", dsn)


def _alembic(dsn: str, *args: str) -> subprocess.CompletedProcess[str]:
    """As cv_owner, like CI; bounded, so a lost `lock_timeout` fails instead of hanging."""
    return subprocess.run(  # noqa: S603 -- fixed argv, literal alembic subcommands, no shell (#2152)
        [sys.executable, "-m", "alembic", *args],
        cwd=_ROOT, env={**os.environ, "CV_PG_DSN": _as(dsn, "cv_owner", "postgresql+psycopg")},
        capture_output=True, text=True, check=False, timeout=120,
    )  # fmt: skip


def _exec(dsn: str, query: str | sql.Composed, params: Params | None = None) -> Rows:
    with psycopg.connect(dsn, autocommit=True) as c:
        cur = c.execute(query, params)
        return cur.fetchall() if cur.description else []


def _at(dsn: str, rev: str) -> None:
    """Move the module's shared database to `rev`."""
    has_version = _exec(dsn, "SELECT to_regclass('public.alembic_version') IS NOT NULL")[0][0]
    current = _exec(dsn, "SELECT version_num FROM alembic_version")[0][0] if has_version else None
    if current != rev:
        done = _alembic(dsn, "downgrade" if rev == _PREV else "upgrade", rev)
        assert done.returncode == 0, done.stderr


@pytest.fixture(autouse=True)
def _head_and_empty(pg: str) -> None:
    """At `_REV` with no key and no MFA material (the probe counts all of it)."""
    _at(pg, _REV)
    _exec(pg, "TRUNCATE auth_keys; DELETE FROM recovery_codes; DELETE FROM mfa_methods")


def _key(**cols: Any) -> dict[str, Any]:
    """A valid row: every column that has no default."""
    row = {"id": uuid4(), "env": "demo", "purpose": "totp_seal", "origin": "generated"}
    return row | {"dek_ref": _DEK_REF, "kek_version": 1} | cols


def _insert(dsn: str, **cols: Any) -> dict[str, Any]:
    row, join = _key(**cols), sql.SQL(", ").join
    insert = sql.SQL("INSERT INTO auth_keys ({}) VALUES ({})")
    _exec(dsn, insert.format(join(map(sql.Identifier, row)), join(sql.Placeholder() for _ in row)),
          tuple(row.values()))  # fmt: skip
    return row


def _row(dsn: str, key_id: UUID) -> Rows:
    return _exec(dsn, "SELECT k::text FROM auth_keys k WHERE k.id = %s", (key_id,))


def _table(dsn: str) -> bool:
    return bool(_exec(dsn, "SELECT to_regclass('auth_keys') IS NOT NULL")[0][0])


def test_only_dek_ref_carries_a_comment_and_it_is_the_secret_tag(pg: str) -> None:
    tagged = _exec(
        pg,
        "SELECT attname, col_description(attrelid, attnum) FROM pg_attribute "
        "WHERE attrelid = 'auth_keys'::regclass AND attnum > 0 "
        "AND col_description(attrelid, attnum) IS NOT NULL",
    )
    assert tagged == [("dek_ref", "SECRET: auth key wrapped under the KEK of (env, kek_version)")]


@pytest.mark.parametrize(
    ("col", "val", "name"),
    [
        ("purpose", "other", "ak_purpose"),
        ("origin", "typed", "ak_origin"),
        ("key_version", 0, "ak_key_version"),
        ("kek_version", 0, "ak_kek_version"),
        ("dek_ref", _RAW, "ak_dek_ref"),  # a plaintext key
        ("dek_ref", "v2" + _DEK_REF[3:], "ak_dek_ref"),  # an `api_keys` wrap
        ("dek_ref", "ak1:" + _DEK_REF[4:].upper(), "ak_dek_ref"),  # upper-case hex
        ("dek_ref", "x" + _DEK_REF, "ak_dek_ref"),  # the start is anchored
        ("dek_ref", _DEK_REF[:-1], "ak_dek_ref"),  # 119 digits
        ("dek_ref", _DEK_REF + "\n", "ak_dek_ref"),  # the end is anchored, newline too
    ],
    ids="purpose origin key_version kek_version plaintext v2 upper x short nl".split(),
)
def test_an_invalid_row_is_refused_by_its_constraint(
    pg: str, col: str, val: Any, name: str
) -> None:
    with pytest.raises(pgerr.CheckViolation) as refused:
        _insert(pg, **{col: val})
    assert refused.value.diag.constraint_name == name


def test_one_key_per_environment_purpose_and_version(pg: str) -> None:
    _insert(pg)
    assert _exec(pg, "SELECT key_version FROM auth_keys") == [(1,)]  # the DDL default
    with pytest.raises(pgerr.UniqueViolation) as refused:
        _insert(pg)
    assert refused.value.diag.constraint_name == "ak_env_purpose_key_version"
    for other in ({"env": "live"}, {"purpose": "recovery_hmac"}, {"key_version": 2}):
        _insert(pg, **other)  # another environment, purpose or version is another key


@pytest.mark.parametrize("column", sorted(_CHANGES))
def test_an_identity_column_is_write_once_and_its_refusal_names_no_value(
    pg: str, column: str
) -> None:
    row = _insert(pg)
    before = _row(pg, row["id"])
    change = sql.SQL("UPDATE auth_keys SET dek_ref = %s, {c} = %s WHERE id = %s")
    with pytest.raises(pgerr.CheckViolation) as refused:
        _exec(
            _as(pg, "cv_app"),
            change.format(c=sql.Identifier(column)),
            (_NEXT_REF, _CHANGES[column], row["id"]),
        )
    assert refused.value.sqlstate == "23514" and refused.value.diag.message_detail is None
    assert refused.value.diag.message_primary == (
        f"trg_auth_keys_write_once: auth_keys.{column} is write-once; store a new row "
        "(ADR-0009 Amendment 4)"
    )
    assert _row(pg, row["id"]) == before  # the wrap did not move either


def test_the_guard_fires_last_is_always_on_and_cv_app_cannot_disable_it(pg: str) -> None:
    """Same-event triggers fire in name order, so the guard must sort last (a later one could
    rewrite NEW); `ENABLE ALWAYS` keeps it on under `replica`. tgtype 19 = ROW | BEFORE | UPDATE."""
    order = _exec(
        pg,
        "SELECT tgname, tgenabled FROM pg_trigger WHERE tgrelid = 'auth_keys'::regclass "
        'AND NOT tgisinternal AND tgtype & 19 = 19 ORDER BY tgname COLLATE "C"',
    )
    assert order == [("trg_auth_keys_touch", "O"), ("trg_auth_keys_write_once", "A")]
    with pytest.raises(pgerr.InsufficientPrivilege):  # DELETE is pinned by the head test
        _exec(_as(pg, "cv_app"), "ALTER TABLE auth_keys DISABLE TRIGGER trg_auth_keys_write_once")


def _seed_mfa(dsn: str) -> None:
    """A user with a sealed TOTP method and two unused recovery codes: what a keyring seals."""
    _exec(
        dsn,
        "WITH u AS (INSERT INTO users (id, email, username, password_hash) SELECT i, "
        "left(i::text, 8) || '@x.io', 'u' || left(i::text, 8), '$argon2id$x' "
        "FROM gen_random_uuid() i RETURNING id), "
        "m AS (INSERT INTO mfa_methods (id, user_id, kind, secret_enc, secret_key_ref, "
        "confirmed_at) SELECT gen_random_uuid(), id, 'totp', decode(repeat('ab', 60), 'hex'), "
        "'local-dev-v1', now() FROM u) INSERT INTO recovery_codes (id, user_id, code_hash) "
        "SELECT gen_random_uuid(), id, lpad(n::text, 64, '0') FROM u, generate_series(1, 2) n",
    )


def _mfa_rows(dsn: str) -> Rows:
    q = "SELECT m::text FROM mfa_methods m UNION SELECT r::text FROM recovery_codes r ORDER BY 1"
    return _exec(dsn, q)


def test_the_round_trip_on_an_empty_then_a_seeded_database_restores_the_schema(pg: str) -> None:
    assert _table(pg)
    _at(pg, _PREV)  # empty `auth_keys`: the downgrade passes its guard
    assert not _table(pg)
    _seed_mfa(pg)  # seeded at 0029, before the upgrade
    seeded = _mfa_rows(pg)
    for rev in (_REV, _PREV, _REV):
        _at(pg, rev)
        assert _table(pg) == (rev == _REV)  # a function left behind fails the next upgrade
        assert _mfa_rows(pg) == seeded  # additive: the sealed material is untouched


def test_downgrade_refuses_while_any_row_exists_and_works_once_they_are_gone(pg: str) -> None:
    row = _insert(pg)
    refused = _alembic(pg, "downgrade", _PREV)
    assert refused.returncode != 0
    assert "0030_auth_keys downgrade refused: auth_keys holds rows" in refused.stderr
    assert _exec(pg, "SELECT version_num FROM alembic_version") == [(_REV,)]
    assert len(_row(pg, row["id"])) == 1  # the row, so the table, is still there
    _exec(pg, "DELETE FROM auth_keys")  # the owner path the message names (cv_app cannot)
    assert _alembic(pg, "downgrade", _PREV).returncode == 0


def test_downgrade_gives_up_on_a_held_writer_lock_instead_of_queueing(pg: str) -> None:
    with psycopg.connect(pg, autocommit=True) as holder, holder.transaction():
        holder.execute("LOCK TABLE auth_keys IN ROW EXCLUSIVE MODE")  # what an open writer holds
        refused = _alembic(pg, "downgrade", _PREV)
    assert refused.returncode != 0 and "lock timeout" in refused.stderr
    assert _exec(pg, "SELECT version_num FROM alembic_version") == [(_REV,)]


# --- The store, as the runtime role -------------------------------------------------------------
@pytest.fixture
async def store(pg: str) -> AsyncIterator[Store]:
    rel = SqlAlchemyRelationalRepository(_as(pg, "cv_app", "postgresql+asyncpg"))
    yield Store(rel, env="demo")
    await rel.dispose()


def _ring(env: str = "demo") -> list[dict[str, Any]]:
    """`totp_seal` first, which is not key order (`recovery_hmac` sorts first)."""
    return [_key(env=env, purpose=p) for p in ("totp_seal", "recovery_hmac")]


async def test_a_keyring_is_written_whole_and_read_by_environment(pg: str, store: Store) -> None:
    _insert(pg, env="live")  # another environment's key sits in the same table
    ring = _ring()
    assert await store.insert_keyring(ring) is True
    rows = await store.rows_for("demo")
    assert [(r["purpose"], r["key_version"], r["origin"], r["kek_version"]) for r in rows] == [
        ("recovery_hmac", 1, "generated", 1), ("totp_seal", 1, "generated", 1)
    ]  # fmt: skip
    assert {r["id"]: r["dek_ref"] for r in rows} == {r["id"]: r["dek_ref"] for r in ring}
    assert {r["env"] for r in rows} == {"demo"}


async def test_the_store_refuses_another_environment_and_an_empty_keyring(
    pg: str, store: Store
) -> None:
    with pytest.raises(keys.AuthKeyEnvironmentError):
        await store.rows_for("live")
    for refused in ([], _ring("live"), _ring() + _ring("live")):  # a mixed batch writes nothing
        with pytest.raises(ValueError, match=r"keyring|environment"):
            await store.insert_keyring(refused)
    assert _exec(pg, "SELECT count(*) FROM auth_keys") == [(0,)]


async def test_only_a_taken_key_is_a_lost_race_a_reused_id_raises(pg: str, store: Store) -> None:
    """A plain `ON CONFLICT DO NOTHING` would report the primary-key clash as a boot that lost."""
    taken = _insert(pg, purpose="recovery_hmac")  # another boot got there first with one of them
    assert await store.insert_keyring(_ring()) is False
    assert [r["purpose"] for r in await store.rows_for("demo")] == ["recovery_hmac"]
    with pytest.raises(StorageQueryFailed) as clash:
        await store.insert_keyring([_key(id=taken["id"], purpose="totp_seal")])
    assert clash.value.sqlstate == "23505" and _exec(pg, "SELECT count(*) FROM auth_keys") == [(1,)]


@pytest.fixture
async def gate(pg: str) -> AsyncIterator[psycopg.AsyncConnection[Any]]:
    """Each row insert parks on advisory lock 7152, held here until the test lets go: no sleep."""
    _exec(
        pg,
        "CREATE FUNCTION park() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN "
        "PERFORM pg_advisory_xact_lock_shared(7152); RETURN NULL; END $$; CREATE TRIGGER "
        "trg_park AFTER INSERT ON auth_keys FOR EACH ROW EXECUTE FUNCTION park()",
    )
    async with await psycopg.AsyncConnection.connect(pg, autocommit=True) as holder:
        await holder.execute("SELECT pg_advisory_lock(7152)")
        yield holder
    _exec(pg, "DROP FUNCTION park() CASCADE")


async def test_two_concurrent_boots_converge_on_the_first_keyring(store: Store, gate: Any) -> None:
    """Unsorted, boots in opposite orders lock the two rows crosswise: `DeadlockDetected`. Both
    hold their first row, or queue behind the boot that does, before either goes on."""
    boots = asyncio.gather(store.insert_keyring(_ring()), store.insert_keyring(_ring()[::-1]))
    q = "SELECT count(*) FROM pg_stat_activity WHERE usename='cv_app' AND wait_event_type='Lock'"
    async with asyncio.timeout(30):  # fails a missed wait fast
        while await (await gate.execute(q)).fetchone() != (2,):
            pass
    await gate.execute("SELECT pg_advisory_unlock(7152)")
    assert sorted(await boots) == [False, True] and len(await store.rows_for("demo")) == 2


@pytest.mark.parametrize(
    ("change", "counted"),
    [
        ("SELECT 1", 3),  # one TOTP method and two unused codes
        ("UPDATE mfa_methods SET revoked_at = now()", 2),  # a revoked method is left out
        ("UPDATE recovery_codes SET used_at = now()", 1),  # used codes are left out
    ],
    ids=["all_counted", "revoked_method", "used_codes"],
)
async def test_the_probe_counts_live_totp_methods_and_unused_codes(
    pg: str, store: Store, change: str, counted: int
) -> None:
    _seed_mfa(pg)
    _exec(pg, change)
    assert await store.count_mfa_material() == counted


_MOVE: dict[str, Any] = {"env": "demo", "from_version": 1, "dek_ref": _NEXT_REF, "kek_version": 2}


async def test_a_scoped_rewrap_compares_and_sets_and_touches_the_row(pg: str, store: Store) -> None:
    old = datetime(2020, 1, 1, tzinfo=UTC)
    totp = _insert(pg, created_at=old, updated_at=old)["id"]
    _insert(pg, purpose="recovery_hmac")  # a sibling the re-wrap leaves alone
    live = _insert(pg, env="live")["id"]  # another environment's key, which the id names
    assert not await store.rewrap(live, **_MOVE)  # not the process's row
    with pytest.raises(keys.AuthKeyEnvironmentError):
        await store.rewrap(totp, **_MOVE | {"env": "live"})
    assert not await store.rewrap(totp, **_MOVE | {"from_version": 9})  # stale
    assert await store.rewrap(totp, **_MOVE) is True  # the runtime role passes the write-once guard
    assert not await store.rewrap(totp, **_MOVE)  # a replay: the row has moved on
    held = {r["purpose"]: (r["kek_version"], r["dek_ref"]) for r in await store.rows_for("demo")}
    assert held == {"recovery_hmac": (1, _DEK_REF), "totp_seal": (2, _NEXT_REF)}
    created, updated = _exec(
        pg, "SELECT created_at, updated_at FROM auth_keys WHERE id = %s", (totp,)
    )[0]
    assert created == old and updated > old  # `trg_auth_keys_touch` set it to now()


@pytest.mark.parametrize(
    ("bad", "sqlstate"),
    [({"dek_ref": _RAW}, "23514"), ({"kek_version": 0}, "23514"), ({"dek_ref": None}, "23502")],
    ids=["plaintext_key", "check", "not_null"],
)
async def test_a_refused_write_surfaces_its_sqlstate_and_nothing_of_the_row(
    pg: str, store: Store, caplog: pytest.LogCaptureFixture, bad: dict[str, Any], sqlstate: str
) -> None:
    """The driver's message ends in `DETAIL: Failing row contains (...)`: id and wrap (C-12.6)."""
    totp, fresh = _insert(pg)["id"], UUID(int=0xBEEF)
    for call in (
        store.insert_keyring([_key(id=fresh, purpose="recovery_hmac") | bad]),
        store.rewrap(totp, **_MOVE | bad),
    ):
        with pytest.raises(StorageQueryFailed) as refused:
            await call
        logging.getLogger(__name__).error("refused: %r", refused.value, exc_info=refused.value)
        assert refused.value.sqlstate == sqlstate and refused.value.__context__ is None
    leaks = [str(fresh), str(totp), _RAW[:16], "ak1:", "Failing row", "[SQL"]
    assert not [leak for leak in leaks if leak in caplog.text], caplog.text

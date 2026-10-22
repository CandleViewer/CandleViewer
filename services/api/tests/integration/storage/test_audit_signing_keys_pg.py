"""Integration: `0046_audit_signing_keys` on real Postgres 16 (#889 S4), bootstrapped with
`infra/scripts/pg_bootstrap.sql` and migrated as `cv_owner` as CI does, so the updates the trigger
judges run as `cv_app`. Placeholder bytes, never key material; needs docker."""

from __future__ import annotations

import hashlib
import os
import re
import shutil
import subprocess
import sys
from collections.abc import Iterator
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

pytestmark = pytest.mark.integration

_ROOT = Path(__file__).resolve().parents[3]
_BOOTSTRAP = _ROOT.parents[1] / "infra" / "scripts" / "pg_bootstrap.sql"
_REV = "0046_audit_signing_keys"
_FILE = _ROOT / "candleviewer" / "migrations" / "versions" / f"{_REV}.py"
#: Read from the revision itself, so a re-parent edits only that file and its lockfile entry.
_PREV: str = re.findall(r'^down_revision.*"(\w+)"$', _FILE.read_text(encoding="utf-8"), re.M)[0]
_T, _GUARD = "audit_signing_keys", "trg_audit_signing_keys_write_once"
_DELETE = "DELETE FROM audit_signing_keys"
_T0, _T1 = datetime(2026, 9, 1, tzinfo=UTC), datetime(2026, 10, 1, tzinfo=UTC)
_SEED, _WRAP, _NEXT_WRAP = b"\x5a" * 60, "ek1:" + "ab" * 60, "ek1:" + "cd" * 60
_RETIRE: dict[str, Any] = {"status": "retired", "valid_until": _T1, "retired_reason": "scheduled"}
#: A rotation's request: its Owner (no such user: a CHECK refuses before the FK), key and digest.
_REQUEST: dict[str, Any] = {
    "created_by": uuid4(),
    "client_ref": str(uuid4()),
    "client_body_sha256": "a" * 64,
}
_ZEROS = {"fingerprint_sha256": "0" * 64, "key_id": "cv-audit-export-v1:" + "0" * 16}
Rows = list[tuple[Any, ...]]


def _public(version: int = 1, pk: bytes = bytes(range(32))) -> dict[str, Any]:
    fp = hashlib.sha256(pk).hexdigest()
    return {"version": version, "public_key": pk, "fingerprint_sha256": fp,
            "key_id": f"cv-audit-export-v{version}:{fp[:16]}"}  # fmt: skip


@pytest.fixture(scope="module")
def pg() -> Iterator[str]:
    """Superuser DSN of a container with the bootstrap roles (the database is `candleviewer`)."""
    with PostgresContainer("postgres:16-alpine", dbname="candleviewer") as container:
        dsn = container.get_connection_url().replace("postgresql+psycopg2", "postgresql")
        info = psycopg.conninfo.conninfo_to_dict(dsn)
        psql = shutil.which("psql")
        assert psql is not None, "psql is needed to run pg_bootstrap.sql (CI runners ship it)"
        subprocess.run(  # noqa: S603 -- resolved psql path, fixed argv, no shell (#889)
            [psql, "-h", str(info["host"]), "-p", str(info["port"]), "-U", str(info["user"]),
             "-d", "candleviewer", "-v", "ON_ERROR_STOP=1",
             *[a for r in ("owner", "app", "ro") for a in ("-v", f"{r}_pw=cv_{r}_test_pw")],
             "-f", str(_BOOTSTRAP)],
            env={**os.environ, "PGPASSWORD": str(info["password"])}, check=True, timeout=120,
        )  # fmt: skip
        yield dsn


def _as(dsn: str, role: str) -> str:
    """`dsn` logged in as a bootstrap role (test-only password `<role>_test_pw`)."""
    return re.sub(r"^postgresql://[^@]+@", f"postgresql://{role}:{role}_test_pw@", dsn)


def _alembic(dsn: str, *args: str) -> subprocess.CompletedProcess[str]:
    """As cv_owner, like CI; bounded, so a lost `lock_timeout` fails instead of hanging."""
    owner = _as(dsn, "cv_owner").replace("postgresql://", "postgresql+psycopg://")
    return subprocess.run(  # noqa: S603 -- fixed argv, literal alembic subcommands, no shell (#889)
        [sys.executable, "-m", "alembic", *args], cwd=_ROOT, env={**os.environ, "CV_PG_DSN": owner},
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
    _at(pg, _REV)
    _exec(pg, "TRUNCATE audit_signing_keys")


def _update(dsn: str, key: UUID, **sets: Any) -> None:
    change = sql.SQL("UPDATE audit_signing_keys SET {} WHERE id = %s").format(
        sql.SQL(", ").join(sql.SQL("{} = %s").format(sql.Identifier(c)) for c in sets)
    )
    _exec(dsn, change, (*sets.values(), key))


def _insert(dsn: str, state: str = "active", **cols: Any) -> UUID:
    """A key with every column that has no default, then moved (by permitted updates) to `state`:
    `active`, `retained` (retired, holding its seed) or `destroyed` (retired, its seed gone)."""
    key = uuid4()
    row = {"id": key, "env": "demo", **_public(), "sealed_seed": _SEED, "dek_ref": _WRAP,
           "kek_version": 1, "status": "active", "valid_from": _T0} | cols  # fmt: skip
    join, insert = sql.SQL(", ").join, sql.SQL("INSERT INTO audit_signing_keys ({}) VALUES ({})")
    _exec(dsn, insert.format(join(map(sql.Identifier, row)), join(sql.Placeholder() for _ in row)),
          tuple(row.values()))  # fmt: skip
    if state != "active":
        _update(dsn, key, **_RETIRE | ({"sealed_seed": None} if state == "destroyed" else {}))
    return key


def _row(dsn: str, key: UUID) -> Rows:
    return _exec(dsn, "SELECT k::text FROM audit_signing_keys k WHERE k.id = %s", (key,))


@pytest.mark.parametrize(
    ("cols", "name"),
    [
        (_public(0), "ask_version"),
        ({"kek_version": 0}, "ask_kek_version"),
        (_public(pk=bytes(31)), "ask_public_key"),
        (_ZEROS, "ask_fingerprint"),  # a fingerprint, and the key id it gives, of another key
        ({"key_id": _public(2)["key_id"]}, "ask_key_id"),  # another version's id
        ({"sealed_seed": bytes(range(32))}, "ask_sealed_seed"),  # a plaintext seed
        ({"dek_ref": bytes(range(32)).hex()}, "ask_dek_ref"),  # a plaintext DEK
        ({"dek_ref": "ak1:" + "ab" * 60}, "ask_dek_ref"),  # an auth key's wrap
        ({"dek_ref": _WRAP + "\n"}, "ask_dek_ref"),  # the end is anchored, newline too
        (_RETIRE | {"status": "revoked"}, "ask_status"),
        (_RETIRE | {"retired_reason": "other"}, "ask_retired_reason"),
        ({"sealed_seed": None}, "ask_lifecycle"),  # active without its seed
        ({"valid_until": _T1}, "ask_lifecycle"),  # active with an end
        (_RETIRE | {"retired_reason": None}, "ask_lifecycle"),
        ({"retired_reason": "scheduled"}, "ask_lifecycle"),  # active with a reason
        (_RETIRE | {"valid_until": None}, "ask_lifecycle"),  # retired with no end
        ({"client_ref": str(uuid4())}, "ask_request"),  # part of a request
        (_REQUEST | {"client_body_sha256": None}, "ask_request"),  # two of its three
        (_REQUEST | {"client_ref": str(uuid4()).upper()}, "ask_client_ref"),
    ],
    ids=lambda v: v if isinstance(v, str) else None,
)
def test_an_invalid_row_is_refused_by_its_constraint(
    pg: str, cols: dict[str, Any], name: str
) -> None:
    with pytest.raises(pgerr.CheckViolation) as refused:
        _insert(pg, **cols)
    assert refused.value.diag.constraint_name == name


def test_one_active_key_per_environment_and_one_of_each_identity(pg: str) -> None:
    user = _exec(
        pg,
        "INSERT INTO users (id, email, username, password_hash) VALUES "
        "(gen_random_uuid(), 'o@x.io', 'owner', '$argon2id$x') RETURNING id",
    )
    request = _REQUEST | {"created_by": user[0][0]}
    first = _insert(pg, **request)
    for cols, name in [
        (_public(2, bytes(32)), "ux_ask_active"),
        (_RETIRE | _public(1, bytes(32)), "ask_env_version"),
        (_RETIRE | _public(2), "ask_env_fingerprint"),
        (_RETIRE | _public(2, bytes(32)) | request, "ask_env_request"),
    ]:
        with pytest.raises(pgerr.UniqueViolation) as refused:
            _insert(pg, **cols)
        assert refused.value.diag.constraint_name == name
    _insert(pg, env="live", **request)  # another environment's key, the same request included
    _update(pg, first, **_RETIRE)
    _insert(pg, **_public(2, bytes(32)))  # once its predecessor retired, a successor is active


def test_the_retire_the_destroy_and_the_rewrap_pass_for_cv_app(pg: str) -> None:
    app, one, two = _as(pg, "cv_app"), _insert(pg), _insert(pg, env="live")
    _update(app, one, dek_ref=_NEXT_WRAP, kek_version=2)  # the KEK re-wrap of an active key
    _update(app, one, **_RETIRE | {"sealed_seed": None})  # retired and destroyed in one UPDATE
    _update(app, two, **_RETIRE)  # retired, still holding its seed: Q3's finding
    _update(app, two, dek_ref=_NEXT_WRAP, kek_version=2)  # re-wrapped while it holds one
    _update(app, two, sealed_seed=None)  # its destroy, retried
    q = "SELECT env::text, status, sealed_seed, kek_version FROM audit_signing_keys ORDER BY 1"
    assert _exec(pg, q) == [("demo", "retired", None, 2), ("live", "retired", None, 2)]


def test_a_change_the_trigger_lets_pass_is_still_refused_by_its_check(pg: str) -> None:
    """Clearing an active key's seed passes the trigger and is refused by `ask_lifecycle`, from the
    constraint and not the trigger, with the row unchanged (21 §3.1.5b, Privileges and triggers)."""
    key = _insert(pg)
    before = _row(pg, key)
    with pytest.raises(pgerr.CheckViolation) as refused:
        _update(_as(pg, "cv_app"), key, sealed_seed=None)
    assert refused.value.diag.constraint_name == "ask_lifecycle"
    assert _row(pg, key) == before


@pytest.mark.parametrize(
    ("state", "sets", "column"),
    [
        ("active", {"id": uuid4()}, "id"),
        ("active", {"env": "live"}, "env"),
        ("active", {"version": 2}, "version"),
        ("active", {"key_id": _public(2)["key_id"]}, "key_id"),
        ("active", {"public_key": bytes(32)}, "public_key"),
        ("active", {"fingerprint_sha256": "0" * 64}, "fingerprint_sha256"),
        ("active", _public(1, bytes(32)), "key_id"),  # another key, consistent: a swap (AD-S12)
        ("active", {"valid_from": _T1}, "valid_from"),
        ("active", {"created_by": uuid4()}, "created_by"),  # refused before its FK is checked
        ("active", {"client_ref": str(uuid4())}, "client_ref"),
        ("active", {"client_body_sha256": "a" * 64}, "client_body_sha256"),
        ("active", {"created_at": _T1}, "created_at"),
        ("active", {"sealed_seed": b"\xa5" * 60}, "sealed_seed"),  # replaced
        ("destroyed", {"sealed_seed": _SEED}, "sealed_seed"),  # set back
        ("retained", {"status": "active", "valid_until": None, "retired_reason": None}, "status"),
        ("destroyed", {"valid_until": _T0}, "valid_until"),
        ("destroyed", {"retired_reason": "compromise"}, "retired_reason"),
        ("active", {"dek_ref": _NEXT_WRAP}, "dek_ref"),  # a wrap without its KEK version
        ("active", {"kek_version": 2}, "kek_version"),  # a KEK version without its wrap
        ("destroyed", {"dek_ref": _NEXT_WRAP, "kek_version": 2}, "dek_ref"),
        ("retained", {"dek_ref": _NEXT_WRAP, "kek_version": 2, "sealed_seed": None}, "dek_ref"),
    ],
    ids=lambda v: v if isinstance(v, str) else None,
)
def test_every_other_change_is_refused_naming_the_column_never_a_value(
    pg: str, state: str, sets: dict[str, Any], column: str
) -> None:
    key = _insert(pg, state)
    before = _row(pg, key)
    with pytest.raises(pgerr.CheckViolation) as refused:
        _update(_as(pg, "cv_app"), key, **sets)
    diag = refused.value.diag
    assert (diag.constraint_name, diag.message_detail) == (_GUARD, None)
    assert diag.message_primary == f"{_GUARD}: refused a change to {_T}.{column} (ADR-0039)"
    assert _row(pg, key) == before


_COLUMNS = (
    "id", "env", "version", "key_id", "public_key", "fingerprint_sha256", "sealed_seed", "dek_ref",
    "kek_version", "status", "valid_from", "valid_until", "retired_reason", "created_by",
    "client_ref", "client_body_sha256", "created_at",
)  # fmt: skip


def test_the_guard_names_every_column_of_the_table(pg: str) -> None:
    """Pins 0046's own columns, each named by the trigger, which refuses changes column by column:
    a later revision adding a column must extend the guard too, as CI-MIG-006 flags (#889 S4a)."""
    columns = _exec(
        pg,
        "SELECT attname FROM pg_attribute WHERE attrelid = 'audit_signing_keys'::regclass"
        " AND attnum > 0 AND NOT attisdropped ORDER BY attnum",
    )
    (source,) = _exec(
        pg, "SELECT pg_get_functiondef('audit_signing_keys_write_once_check'::regproc)"
    )
    assert tuple(name for (name,) in columns) == _COLUMNS
    assert [c for c in _COLUMNS if f"NEW.{c} IS DISTINCT FROM OLD.{c}" not in source[0]] == []


def test_the_guard_is_alone_always_on_and_cv_app_cannot_delete_or_disable(pg: str) -> None:
    """Same-event triggers fire in name order, so the guard must sort last; `ENABLE ALWAYS` keeps
    it on under `replica`. tgtype 19 = ROW | BEFORE | UPDATE."""
    order = _exec(
        pg,
        "SELECT tgname, tgenabled FROM pg_trigger WHERE tgrelid = 'audit_signing_keys'::regclass "
        'AND NOT tgisinternal AND tgtype & 19 = 19 ORDER BY tgname COLLATE "C"',
    )
    assert order == [(_GUARD, "A")]
    probe = (
        "SELECT string_agg(p, ' ' ORDER BY p) FROM unnest(ARRAY['SELECT', 'INSERT', 'UPDATE', "
        "'DELETE', 'TRUNCATE', 'REFERENCES', 'TRIGGER']) AS p "
        "WHERE has_table_privilege(%s, 'audit_signing_keys', p)"
    )
    held = [_exec(pg, probe, (role,))[0] for role in ("cv_app", "cv_ro")]
    assert held == [("INSERT SELECT UPDATE",), ("SELECT",)]
    key, app = _insert(pg), _as(pg, "cv_app")
    for refused in (_DELETE, "ALTER TABLE audit_signing_keys DISABLE TRIGGER " + _GUARD):
        with pytest.raises(pgerr.InsufficientPrivilege):
            _exec(app, refused)
    assert len(_row(pg, key)) == 1


def test_the_round_trip_restores_the_schema_and_the_downgrade_refuses_while_a_row_exists(
    pg: str,
) -> None:
    for rev in (_PREV, _REV, _PREV, _REV):  # an empty table: the downgrade passes its guard
        _at(pg, rev)  # a function left behind would fail the next upgrade
        assert _exec(pg, f"SELECT to_regclass('{_T}') IS NOT NULL") == [(rev == _REV,)]
    key = _insert(pg, "destroyed")  # a retired key whose seed is gone still holds a public key
    refused = _alembic(pg, "downgrade", _PREV)
    assert refused.returncode != 0
    assert f"{_REV} downgrade refused: audit_signing_keys holds rows" in refused.stderr
    assert _exec(pg, "SELECT version_num FROM alembic_version") == [(_REV,)] and _row(pg, key)
    _exec(pg, _DELETE)  # the owner path the message names (cv_app cannot)
    assert _alembic(pg, "downgrade", _PREV).returncode == 0


def test_downgrade_gives_up_on_a_held_writer_lock_instead_of_queueing(pg: str) -> None:
    with psycopg.connect(pg, autocommit=True) as holder, holder.transaction():
        holder.execute("LOCK TABLE audit_signing_keys IN ROW EXCLUSIVE MODE")  # an open writer's
        refused = _alembic(pg, "downgrade", _PREV)
    assert refused.returncode != 0 and "lock timeout" in refused.stderr
    assert _exec(pg, "SELECT version_num FROM alembic_version") == [(_REV,)]

"""Integration: `0024_api_keys_write_once` on real Postgres 16 (#2336, SR-003, KV-T02 / AC-24).

Bootstrapped with the shipped `infra/scripts/pg_bootstrap.sql` and migrated as `cv_owner`, as in
the CI `migrations` job, so writes run as the real runtime role `cv_app`. Synthetic KEKs and keys
only; no network beyond the local testcontainer. Not run locally (no docker); CI lanes only.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import psycopg
import pytest
from psycopg import sql
from psycopg.abc import Params
from testcontainers.postgres import PostgresContainer

from candleviewer.secrets import KEY_ID_SLOT
from candleviewer.secrets import _envelope as env
from candleviewer.secrets._kek import LoadedKek
from candleviewer.secrets.broker import CredentialBroker
from candleviewer.secrets.secret import Secret
from candleviewer.storage.repositories.credentials_sqlalchemy import SqlAlchemyCredentialStore
from candleviewer.storage.repositories.relational_sqlalchemy import (
    SqlAlchemyRelationalRepository,
)
from tests.unit.credentials_m2._vectors import KEK_V1, KEK_V2, kek

pytestmark = pytest.mark.integration

_ROOT = Path(__file__).resolve().parents[3]
_BOOTSTRAP = _ROOT.parents[1] / "infra" / "scripts" / "pg_bootstrap.sql"
_BOOTSTRAP_ROLES = (("owner_pw", "cv_owner"), ("app_pw", "cv_app"), ("ro_pw", "cv_ro"))
_REV, _PREV = "0024_api_keys_write_once", "0023_replay_sessions"
_ACCT = UUID("00000000-0000-4000-8000-0000000002a1")
_ACCT2 = UUID("00000000-0000-4000-8000-0000000002a2")  # same env: FK and unique indexes pass
_SNAP: dict[str, Any] = {"uid": "1", "permissions": {"ContractTrade": ["Order"], "Wallet": []}}
_OLD_KEY, _NEW_KEY = "older" + "0" * 11 + "WXYZ", "newer" + "0" * 11 + "WXYZ"  # same last4
_SEALED = ("key_id_enc", "secret_enc", "enc_nonce", "dek_ref", "kek_version")
#: A value per protected column that passes every CHECK and FK; `ak_alg` admits only the
#: current `enc_alg`, which is fine because BEFORE row triggers fire before CHECKs.
_CHANGES: dict[str, Any] = {
    "id": UUID("00000000-0000-4000-8000-0000000002ff"),
    "exchange_account_id": _ACCT2,
    "key_id_enc": b"other-sealed-key-id",
    "key_id_last4": "QRST",
    "secret_enc": b"other-sealed-secret",
    "enc_nonce": b"\x01" * 12,
    "enc_alg": "AES-128-GCM",
}
#: Every other column that may change, plus each protected column set to its own value.
_OTHERS = (
    "UPDATE api_keys SET label = 'renamed', dek_ref = 'v1:01', kek_version = 2, "
    "permission_snapshot = jsonb_build_object('uid', '7', 'permissions', '{}'::jsonb), "
    "permission_snapshot_at = now(), can_trade = true, ip_whitelist = '{10.0.0.1/32}', "
    "ip_whitelist_verified_at = now(), status = 'revoked', expires_at = now(), "
    "last_used_at = now(), last_error_code = 'E1', last_error_at = now(), "
    "rotation_due_at = now(), updated_by = NULL, updated_at = now(), revoked_at = now(), "
    "id = id, exchange_account_id = exchange_account_id, key_id_enc = key_id_enc, "
    "key_id_last4 = key_id_last4, secret_enc = secret_enc, enc_nonce = enc_nonce, "
    "enc_alg = enc_alg WHERE id = %s"
)


@pytest.fixture(scope="module")
def pg() -> Iterator[str]:
    """Superuser DSN of a container with the bootstrap roles (`pg_bootstrap.sql` needs the
    database to be named `candleviewer`)."""
    with PostgresContainer("postgres:16-alpine", dbname="candleviewer") as container:
        dsn = container.get_connection_url().replace("postgresql+psycopg2", "postgresql")
        info = psycopg.conninfo.conninfo_to_dict(dsn)
        psql = shutil.which("psql")
        assert psql is not None, "psql is needed to run pg_bootstrap.sql (CI runners ship it)"
        pws = [f"{var}={role}_test_pw" for var, role in _BOOTSTRAP_ROLES]
        subprocess.run(  # noqa: S603 -- resolved psql path, fixed argv, no shell
            [psql, "-h", str(info["host"]), "-p", str(info["port"]), "-U", str(info["user"]),
             "-d", "candleviewer", "-v", "ON_ERROR_STOP=1",
             *[arg for pw in pws for arg in ("-v", pw)], "-f", str(_BOOTSTRAP)],
            env={**os.environ, "PGPASSWORD": str(info["password"])}, check=True, timeout=120,
        )  # fmt: skip
        yield dsn


def _as(dsn: str, role: str, driver: str = "postgresql") -> str:
    """`dsn` logged in as a bootstrap role (test-only password `<role>_test_pw`)."""
    return re.sub(r"^postgresql://[^@]+@", f"{driver}://{role}:{role}_test_pw@", dsn)


def _alembic(dsn: str, *args: str) -> subprocess.CompletedProcess[str]:
    """As cv_owner, like CI; bounded, so a lost `lock_timeout` fails instead of hanging."""
    return subprocess.run(  # noqa: S603 -- fixed argv, literal alembic subcommands, no shell
        [sys.executable, "-m", "alembic", *args],
        cwd=_ROOT, env={**os.environ, "CV_PG_DSN": _as(dsn, "cv_owner", "postgresql+psycopg")},
        capture_output=True, text=True, check=False, timeout=120,
    )  # fmt: skip


def _exec(
    dsn: str, query: str | sql.Composed, params: Params | None = None
) -> list[tuple[Any, ...]]:
    with psycopg.connect(dsn, autocommit=True) as c:
        cur = c.execute(query, params)
        return cur.fetchall() if cur.description else []


def _account(dsn: str, acct: UUID) -> UUID:
    _exec(
        dsn,
        "INSERT INTO exchange_accounts (id, exchange, env, kind, exchange_uid, label) "
        "VALUES (%s, 'bybit', 'demo', 'main', %s, %s) ON CONFLICT DO NOTHING",
        (acct, str(acct.int % 10**12), f"acct-{acct}"),
    )
    return acct


def _at(dsn: str, rev: str) -> None:
    """Move the module's shared database to `rev` and make sure the seed accounts exist."""
    has_version = _exec(dsn, "SELECT to_regclass('public.alembic_version') IS NOT NULL")[0][0]
    current = _exec(dsn, "SELECT version_num FROM alembic_version")[0][0] if has_version else None
    if current != rev:
        done = _alembic(dsn, "downgrade" if current == _REV else "upgrade", rev)
        assert done.returncode == 0, done.stderr
    _account(dsn, _ACCT)
    _account(dsn, _ACCT2)


def _insert(dsn: str, acct: UUID = _ACCT) -> UUID:
    key_id = uuid4()
    _exec(
        dsn,
        "INSERT INTO api_keys (id, exchange_account_id, label, key_id_enc, key_id_last4, "
        "secret_enc, enc_nonce, dek_ref, permission_snapshot) "
        "VALUES (%s, %s, %s, %s, 'WXYZ', %s, %s, 'v1:00', %s::jsonb)",
        (key_id, acct, f"k-{key_id}", b"sealed-key-id", b"sealed-secret", bytes(12),
         json.dumps(_SNAP)),
    )  # fmt: skip
    return key_id


def _rows(dsn: str, *ids: UUID) -> list[tuple[Any, ...]]:
    return _exec(
        dsn, "SELECT k::text FROM api_keys k WHERE k.id = ANY(%s) ORDER BY k.id", [list(ids)]
    )


def _guard(dsn: str) -> tuple[Any, ...]:
    """(trigger `tgenabled` or None, guard function exists, cv_app may DELETE from api_keys)."""
    return _exec(
        dsn,
        "SELECT (SELECT tgenabled FROM pg_trigger WHERE tgname = 'trg_api_keys_write_once'), "
        "to_regprocedure('api_keys_write_once_check()') IS NOT NULL, "
        "has_table_privilege('cv_app', 'api_keys', 'DELETE')",
    )[0]


def _refusal(column: str) -> str:
    return f"trg_api_keys_write_once: api_keys.{column} is write-once; store a new row (SR-003)"


def _sealed(dsn: str, key_id: UUID) -> dict[str, Any]:
    cols = sql.SQL(", ").join(map(sql.Identifier, _SEALED))
    query = sql.SQL("SELECT {} FROM api_keys WHERE id = %s").format(cols)
    return dict(zip(_SEALED, _exec(dsn, query, (key_id,))[0], strict=True))


def _write(dsn: str, key_id: UUID, cols: dict[str, Any]) -> None:
    sets = sql.SQL(", ").join(sql.SQL("{} = %s").format(sql.Identifier(c)) for c in cols)
    _exec(
        dsn, sql.SQL("UPDATE api_keys SET {} WHERE id = %s").format(sets), [*cols.values(), key_id]
    )


def _resealed(key_id: UUID, acct: UUID, api_key: str) -> dict[str, Any]:
    """What an in-place edit would write (#896): a fresh DEK sealing `api_key` and a new secret
    under the same credential id, wrapped by the current KEK."""
    dek = env.new_dek()
    key_enc = env.seal(dek, api_key.encode(), env.cred_aad("demo", acct, key_id, "key_id"))
    secret = env.seal(dek, b"edited", env.cred_aad("demo", acct, key_id, "secret"))
    ref = kek(KEK_V1, 1).wrap_dek(dek, credential_id=key_id)
    return {"key_id_enc": key_enc, "secret_enc": secret, "enc_nonce": secret[:12], "dek_ref": ref}


async def _audit(action: str, fields: dict[str, str]) -> None:
    return None


def _store(dsn: str) -> tuple[SqlAlchemyRelationalRepository, SqlAlchemyCredentialStore]:
    """The M10 adapter, connected as the runtime role."""
    rel = SqlAlchemyRelationalRepository(_as(dsn, "cv_app", "postgresql+asyncpg"))
    return rel, SqlAlchemyCredentialStore(rel)


def _broker(store: SqlAlchemyCredentialStore, kek_: LoadedKek | None = None) -> CredentialBroker:
    """A fresh broker, so no DEK is cached between reads."""
    return CredentialBroker(store, _audit, kek_ or kek(KEK_V1, 1))


async def _seal(dsn: str, store: SqlAlchemyCredentialStore, acct: UUID, api_key: str) -> UUID:
    """`CredentialBroker.store` (fresh uuid4, INSERT only), then activate the row."""
    meta = await _broker(store).store("demo", acct, "k", Secret(api_key), Secret("S"), _SNAP)
    _exec(_as(dsn, "cv_app"), "UPDATE api_keys SET status = 'active' WHERE id = %s", (meta.key_id,))
    return meta.key_id


async def _api_key(b: CredentialBroker, key_id: UUID) -> str:
    """The key id M2 decrypts, read the way the exchange adapter signs (#2339)."""
    handle = b.borrow_handle("exchange_adapter")
    return (await handle.sign(key_id, (KEY_ID_SLOT,), purpose="sign_rest")).api_key.reveal()


@pytest.mark.parametrize(("column", "value"), list(_CHANGES.items()), ids=list(_CHANGES))
def test_changing_a_protected_column_is_refused_atomically(
    pg: str, column: str, value: Any
) -> None:
    """One cv_app statement renames two rows and changes `column` on one: refused as a whole
    (SQLSTATE 23514), naming the column and no value; both rows stay byte-identical. Each row
    takes the change once, so whatever order the scan visits them in, one statement has already
    updated the other row when the trigger refuses."""
    _at(pg, _REV)
    rows = _insert(pg), _insert(pg)
    before = _rows(pg, *rows)
    change = sql.SQL(
        "UPDATE api_keys SET label = label || '~', {c} = CASE WHEN id = %s THEN %s ELSE {c} END "
        "WHERE id IN (%s, %s)"
    ).format(c=sql.Identifier(column))
    for victim in rows:
        with pytest.raises(psycopg.errors.CheckViolation) as refused:
            _exec(_as(pg, "cv_app"), change, (victim, value, *rows))
        assert refused.value.diag.message_primary == _refusal(column)
        assert refused.value.diag.message_detail is None
    assert _rows(pg, *rows) == before


def test_other_columns_and_unchanged_values_stay_writable(pg: str) -> None:
    _at(pg, _REV)
    key_id = _insert(pg)
    _exec(_as(pg, "cv_app"), _OTHERS, (key_id,))
    _exec(_as(pg, "cv_app"), "UPDATE api_keys SET label = 'none' WHERE false")
    assert _exec(
        pg, "SELECT label, kek_version, status::text FROM api_keys WHERE id = %s", (key_id,)
    ) == [("renamed", 2, "revoked")]


async def test_restoring_an_older_sealed_version_is_refused(pg: str) -> None:
    """AC-24 / KV-T02 as cv_app. At the parent revision an in-place re-seal, then a restore of
    the captured older ciphertext and `dek_ref`, both pass and the older key decrypts again: the
    rollback the #835 sign-off named. At head the same restore is refused."""
    _at(pg, _PREV)
    app = _as(pg, "cv_app")
    rel, store = _store(pg)
    try:
        acct = _account(pg, uuid4())
        key_id = await _seal(pg, store, acct, _OLD_KEY)
        older = _sealed(pg, key_id)
        _write(app, key_id, _resealed(key_id, acct, _NEW_KEY))
        _write(app, key_id, older)
        assert await _api_key(_broker(store), key_id) == _OLD_KEY
        _write(app, key_id, _resealed(key_id, acct, _NEW_KEY))
        _at(pg, _REV)
        with pytest.raises(psycopg.errors.CheckViolation) as refused:
            _write(app, key_id, older)
        assert refused.value.diag.message_primary == _refusal("key_id_enc")
        assert await _api_key(_broker(store), key_id) == _NEW_KEY
    finally:
        await rel.dispose()


async def test_m10_rewrap_touch_and_revoke_still_succeed(pg: str) -> None:
    """Scope item 2 through the M10 adapter as cv_app: the re-wrap compare-and-set (true, then
    false once the row has moved on), the `last_used_at` touch and revoke pass the trigger, and
    the sealed columns are unchanged."""
    _at(pg, _REV)
    rel, store = _store(pg)
    try:
        key_id = await _seal(pg, store, _account(pg, uuid4()), _NEW_KEY)
        before = _sealed(pg, key_id)
        dek = kek(KEK_V1, 1).unwrap_dek(before["dek_ref"], credential_id=key_id)
        ref = kek(KEK_V2, 2).wrap_dek(dek, credential_id=key_id)
        assert await store.rewrap(key_id, from_version=1, dek_ref=ref, kek_version=2)
        assert not await store.rewrap(key_id, from_version=1, dek_ref=ref, kek_version=2)
        rewrapped = _broker(store, kek(KEK_V2, 2))
        assert await _api_key(rewrapped, key_id) == _NEW_KEY  # touches last_used_at
        await rewrapped.destroy(key_id)  # mark_revoked
        assert _sealed(pg, key_id) == {**before, "dek_ref": ref, "kek_version": 2}
        assert _exec(
            pg,
            "SELECT last_used_at IS NOT NULL, revoked_at IS NOT NULL FROM api_keys WHERE id = %s",
            (key_id,),
        ) == [(True, True)]
    finally:
        await rel.dispose()


@pytest.mark.parametrize(
    "statement",
    [
        "DELETE FROM api_keys",
        "TRUNCATE api_keys CASCADE",
        "ALTER TABLE api_keys DISABLE TRIGGER trg_api_keys_write_once",
        "DROP TRIGGER trg_api_keys_write_once ON api_keys",
        "SET session_replication_role = replica",
    ],
)
def test_cv_app_can_neither_delete_rows_nor_switch_the_guard_off(pg: str, statement: str) -> None:
    _at(pg, _REV)
    key_id = _insert(pg)
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        _exec(_as(pg, "cv_app"), statement)
    assert len(_rows(pg, key_id)) == 1
    assert _guard(pg) == ("A", True, False)


def test_account_delete_by_cv_app_still_cascades_to_its_keys(pg: str) -> None:
    """Pins the residual named in the PR for the owner: referential actions run as the table
    owner, so deleting the parent account removes its keys despite the revoked DELETE."""
    _at(pg, _REV)
    acct = _account(pg, uuid4())
    key_id = _insert(pg, acct)
    _exec(_as(pg, "cv_app"), "DELETE FROM exchange_accounts WHERE id = %s", (acct,))
    assert _rows(pg, key_id) == []


def test_guard_is_the_last_before_update_row_trigger(pg: str) -> None:
    """Same-event triggers fire in name order; a later BEFORE UPDATE trigger could rewrite NEW
    after the check. tgtype 19 = ROW | BEFORE | UPDATE."""
    _at(pg, _REV)
    order = _exec(
        pg,
        "SELECT tgname, tgenabled FROM pg_trigger WHERE tgrelid = 'api_keys'::regclass "
        'AND NOT tgisinternal AND tgtype & 19 = 19 ORDER BY tgname COLLATE "C"',
    )
    assert order[-1] == ("trg_api_keys_write_once", "A")


def test_guard_fires_in_replica_mode(pg: str) -> None:
    """`ENABLE ALWAYS`: a `session_replication_role = replica` session is refused too."""
    _at(pg, _REV)
    key_id = _insert(pg)
    with psycopg.connect(pg, autocommit=True) as c:
        c.execute("SET session_replication_role = replica")
        with pytest.raises(psycopg.errors.CheckViolation) as refused:
            c.execute("UPDATE api_keys SET secret_enc = 'x'::bytea WHERE id = %s", (key_id,))
    assert refused.value.diag.message_primary == _refusal("secret_enc")


def test_round_trip_empty_then_seeded(pg: str) -> None:
    _at(pg, _REV)
    _exec(pg, "TRUNCATE api_keys CASCADE")
    assert _guard(pg) == ("A", True, False)
    _exec(_as(pg, "cv_app"), "UPDATE api_keys SET label = label")  # zero rows: nothing to refuse
    _at(pg, _PREV)
    assert _guard(pg) == (None, False, True)
    key_id = _insert(pg)
    _at(pg, _REV)
    assert _guard(pg) == ("A", True, False)
    _at(pg, _PREV)
    _at(pg, _REV)
    assert len(_rows(pg, key_id)) == 1


def test_upgrade_gives_up_on_a_held_lock_instead_of_queueing(pg: str) -> None:
    _at(pg, _PREV)
    with psycopg.connect(pg, autocommit=True) as holder, holder.transaction():
        holder.execute("LOCK TABLE api_keys IN ROW EXCLUSIVE MODE")  # what an open writer holds
        refused = _alembic(pg, "upgrade", _REV)
    assert refused.returncode != 0
    assert "lock timeout" in refused.stderr
    assert _exec(pg, "SELECT version_num FROM alembic_version") == [(_PREV,)]
    _at(pg, _REV)


def test_downgrade_gives_up_on_a_reader_lock_instead_of_queueing(pg: str) -> None:
    """DROP TRIGGER needs ACCESS EXCLUSIVE, so even an open reader blocks the rollback; the
    `lock_timeout` bounds that wait too, and the failed downgrade leaves the guard in place."""
    _at(pg, _REV)
    with psycopg.connect(pg, autocommit=True) as holder, holder.transaction():
        holder.execute("LOCK TABLE api_keys IN ACCESS SHARE MODE")  # what an open reader holds
        refused = _alembic(pg, "downgrade", _PREV)
    assert refused.returncode != 0
    assert "lock timeout" in refused.stderr
    assert _guard(pg) == ("A", True, False)

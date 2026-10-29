"""Integration: `SqlAlchemyAccountsStore` on real Postgres 16 (E27-T01, migrations 0017/0019).

CI-only (testcontainers; no docker socket locally) - NOT run by the author. Keys are written by
M2's real writer, `SqlAlchemyCredentialStore.insert`, from M2's own `CredentialRow` record with
fixed fake bytes (no KEK, no plaintext), and revoked through its `mark_revoked`. So the accounts
store is proven to read exactly the rows M2 writes and to honour M2's revocation.
"""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
import time
import uuid
from collections.abc import AsyncIterator, Iterator
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import psycopg
import pytest
import pytest_asyncio
import sqlalchemy as sa
from testcontainers.postgres import PostgresContainer

from candleviewer.accounts.consequences import GRANTEES_LISTED, ConsequenceRead, StoreReadFailed
from candleviewer.accounts.exposure import ExposureOutcome, ExposureUnknown
from candleviewer.accounts.models import ExchangeAccount
from candleviewer.accounts.profile_repository import ArmedRule
from candleviewer.accounts.repository import AccountsRepository
from candleviewer.secrets.models import CredentialRow
from candleviewer.storage.repositories import accounts_sqlalchemy as store_sql
from candleviewer.storage.repositories.accounts import (
    SUB_ACCOUNT_CAP_CONFLICT,
    AccountKey,
    AccountsStoreConflictError,
    AccountsStoreRuleError,
    AccountsStoreScopeDeniedError,
    AccountsStoreStaleError,
    AccountsStoreUnchangedError,
    ExchangeAccountPatch,
    ExchangeAccountRow,
    GrantScope,
    NewExchangeAccount,
    NewKeyRotation,
    OwnerScope,
    PolicyDisarm,
    RotationStep,
    VerifiedKey,
)
from candleviewer.storage.repositories.accounts_sqlalchemy import SqlAlchemyAccountsStore
from candleviewer.storage.repositories.audit_sqlalchemy import insert_audit_row_locked
from candleviewer.storage.repositories.credentials_sqlalchemy import SqlAlchemyCredentialStore
from candleviewer.storage.repositories.key_selfcheck_sqlalchemy import SqlAlchemyKeySelfCheckStore
from candleviewer.storage.repositories.relational_sqlalchemy import (
    SqlAlchemyRelationalRepository,
    constraint_of,
    sqlstate_of,
)
from tests.integration._refused import assert_no_row_values, rendered_graph, server_text

pytestmark = pytest.mark.integration

_ROOT = Path(__file__).resolve().parents[3]
_FROZEN_AT = datetime(2026, 10, 1, tzinfo=UTC)
_SNAPSHOT: dict[str, object] = {
    "fetched_at": "2026-10-01T00:00:00+00:00",
    "uid": "1",
    "permissions": {},
}
# The fake ciphertexts `_seed_key` writes (S), and values planted by name, as a traceback prints
# the calling line (#2748). `ux_ea_label` is on lower(label), so its DETAIL prints lower case.
_KEY_ID_ENC, _SECRET_ENC = b"\x01" * 28, b"\x02" * 28
_NONCE, _SEED_DEK, _UID = b"SECRET-NONCE", "v1:SECRET-SEED-DEK", "771234567890123"
_LABEL, _LABEL2, _BAD_UID, _IP = "secret-label-1", "secret-label-2", "SECRET-uid", "198.51.100.23"
# `(__cause__, __suppress_context__)` of an error raised `from None`, or of a stripped driver error
_TYPED = (None, True)


@pytest.fixture(scope="module")
def pg_dsn() -> Iterator[str]:
    with PostgresContainer("postgres:16-alpine") as container:
        url = container.get_connection_url()
        subprocess.run(
            [sys.executable, "-m", "alembic", "upgrade", "head"],
            cwd=_ROOT,
            env={
                **os.environ,
                "CV_PG_DSN": url.replace("postgresql+psycopg2", "postgresql+psycopg"),
            },
            check=True,
        )
        yield url.replace("postgresql+psycopg2", "postgresql+asyncpg")


def _c(dsn: str) -> psycopg.Connection[tuple[object, ...]]:
    return psycopg.connect(dsn.replace("postgresql+asyncpg", "postgresql"), autocommit=True)


def _exchange(dsn: str) -> str:
    with _c(dsn) as c:
        row = c.execute(
            "SELECT enumlabel FROM pg_enum e JOIN pg_type t ON t.oid = e.enumtypid "
            "WHERE t.typname = 'exchange_code' LIMIT 1"
        ).fetchone()
    assert row is not None
    return str(row[0])


def _user(dsn: str, role: str | None = None) -> uuid.UUID:
    uid = uuid.uuid4()
    with _c(dsn) as c:
        c.execute(
            "INSERT INTO users (id, email, username, display_name, password_hash, status) "
            "VALUES (%s, %s, %s, 'u', '$argon2id$x', 'active')",
            (str(uid), f"{uid}@example.test", f"u{str(uid)[:12]}"),
        )
        if role:
            c.execute(
                "INSERT INTO user_roles (user_id, role_id) "
                "SELECT %s, id FROM roles WHERE name = %s",
                (str(uid), role),
            )
    return uid


def _grant(dsn: str, user: uuid.UUID, acct: uuid.UUID, *, can_view: bool, frozen: bool) -> None:
    # 0001 `uaa_frozen_consistency`: a frozen grant must carry `frozen_at`.
    with _c(dsn) as c:
        c.execute(
            "INSERT INTO user_account_access "
            "(user_id, exchange_account_id, can_view, frozen, frozen_at) "
            "VALUES (%s, %s, %s, %s, %s)",
            (str(user), str(acct), can_view, frozen, _FROZEN_AT if frozen else None),
        )


def _uid() -> str:
    return str(uuid.uuid4().int % 10**15)


@pytest_asyncio.fixture
async def rel(pg_dsn: str) -> AsyncIterator[SqlAlchemyRelationalRepository]:
    repo = SqlAlchemyRelationalRepository(pg_dsn, "accounts-it")
    try:
        yield repo
    finally:
        await repo.dispose()


@pytest.fixture
def store(rel: SqlAlchemyRelationalRepository) -> SqlAlchemyAccountsStore:
    return SqlAlchemyAccountsStore(rel)


@pytest.fixture
def creds(rel: SqlAlchemyRelationalRepository) -> SqlAlchemyCredentialStore:
    """M2's real `api_keys` writer; the accounts store only reads what it writes (C-3.2)."""
    return SqlAlchemyCredentialStore(rel)


def _new(
    exch: str,
    *,
    env: str = "demo",
    label: str | None = None,
    parent: uuid.UUID | None = None,
    uid: str | None = None,
) -> NewExchangeAccount:
    return NewExchangeAccount(
        uuid.uuid4(), exch, env, "sub" if parent else "main", uid or _uid(),
        label or f"L{uuid.uuid4().hex[:8]}", parent,
    )  # fmt: skip


async def _seed_key(creds: SqlAlchemyCredentialStore, acct: uuid.UUID) -> uuid.UUID:
    """A `pending` key on a demo account, written by M2's own writer and record type."""
    kid = uuid.uuid4()
    row = CredentialRow(
        id=kid, exchange_account_id=acct, env="demo", label=f"k{kid.hex[:8]}",
        key_id_enc=_KEY_ID_ENC, key_id_last4="abcd", secret_enc=_SECRET_ENC,
        enc_nonce=_NONCE, dek_ref=_SEED_DEK, kek_version=1,
        permission_snapshot=dict(_SNAPSHOT),
    )  # fmt: skip
    await creds.insert(row.to_record())
    return kid


async def test_account_round_trip_and_soft_delete_frees_identity(
    store: SqlAlchemyAccountsStore, pg_dsn: str
) -> None:
    exch, owner = _exchange(pg_dsn), OwnerScope(_user(pg_dsn, "owner"))
    main = await store.create_account(owner, _new(exch))
    sub = await store.create_account(owner, _new(exch, parent=main.id))
    assert (await store.get_account(owner, sub.id)) == sub
    page = await store.list_accounts(owner, env="demo", kind="sub", after=None, limit=500)
    assert sub.id in {r.id for r in page.items}
    upd = await store.update_account(
        owner, main.id, ExchangeAccountPatch(label=main.label + "x"), if_match=main.updated_at
    )
    assert upd is not None and upd.updated_at > main.updated_at
    with pytest.raises(AccountsStoreStaleError):
        await store.update_account(
            owner, main.id, ExchangeAccountPatch(is_enabled=False), if_match=main.updated_at
        )
    assert await store.soft_delete_account(owner, sub.id) is True
    assert await store.get_account(owner, sub.id) is None
    assert await store.soft_delete_account(owner, sub.id) is False
    assert (
        await store.update_account(owner, sub.id, ExchangeAccountPatch(label="z"), if_match=None)
        is None
    )
    again = NewExchangeAccount(uuid.uuid4(), exch, "demo", "main", sub.exchange_uid, sub.label)
    assert (await store.create_account(owner, again)).exchange_uid == sub.exchange_uid


async def test_constraint_mapping(
    rel: SqlAlchemyRelationalRepository, store: SqlAlchemyAccountsStore, pg_dsn: str
) -> None:
    exch, owner = _exchange(pg_dsn), OwnerScope(_user(pg_dsn, "owner"))
    a = await store.create_account(owner, _new(exch, label=_LABEL, uid=_UID))
    with server_text(rel) as seen, pytest.raises(AccountsStoreConflictError) as ei:
        await store.create_account(owner, _new(exch, label=_LABEL.upper()))
    assert ei.value.constraint == "ux_ea_label"
    assert (ei.value.__cause__, ei.value.__suppress_context__) == _TYPED
    assert_no_row_values(ei.value, seen, _LABEL)  # the DETAIL's key, `lower(label)`
    left = rendered_graph(ei.value) + "\n".join(seen.logs)
    assert _LABEL.upper() not in left  # the refused value itself: the server never prints it
    same_uid = NewExchangeAccount(uuid.uuid4(), exch, "demo", "main", a.exchange_uid, "other")
    with server_text(rel) as seen, pytest.raises(AccountsStoreConflictError) as ei2:
        await store.create_account(owner, same_uid)
    assert ei2.value.constraint == "ux_ea_uid"
    assert (ei2.value.__cause__, ei2.value.__suppress_context__) == _TYPED
    assert_no_row_values(ei2.value, seen, _UID)
    bad_uid = NewExchangeAccount(uuid.uuid4(), exch, "demo", "main", _BAD_UID, _LABEL2)
    with server_text(rel) as seen, pytest.raises(AccountsStoreRuleError) as ei3:
        await store.create_account(owner, bad_uid)
    assert ei3.value.rule == "ea_uid_fmt"
    assert (ei3.value.__cause__, ei3.value.__suppress_context__) == _TYPED
    assert_no_row_values(ei3.value, seen, _BAD_UID, _LABEL2)  # the failing row, whole
    sub = await store.create_account(owner, _new(exch, parent=a.id))
    deleted = await store.create_account(owner, _new(exch))
    await store.soft_delete_account(owner, deleted.id)
    for parent, env in (
        (uuid.uuid4(), "demo"),
        (deleted.id, "demo"),
        (sub.id, "demo"),
        (a.id, "live"),
    ):
        n = NewExchangeAccount(
            uuid.uuid4(), exch, env, "sub", _uid(), f"s{uuid.uuid4().hex[:6]}", parent
        )
        with pytest.raises(AccountsStoreRuleError) as e:
            await store.create_account(owner, n)
        assert e.value.rule == "parent_unavailable"
    shape = NewExchangeAccount(uuid.uuid4(), exch, "demo", "sub", _uid(), "shape", None)
    with pytest.raises(AccountsStoreRuleError) as e2:
        await store.create_account(owner, shape)
    assert e2.value.rule == "ea_parent_shape"


async def test_sr051_scoping_matrix(store: SqlAlchemyAccountsStore, pg_dsn: str) -> None:
    exch = _exchange(pg_dsn)
    owner = OwnerScope(_user(pg_dsn, "owner"))
    granted = await store.create_account(owner, _new(exch))
    frozen = await store.create_account(owner, _new(exch))
    noview = await store.create_account(owner, _new(exch))
    foreign = await store.create_account(owner, _new(exch))
    gone = await store.create_account(owner, _new(exch))
    mgr, viewer, nogrant = (
        _user(pg_dsn, "manager"),
        _user(pg_dsn, "viewer"),
        _user(pg_dsn, "manager"),
    )
    _grant(pg_dsn, mgr, granted.id, can_view=True, frozen=False)
    _grant(pg_dsn, mgr, frozen.id, can_view=True, frozen=True)
    _grant(pg_dsn, mgr, noview.id, can_view=False, frozen=False)
    _grant(pg_dsn, mgr, gone.id, can_view=True, frozen=False)
    _grant(pg_dsn, viewer, granted.id, can_view=True, frozen=False)
    await store.soft_delete_account(owner, gone.id)
    everything = frozenset({granted.id, frozen.id, noview.id, foreign.id, gone.id})
    # Forged scope naming every id: the live-grant re-check in SQL still narrows it.
    forged = GrantScope(mgr, everything)
    seen = await store.list_accounts(forged, env=None, kind=None, after=None, limit=500)
    assert {r.id for r in seen.items} == {granted.id}
    for acct in (frozen, noview, foreign, gone):
        assert await store.get_account(forged, acct.id) is None
    assert (await store.get_account(forged, granted.id)) is not None
    assert await store.get_account(GrantScope(nogrant, everything), granted.id) is None
    v = await store.list_accounts(
        GrantScope(viewer, everything), env=None, kind=None, after=None, limit=500
    )
    assert {r.id for r in v.items} == {granted.id}
    with _c(pg_dsn) as c:  # grant deleted mid-run
        c.execute("DELETE FROM user_account_access WHERE user_id = %s", (str(mgr),))
    assert await store.get_account(forged, granted.id) is None
    # forged OwnerScope for a non-owner: forbidden-role case on every OwnerScope method, reads
    # included (uniform 403, decided by the caller alone)
    fake = OwnerScope(mgr)
    other = uuid.uuid4()
    smuggled = _new(exch)
    with pytest.raises(AccountsStoreScopeDeniedError):
        await store.get_account(fake, granted.id)
    with pytest.raises(AccountsStoreScopeDeniedError):
        await store.list_accounts(fake, env=None, kind=None, after=None, limit=500)
    with pytest.raises(AccountsStoreScopeDeniedError):
        await store.create_account(fake, smuggled)
    with pytest.raises(AccountsStoreScopeDeniedError):
        await store.update_account(fake, granted.id, ExchangeAccountPatch(label="h"), if_match=None)
    with pytest.raises(AccountsStoreScopeDeniedError):
        await store.soft_delete_account(fake, granted.id)
    with pytest.raises(AccountsStoreScopeDeniedError):
        await store.list_keys(fake, granted.id)
    with pytest.raises(AccountsStoreScopeDeniedError):
        await store.get_key(fake, granted.id, other)
    with pytest.raises(AccountsStoreScopeDeniedError):
        await store.list_rotations(fake, granted.id, limit=1)
    with pytest.raises(AccountsStoreScopeDeniedError):
        await store.get_rotation(fake, granted.id, other)
    with pytest.raises(AccountsStoreScopeDeniedError):
        await store.start_rotation(fake, NewKeyRotation(other, granted.id, other, other))
    with pytest.raises(AccountsStoreScopeDeniedError):
        await store.transition_key_status(fake, granted.id, other, expected="pending", new="active")
    with pytest.raises(AccountsStoreScopeDeniedError):
        await store.record_rotation_step(fake, granted.id, other, "failed", failure_reason="x")
    # row-level post-conditions: the refused writes changed nothing
    assert await store.get_account(owner, granted.id) == granted
    assert await store.get_account(owner, smuggled.id) is None


async def test_predicate_applies_before_limit_and_keyset_has_no_gaps(
    store: SqlAlchemyAccountsStore, pg_dsn: str
) -> None:
    exch = _exchange(pg_dsn)
    owner = OwnerScope(_user(pg_dsn, "owner"))
    made = [await store.create_account(owner, _new(exch, env="testnet")) for _ in range(5)]
    mgr = _user(pg_dsn, "manager")
    newest = made[-1]
    _grant(pg_dsn, mgr, newest.id, can_view=True, frozen=False)
    one = await store.list_accounts(
        GrantScope(mgr, frozenset({newest.id})), env="testnet", kind=None, after=None, limit=1
    )
    assert [r.id for r in one.items] == [newest.id]
    seen: list[uuid.UUID] = []
    after: AccountKey | None = None
    while True:
        page = await store.list_accounts(owner, env="testnet", kind="main", after=after, limit=2)
        seen += [r.id for r in page.items]
        after = page.next_after
        if after is None:
            break
    assert seen[-5:] == [m.id for m in made] and len(seen) == len(set(seen))


async def test_keys_metadata_status_and_cross_account(
    store: SqlAlchemyAccountsStore, creds: SqlAlchemyCredentialStore, pg_dsn: str
) -> None:
    exch, owner = _exchange(pg_dsn), OwnerScope(_user(pg_dsn, "owner"))
    a = await store.create_account(owner, _new(exch))
    b = await store.create_account(owner, _new(exch))
    k1 = await _seed_key(creds, a.id)
    k2 = await _seed_key(creds, a.id)
    revoked = await _seed_key(creds, a.id)
    await creds.mark_revoked(revoked)  # M2's revoke path, not a hand-written UPDATE
    got = await store.get_key(owner, a.id, k1)
    assert got is not None and got.key_id_last4 == "abcd" and got.status == "pending"
    assert got.permission_snapshot == _SNAPSHOT and not hasattr(got, "secret_enc")
    assert {k.id for k in await store.list_keys(owner, a.id)} == {k1, k2}
    gone = await store.get_key(owner, a.id, revoked)  # revoked stays visible by id
    assert gone is not None and gone.status == "revoked" and gone.revoked_at is not None
    assert await store.get_key(owner, b.id, k1) is None  # path IDOR: key of A under B
    act = await store.transition_key_status(owner, a.id, k1, expected="pending", new="active")
    assert act is not None and act.status == "active"
    with pytest.raises(AccountsStoreConflictError) as e:
        await store.transition_key_status(owner, a.id, k1, expected="pending", new="active")
    assert e.value.constraint == "key_status"
    with pytest.raises(AccountsStoreConflictError) as e2:
        await store.transition_key_status(owner, a.id, k2, expected="pending", new="active")
    assert e2.value.constraint == "ux_api_keys_active"
    assert (
        await store.transition_key_status(owner, a.id, revoked, expected="revoked", new="active")
        is None
    )
    assert (
        await store.transition_key_status(owner, b.id, k2, expected="pending", new="invalid")
        is None
    )
    victim = await store.get_key(owner, a.id, k2)  # the refused cross-account write changed nothing
    assert victim is not None and victim.status == "pending"
    with pytest.raises(ValueError):
        await store.transition_key_status(owner, a.id, k2, expected="pending", new="revoked")


async def test_rotation_lifecycle_and_scoping(
    store: SqlAlchemyAccountsStore, creds: SqlAlchemyCredentialStore, pg_dsn: str
) -> None:
    exch, owner = _exchange(pg_dsn), OwnerScope(_user(pg_dsn, "owner"))
    a = await store.create_account(owner, _new(exch))
    b = await store.create_account(owner, _new(exch))
    old, new = await _seed_key(creds, a.id), await _seed_key(creds, a.id)
    live = await store.transition_key_status(owner, a.id, old, expected="pending", new="active")
    assert live is not None and live.status == "active"
    rid = uuid.uuid4()
    started = await store.start_rotation(owner, NewKeyRotation(rid, a.id, old, new, 60))
    assert started is not None and started.grace_seconds == 60
    assert await store.get_rotation(owner, b.id, rid) is None  # rotation of A under B
    assert await store.start_rotation(owner, NewKeyRotation(uuid.uuid4(), b.id, old, new)) is None
    # a step through B is refused; the "validated" step below proves it changed nothing
    assert (
        await store.record_rotation_step(owner, b.id, rid, "validated", failure_reason=None) is None
    )
    assert [r.id for r in await store.list_rotations(owner, a.id, limit=10)] == [rid]
    with pytest.raises(AccountsStoreConflictError) as e:
        await store.record_rotation_step(owner, a.id, rid, "cutover", failure_reason=None)
    assert e.value.constraint == "rotation_state"
    steps: tuple[RotationStep, ...] = ("validated", "cutover", "completed")
    for step in steps:
        r = await store.record_rotation_step(owner, a.id, rid, step, failure_reason=None)
        assert r is not None
    assert r is not None and r.completed_at is not None
    with pytest.raises(AccountsStoreConflictError):
        await store.record_rotation_step(owner, a.id, rid, "failed", failure_reason="late")
    with pytest.raises(AccountsStoreRuleError) as e2:
        await store.start_rotation(owner, NewKeyRotation(uuid.uuid4(), a.id, old, old))
    assert e2.value.rule == "akr_distinct"
    assert isinstance(r.started_at, datetime)


def _delta(after: dict[str, int], before: dict[str, int]) -> dict[str, int]:
    return {
        k: after.get(k, 0) - before.get(k, 0)
        for k in after.keys() | before.keys()
        if after.get(k, 0) != before.get(k, 0)
    }


async def test_row_counts_are_env_scoped_live_accounts_and_every_key_row(
    store: SqlAlchemyAccountsStore, creds: SqlAlchemyCredentialStore, pg_dsn: str
) -> None:
    """#2314: the M13 row-gauge reads. Deltas, because the module shares one database."""
    exch, owner = _exchange(pg_dsn), OwnerScope(_user(pg_dsn, "owner"))
    demo_a = await store.count_accounts_by_kind("demo")
    test_a = await store.count_accounts_by_kind("testnet")
    demo_k = await store.count_api_keys_by_status("demo")
    test_k = await store.count_api_keys_by_status("testnet")
    demo_p = await store.count_profiles_by_trading_state("demo")
    test_p = await store.count_profiles_by_trading_state("testnet")
    main = await store.create_account(owner, _new(exch))
    sub = await store.create_account(owner, _new(exch, parent=main.id))
    gone = await store.create_account(owner, _new(exch))
    await store.create_account(owner, _new(exch, env="testnet"))
    active, revoked = await _seed_key(creds, main.id), await _seed_key(creds, main.id)
    await _seed_key(creds, gone.id)  # stays `pending` on an account soft-deleted below
    await store.transition_key_status(owner, main.id, active, expected="pending", new="active")
    await creds.mark_revoked(revoked)
    await store.soft_delete_account(owner, gone.id)
    assert _delta(await store.count_accounts_by_kind("demo"), demo_a) == {"main": 1, "sub": 1}
    assert _delta(await store.count_accounts_by_kind("testnet"), test_a) == {"main": 1}
    # every key row of the env's accounts counts, soft-deleted accounts included (21 §3.2)
    assert _delta(await store.count_api_keys_by_status("demo"), demo_k) == {
        "active": 1, "revoked": 1, "pending": 1,
    }  # fmt: skip
    assert _delta(await store.count_api_keys_by_status("testnet"), test_k) == {}
    # #906 D1a: each live account's bootstrap `Default` counts, trading disabled; the soft-deleted
    # account's does not, and the other environment's stays out of it
    demo = await store.count_profiles_by_trading_state("demo")
    assert _delta(demo, demo_p) == {"trading_disabled": 2}
    testnet = await store.count_profiles_by_trading_state("testnet")
    assert _delta(testnet, test_p) == {"trading_disabled": 1}
    with _c(pg_dsn) as c:  # one profile enabled for trading (0037 `ap_trading_caps`), one deleted
        c.execute(
            "UPDATE account_profiles SET trading_enabled = true, max_position_notional_usd = 1000, "
            "max_daily_loss_usd = 100, max_open_positions = 1, max_concurrent_orders = 1, "
            "max_leverage_cap = 10 WHERE exchange_account_id = %s",
            (main.id,),
        )
        c.execute(
            "UPDATE account_profiles SET deleted_at = now() WHERE exchange_account_id = %s",
            (sub.id,),
        )
    demo = await store.count_profiles_by_trading_state("demo")
    assert _delta(demo, demo_p) == {"trading_enabled": 1}  # sub's Default left both states
    with pytest.raises(ValueError):
        await store.count_accounts_by_kind("prod")
    with pytest.raises(ValueError):
        await store.count_profiles_by_trading_state("prod")


async def test_key_selfcheck_store_is_env_bound_and_writes_only_its_columns(
    store: SqlAlchemyAccountsStore,
    creds: SqlAlchemyCredentialStore,
    rel: SqlAlchemyRelationalRepository,
    pg_dsn: str,
) -> None:
    """E27-T03 (#836): the self-check's system store on M2's real rows (`cidr[]`, jsonb merge)."""
    exch, owner = _exchange(pg_dsn), OwnerScope(_user(pg_dsn, "owner"))
    acct = await store.create_account(owner, _new(exch))
    kid, gone = await _seed_key(creds, acct.id), await _seed_key(creds, acct.id)
    await store.transition_key_status(owner, acct.id, kid, expected="pending", new="active")
    await creds.mark_revoked(gone)
    with _c(pg_dsn) as c:
        c.execute("UPDATE exchange_accounts SET trading_enabled = true WHERE id = %s", (acct.id,))
        c.execute(  # a field the import stored and the check never reads
            "UPDATE api_keys SET permission_snapshot = permission_snapshot || %s::jsonb "
            "WHERE id = %s",
            ('{"type": "HMAC"}', kid),
        )
    demo, live = (SqlAlchemyKeySelfCheckStore(rel, env=env) for env in ("demo", "live"))
    assert kid not in {t.key_id for t in await live.targets()}
    [target] = [t for t in await demo.targets() if t.account.id == acct.id]  # one usable key
    assert (target.key_id, target.account.trading_enabled) == (kid, True)
    assert target.status == "active" and target.created_at is not None  # key age (#837)
    at, rights = datetime(2026, 10, 16, 9, tzinfo=UTC), {"ContractTrade": ["Order", "Position"]}
    facts = {"fetched_at": at.isoformat(), "uid": "1", "readOnly": 0, "permissions": rights}
    verified = VerifiedKey(facts, True, False, ("203.0.113.7",), None, at)
    assert await live.record_pass(kid, verified) is False
    assert await demo.record_pass(kid, verified) is True
    assert await demo.record_error(kid, code="10018", at=at) is True
    disarms = [await demo.disable_trading(acct.id, code="key_uid_mismatch", at=at) for _ in "ab"]
    assert disarms == [True, False]
    with _c(pg_dsn) as c:
        key = c.execute(
            "SELECT permission_snapshot, permission_snapshot_at, can_trade, ip_whitelist::text[], "
            "ip_whitelist_verified_at, last_error_code, last_error_at, status::text "
            "FROM api_keys WHERE id = %s",
            (kid,),
        ).fetchone()
        armed = c.execute(
            "SELECT trading_enabled FROM exchange_accounts WHERE id = %s", (acct.id,)
        ).fetchone()
    assert key is not None and key[0] == {**facts, "type": "HMAC"}  # merged, not replaced
    assert key[1:] == (at, True, ["203.0.113.7/32"], at, "10018", at, "active")
    assert armed == (False,)
    assert await demo.record_error(kid, code="key_expired", at=at) is True
    [failed] = [t for t in await demo.targets() if t.key_id == kid]
    expiry = at + timedelta(days=90)
    assert await demo.record_pass(kid, replace(verified, expires_at=expiry)) is True
    [passed] = [t for t in await demo.targets() if t.key_id == kid]  # a pass clears the rule code
    assert (failed.last_error_code, passed.last_error_code, passed.expires_at) == (
        "key_expired", None, expiry,
    )  # fmt: skip


async def test_a_pass_that_is_trade_and_read_only_leaves_without_the_key_row(
    rel: SqlAlchemyRelationalRepository,
    store: SqlAlchemyAccountsStore,
    creds: SqlAlchemyCredentialStore,
    pg_dsn: str,
) -> None:
    """`ak_readonly_excl`: its DETAIL quotes the whole `api_keys` row, ciphertexts and all."""
    exch, owner = _exchange(pg_dsn), OwnerScope(_user(pg_dsn, "owner"))
    kid = await _seed_key(creds, (await store.create_account(owner, _new(exch))).id)
    verified = VerifiedKey({"uid": "1", "permissions": {}}, True, True, (_IP,), None, _FROZEN_AT)
    with server_text(rel) as seen, pytest.raises(sa.exc.IntegrityError) as err:
        await SqlAlchemyKeySelfCheckStore(rel, env="demo").record_pass(kid, verified)
    assert (sqlstate_of(err.value), constraint_of(err.value)) == ("23514", "ak_readonly_excl")
    assert (err.value.__cause__, err.value.__suppress_context__) == _TYPED
    assert_no_row_values(err.value, seen, _IP, _KEY_ID_ENC, _SECRET_ENC, _NONCE, _SEED_DEK)


async def test_a_disarm_commits_its_code_and_time_and_stays_owed_until_its_record_is_marked(
    store: SqlAlchemyAccountsStore, rel: SqlAlchemyRelationalRepository, pg_dsn: str
) -> None:
    """#836 slice 2d: the boot re-send reads what the disarm wrote, on its environment only,
    a soft-deleted account included, until the record is marked once."""
    exch, owner = _exchange(pg_dsn), OwnerScope(_user(pg_dsn, "owner"))
    acct = await store.create_account(owner, _new(exch))
    with _c(pg_dsn) as c:
        c.execute("UPDATE exchange_accounts SET trading_enabled = true WHERE id = %s", (acct.id,))
    demo, live = (SqlAlchemyKeySelfCheckStore(rel, env=env) for env in ("demo", "live"))
    at = datetime(2026, 10, 18, 9, 0, 0, 123456, tzinfo=UTC)
    later, rule = datetime(2026, 10, 18, 10, tzinfo=UTC), "key_withdraw_permission"
    assert await live.disable_trading(acct.id, code=rule, at=at) is False
    assert await demo.disable_trading(acct.id, code=rule, at=at) is True
    assert await demo.disable_trading(acct.id, code="key_uid_mismatch", at=later) is False
    owed = PolicyDisarm(acct.id, rule, at)
    assert owed in await demo.owed_disarms() and owed not in await live.owed_disarms()
    assert await store.soft_delete_account(owner, acct.id) is True
    assert owed in await demo.owed_disarms()  # the disarm happened: its record is still owed
    other = PolicyDisarm(acct.id, rule, later)  # a disarm that is not the stored one
    assert [await s.mark_disarm_audited(d, at=later) for s, d in ((demo, other), (live, owed))] == [
        False, False,
    ]  # fmt: skip
    assert [await demo.mark_disarm_audited(owed, at=later) for _ in "ab"] == [True, False]
    assert owed not in await demo.owed_disarms()
    with _c(pg_dsn) as c:
        row = c.execute(
            "SELECT trading_enabled, policy_disarm_code, policy_disarmed_at, "
            "policy_disarm_audited_at FROM exchange_accounts WHERE id = %s",
            (acct.id,),
        ).fetchone()
    assert row == (False, rule, at, later)


async def _subs(store: SqlAlchemyAccountsStore, owner: OwnerScope, exch: str, parent: uuid.UUID,
                n: int) -> list[uuid.UUID]:  # fmt: skip
    return [(await store.create_account(owner, _new(exch, parent=parent))).id for _ in range(n)]


async def test_the_sixth_live_sub_under_one_parent_is_a_conflict_and_is_not_stored(
    store: SqlAlchemyAccountsStore, pg_dsn: str
) -> None:
    """#895, 22 createExchangeAccount: the 5th sub is admitted, the 6th refused with the cap's
    conflict; a soft-deleted sub, another parent's subs and a main account are not counted."""
    exch, owner = _exchange(pg_dsn), OwnerScope(_user(pg_dsn, "owner"))
    parent = await store.create_account(owner, _new(exch))
    other = await store.create_account(owner, _new(exch))
    await _subs(store, owner, exch, other.id, 5)  # another parent's subs
    subs = await _subs(store, owner, exch, parent.id, 5)  # the 5th is admitted
    sixth = _new(exch, parent=parent.id)
    with pytest.raises(AccountsStoreConflictError) as ei:
        await store.create_account(owner, sixth)
    assert ei.value.constraint == SUB_ACCOUNT_CAP_CONFLICT
    assert (ei.value.__cause__, ei.value.__suppress_context__) == _TYPED
    assert await store.get_account(owner, sixth.id) is None
    await store.create_account(owner, _new(exch))  # a main account is not capped
    assert await store.soft_delete_account(owner, subs[0]) is True
    assert (await store.create_account(owner, sixth)).id == sixth.id  # the deleted one freed a slot


async def test_a_recorded_business_kyc_tier_widens_the_cap_to_twenty(
    store: SqlAlchemyAccountsStore, pg_dsn: str
) -> None:
    exch, owner = _exchange(pg_dsn), OwnerScope(_user(pg_dsn, "owner"))
    parent = await store.create_account(owner, _new(exch))
    with _c(pg_dsn) as c:
        c.execute(
            "INSERT INTO settings (id, scope, key, value, value_type) VALUES "
            "(%s, 'system', 'accounts.subaccount_tier', to_jsonb('business_kyc'::text), 'string')",
            (str(uuid.uuid4()),),
        )
    try:
        await _subs(store, owner, exch, parent.id, 20)
        with pytest.raises(AccountsStoreConflictError):
            await store.create_account(owner, _new(exch, parent=parent.id))
    finally:
        with _c(pg_dsn) as c:
            c.execute(
                "DELETE FROM settings WHERE scope = 'system' AND key = 'accounts.subaccount_tier'"
            )


async def test_two_concurrent_creates_for_the_last_slot_admit_exactly_one(
    store: SqlAlchemyAccountsStore, pg_dsn: str
) -> None:
    """`FOR NO KEY UPDATE` on the parent serialises them: the later count sees the first commit."""
    exch, owner = _exchange(pg_dsn), OwnerScope(_user(pg_dsn, "owner"))
    parent = await store.create_account(owner, _new(exch))
    await _subs(store, owner, exch, parent.id, 4)
    got = await asyncio.gather(
        *(store.create_account(owner, _new(exch, parent=parent.id)) for _ in "ab"),
        return_exceptions=True,
    )
    refused = [g for g in got if isinstance(g, AccountsStoreConflictError)]
    assert len(refused) == 1 and refused[0].constraint == SUB_ACCOUNT_CAP_CONFLICT
    with _c(pg_dsn) as c:
        row = c.execute(
            "SELECT count(*) FROM exchange_accounts WHERE parent_account_id = %s "
            "AND deleted_at IS NULL",
            (parent.id,),
        ).fetchone()
    assert row == (5,)


async def test_list_grantees_lists_live_and_frozen_grants_of_live_users_owner_only(
    store: SqlAlchemyAccountsStore, pg_dsn: str
) -> None:
    """#898 B2b `assigned_users` (ruling 9): a frozen grant is listed, a soft-revoked one
    (`can_view` false) and a deleted user's are not; by username; behind the owner gate."""
    exch, owner = _exchange(pg_dsn), OwnerScope(_user(pg_dsn, "owner"))
    acct = await store.create_account(owner, _new(exch))
    other = await store.create_account(owner, _new(exch))
    live, frozen, revoked, deleted = (_user(pg_dsn, "manager") for _ in range(4))
    _grant(pg_dsn, live, acct.id, can_view=True, frozen=False)
    _grant(pg_dsn, frozen, acct.id, can_view=True, frozen=True)
    _grant(pg_dsn, revoked, acct.id, can_view=False, frozen=False)
    _grant(pg_dsn, deleted, acct.id, can_view=True, frozen=False)
    _grant(pg_dsn, revoked, other.id, can_view=True, frozen=False)
    with _c(pg_dsn) as c:
        c.execute("UPDATE user_account_access SET can_trade = true WHERE user_id = %s", (live,))
        c.execute("UPDATE users SET deleted_at = now() WHERE id = %s", (deleted,))
    got = await store.list_grantees(owner, acct.id)
    assert {(g.user_id, g.can_trade) for g in got} == {(live, True), (frozen, False)}
    assert [g.username for g in got] == sorted(g.username for g in got)
    assert await store.list_grantees(owner, uuid.uuid4()) == ()
    with pytest.raises(AccountsStoreScopeDeniedError):
        await store.list_grantees(OwnerScope(live), acct.id)  # a manager is not a live owner
    with pytest.raises(AccountsStoreScopeDeniedError):
        await store.list_grantees(GrantScope(live, frozenset({acct.id})), acct.id)  # type: ignore[arg-type]


async def test_list_grantees_reads_one_past_the_summarys_listing(
    store: SqlAlchemyAccountsStore, pg_dsn: str
) -> None:
    """#898 B2b: the statement returns the 501st grantee, so the read can fail closed on it."""
    exch, owner = _exchange(pg_dsn), OwnerScope(_user(pg_dsn, "owner"))
    acct = await store.create_account(owner, _new(exch))
    users = [uuid.uuid4() for _ in range(GRANTEES_LISTED + 2)]
    with _c(pg_dsn) as c, c.cursor() as cur:
        cur.executemany(
            "INSERT INTO users (id, email, username, display_name, password_hash, status) "
            "VALUES (%s, %s, %s, 'u', '$argon2id$x', 'active')",
            [(str(u), f"{u}@example.test", f"g{u.hex[:12]}") for u in users],
        )
        cur.executemany(
            "INSERT INTO user_account_access (user_id, exchange_account_id, can_view) "
            "VALUES (%s, %s, true)",
            [(str(u), str(acct.id)) for u in users],
        )
    assert len(await store.list_grantees(owner, acct.id)) == GRANTEES_LISTED + 1


class _NoExposure:
    """The exposure read and the other ports, answered at once: only the store is timed."""

    async def read(
        self, account: ExchangeAccount, keys: object, *, within_s: float | None = None
    ) -> ExposureOutcome:
        return ExposureUnknown("leave_positions", ())

    async def armed_on(self, account_id: uuid.UUID) -> tuple[ArmedRule, ...]:
        return ()

    async def covering(self, account_id: uuid.UUID, *, limit: int) -> tuple[ArmedRule, ...]:
        return ()

    async def running(self, account_id: uuid.UUID) -> int:
        return 0


#: Fable M1: a grantee statement that outlasts the 0.25 s store bound eightfold.
_SLOW_GRANTEES = sa.text(
    "SELECT NULL::text AS user_id, NULL::text AS username, false AS can_trade "
    "FROM pg_sleep(2) WHERE CAST(:account AS uuid) IS NOT NULL"
)


async def test_a_slow_grantee_read_fails_closed_at_its_bound_and_the_pool_stays_healthy(
    store: SqlAlchemyAccountsStore, pg_dsn: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """#898 B2b, Fable M1: the 0.25 s bound cancels a running statement on a live connection;
    `StoreReadFailed` arrives well before the statement would end, and the next read on the
    same store and pool succeeds."""
    exch, owner = _exchange(pg_dsn), OwnerScope(_user(pg_dsn, "owner"))
    acct = await store.create_account(owner, _new(exch))
    user = _user(pg_dsn, "manager")
    _grant(pg_dsn, user, acct.id, can_view=True, frozen=False)
    ports = _NoExposure()
    read = ConsequenceRead(AccountsRepository(store), ports, ports, ports, env="demo")
    assert await store.list_grantees(owner, acct.id)  # the pool is warm
    monkeypatch.setattr(store_sql, "_LIST_GRANTEES", _SLOW_GRANTEES)
    started = time.monotonic()
    with pytest.raises(StoreReadFailed):
        await read.read(owner, owner, acct.id)
    assert time.monotonic() - started < 0.5
    monkeypatch.undo()
    got = await store.list_grantees(owner, acct.id)
    assert [g.user_id for g in got] == [user]


async def test_the_grantee_read_ends_on_the_server_at_250_ms_without_a_caller_bound(
    store: SqlAlchemyAccountsStore, pg_dsn: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The server-side cap alone (no caller bound): Postgres cancels the statement (57014)."""
    exch, owner = _exchange(pg_dsn), OwnerScope(_user(pg_dsn, "owner"))
    acct = await store.create_account(owner, _new(exch))
    monkeypatch.setattr(store_sql, "_LIST_GRANTEES", _SLOW_GRANTEES)
    started = time.monotonic()
    with pytest.raises(Exception) as raised:
        await store.list_grantees(owner, acct.id)
    assert time.monotonic() - started < 1.0  # the statement sleeps 2 s
    assert sqlstate_of(raised.value) == "57014"
    monkeypatch.undo()
    assert await store.list_grantees(owner, acct.id) == ()


# -- #898 B3b2: the patch's write-ahead and its compare-and-set on `is_enabled` ------------------


async def test_a_refused_write_ahead_rolls_the_disable_back(
    store: SqlAlchemyAccountsStore, pg_dsn: str
) -> None:
    owner = OwnerScope(_user(pg_dsn, "owner"))
    acct = await store.create_account(owner, _new(_exchange(pg_dsn)))
    seen: list[bool] = []

    async def refused(row: ExchangeAccountRow) -> None:
        seen.append(row.is_enabled)
        raise RuntimeError("the audit writer refused")

    with pytest.raises(RuntimeError):
        await store.update_account(
            owner,
            acct.id,
            ExchangeAccountPatch(is_enabled=False),
            if_match=None,
            expect_enabled=True,
            write_ahead=refused,
        )
    assert seen == [False]  # the hook saw the written row, inside its transaction
    assert await store.get_account(owner, acct.id) == acct  # rolled back


async def test_a_stale_tag_is_412_and_a_missed_enabled_flag_a_repeat(
    store: SqlAlchemyAccountsStore, pg_dsn: str
) -> None:
    owner = OwnerScope(_user(pg_dsn, "owner"))
    acct = await store.create_account(owner, _new(_exchange(pg_dsn)))
    off = ExchangeAccountPatch(is_enabled=False)
    done = await store.update_account(owner, acct.id, off, if_match=None, expect_enabled=True)
    assert done is not None and done.is_enabled is False
    with pytest.raises(AccountsStoreStaleError):  # the tag the caller read moved
        await store.update_account(
            owner, acct.id, off, if_match=acct.updated_at, expect_enabled=True
        )
    with pytest.raises(AccountsStoreUnchangedError):  # no tag: the disable is a repeat
        await store.update_account(owner, acct.id, off, if_match=None, expect_enabled=True)
    with pytest.raises(AccountsStoreUnchangedError):  # the current tag: still a repeat
        await store.update_account(
            owner, acct.id, off, if_match=done.updated_at, expect_enabled=True
        )


def _waiting_on_a_lock(dsn: str) -> bool:
    with _c(dsn) as conn:
        row = conn.execute(
            "SELECT count(*) FROM pg_stat_activity WHERE wait_event_type = 'Lock'"
        ).fetchone()
    return row is not None and int(str(row[0])) > 0


async def test_two_racing_disables_store_once_and_write_one_record(
    rel: SqlAlchemyRelationalRepository, pg_dsn: str
) -> None:
    """Ruling 6: the second blocks on the row lock, sees the account disabled and is a repeat."""
    owner = OwnerScope(_user(pg_dsn, "owner"))
    first, second = SqlAlchemyAccountsStore(rel), SqlAlchemyAccountsStore(rel)
    acct = await first.create_account(owner, _new(_exchange(pg_dsn)))
    records: list[str] = []
    held = asyncio.Event()
    go = asyncio.Event()

    async def slow(row: ExchangeAccountRow) -> None:
        records.append("first")
        held.set()
        await go.wait()  # the first holds the row lock inside its transaction

    async def fast(row: ExchangeAccountRow) -> None:
        records.append("second")

    off = ExchangeAccountPatch(is_enabled=False)
    one = asyncio.create_task(
        first.update_account(
            owner, acct.id, off, if_match=None, expect_enabled=True, write_ahead=slow
        )
    )
    await held.wait()
    two = asyncio.create_task(
        second.update_account(
            owner, acct.id, off, if_match=None, expect_enabled=True, write_ahead=fast
        )
    )
    async with asyncio.timeout(10):  # an event waiter on the server's own view, no sleep
        while not await asyncio.to_thread(_waiting_on_a_lock, pg_dsn):  # noqa: ASYNC110 - polls the server's lock view, bounded above
            await asyncio.sleep(0)
    go.set()
    assert (await one) is not None
    with pytest.raises(AccountsStoreUnchangedError):
        await two
    assert records == ["first"]


# -- #898 B3c: the delete's soft delete switches the account off and keeps its history ---------


async def test_the_soft_delete_switches_the_account_off_and_its_history_survives(
    store: SqlAlchemyAccountsStore, rel: SqlAlchemyRelationalRepository, pg_dsn: str
) -> None:
    """`_SOFT_DELETE` sets `deleted_at` and `is_enabled = false` (22: "marks it `disabled`") with
    `trading_enabled`; the account's executions and the audit records naming it are untouched
    (the ticket's "Historical records survive"), and a read of the account no longer finds it."""
    owner = OwnerScope(_user(pg_dsn, "owner"))
    acct = await store.create_account(owner, _new(_exchange(pg_dsn)))
    exec_id = uuid.uuid4()
    with _c(pg_dsn) as c:
        c.execute(
            "INSERT INTO executions (id, exchange_account_id, exec_id, symbol, side, exec_qty, "
            "exec_price, exec_value, exec_type, is_maker, exec_ts) VALUES (%s, %s, 'E1', "
            "'BTCUSDT', 'Buy', 1, 60000, 60000, 'Trade', false, now())",
            (str(exec_id), str(acct.id)),
        )
    record = {
        "record_id": str(uuid.uuid4()), "actor_label": "owner", "action": "account.deleted",
        "object_kind": "exchange_account", "object_id": str(acct.id), "outcome": "success",
        "severity": "warning", "event_ts": datetime.now(UTC).isoformat(),
    }  # fmt: skip
    async with rel.unit_of_work() as uow:
        assert await insert_audit_row_locked(uow.session, record)
        await uow.commit()
    assert await store.soft_delete_account(owner, acct.id) is True
    with _c(pg_dsn) as c:
        flags = c.execute(
            "SELECT is_enabled, trading_enabled, deleted_at IS NOT NULL FROM exchange_accounts "
            "WHERE id = %s",
            (str(acct.id),),
        ).fetchone()
        executions = c.execute(
            "SELECT count(*) FROM executions WHERE exchange_account_id = %s", (str(acct.id),)
        ).fetchone()
        audited = c.execute(
            "SELECT count(*) FROM audit_log WHERE object_id = %s", (str(acct.id),)
        ).fetchone()
    assert flags == (False, False, True)
    assert executions == (1,) and audited == (1,)
    assert await store.get_account(owner, acct.id) is None

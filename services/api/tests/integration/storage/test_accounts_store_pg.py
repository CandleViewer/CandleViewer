"""Integration: `SqlAlchemyAccountsStore` on real Postgres 16 (E27-T01, migrations 0017/0019).

CI-only (testcontainers; no docker socket locally) - NOT run by the author. Keys are written by
M2's real writer, `SqlAlchemyCredentialStore.insert`, from M2's own `CredentialRow` record with
fixed fake bytes (no KEK, no plaintext), and revoked through its `mark_revoked`. So the accounts
store is proven to read exactly the rows M2 writes and to honour M2's revocation.
"""

from __future__ import annotations

import os
import subprocess
import sys
import uuid
from collections.abc import AsyncIterator, Iterator
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import psycopg
import pytest
import pytest_asyncio
from testcontainers.postgres import PostgresContainer

from candleviewer.secrets.models import CredentialRow
from candleviewer.storage.repositories.accounts import (
    AccountKey,
    AccountsStoreConflictError,
    AccountsStoreRuleError,
    AccountsStoreScopeDeniedError,
    AccountsStoreStaleError,
    ExchangeAccountPatch,
    GrantScope,
    NewExchangeAccount,
    NewKeyRotation,
    OwnerScope,
    PolicyDisarm,
    RotationStep,
    VerifiedKey,
)
from candleviewer.storage.repositories.accounts_sqlalchemy import SqlAlchemyAccountsStore
from candleviewer.storage.repositories.credentials_sqlalchemy import SqlAlchemyCredentialStore
from candleviewer.storage.repositories.key_selfcheck_sqlalchemy import SqlAlchemyKeySelfCheckStore
from candleviewer.storage.repositories.relational_sqlalchemy import (
    SqlAlchemyRelationalRepository,
)

pytestmark = pytest.mark.integration

_ROOT = Path(__file__).resolve().parents[3]
_FROZEN_AT = datetime(2026, 10, 1, tzinfo=UTC)
_SNAPSHOT: dict[str, object] = {
    "fetched_at": "2026-10-01T00:00:00+00:00",
    "uid": "1",
    "permissions": {},
}


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
    exch: str, *, env: str = "demo", label: str | None = None, parent: uuid.UUID | None = None
) -> NewExchangeAccount:
    return NewExchangeAccount(
        uuid.uuid4(), exch, env, "sub" if parent else "main", _uid(),
        label or f"L{uuid.uuid4().hex[:8]}", parent,
    )  # fmt: skip


async def _seed_key(creds: SqlAlchemyCredentialStore, acct: uuid.UUID) -> uuid.UUID:
    """A `pending` key on a demo account, written by M2's own writer and record type."""
    kid = uuid.uuid4()
    row = CredentialRow(
        id=kid, exchange_account_id=acct, env="demo", label=f"k{kid.hex[:8]}",
        key_id_enc=b"\x01" * 28, key_id_last4="abcd", secret_enc=b"\x02" * 28,
        enc_nonce=b"\x03" * 12, dek_ref="v1:00", kek_version=1,
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


async def test_constraint_mapping(store: SqlAlchemyAccountsStore, pg_dsn: str) -> None:
    exch, owner = _exchange(pg_dsn), OwnerScope(_user(pg_dsn, "owner"))
    a = await store.create_account(owner, _new(exch, label="Dup"))
    with pytest.raises(AccountsStoreConflictError) as ei:
        await store.create_account(owner, _new(exch, label="dUP"))
    assert ei.value.constraint == "ux_ea_label"
    same_uid = NewExchangeAccount(uuid.uuid4(), exch, "demo", "main", a.exchange_uid, "other")
    with pytest.raises(AccountsStoreConflictError) as ei2:
        await store.create_account(owner, same_uid)
    assert ei2.value.constraint == "ux_ea_uid"
    bad_uid = NewExchangeAccount(uuid.uuid4(), exch, "demo", "main", "abc", "q1")
    with pytest.raises(AccountsStoreRuleError) as ei3:
        await store.create_account(owner, bad_uid)
    assert ei3.value.rule == "ea_uid_fmt"
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
    main = await store.create_account(owner, _new(exch))
    await store.create_account(owner, _new(exch, parent=main.id))
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
    with pytest.raises(ValueError):
        await store.count_accounts_by_kind("prod")


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

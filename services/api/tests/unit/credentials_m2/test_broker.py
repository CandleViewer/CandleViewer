"""E27-T02 credential broker: round-trip, DB-dump-alone, tamper, wrong KEK, rewrap, audit."""

from __future__ import annotations

import gc
from typing import Any
from uuid import uuid4

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from candleviewer.secrets import _envelope as env
from candleviewer.secrets.broker import CredentialBroker, reject_withdraw
from candleviewer.secrets.errors import (
    CredentialUnavailable,
    KekUnavailable,
    WithdrawPermissionRejected,
)
from candleviewer.secrets.secret import Secret
from candleviewer.secrets.store import InMemoryCredentialStore
from tests.unit.credentials_m2.conftest import (
    ACCOUNT,
    API_KEY,
    API_SECRET,
    KEK_V1,
    KEK_V2,
    SNAPSHOT,
    AuditLog,
    FakeClock,
    kek,
)


async def _store(b: CredentialBroker, key: str = API_KEY, secret: str = API_SECRET) -> Any:
    return await b.store(ACCOUNT, "main", Secret(key), Secret(secret), SNAPSHOT)


async def _borrow(b: CredentialBroker, key_id: Any) -> tuple[str, str]:
    async def fn(k: Secret[str], s: Secret[str]) -> tuple[str, str]:
        return k.reveal(), s.reveal()

    return await b.with_credentials(key_id, fn, caller_module="exchange_adapter", purpose="sign")


async def test_broker_round_trip_returns_stored_plaintext(broker: CredentialBroker) -> None:
    meta = await _store(broker)
    assert meta.key_id_last4 == "WXYZ" and meta.kek_version == 1
    assert await _borrow(broker, meta.key_id) == (API_KEY, API_SECRET)


async def test_broker_row_holds_no_plaintext(broker: CredentialBroker, store: Any) -> None:
    meta = await _store(broker)
    row = store.rows[meta.key_id]
    blob = repr(row).encode() + row["key_id_enc"] + row["secret_enc"]
    assert API_KEY.encode() not in blob and API_SECRET.encode() not in blob
    assert len(row["enc_nonce"]) == 12 and row["enc_alg"] == "AES-256-GCM"


async def test_broker_holds_no_reference_after_callback(broker: CredentialBroker) -> None:
    meta = await _store(broker)
    seen: list[int] = []

    async def fn(k: Secret[str], s: Secret[str]) -> None:
        seen.extend([id(k), id(s)])

    await broker.with_credentials(meta.key_id, fn, caller_module="t", purpose="p")
    gc.collect()
    live = {id(o) for o in gc.get_objects() if isinstance(o, Secret)}
    assert seen and not live.intersection(seen)


async def test_broker_dump_without_kek_cannot_decrypt(broker: CredentialBroker, store: Any) -> None:
    meta = await _store(broker)
    dump = InMemoryCredentialStore()
    dump.rows = {k: dict(v) for k, v in store.rows.items()}
    no_kek = CredentialBroker(dump, AuditLog(), None)
    with pytest.raises(KekUnavailable):
        await _borrow(no_kek, meta.key_id)
    wrong = CredentialBroker(dump, AuditLog(), kek(bytes(32)))
    with pytest.raises(CredentialUnavailable):
        await _borrow(wrong, meta.key_id)


async def test_broker_wrong_kek_material_fails_tag_check(store: Any, audit: AuditLog) -> None:
    b1 = CredentialBroker(store, audit, kek(KEK_V1, 1))
    meta = await _store(b1)
    b2 = CredentialBroker(store, audit, kek(KEK_V2, 1), dek_cache_ttl_s=0)
    with pytest.raises(CredentialUnavailable) as ei:
        await _borrow(b2, meta.key_id)
    assert API_KEY not in str(ei.value) and "credential_unavailable" in str(ei.value)


async def test_broker_version_mismatch_fails(store: Any, audit: AuditLog) -> None:
    meta = await _store(CredentialBroker(store, audit, kek(KEK_V1, 1)))
    with pytest.raises(CredentialUnavailable):
        await _borrow(CredentialBroker(store, audit, kek(KEK_V2, 2)), meta.key_id)


@pytest.mark.parametrize("field", ["key_id_enc", "secret_enc", "enc_nonce", "dek_ref"])
async def test_broker_tampered_field_is_rejected(
    broker: CredentialBroker, store: Any, field: str
) -> None:
    meta = await _store(broker)
    broker.flush_cache()
    row = store.rows[meta.key_id]
    if field == "dek_ref":
        h = row[field]
        row[field] = h[:-1] + ("0" if h[-1] != "0" else "1")
    else:
        b = bytearray(row[field])
        b[-1] ^= 1
        row[field] = bytes(b)
    with pytest.raises(CredentialUnavailable):
        await _borrow(broker, meta.key_id)


async def test_broker_swapped_dek_between_rows_is_rejected(
    broker: CredentialBroker, store: Any
) -> None:
    a, b = await _store(broker), await _store(broker, "OTHERKEY0000QQQQ")
    broker.flush_cache()
    store.rows[a.key_id]["dek_ref"] = store.rows[b.key_id]["dek_ref"]
    with pytest.raises(CredentialUnavailable):
        await _borrow(broker, a.key_id)


async def test_broker_bad_dek_ref_prefix_is_rejected(broker: CredentialBroker, store: Any) -> None:
    meta = await _store(broker)
    broker.flush_cache()
    store.rows[meta.key_id]["dek_ref"] = "v9:00"
    with pytest.raises(CredentialUnavailable):
        await _borrow(broker, meta.key_id)


@settings(max_examples=40, deadline=None)
@given(key=st.text(alphabet="ABCDEFGHJKLMNPQRSTUVWXYZ0123456789", min_size=4, max_size=36),
       secret=st.text(min_size=1, max_size=64))  # fmt: skip
async def test_broker_round_trip_property(key: str, secret: str) -> None:
    b = CredentialBroker(InMemoryCredentialStore(), AuditLog(), kek())
    meta = await _store(b, key, secret)
    assert await _borrow(b, meta.key_id) == (key, secret)


@settings(max_examples=60, deadline=None)
@given(pos=st.integers(min_value=0, max_value=10_000), bit=st.integers(min_value=0, max_value=7),
       which=st.sampled_from(["key_id_enc", "secret_enc"]))  # fmt: skip
async def test_broker_any_bitflip_is_rejected_property(pos: int, bit: int, which: str) -> None:
    s = InMemoryCredentialStore()
    b = CredentialBroker(s, AuditLog(), kek(), dek_cache_ttl_s=0)
    meta = await _store(b)
    blob = bytearray(s.rows[meta.key_id][which])
    blob[pos % len(blob)] ^= 1 << bit
    s.rows[meta.key_id][which] = bytes(blob)
    with pytest.raises(CredentialUnavailable):
        await _borrow(b, meta.key_id)


def test_envelope_nonce_unique_across_1e5() -> None:
    seen = {env.new_nonce() for _ in range(100_000)}
    assert len(seen) == 100_000


async def test_broker_each_encryption_gets_fresh_nonce(
    broker: CredentialBroker, store: Any
) -> None:
    a, b = await _store(broker), await _store(broker)
    ra, rb = store.rows[a.key_id], store.rows[b.key_id]
    nonces = {ra["enc_nonce"], rb["enc_nonce"], ra["key_id_enc"][:12], rb["key_id_enc"][:12]}
    assert len(nonces) == 4


@pytest.mark.parametrize("perm", ["Withdraw", "withdraw", "WITHDRAW", "Withdraw ", "subWithdrawX"])
async def test_broker_withdraw_permission_rejected(
    broker: CredentialBroker, perm: str, store: Any
) -> None:
    snap = {"uid": "1", "permissions": {perm: ["Withdraw"]}}
    with pytest.raises(WithdrawPermissionRejected):
        await broker.store(ACCOUNT, "x", Secret(API_KEY), Secret(API_SECRET), snap)
    assert not store.rows


def test_reject_withdraw_allows_empty_list() -> None:
    reject_withdraw({"Withdraw": [], "ContractTrade": ["Order"]})


async def test_broker_snapshot_without_permissions_rejected(broker: CredentialBroker) -> None:
    with pytest.raises(WithdrawPermissionRejected):
        await broker.store(ACCOUNT, "x", Secret(API_KEY), Secret(API_SECRET), {"uid": "1"})


@pytest.mark.parametrize("bad", ["ab", "abc-", "ab cd"])
async def test_broker_rejects_bad_key_shape(broker: CredentialBroker, bad: str) -> None:
    with pytest.raises(CredentialUnavailable):
        await _store(broker, bad)


async def test_broker_audits_store_borrow_destroy(
    broker: CredentialBroker, audit: AuditLog
) -> None:
    meta = await _store(broker)
    await _borrow(broker, meta.key_id)
    await broker.destroy(meta.key_id)
    assert audit.actions() == [
        "security.credential_stored",
        "security.credential_borrowed",
        "security.credential_destroyed",
    ]
    borrowed = audit.records[1][1]
    assert borrowed["caller_module"] == "exchange_adapter" and borrowed["purpose"] == "sign"
    for _, fields in audit.records:
        assert API_KEY not in str(fields) and API_SECRET not in str(fields)


async def test_broker_audit_failure_refuses_action(
    broker: CredentialBroker, audit: AuditLog, store: Any
) -> None:
    meta = await _store(broker)
    audit.fail = True
    with pytest.raises(RuntimeError):
        await _borrow(broker, meta.key_id)
    with pytest.raises(RuntimeError):
        await _store(broker)
    assert len(store.rows) == 1


async def test_broker_destroyed_key_cannot_be_borrowed(broker: CredentialBroker) -> None:
    meta = await _store(broker)
    await broker.destroy(meta.key_id)
    with pytest.raises(CredentialUnavailable):
        await _borrow(broker, meta.key_id)


async def test_broker_destroy_unknown_key_audits(broker: CredentialBroker, audit: AuditLog) -> None:
    await broker.destroy(uuid4())
    assert audit.actions() == ["security.credential_destroyed"]


async def test_broker_unknown_key_unavailable(broker: CredentialBroker) -> None:
    with pytest.raises(CredentialUnavailable):
        await _borrow(broker, uuid4())


async def test_dek_cache_hit_ttl_and_flush(store: Any, audit: AuditLog, clock: FakeClock) -> None:
    b = CredentialBroker(store, audit, kek(), clock=clock, dek_cache_ttl_s=300)
    meta = await _store(b)
    await _borrow(b, meta.key_id)
    assert len(b._cache) == 1
    clock.t = 299
    store.rows[meta.key_id]["dek_ref"] = "v1:00"  # cache hit bypasses the wrapped DEK
    assert await _borrow(b, meta.key_id) == (API_KEY, API_SECRET)
    clock.t = 301
    with pytest.raises(CredentialUnavailable):
        await _borrow(b, meta.key_id)
    assert len(b._cache) == 0


async def test_dek_cache_flushed_on_destroy(broker: CredentialBroker) -> None:
    meta = await _store(broker)
    await _borrow(broker, meta.key_id)
    await broker.destroy(meta.key_id)
    assert len(broker._cache) == 0


async def test_drop_kek_fails_closed(broker: CredentialBroker) -> None:
    meta = await _store(broker)
    await _borrow(broker, meta.key_id)
    broker.drop_kek()
    assert len(broker._cache) == 0
    with pytest.raises(KekUnavailable):
        await _borrow(broker, meta.key_id)


async def _seed(n: int) -> tuple[InMemoryCredentialStore, list[Any], dict[Any, bytes]]:
    s = InMemoryCredentialStore()
    b = CredentialBroker(s, AuditLog(), kek(KEK_V1, 1))
    metas = [await _store(b, f"KEY{i:04d}ABCDEFGH") for i in range(n)]
    return s, metas, {m.key_id: s.rows[m.key_id]["secret_enc"] for m in metas}


async def test_rewrap_all_keeps_ciphertext_and_bumps_version() -> None:
    s, metas, before = await _seed(20)
    old_refs = {k: s.rows[k]["dek_ref"] for k in before}
    audit = AuditLog()
    b2 = CredentialBroker(s, audit, kek(KEK_V2, 2), prev_kek=kek(KEK_V1, 1))
    rep = await b2.rewrap_all(2, batch=7)
    assert (rep.rewrapped, rep.remaining) == (20, 0)
    for m in metas:
        row = s.rows[m.key_id]
        assert row["kek_version"] == 2 and row["secret_enc"] == before[m.key_id]
        assert row["dek_ref"] != old_refs[m.key_id]
    only_v2 = CredentialBroker(s, AuditLog(), kek(KEK_V2, 2))
    for i, m in enumerate(metas):
        assert (await _borrow(only_v2, m.key_id))[0] == f"KEY{i:04d}ABCDEFGH"
    assert audit.actions() == ["security.kek_rotation_started", "security.kek_rotated"]
    assert (await b2.rewrap_all(2)).rewrapped == 0  # idempotent


async def test_rewrap_all_resumes_after_kill() -> None:
    s, metas, _ = await _seed(20)

    class Killed(Exception):
        pass

    calls = 0
    real = s.rewrap

    async def dying(key_id: Any, **kw: Any) -> bool:
        nonlocal calls
        if calls == 8:
            raise Killed
        calls += 1
        return await real(key_id, **kw)

    s.rewrap = dying  # type: ignore[method-assign]  # inject a crash after 8 rows
    b2 = CredentialBroker(s, AuditLog(), kek(KEK_V2, 2), prev_kek=kek(KEK_V1, 1))
    with pytest.raises(Killed):
        await b2.rewrap_all(2)
    assert sorted(r["kek_version"] for r in s.rows.values()).count(2) == 8
    s.rewrap = real  # type: ignore[method-assign]  # restart
    rep = await CredentialBroker(s, AuditLog(), kek(KEK_V2, 2), prev_kek=kek(KEK_V1, 1)).rewrap_all(
        2
    )
    assert rep.rewrapped == 12 and rep.remaining == 0
    only_v2 = CredentialBroker(s, AuditLog(), kek(KEK_V2, 2))
    for m in metas:
        await _borrow(only_v2, m.key_id)


async def test_rewrap_all_requires_both_keks() -> None:
    s, _, _ = await _seed(1)
    with pytest.raises(KekUnavailable):
        await CredentialBroker(s, AuditLog(), kek(KEK_V2, 2)).rewrap_all(2)
    with pytest.raises(KekUnavailable):
        await CredentialBroker(s, AuditLog(), kek(KEK_V2, 3), prev_kek=kek(KEK_V1, 1)).rewrap_all(3)


async def test_rewrap_all_wrong_prev_kek_fails_loudly() -> None:
    s, _, _ = await _seed(2)
    b = CredentialBroker(s, AuditLog(), kek(KEK_V2, 2), prev_kek=kek(bytes(32), 1))
    with pytest.raises(CredentialUnavailable):
        await b.rewrap_all(2)
    assert all(r["kek_version"] == 1 for r in s.rows.values())


async def test_rewrap_skips_row_moved_concurrently() -> None:
    s, metas, _ = await _seed(2)
    s.rows[metas[0].key_id]["kek_version"] = 2  # moved after listing
    orig = s.ids_at_kek_version
    first = True

    async def stale(version: int, limit: int) -> list[Any]:
        nonlocal first
        if first:
            first = False
            return [m.key_id for m in metas]
        return await orig(version, limit)

    s.ids_at_kek_version = stale  # type: ignore[method-assign]  # simulate a stale listing
    b = CredentialBroker(s, AuditLog(), kek(KEK_V2, 2), prev_kek=kek(KEK_V1, 1))
    assert (await b.rewrap_all(2)).rewrapped == 1


async def test_rewrap_cas_lost_not_counted() -> None:
    s, _, _ = await _seed(1)

    async def lose(key_id: Any, **kw: Any) -> bool:
        s.rows[key_id]["kek_version"] = kw["kek_version"]
        return False

    s.rewrap = lose  # type: ignore[method-assign]  # another worker won the CAS
    rep = await CredentialBroker(s, AuditLog(), kek(KEK_V2, 2), prev_kek=kek(KEK_V1, 1)).rewrap_all(
        2
    )
    assert rep.rewrapped == 0


async def test_borrow_with_cache_disabled_zeroes_dek(store: Any, audit: AuditLog) -> None:
    b = CredentialBroker(store, audit, kek(), dek_cache_ttl_s=0)
    meta = await _store(b)
    assert await _borrow(b, meta.key_id) == (API_KEY, API_SECRET)
    assert len(b._cache) == 0


async def test_rewrap_tolerates_row_vanishing() -> None:
    s, _metas, _ = await _seed(1)
    orig = s.get

    async def gone(key_id: Any) -> Any:
        return None

    s.get = gone  # type: ignore[method-assign]  # row deleted between listing and load
    b = CredentialBroker(s, AuditLog(), kek(KEK_V2, 2), prev_kek=kek(KEK_V1, 1))
    ids = s.ids_at_kek_version

    calls = 0

    async def once(version: int, limit: int) -> list[Any]:
        nonlocal calls
        calls += 1
        return await ids(version, limit) if calls == 1 else []

    s.ids_at_kek_version = once  # type: ignore[method-assign]  # single page
    assert (await b.rewrap_all(2)).rewrapped == 0
    s.get = orig  # type: ignore[method-assign]

"""Stored rows: round-trip property, row golden, tamper and AAD-binding rejection (E27-T02)."""

from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from candleviewer.secrets import _envelope as env
from candleviewer.secrets.broker import CredentialBroker
from candleviewer.secrets.errors import (
    CredentialUnavailable,
    KekUnavailable,
    WithdrawPermissionRejected,
)
from candleviewer.secrets.secret import Secret
from candleviewer.secrets.store import InMemoryCredentialStore
from tests.unit.credentials_m2._helpers import (
    _borrow,
    _store,
)
from tests.unit.credentials_m2._vectors import (
    ACCOUNT,
    API_KEY,
    API_SECRET,
    ENV,
    KEK_V1,
    SNAPSHOT,
    AuditLog,
    kek,
)
from tests.unit.credentials_m2.test_permissions import _snap_with


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
    if which == "secret_enc":
        s.rows[meta.key_id]["enc_nonce"] = bytes(blob[:12])
    with pytest.raises(CredentialUnavailable):
        await _borrow(b, meta.key_id)


async def test_broker_each_encryption_gets_fresh_nonce(
    broker: CredentialBroker, store: Any
) -> None:
    a, b = await _store(broker), await _store(broker)
    ra, rb = store.rows[a.key_id], store.rows[b.key_id]
    assert len({ra["secret_enc"][:12], rb["secret_enc"][:12], ra["key_id_enc"][:12],
                rb["key_id_enc"][:12]}) == 4  # fmt: skip
    assert not ra["dek_ref"][3:27] == rb["dek_ref"][3:27]


#: Regression pin (not a KAT): sha256 of dek_ref ‖ key_id_enc ‖ secret_enc for the fixed
#: inputs below. A change to the layout, AAD or field order changes it — and would make every
#: stored row undecryptable, so it must never change silently. Independent AES-GCM KAT:
#: `test_sealed_layout_golden_vector`.
GOLDEN_ROW_SHA256 = "51c619e0b2d30074200766e4e7420b869a810f165c8e4444de97e529a02d2ad6"


async def test_stored_row_golden_vector(monkeypatch: pytest.MonkeyPatch, store: Any) -> None:
    """Fixed KEK, DEK, nonces and id ⇒ pinned dek_ref / key_id_enc / secret_enc bytes."""
    import candleviewer.secrets.broker as br

    monkeypatch.setattr(env, "new_dek", lambda: bytearray(range(32)))
    monkeypatch.setattr(env, "new_nonce", lambda: bytes(range(12)))
    monkeypatch.setattr(br, "uuid4", lambda: UUID(int=0xAA))
    b = CredentialBroker(store, AuditLog(), kek())
    meta = await b.store("demo", ACCOUNT, "l", Secret("ABCD1234"), Secret("s3cret"), SNAPSHOT)
    row = store.rows[meta.key_id]
    digest = (
        __import__("hashlib")
        .sha256(row["dek_ref"].encode() + row["key_id_enc"] + row["secret_enc"])
        .hexdigest()
    )
    assert digest == GOLDEN_ROW_SHA256


@pytest.mark.parametrize("field", ["key_id_enc", "secret_enc", "enc_nonce", "dek_ref"])
@pytest.mark.parametrize("pos", [0, 5, 13, -1])
async def test_broker_tampered_field_is_rejected(
    broker: CredentialBroker, store: Any, field: str, pos: int
) -> None:
    meta = await _store(broker)
    broker.flush_cache()
    row = store.rows[meta.key_id]
    if field == "dek_ref":
        raw = bytearray(bytes.fromhex(row[field][3:]))
        raw[pos] ^= 1
        row[field] = "v1:" + raw.hex()
    else:
        b = bytearray(row[field])
        b[pos % len(b)] ^= 1
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


@pytest.mark.parametrize("what", ["id", "exchange_account_id"])
async def test_broker_aad_inputs_bound(broker: CredentialBroker, store: Any, what: str) -> None:
    """Changing the row identity (an AAD input) under fixed ciphertext is rejected."""
    meta = await _store(broker)
    broker.flush_cache()
    row = store.rows.pop(meta.key_id)
    if what == "id":
        row["id"] = uuid4()
    else:
        row["exchange_account_id"] = uuid4()
    store.rows[row["id"]] = row
    with pytest.raises(CredentialUnavailable):
        await _borrow(broker, row["id"])


async def test_kek_version_bound_in_wrap(store: Any) -> None:
    """A DEK wrapped at version 1 does not unwrap when the row claims version 2 (same KEK)."""
    meta = await _store(CredentialBroker(store, AuditLog(), kek(KEK_V1, 1)))
    store.rows[meta.key_id]["kek_version"] = 2
    with pytest.raises(CredentialUnavailable):
        await _borrow(CredentialBroker(store, AuditLog(), kek(KEK_V1, 2)), meta.key_id)


async def test_broker_bad_dek_ref_prefix_is_rejected(broker: CredentialBroker, store: Any) -> None:
    meta = await _store(broker)
    broker.flush_cache()
    store.rows[meta.key_id]["dek_ref"] = "v9:00"
    with pytest.raises(CredentialUnavailable):
        await _borrow(broker, meta.key_id)


async def test_cross_environment_row_fails(broker: CredentialBroker, store: Any) -> None:
    meta = await _store(broker)
    broker.flush_cache()
    store.rows[meta.key_id]["env"] = "live"  # a DB writer relabels the account's env
    with pytest.raises(CredentialUnavailable):
        await _borrow(broker, meta.key_id)


async def test_enc_alg_and_dek_length_checked(broker: CredentialBroker, store: Any) -> None:
    meta = await _store(broker)
    broker.flush_cache()
    store.rows[meta.key_id]["enc_alg"] = "ROT13"
    with pytest.raises(CredentialUnavailable):
        await _borrow(broker, meta.key_id)


def test_closed_kek_refuses_use() -> None:
    k = kek()
    k.close()
    with pytest.raises(KekUnavailable):
        k.kcv()
    with pytest.raises(KekUnavailable):
        k.wrap_dek(env.new_dek(), credential_id=uuid4())


# --- store-level permission gate (C-2.8) -------------------------------------------


@pytest.mark.parametrize(
    "perms",
    [
        # Bybit v5 GET /v5/user/query-api shape (value inside a group). Structural: built from
        # the synthetic packages/fixtures/accounts snapshot with the group value altered.
        {"Wallet": ["AccountTransfer", "Withdraw"]},
        {"Wallet": ["withdraw"]},
        {"Wallet": [" WITHDRAW "]},
        {"Withdraw": ["Withdraw"]},
        {"withdraw ": ["x"]},
        {"Nested": {"deep": ["SubWithdrawal"]}},
    ],
)
async def test_broker_withdraw_permission_rejected(
    broker: CredentialBroker, store: Any, perms: dict[str, Any]
) -> None:
    with pytest.raises(WithdrawPermissionRejected):
        await broker.store(
            ENV, ACCOUNT, "x", Secret(API_KEY), Secret(API_SECRET), _snap_with(perms)
        )
    assert not store.rows


async def test_broker_snapshot_without_permissions_rejected(broker: CredentialBroker) -> None:
    with pytest.raises(WithdrawPermissionRejected):
        await broker.store(ENV, ACCOUNT, "x", Secret(API_KEY), Secret(API_SECRET), {"uid": "1"})


async def test_store_projects_snapshot_and_drops_api_key(
    broker: CredentialBroker, store: Any
) -> None:
    snap = {**SNAPSHOT, "apiKey": API_KEY, "rsaPublicKey": "x", "parentUid": "9"}
    meta = await broker.store(ENV, ACCOUNT, "l", Secret(API_KEY), Secret(API_SECRET), snap)
    stored = store.rows[meta.key_id]["permission_snapshot"]
    assert "apiKey" not in stored and API_KEY not in repr(stored)
    assert set(stored) <= {"fetched_at", "uid", "note", "readOnly", "permissions", "ips",
                           "type", "expiredAt"}  # fmt: skip


async def test_dek_of_wrong_length_is_refused(broker: CredentialBroker, store: Any) -> None:
    """A wrap that authenticates but yields a 16-byte DEK (AES-128) is refused, not used."""
    from candleviewer.secrets import _envelope as env_

    meta = await _store(broker)
    broker.flush_cache()
    row = store.rows[meta.key_id]
    kek_ = broker._require_kek()
    short = bytearray(16)
    row["dek_ref"] = "v1:" + env_.seal(kek_._key, short, env_.dek_aad(row["id"], 1)).hex()
    with pytest.raises(CredentialUnavailable):
        await _borrow(broker, meta.key_id)

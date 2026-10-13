"""Credential broker: round-trip, scoped borrow, audit, status gating, destroy fence."""

from __future__ import annotations

import copy
import gc
from typing import Any
from uuid import uuid4

import pytest

from candleviewer.secrets.broker import CredentialBroker
from candleviewer.secrets.errors import (
    CredentialUnavailable,
    KekUnavailable,
)
from candleviewer.secrets.secret import Secret
from candleviewer.secrets.store import InMemoryCredentialStore
from tests.unit.credentials_m2._helpers import (
    _borrow,
    _store,
    _with,
)
from tests.unit.credentials_m2._vectors import (
    API_KEY,
    API_SECRET,
    KEK_V1,
    KEK_V2,
    AuditLog,
    kek,
)


async def test_broker_round_trip_returns_stored_plaintext(broker: CredentialBroker) -> None:
    meta = await _store(broker)
    assert meta.key_id_last4 == "WXYZ" and meta.kek_version == 1
    assert await _borrow(broker, meta.key_id) == (API_KEY, API_SECRET)


async def test_broker_row_holds_no_plaintext(broker: CredentialBroker, store: Any) -> None:
    meta = await _store(broker)
    row = store.rows[meta.key_id]
    blob = repr(row).encode() + row["key_id_enc"] + row["secret_enc"]
    assert API_KEY.encode() not in blob and API_SECRET.encode() not in blob
    assert row["enc_nonce"] == row["secret_enc"][:12] and row["enc_alg"] == "AES-256-GCM"


async def test_borrowed_secret_invalidated_after_borrow(broker: CredentialBroker) -> None:
    meta = await _store(broker)
    kept: list[Secret[str]] = []

    async def fn(k: Secret[str], s: Secret[str]) -> None:
        kept.extend([k, s])

    await _with(broker, meta.key_id, fn)
    gc.collect()
    for s in kept:
        with pytest.raises(RuntimeError):
            s.reveal()


async def test_borrowed_secret_invalidated_even_if_fn_raises(broker: CredentialBroker) -> None:
    meta = await _store(broker)
    kept: list[Secret[str]] = []

    async def fn(k: Secret[str], s: Secret[str]) -> None:
        kept.append(k)
        raise LookupError("boom")

    with pytest.raises(LookupError):
        await _with(broker, meta.key_id, fn)
    with pytest.raises(RuntimeError):
        kept[0].reveal()


async def test_broker_dump_without_kek_cannot_decrypt(broker: CredentialBroker, store: Any) -> None:
    meta = await _store(broker)
    dump = InMemoryCredentialStore()
    dump.rows = copy.deepcopy(store.rows)
    with pytest.raises(KekUnavailable):
        await _borrow(CredentialBroker(dump, AuditLog(), None), meta.key_id)
    with pytest.raises(CredentialUnavailable):
        await _borrow(CredentialBroker(dump, AuditLog(), kek(bytes(32))), meta.key_id)


async def test_broker_wrong_kek_material_fails_tag_check(store: Any, audit: AuditLog) -> None:
    meta = await _store(CredentialBroker(store, audit, kek(KEK_V1, 1)))
    b2 = CredentialBroker(store, audit, kek(KEK_V2, 1), dek_cache_ttl_s=0)
    with pytest.raises(CredentialUnavailable) as ei:
        await _borrow(b2, meta.key_id)
    assert API_KEY not in str(ei.value) and str(ei.value) == "credential_unavailable"


async def test_broker_unknown_version_fails(store: Any, audit: AuditLog) -> None:
    meta = await _store(CredentialBroker(store, audit, kek(KEK_V1, 1)))
    with pytest.raises(CredentialUnavailable):
        await _borrow(CredentialBroker(store, audit, kek(KEK_V2, 3)), meta.key_id)


@pytest.mark.parametrize("bad", ["ab", "abc-", "ab cd"])
async def test_broker_rejects_bad_key_shape(broker: CredentialBroker, bad: str) -> None:
    with pytest.raises(CredentialUnavailable):
        await _store(broker, bad)


def test_borrow_handle_rejects_unknown_caller(broker: CredentialBroker) -> None:
    for caller in ("admin", "rules", "", "exchange_adapter "):
        with pytest.raises(ValueError):
            broker.borrow_handle(caller)


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
    assert borrowed["caller_module"] == "exchange_adapter" and borrowed["purpose"] == "sign_rest"
    for _, fields in audit.records:
        assert API_KEY not in str(fields) and API_SECRET not in str(fields)


async def test_broker_audit_failure_refuses_action(
    broker: CredentialBroker, audit: AuditLog, store: Any
) -> None:
    meta = await _store(broker)
    audit.fail = True
    for op in (_borrow(broker, meta.key_id), _store(broker), broker.destroy(meta.key_id)):
        with pytest.raises(CredentialUnavailable) as ei:  # typed; raw sink error never leaks
            await op
        assert str(ei.value) == "audit_timeout"
    assert len(store.rows) == 1 and not store.rows[meta.key_id]["revoked"]


async def test_broker_destroyed_key_cannot_be_borrowed(broker: CredentialBroker) -> None:
    meta = await _store(broker)
    await broker.destroy(meta.key_id)
    with pytest.raises(CredentialUnavailable):
        await _borrow(broker, meta.key_id)


async def test_broker_destroy_unknown_key_raises(broker: CredentialBroker, audit: AuditLog) -> None:
    with pytest.raises(CredentialUnavailable):
        await broker.destroy(uuid4())
    assert audit.actions() == []


async def test_broker_unknown_key_unavailable(broker: CredentialBroker) -> None:
    with pytest.raises(CredentialUnavailable):
        await _borrow(broker, uuid4())


async def test_dek_cache_flushed_on_destroy(broker: CredentialBroker) -> None:
    meta = await _store(broker)
    await _borrow(broker, meta.key_id)
    await broker.destroy(meta.key_id)
    assert len(broker._cache) == 0


async def test_borrow_with_cache_disabled(store: Any, audit: AuditLog) -> None:
    b = CredentialBroker(store, audit, kek(), dek_cache_ttl_s=0)
    meta = await _store(b)
    assert await _borrow(b, meta.key_id) == (API_KEY, API_SECRET)
    assert len(b._cache) == 0


async def test_drop_kek_fails_closed(broker: CredentialBroker) -> None:
    meta = await _store(broker)
    await _borrow(broker, meta.key_id)
    broker.drop_kek()
    assert len(broker._cache) == 0
    with pytest.raises(KekUnavailable):
        await _borrow(broker, meta.key_id)


async def test_in_memory_touch_is_noop(store: Any) -> None:
    assert await store.touch_last_used(uuid4()) is None

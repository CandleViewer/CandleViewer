"""Kill the five E27-T02 mutation survivors (QA gap G3, #835): E6, SV7, B17, RO8, SV10."""

from __future__ import annotations

from typing import Any

import pytest
from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from structlog.testing import capture_logs

from candleviewer.secrets import _envelope as env
from candleviewer.secrets._kek import LoadedKek
from candleviewer.secrets.broker import CredentialBroker
from candleviewer.secrets.errors import CredentialUnavailable
from candleviewer.secrets.store import InMemoryCredentialStore
from tests.unit.credentials_m2._helpers import _borrow, _store
from tests.unit.credentials_m2._service_fakes import _ctx, _Src, _svc, _zeroed
from tests.unit.credentials_m2._vectors import API_SECRET, KEK_V1, AuditLog, kek
from tests.unit.credentials_m2.test_rotation import _rot as rot
from tests.unit.credentials_m2.test_rotation import _seed as seed


async def _dek_of(store: InMemoryCredentialStore, key_id: Any) -> bytes:
    row = store.rows[key_id]
    return bytes(kek().unwrap_dek(row["dek_ref"], credential_id=row["id"]))


async def test_e6_each_store_draws_a_fresh_full_length_dek(
    broker: CredentialBroker, store: InMemoryCredentialStore
) -> None:
    a, b = await _store(broker), await _store(broker)
    dek_a, dek_b = await _dek_of(store, a.key_id), await _dek_of(store, b.key_id)
    assert len(dek_a) == len(dek_b) == env.KEY_LEN == 32
    assert dek_a != dek_b
    assert dek_a != bytes(32) and dek_b != bytes(32)
    assert len(set(dek_a)) >= 8 and len(set(dek_b)) >= 8  # not a degenerate/constant fill
    assert store.rows[a.key_id]["secret_enc"] != store.rows[b.key_id]["secret_enc"]
    assert store.rows[a.key_id]["dek_ref"] != store.rows[b.key_id]["dek_ref"]


async def test_e6_dump_only_attacker_without_kek_cannot_decrypt(
    broker: CredentialBroker, store: InMemoryCredentialStore
) -> None:
    meta = await _store(broker)
    row = store.rows[meta.key_id]
    aad = env.cred_aad(row["env"], row["exchange_account_id"], row["id"], "secret")
    blob = row["secret_enc"]
    # Guesses a dump-only attacker can make with no KEK: the all-zero DEK, and the other
    # trivially derivable keys. Every one must fail the GCM tag.
    guesses = [bytes(32), b"\xff" * 32, bytes(range(32)), row["id"].bytes * 2]
    for guess in guesses:
        with pytest.raises(InvalidTag):
            AESGCM(guess).decrypt(blob[: env.NONCE_LEN], blob[env.NONCE_LEN :], aad)
    assert API_SECRET.encode() not in blob


async def test_sv7_stop_zeroes_the_kek_buffer() -> None:
    src = _Src(KEK_V1, 1)
    svc = _svc(src)
    await svc.start(_ctx())
    assert src.handed and any(k._key != bytearray(32) for k in src.handed)  # live before stop
    await svc.stop(0.1)
    assert _zeroed(src)
    assert all(not any(k._key) for k in src.handed)


async def test_b17_wrong_length_dek_is_refused_before_any_gcm_call(
    broker: CredentialBroker, monkeypatch: pytest.MonkeyPatch
) -> None:
    meta = await _store(broker)
    short = bytearray(
        16
    )  # a 16-byte DEK would be a valid AES-128 key: only the length check stops it
    monkeypatch.setattr(LoadedKek, "unwrap_dek", lambda *_a, **_k: short)
    gcm_calls: list[int] = []

    def spy(*a: Any, **k: Any) -> bytearray:
        gcm_calls.append(1)
        raise AssertionError("GCM open reached despite wrong DEK length")

    monkeypatch.setattr(env, "open_", spy)
    with pytest.raises(CredentialUnavailable):
        await _borrow(broker, meta.key_id)
    assert gcm_calls == []  # refused by the length check, not by the GCM tag
    assert not any(short) and len(broker._cache) == 0  # wiped and never cached


async def test_ro8_kek_rotation_flushes_the_dek_cache() -> None:
    s, metas, _ = await seed(3)
    b = rot(s)
    await _borrow(b, metas[0].key_id)  # mid-rotation borrow under the previous KEK caches a DEK
    assert len(b._cache) == 1
    cached = b._cache._items[metas[0].key_id][1]
    await b.rewrap_all(2)
    assert len(b._cache) == 0
    assert not any(cached)  # the cached DEK buffer was zeroed, not just dropped


async def test_sv10_kek_loss_emits_critical_structured_log() -> None:
    svc = _svc(_Src(None, 1), audit=AuditLog())
    with capture_logs() as logs:
        await svc.start(_ctx())
    hits = [e for e in logs if e["event"] == "secrets.kek_unavailable"]
    assert len(hits) == 1
    assert hits[0]["log_level"] == "critical"
    assert hits[0]["reason"] == "kek_unavailable" and hits[0]["remediation"]

"""`InMemoryAuthKeyStore`, M2's fake of the `AuthKeyStore` port (#2152 S4): it refuses what the M10
adapter and the table refuse (21 Sec.3.1.5a), so the boot tests that run on it cannot pass on a
write Postgres would refuse. Its Postgres twin: `tests/integration/storage/test_auth_keys_pg.py`."""

from __future__ import annotations

from typing import Any
from uuid import UUID

import pytest

from candleviewer.secrets.store import InMemoryAuthKeyStore

WRAP, NEXT = "ak1:" + "ab" * 60, "ak1:" + "cd" * 60
ENROLLED = ("security.auth_keyring_enrolled", {"origin": "generated"})
REWRAPPED = ("security.auth_keyring_rewrapped", {"from": "1", "to": "2"})


def _ring(env: str = "demo", first: int = 1) -> list[dict[str, Any]]:
    return [
        {"id": UUID(int=first + n), "env": env, "purpose": p, "origin": "generated",
         "dek_ref": WRAP, "kek_version": 1}
        for n, p in enumerate(("totp_seal", "recovery_hmac"))
    ]  # fmt: skip


async def test_a_keyring_is_written_whole_with_its_record_and_read_by_purpose() -> None:
    store = InMemoryAuthKeyStore()
    assert await store.insert_keyring(_ring(), audit=ENROLLED)
    assert [r["purpose"] for r in await store.rows_for("demo")] == ["recovery_hmac", "totp_seal"]
    assert {r["key_version"] for r in store.rows} == {1} and store.audit == [ENROLLED]
    assert not await store.insert_keyring(_ring(first=7), audit=ENROLLED)  # another boot's first
    assert len(store.rows) == 2 and store.audit == [ENROLLED]  # lost: nothing written or recorded


@pytest.mark.parametrize(
    "records",
    [
        [],
        _ring("live"),
        [_ring()[0] | {"dek_ref": "v2:" + "ab" * 60}],
        [_ring()[0] | {"kek_version": 0}],
    ],
    ids=["empty", "another_environment", "not_an_auth_wrap", "kek_version"],
)
async def test_a_keyring_the_table_refuses_is_refused_before_any_write(records: Any) -> None:
    store = InMemoryAuthKeyStore()
    with pytest.raises(ValueError):
        await store.insert_keyring(records, audit=ENROLLED)
    assert (store.rows, store.audit) == ([], [])


async def test_a_reused_id_raises_and_a_failed_record_writes_nothing() -> None:
    store = InMemoryAuthKeyStore()
    await store.insert_keyring(_ring()[:1], audit=ENROLLED)
    with pytest.raises(ValueError, match="unique"):
        await store.insert_keyring([_ring()[0] | {"purpose": "recovery_hmac"}], audit=ENROLLED)
    store.audit_fails = True
    with pytest.raises(RuntimeError):
        await store.insert_keyring(_ring()[1:], audit=ENROLLED)
    assert len(store.rows) == 1 and len(store.audit) == 1


async def test_a_rewrap_is_a_compare_and_set_committed_with_its_record() -> None:
    store = InMemoryAuthKeyStore(mfa_material=3)
    await store.insert_keyring(_ring(), audit=ENROLLED)
    move: dict[str, Any] = {"env": "demo", "dek_ref": NEXT, "kek_version": 2, "audit": REWRAPPED}
    key = UUID(int=1)
    assert not await store.rewrap(key, from_version=2, **move)  # stale: not at that version
    assert await store.rewrap(key, from_version=1, **move)
    assert not await store.rewrap(key, from_version=1, **move)  # a replay: it moved on
    assert [await store.count_at_kek_version(v, "demo") for v in (1, 2)] == [1, 1]
    assert store.audit[-1] == REWRAPPED and await store.count_mfa_material() == 3
    store.audit_fails = True
    with pytest.raises(RuntimeError):
        await store.rewrap(UUID(int=2), from_version=1, **move)
    assert await store.count_at_kek_version(1, "demo") == 1  # the failed record moved nothing
    for refused in ({"env": "live"}, {"dek_ref": "plain"}, {"kek_version": 0}):
        with pytest.raises(ValueError):
            await store.rewrap(UUID(int=2), from_version=1, **move | refused)
    with pytest.raises(ValueError):
        await store.rows_for("live")

"""`SqlAlchemyCredentialStore.get` against a fake unit of work (E27-T03, SR-E27-14).

The borrow's C-2.8 re-check refuses a snapshot that is no dict, so `get` decodes the jsonb the
driver hands back, as text (no asyncpg codec) or as a mapping. A snapshot that is no JSON object (a
row edited past `ak_snapshot_shape`, KV-T03) comes back as no mapping: the re-check refuses it as
`snapshot_invalid`, while `destroy()` and the KEK re-wrap still reach the row. A live driver is
CI's: `tests/integration/storage/test_credentials_store_pg.py`.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from types import MappingProxyType, SimpleNamespace
from typing import Any, cast
from uuid import UUID

import pytest

from candleviewer.secrets import KEY_ID_SLOT
from candleviewer.secrets._rotation import RotatingBroker
from candleviewer.secrets.broker import CredentialBroker
from candleviewer.secrets.errors import SnapshotInvalid
from candleviewer.secrets.store import InMemoryCredentialStore
from candleviewer.storage.repositories.credentials_sqlalchemy import SqlAlchemyCredentialStore
from tests.unit.credentials_m2._helpers import _h, _store
from tests.unit.credentials_m2._vectors import KEK_V1, KEK_V2, SNAPSHOT, AuditLog, kek

KEY = UUID(int=11)
ROW = {
    "id": KEY, "env": "demo", "key_id_enc": b"k", "secret_enc": b"s", "enc_nonce": b"n",
    "can_withdraw": False, "can_transfer": False,
}  # fmt: skip
#: `dict()` turns this array of pairs into an object; only the decode's `Mapping` check refuses it.
_PAIRS = [["permissions", {"ContractTrade": ["Order", "Position"]}], ["uid", "1"]]
#: An object snapshot as the driver may hand it back: text, a dict, or a mapping that is no dict.
_OBJECT = {"text": json.dumps(SNAPSHOT), "dict": SNAPSHOT, "proxy": MappingProxyType(SNAPSHOT)}
#: Snapshots that are no JSON object, as the driver may hand them back (text, or decoded).
_NO_OBJECT = {
    "array_text": "[1]",
    "no_json": "{",
    "null": None,
    "int": 7,
    "pairs_text": json.dumps(_PAIRS),
    "pairs": _PAIRS,
}


def _pg(row: dict[str, Any]) -> SqlAlchemyCredentialStore:
    """The adapter over a unit of work that answers every statement with this one row."""

    @asynccontextmanager
    async def unit_of_work() -> AsyncIterator[Any]:
        async def execute(*_: object) -> Any:
            rows = SimpleNamespace(all=lambda: [row])
            return SimpleNamespace(returns_rows=True, mappings=lambda: rows)

        async def commit() -> None:
            return None

        yield SimpleNamespace(session=SimpleNamespace(execute=execute), commit=commit)

    return SqlAlchemyCredentialStore(cast(Any, SimpleNamespace(unit_of_work=unit_of_work)))


class _Tampered(InMemoryCredentialStore):
    """M2's in-memory store whose reads of `key_id` go through the adapter with the snapshot
    `raw`, as Postgres would return a row whose `ak_snapshot_shape` CHECK was dropped."""

    def __init__(self, raw: object) -> None:
        super().__init__()
        self.raw, self.key_id = raw, UUID(int=0)

    async def get(self, key_id: UUID, env: str) -> dict[str, Any] | None:
        row = await super().get(key_id, env)
        if row is None or key_id != self.key_id:
            return row
        return await _pg({**row, "permission_snapshot": self.raw}).get(key_id, env)


@pytest.mark.parametrize("raw", list(_OBJECT.values()), ids=list(_OBJECT))
async def test_get_decodes_an_object_snapshot_to_a_dict(raw: object) -> None:
    rec = await _pg({**ROW, "permission_snapshot": raw}).get(KEY, "demo")
    assert rec is not None
    assert type(rec["permission_snapshot"]) is dict and rec["permission_snapshot"] == SNAPSHOT


async def test_get_returns_the_fund_flags_as_read() -> None:
    rec = await _pg({**ROW, "permission_snapshot": SNAPSHOT}).get(KEY, "demo")
    assert rec is not None and (rec["can_withdraw"], rec["can_transfer"]) == (False, False)


@pytest.mark.parametrize("raw", list(_NO_OBJECT.values()), ids=list(_NO_OBJECT))
async def test_get_never_hands_over_a_snapshot_that_is_no_object_as_a_mapping(raw: object) -> None:
    rec = await _pg({**ROW, "permission_snapshot": raw}).get(KEY, "demo")
    assert rec is not None and not isinstance(rec["permission_snapshot"], Mapping)


async def test_a_borrow_signs_when_the_driver_returns_the_snapshot_as_text() -> None:
    """Without the decode, every borrow reads the text as a malformed snapshot and is refused."""
    memory = InMemoryCredentialStore()
    meta = await _store(CredentialBroker(memory, AuditLog(), kek()))
    row = memory.rows[meta.key_id]
    text = json.dumps(row["permission_snapshot"])
    broker = CredentialBroker(_pg({**row, "permission_snapshot": text}), AuditLog(), kek())
    try:
        signed = await _h(broker).sign(meta.key_id, (KEY_ID_SLOT,), purpose="sign_rest")
    finally:
        await broker.aclose()
    assert signed.signature


@pytest.mark.parametrize("raw", list(_NO_OBJECT.values()), ids=list(_NO_OBJECT))
async def test_a_borrow_refuses_a_snapshot_that_is_no_object_as_snapshot_invalid(
    raw: object,
) -> None:
    store = _Tampered(raw)
    broker = CredentialBroker(store, AuditLog(), kek())
    store.key_id = (await _store(broker)).key_id
    with pytest.raises(SnapshotInvalid):
        await _h(broker).sign(store.key_id, (KEY_ID_SLOT,), purpose="sign_rest")


async def test_destroy_revokes_a_row_whose_snapshot_is_no_object() -> None:
    store, audit = _Tampered("[1]"), AuditLog()
    broker = CredentialBroker(store, audit, kek())
    store.key_id = (await _store(broker)).key_id
    await broker.destroy(store.key_id)
    assert (store.rows[store.key_id]["revoked"], audit.actions()[-1]) == (
        True,
        "security.credential_destroyed",
    )


async def test_a_kek_rewrap_moves_a_row_whose_snapshot_is_no_object_and_every_other() -> None:
    """Each row's outcome is its own: the tampered row, read first, never aborts the run."""
    store, audit = _Tampered("[1]"), AuditLog()
    first = CredentialBroker(store, AuditLog(), kek(KEK_V1, 1))
    ids = [(await _store(first, f"KEY{i:04d}ABCDEFGH")).key_id for i in range(3)]
    store.key_id = min(ids)
    rotating = RotatingBroker(store, audit, kek(KEK_V2, 2), prev_kek=kek(KEK_V1, 1))
    report = await rotating.rewrap_all(2)
    assert (report.rewrapped, report.failed, audit.actions()[-1]) == (3, (), "security.kek_rotated")

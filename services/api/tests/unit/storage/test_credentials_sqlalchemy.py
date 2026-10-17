"""`SqlAlchemyCredentialStore.get` against a fake unit of work (E27-T03, SR-E27-14).

The borrow's C-2.8 re-check refuses a snapshot that is no dict, so `get` decodes the jsonb the
driver hands back, as text (no asyncpg codec) or as a mapping. A live driver is CI's:
`tests/integration/storage/test_credentials_store_pg.py`.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import Any, cast
from uuid import UUID

import pytest

from candleviewer.secrets import KEY_ID_SLOT
from candleviewer.secrets.broker import CredentialBroker
from candleviewer.secrets.store import InMemoryCredentialStore
from candleviewer.storage.repositories.credentials_sqlalchemy import SqlAlchemyCredentialStore
from tests.unit.credentials_m2._helpers import _h, _store
from tests.unit.credentials_m2._vectors import SNAPSHOT, AuditLog, kek

KEY = UUID(int=11)
ROW = {
    "id": KEY, "env": "demo", "key_id_enc": b"k", "secret_enc": b"s", "enc_nonce": b"n",
    "can_withdraw": False, "can_transfer": False,
}  # fmt: skip


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


@pytest.mark.parametrize("as_text", [True, False], ids=["text", "mapping"])
async def test_get_decodes_the_snapshot_whether_the_driver_gives_text_or_a_mapping(
    as_text: bool,
) -> None:
    raw: object = json.dumps(SNAPSHOT) if as_text else SNAPSHOT
    rec = await _pg({**ROW, "permission_snapshot": raw}).get(KEY, "demo")
    assert rec is not None
    assert rec["permission_snapshot"] == SNAPSHOT and type(rec["permission_snapshot"]) is dict
    assert (rec["can_withdraw"], rec["can_transfer"]) == (False, False)


@pytest.mark.parametrize("raw", ["[1]", "{", None, 7], ids=["array_text", "no_json", "null", "int"])
async def test_get_fails_closed_on_a_snapshot_that_is_no_object(raw: object) -> None:
    with pytest.raises((TypeError, ValueError)):
        await _pg({**ROW, "permission_snapshot": raw}).get(KEY, "demo")


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

"""Integration: the `api_keys` write-once guard at the head revision (#2758 items 3 and 4).

`test_0024_api_keys_write_once_migration.py` moves its database between 0023 and 0024, so its
trigger-order check sees revision 0024 only. This module migrates to head, so a later revision
that adds a BEFORE UPDATE trigger on `api_keys` fails here. It also drives one write the guard
refuses through the app's engine. Synthetic rows only; no network beyond the local testcontainer.
Not run locally (no docker); CI integration lane.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import traceback
from collections.abc import Iterator
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import psycopg
import pytest
import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import create_async_engine
from testcontainers.postgres import PostgresContainer

from candleviewer.storage.repositories.relational_sqlalchemy import (
    SqlAlchemyRelationalRepository,
)

pytestmark = pytest.mark.integration

_ROOT = Path(__file__).resolve().parents[3]
_SNAP: dict[str, Any] = {"uid": "1", "permissions": {"ContractTrade": ["Order"], "Wallet": []}}
_MARK = b"bound-value-mark"  # bound into the refused write; stands in for SECRET ciphertext
_RESEAL = sa.text("UPDATE api_keys SET secret_enc = :sealed WHERE id = :id")
_REFUSAL = "trg_api_keys_write_once: api_keys.secret_enc is write-once; store a new row (SR-003)"


@pytest.fixture(scope="module")
def pg() -> Iterator[str]:
    """Superuser DSN (no driver suffix) of a fresh database migrated to head."""
    with PostgresContainer("postgres:16-alpine") as container:
        url = container.get_connection_url()
        subprocess.run(
            [sys.executable, "-m", "alembic", "upgrade", "head"],
            cwd=_ROOT, env={**os.environ, "CV_PG_DSN": url}, check=True, timeout=300,
        )  # fmt: skip
        yield url.replace("postgresql+psycopg2", "postgresql")


def _exec(dsn: str, query: str, params: tuple[Any, ...] | None = None) -> list[tuple[Any, ...]]:
    with psycopg.connect(dsn, autocommit=True) as c:
        cur = c.execute(query, params)
        return cur.fetchall() if cur.description else []


def _key(dsn: str) -> UUID:
    """One synthetic `api_keys` row on a fresh demo account."""
    acct, key_id = uuid4(), uuid4()
    _exec(
        dsn,
        "INSERT INTO exchange_accounts (id, exchange, env, kind, exchange_uid, label) "
        "VALUES (%s, 'bybit', 'demo', 'main', %s, %s)",
        (acct, str(acct.int % 10**12), f"acct-{acct}"),
    )
    _exec(
        dsn,
        "INSERT INTO api_keys (id, exchange_account_id, label, key_id_enc, key_id_last4, "
        "secret_enc, enc_nonce, dek_ref, permission_snapshot) "
        "VALUES (%s, %s, 'k', %s, 'WXYZ', %s, %s, 'v1:00', %s::jsonb)",
        (key_id, acct, b"sealed-key-id", b"sealed-secret", bytes(12), json.dumps(_SNAP)),
    )
    return key_id


def _rendered(exc: BaseException) -> str:
    """What a log of `exc` would carry: every message in the chain."""
    return "".join(traceback.format_exception(exc))


def test_the_guard_is_the_last_before_update_row_trigger_at_head(pg: str) -> None:
    """#2758 item 3. Same-event row triggers fire in name order, so a BEFORE UPDATE trigger
    that sorts after the guard could rewrite NEW after the check; one that sorts before it
    cannot get past it. tgtype 19 = ROW | BEFORE | UPDATE, which also matches
    `BEFORE INSERT OR UPDATE`."""
    order = _exec(
        pg,
        "SELECT tgname, tgenabled FROM pg_trigger WHERE tgrelid = 'api_keys'::regclass "
        'AND NOT tgisinternal AND tgtype & 19 = 19 ORDER BY tgname COLLATE "C"',
    )
    assert order[-1:] == [("trg_api_keys_write_once", "A")], order


async def test_a_refused_write_through_the_app_engine_renders_no_bound_value(pg: str) -> None:
    """#2758 item 4 (C-12.6). Through `SqlAlchemyRelationalRepository` (`hide_parameters=True`)
    the guard's refusal names the column but carries neither bound value. Control: a default
    engine renders both for the same write, so a leak would show here."""
    key_id = _key(pg)
    params = {"sealed": _MARK, "id": key_id}
    asyncpg_dsn = pg.replace("postgresql", "postgresql+asyncpg", 1)
    rel, default = SqlAlchemyRelationalRepository(asyncpg_dsn), create_async_engine(asyncpg_dsn)
    try:
        with pytest.raises(IntegrityError) as hidden:
            async with rel.unit_of_work() as uow:
                await uow.session.execute(_RESEAL, params)
        with pytest.raises(IntegrityError) as shown:
            async with default.begin() as conn:
                await conn.execute(_RESEAL, params)
    finally:
        await rel.dispose()
        await default.dispose()
    bound = [_MARK.decode(), str(key_id)]
    assert _REFUSAL in _rendered(hidden.value)
    assert [value for value in bound if value in _rendered(hidden.value)] == []
    assert [value for value in bound if value in _rendered(shown.value)] == bound

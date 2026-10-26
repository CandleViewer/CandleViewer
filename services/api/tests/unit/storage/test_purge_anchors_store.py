"""Unit tests for a purge's durable idempotency anchor (E16-T06 #490): the port's refusals, the
Core statements as asyncpg receives them, and the store against a recording fake unit of work.
Real SQL: tests/integration/storage/test_ia_purge_anchor_migration.py (CI only)."""

from __future__ import annotations

import hashlib
import uuid
from typing import Any, cast

import pytest

from candleviewer.storage.repositories import purge_anchors_sqlalchemy as mod
from candleviewer.storage.repositories.purge_anchors import (
    MAX_BEFORE_US,
    PURGE_OPERATION,
    NewPurgeAnchor,
    require_bound,
)
from tests.unit.storage.test_idempotency_anchors_store import _params, _Rel, _sql

_USER, _ANCHOR = uuid.UUID(int=0x1001), uuid.UUID(int=0x2001)
_REF = "9b2f7c1e-4d3a-4f6b-8a0c-5e1d2c3b4a59"
_SHA = hashlib.sha256(b'{"symbol":"BTCUSDT"}').hexdigest()
_BEFORE = 1_792_548_000_000_000


def _anchor(**over: Any) -> NewPurgeAnchor:
    values: dict[str, Any] = {
        "id": _ANCHOR, "created_by": _USER, "client_ref": _REF, "request_sha256": _SHA,
        "before_us": _BEFORE,
    }  # fmt: skip
    return NewPurgeAnchor(**(values | over))


@pytest.mark.parametrize(
    ("over", "rule"),
    [
        ({"client_ref": _REF.upper()}, "ia_ref_fmt"),
        ({"request_sha256": _SHA.upper()}, "sha256_hex"),
        ({"before_us": -1}, "ia_bound"),
        ({"before_us": MAX_BEFORE_US + 1}, "ia_bound"),
        ({"before_us": True}, "ia_bound"),
        ({"before_us": 1.5}, "ia_bound"),
    ],
    ids=["upper-key", "upper-sha", "negative", "past-bigint", "bool", "float"],
)
def test_an_anchor_the_table_would_refuse_is_refused(over: dict[str, Any], rule: str) -> None:
    with pytest.raises(ValueError, match=rule):
        _anchor(**over)


def test_the_bound_takes_zero_and_the_largest_bigint() -> None:
    require_bound(0)
    require_bound(MAX_BEFORE_US)
    assert "client_ref" not in repr(_anchor()) and _REF not in repr(_anchor())


def test_find_is_scoped_to_the_principal_and_the_purge_and_never_reads_the_key() -> None:
    stmt = mod.find_statement(_USER, _REF, _SHA)
    sql = _sql(stmt)
    selected = sql.split(" FROM ", 1)[0]
    assert selected.startswith("SELECT idempotency_anchors.id, idempotency_anchors.before_us, ")
    assert "client_ref" not in selected and "request_sha256 = " in selected
    assert sql.endswith(
        "WHERE idempotency_anchors.created_by = $2::UUID AND idempotency_anchors.operation = $3::"
        "VARCHAR AND idempotency_anchors.client_ref = $4::VARCHAR"
    )
    assert list(_params(stmt).values()) == [_SHA, _USER, PURGE_OPERATION, _REF]


def test_the_create_writes_the_purge_row_once_and_returns_the_id() -> None:
    stmt = mod.create_statement(_anchor())
    sql = _sql(stmt)
    assert sql.endswith(
        "ON CONFLICT (created_by, operation, client_ref) DO NOTHING "
        "RETURNING idempotency_anchors.id"
    )
    params = _params(stmt)
    assert params["operation"] == PURGE_OPERATION and params["before_us"] == _BEFORE
    assert set(params) == {
        "id", "created_by", "operation", "client_ref", "request_sha256", "before_us",
    }  # fmt: skip  # no target and no outcome


def _store(rel: _Rel) -> mod.SqlAlchemyPurgeAnchorStore:
    return mod.SqlAlchemyPurgeAnchorStore(cast(Any, rel))  # structural fake


async def test_find_maps_the_row_and_reads_absence_as_none() -> None:
    rel = _Rel([{"id": str(_ANCHOR), "before_us": _BEFORE, "body_matches": False}], [])
    found = await _store(rel).find(_USER, _REF, _SHA)
    assert found is not None and (found.id, found.before_us) == (_ANCHOR, _BEFORE)
    assert found.body_matches is False
    assert await _store(rel).find(_USER, _REF, _SHA) is None
    assert rel.commits == 0


async def test_find_refuses_a_key_the_column_could_not_hold_before_any_statement() -> None:
    rel = _Rel()
    with pytest.raises(ValueError, match="ia_ref_fmt"):
        await _store(rel).find(_USER, _REF.upper(), _SHA)
    assert rel.statements == []


async def test_a_create_is_true_once_then_false_for_a_held_key() -> None:
    rel = _Rel([{"id": _ANCHOR}], [])
    store = _store(rel)
    assert await store.create(_anchor()) is True
    assert await store.create(_anchor()) is False
    assert rel.commits == 2

"""Unit tests for the replay anchor's port and Postgres adapter (E29-T04 #913): the dataclass
refusals, the Core statements as asyncpg receives them, and the store against a recording fake
unit of work. Real SQL: tests/integration/storage/test_order_submission_pg.py (CI only)."""

from __future__ import annotations

import hashlib
import re
import uuid
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from dataclasses import fields
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any, cast

import pytest
from sqlalchemy.engine import Dialect, make_url
from sqlalchemy.exc import IntegrityError
from sqlalchemy.sql.elements import TextClause

from candleviewer.db import models
from candleviewer.storage.repositories import idempotency_anchors_sqlalchemy as mod
from candleviewer.storage.repositories.idempotency_anchors import (
    AnchorOutcome,
    AnchorRow,
    NewAnchor,
    require_client_ref,
)
from candleviewer.storage.repositories.orders import OrderConstraintError

_ASYNCPG: Dialect = make_url("postgresql+asyncpg://").get_dialect()()
_T = datetime(2026, 10, 21, 9, tzinfo=UTC)
_USER, _ANCHOR, _GROUP, _ORDER = (uuid.UUID(int=n) for n in (0x1001, 0x2001, 0x3001, 0x4001))
_REF = "9b2f7c1e-4d3a-4f6b-8a0c-5e1d2c3b4a59"  # hex letters, so its upper case differs
_SHA = hashlib.sha256(b'{"symbol":"BTCUSDT","side":"Buy"}').hexdigest()


def _sql(stmt: Any) -> str:
    text = str(stmt.compile(dialect=_ASYNCPG, compile_kwargs={"render_postcompile": True}))
    return " ".join(text.split())


def _params(stmt: Any) -> dict[str, Any]:
    return dict(stmt.compile(dialect=_ASYNCPG).params)


def _anchor(**over: Any) -> NewAnchor:
    values: dict[str, Any] = {
        "id": _ANCHOR, "created_by": _USER, "operation": "placeOrder", "client_ref": _REF,
        "request_sha256": _SHA, "trade_group_id": _GROUP,
    }  # fmt: skip
    return NewAnchor(**(values | over))


@pytest.mark.parametrize(
    "ref",
    [_REF.upper(), f"{{{_REF}}}", _REF.replace("-", ""), _REF + "\n", f" {_REF}",
     f"urn:uuid:{_REF}", _REF[:-1] + "g", "", "cv-0c000000"],
    ids=["upper", "braces", "no-hyphens", "newline", "space", "urn", "non-hex", "empty", "other"],
)  # fmt: skip
def test_a_key_is_only_canonical_lower_case_uuid_text(ref: str) -> None:
    """`ia_ref_fmt` in code, as `models.GROUP_REF_PATTERN` reads it in SQL."""
    assert re.fullmatch(models.GROUP_REF_PATTERN, ref) is None
    with pytest.raises(ValueError, match="ia_ref_fmt") as exc:
        _anchor(client_ref=ref)
    assert ref.strip() == "" or ref.strip() not in str(exc.value)  # a key is P1 (21 Sec.12)


def test_a_canonical_key_of_any_version_passes_both_checks() -> None:
    for ref in (_REF, str(uuid.uuid5(uuid.NAMESPACE_DNS, "candleviewer.example"))):
        require_client_ref(ref)
        assert re.fullmatch(models.GROUP_REF_PATTERN, ref)


@pytest.mark.parametrize(
    ("over", "rule"),
    [
        ({"request_sha256": _SHA.upper()}, "sha256_hex"),
        ({"request_sha256": _SHA[:-1]}, "sha256_hex"),
        ({"trade_group_id": None}, "ia_target"),
        ({"order_id": _ORDER}, "ia_target"),
        ({"operation": "cancelOrder"}, "ia_operation"),
    ],
)
def test_an_anchor_the_table_would_refuse_is_refused_before_any_statement(
    over: dict[str, Any], rule: str
) -> None:
    with pytest.raises(ValueError, match=rule):
        _anchor(**over)


def test_a_position_route_may_anchor_no_target_but_never_two() -> None:
    _anchor(operation="closeAllPositions", trade_group_id=None)
    with pytest.raises(ValueError, match="ia_target"):
        _anchor(operation="closePosition", order_id=_ORDER)


@pytest.mark.parametrize(
    ("over", "rule"),
    [
        ({"status": 429}, "ia_code"),
        ({"status": 202, "code": "conflict"}, "ia_code"),
        ({"status": 502, "code": "Exchange-Error"}, "ia_code"),
        ({"status": 429, "code": "exchange_rate_limited", "ret_code": 10006}, "ia_ret_code"),
        ({"status": 502, "code": "exchange_error", "ret_code": 2**31}, "the column holds"),
        ({"status": 500, "code": "internal_error"}, "ia_decided"),
        ({"decided_at": datetime(2026, 10, 21)}, "timezone-aware"),
    ],
)
def test_an_outcome_the_table_would_refuse_is_refused(over: dict[str, Any], rule: str) -> None:
    values: dict[str, Any] = {"status": 202, "decided_at": _T} | over
    with pytest.raises(ValueError, match=rule):
        AnchorOutcome(**values)


def test_the_row_allow_list_never_reads_the_key_or_the_fingerprint() -> None:
    table = [c.name for c in models.idempotency_anchors.columns]
    assert list(mod.ANCHOR_FIELDS) == [
        c for c in table if c not in ("client_ref", "request_sha256")
    ]
    assert [f.name for f in fields(AnchorRow)] == [*mod.ANCHOR_FIELDS, "body_matches"]


def test_find_is_scoped_to_the_principal_and_operation_and_compares_the_fingerprint_in_sql() -> (
    None
):
    stmt = mod.find_statement(_USER, "placeOrder", _REF, _SHA)
    sql = _sql(stmt)
    selected = sql.split(" FROM ", 1)[0]
    assert "client_ref" not in selected and "request_sha256 = " in selected
    assert sql.endswith(
        "WHERE idempotency_anchors.created_by = $2::UUID AND idempotency_anchors.operation = $3::"
        "VARCHAR AND idempotency_anchors.client_ref = $4::VARCHAR"
    )
    assert list(_params(stmt).values()) == [_SHA, _USER, "placeOrder", _REF]


def test_the_insert_writes_nothing_for_a_held_key_and_returns_the_id() -> None:
    sql = _sql(mod.insert_anchor_statement(_anchor()))
    assert sql.endswith(
        "ON CONFLICT (created_by, operation, client_ref) DO NOTHING "
        "RETURNING idempotency_anchors.id"
    )


def test_the_outcome_is_a_compare_and_set_from_null_keyed_by_the_anchor_id_alone() -> None:
    outcome = AnchorOutcome(status=502, code="exchange_error", ret_code=110007, decided_at=_T)
    sql = _sql(mod.record_outcome_statement(_ANCHOR, outcome))
    assert sql.startswith(
        "UPDATE idempotency_anchors SET outcome_status=$1::SMALLINT, outcome_code=$2::VARCHAR, "
        "outcome_ret_code=$3::INTEGER, decided_at=$4::TIMESTAMP WITH TIME ZONE"
    )
    assert sql.endswith(
        "WHERE idempotency_anchors.id = $5::UUID AND idempotency_anchors.outcome_status IS NULL "
        "RETURNING idempotency_anchors.id"
    )
    builders = {name for name in vars(mod) if name.endswith("_statement")}
    unscoped = {name for name in builders if "created_by" not in _sql(_built(name))}
    assert unscoped == set(mod.BY_ID) == {"record_outcome_statement"}


def _built(name: str) -> Any:
    outcome = AnchorOutcome(status=202, decided_at=_T)
    builders: dict[str, Callable[[], Any]] = {
        "find_statement": lambda: mod.find_statement(_USER, "placeOrder", _REF, _SHA),
        "insert_anchor_statement": lambda: mod.insert_anchor_statement(_anchor()),
        "record_outcome_statement": lambda: mod.record_outcome_statement(_ANCHOR, outcome),
    }
    return builders[name]()


class _Rel:
    """Scripted unit of work: the cap is answered apart; each other statement takes the next
    result (a list of mappings) or raises it; commits are counted."""

    def __init__(self, *script: list[dict[str, Any]] | BaseException) -> None:
        self.script = list(script)
        self.statements: list[Any] = []
        self.commits = 0

    @asynccontextmanager
    async def unit_of_work(self) -> AsyncIterator[Any]:
        async def execute(stmt: Any, params: Any = None) -> Any:
            if isinstance(stmt, TextClause):
                return None
            self.statements.append(stmt)
            item = self.script.pop(0)
            if isinstance(item, BaseException):
                raise item
            rows = item
            return SimpleNamespace(
                mappings=lambda: SimpleNamespace(first=lambda: rows[0] if rows else None),
                first=lambda: rows[0] if rows else None,
            )

        async def commit() -> None:
            self.commits += 1

        yield SimpleNamespace(session=SimpleNamespace(execute=execute), commit=commit)


def _store(rel: _Rel) -> mod.SqlAlchemyIdempotencyAnchorStore:
    return mod.SqlAlchemyIdempotencyAnchorStore(cast(Any, rel))  # structural fake


async def test_find_maps_the_row_and_reads_absence_as_none() -> None:
    row = {name: None for name in mod.ANCHOR_FIELDS} | {
        "id": str(_ANCHOR), "created_by": _USER, "operation": "placeOrder", "order_id": str(_ORDER),
        "created_at": _T, "body_matches": True,
    }  # fmt: skip
    rel = _Rel([row], [])
    found = await _store(rel).find(_USER, "placeOrder", _REF, _SHA)
    assert found is not None and (found.id, found.order_id) == (_ANCHOR, _ORDER)
    assert found.body_matches is True and found.trade_group_id is None
    assert await _store(rel).find(_USER, "placeOrder", _REF, _SHA) is None
    assert rel.commits == 0


async def test_find_refuses_a_key_the_column_could_not_hold_before_any_statement() -> None:
    rel = _Rel()
    with pytest.raises(ValueError, match="ia_ref_fmt"):
        await _store(rel).find(_USER, "placeOrder", _REF.upper(), _SHA)
    assert rel.statements == []


async def test_the_outcome_is_recorded_once() -> None:
    rel = _Rel([{"id": _ANCHOR}], [])
    store, outcome = _store(rel), AnchorOutcome(status=202, decided_at=_T)
    assert await store.record_outcome(_ANCHOR, outcome) is True
    assert await store.record_outcome(_ANCHOR, outcome) is False
    assert rel.commits == 2


async def test_a_refused_outcome_leaves_as_its_constraint_name_with_no_value() -> None:
    orig = SimpleNamespace(sqlstate="23514", constraint_name="trg_ia_write_once")
    error = IntegrityError("UPDATE ... 110007", {"p": "110007"}, cast(Any, orig))
    with pytest.raises(OrderConstraintError) as exc:
        await _store(_Rel(error)).record_outcome(_ANCHOR, AnchorOutcome(status=202, decided_at=_T))
    assert exc.value.constraint == "trg_ia_write_once" and "110007" not in str(exc.value)
    assert exc.value.__cause__ is None and exc.value.__suppress_context__

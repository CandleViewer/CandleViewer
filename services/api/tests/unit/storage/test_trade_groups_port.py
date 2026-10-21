"""The trade-group store port, without a database (E28-T01 #905).

The JSON codec of `algo_params` and `profile_snapshot`, the write dataclasses' refusals and the
snapshot check run here; the port's names, literals, column lists and status sets are pinned to
`db.models`, the 0039 revision and 21-database-schema.md Sec.3.3.2, and its imports to the stdlib
and the driver-free sibling ports. The adapter's statements and paths are
`test_trade_groups_store.py`'s; real SQL is `tests/integration/storage/` (CI only).
"""

from __future__ import annotations

import ast
import importlib.util
import re
import sys
from collections.abc import Callable
from dataclasses import MISSING, fields
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, get_args
from uuid import UUID

import pytest
from sqlalchemy import CheckConstraint, Column, DateTime, Numeric, Table, UniqueConstraint
from sqlalchemy.dialects.postgresql import DOMAIN, ENUM

from candleviewer.db import models
from candleviewer.storage.repositories import orders
from candleviewer.storage.repositories import trade_groups as port
from candleviewer.storage.repositories.trade_groups import (
    ACCOUNT_NOT_LIVE,
    CREATE_ONLY_GROUP_COLUMNS,
    DEFINITION_NOT_LIVE,
    GROUP_PATCH_COLUMNS,
    LEG_PATCH_COLUMNS,
    MAX_DEPTH,
    MAX_PAYLOAD_CHARS,
    NO_STOP_LEG_STATUSES,
    OPEN_GROUP_STATUSES,
    PROFILE_CHANGED,
    TRADE_GROUP_CONFLICTS,
    TRADE_GROUP_RULES,
    UNPROTECTED_LEG_STATUSES,
    WRITE_ONCE_GROUP_COLUMNS,
    WRITE_ONCE_LEG_COLUMNS,
    AlgoKind,
    EntryType,
    ExchangeEnv,
    GroupOrigin,
    GroupPatch,
    JsonObject,
    LegFailurePolicy,
    LegPatch,
    LegSnapshotRow,
    LegStatus,
    NewTradeGroup,
    NewTradeGroupLeg,
    RequestedQtyMode,
    TradeGroupLegRow,
    TradeGroupRecord,
    TradeGroupRefusal,
    TradeGroupRow,
    TradeGroupStatus,
    TradeGroupStoreConflictError,
    TradeGroupStoreError,
    TradeGroupStoreRefusedError,
    TradeGroupStoreRuleError,
    TradeGroupStoreScopeDeniedError,
    TradeGroupStoreStaleError,
    UnprotectedLegRow,
    parse_json,
    render_json,
)

_API = Path(__file__).resolve().parents[3]
_MIGRATION = _API / "candleviewer" / "migrations" / "versions" / "0039_trade_groups.py"
_DOC = _API.parents[1] / "docs" / "plan" / "21-database-schema.md"
_PROFILES = _API / "tests" / "fixtures" / "profiles"
_TABLES = (models.trade_groups, models.trade_group_legs)

_T = datetime(2026, 10, 20, 9, tzinfo=UTC)
_GROUP, _LEG, _USER, _OTHER = UUID(int=1), UUID(int=2), UUID(int=3), UUID(int=9)
#: The ids and version `risk_based.json` names.
_ACCOUNT = UUID("7d3c9a10-28a1-4c1e-9e01-0000000000a1")
_PROFILE = UUID("0b5f6d0e-28a1-4c1e-9e01-000000000001")
_SNAPSHOT: JsonObject = parse_json((_PROFILES / "risk_based.json").read_text())
_REF = "9b2f7c1e-4d3a-4f6b-8a0c-5e1d2c3b4a59"
_BODY = "ab" * 32  # synthetic 64-hex shape
#: A marker in every P1 value a test hands over: no message or repr may repeat it.
_MARK = "q7z"


def _group(**over: Any) -> NewTradeGroup:
    base: dict[str, Any] = {
        "id": _GROUP, "client_group_ref": _REF, "client_body_sha256": _BODY, "created_by": _USER,
        "env": "demo", "symbol": "BTCUSDT", "side": "Buy", "status": "submitting",
        "leg_failure_policy": "abort_on_first", "algo": "none", "algo_params": None,
        "intent_note": None, "origin": "manual", "origin_rule_id": None,
        "origin_rule_run_id": None, "definition_id": None, "requested_qty_mode": "risk_based",
        "requested_qty_value": Decimal("1"), "entry_type": "Limit",
        "entry_price": Decimal("63099.80"), "trigger_price": None, "trigger_by": None,
        "sl_price_hint": Decimal("62000"), "tp_price_hint": None, "is_paper": False,
    }  # fmt: skip
    return NewTradeGroup(**(base | over))


def _leg(**over: Any) -> NewTradeGroupLeg:
    base: dict[str, Any] = {
        "id": _LEG, "exchange_account_id": _ACCOUNT, "account_profile_id": _PROFILE,
        "profile_version": 3, "profile_snapshot": _SNAPSHOT, "status": "pending",
        "sequence_no": 0, "target_qty": Decimal("0.010"), "resolved_leverage": Decimal("5"),
        "resolved_sl_price": Decimal("62000"), "resolved_tp_price": None,
        "risk_usd": Decimal("11.50"), "rejection_code": None, "rejection_message": None,
    }  # fmt: skip
    return NewTradeGroupLeg(**(base | over))


_GROUP_ROW = TradeGroupRow(
    id=_GROUP, client_group_ref=_REF, definition_id=None, env="demo", symbol="BTCUSDT", side="Buy",
    status="open", leg_failure_policy="all_or_none", algo="twap", algo_params={_MARK: 1},
    intent_note=f"{_MARK} note", origin="manual", origin_rule_id=None, origin_rule_run_id=None,
    requested_qty_mode="risk_based", requested_qty_value=Decimal("1"), entry_type="Market",
    entry_price=None, trigger_price=None, trigger_by=None, sl_price_hint=None, tp_price_hint=None,
    is_paper=False, submitted_at=_T, opened_at=_T, closed_at=None, created_by=_USER,
    created_at=_T, updated_at=_T,
)  # fmt: skip
_LEG_ROW = TradeGroupLegRow(
    id=_LEG, trade_group_id=_GROUP, exchange_account_id=_ACCOUNT, account_profile_id=_PROFILE,
    profile_version=3, status="rejected", sequence_no=0, target_qty=Decimal("0.010"),
    filled_qty=Decimal("0"), avg_entry_price=None, avg_exit_price=None,
    resolved_leverage=Decimal("5"), resolved_sl_price=None, resolved_tp_price=None,
    native_sl_confirmed=False, native_sl_confirmed_at=None, risk_usd=None,
    realised_pnl=Decimal("0"), fees_paid=Decimal("0"), rejection_code=f"{_MARK}-code",
    rejection_message=f"{_MARK} message", submitted_at=None, closed_at=None, created_at=_T,
    updated_at=_T,
)  # fmt: skip


def _nested(levels: int, container: Callable[[object], object] = lambda v: {"k": v}) -> Any:
    """`levels` containers deep: the top-level object, then `container` around the rest."""
    value: object = 1
    for _ in range(levels - 1):
        value = container(value)
    return {"k": value}


def _checks(table: Table) -> dict[str, str]:
    """Every model CHECK of the table by the name the database gives it, the body on one line."""
    return {
        str(c.name).removeprefix(f"ck_{table.name}_"): " ".join(str(c.sqltext).split())
        for c in table.constraints
        if isinstance(c, CheckConstraint)
    }


def _function(name: str) -> str:
    """`CREATE FUNCTION <name>()` of the 0039 revision, up to its closing `END`."""
    return _MIGRATION.read_text().split(f"CREATE FUNCTION {name}() ", 1)[1].split("END $BODY$;")[0]


#: `CREATE TRIGGER <name> BEFORE <events> ON <table> FOR EACH ROW EXECUTE FUNCTION <function>();`
_TRIGGER = re.compile(
    r"CREATE TRIGGER \w+ BEFORE [^;]*?\sON (\w+)\s+FOR EACH ROW EXECUTE FUNCTION (\w+)\(\);"
)


def _trigger_refusals() -> dict[str, set[str]]:
    """Per table, the constraint names its 0039 triggers raise (`USING ... CONSTRAINT`)."""
    sql = _MIGRATION.read_text()
    raised: dict[str, set[str]] = {}
    for table, function in re.findall(_TRIGGER, sql):
        if f"CREATE FUNCTION {function}() " in sql:
            names = re.findall(r"CONSTRAINT = '(\w+)'", _function(function))
            raised.setdefault(table, set()).update(names)
    return raised


# -- the JSON codec --------------------------------------------------------------------------------


def test_render_json_is_compact_and_parse_json_reads_it_back() -> None:
    value: JsonObject = {"legs": [{"qty": "0.010", "n": 2}], "ok": True, "none": None, "s": "é"}
    text = render_json(value)
    assert text == '{"legs":[{"qty":"0.010","n":2}],"ok":true,"none":null,"s":"é"}'
    assert parse_json(text) == value


def test_render_json_takes_max_depth_containers_and_max_payload_chars() -> None:
    for deepest in (_nested(MAX_DEPTH), _nested(MAX_DEPTH, lambda v: [v])):
        assert parse_json(render_json(deepest)) == deepest
    filler = "x" * (MAX_PAYLOAD_CHARS - len('{"k":""}'))
    assert len(render_json({"k": filler})) == MAX_PAYLOAD_CHARS


@pytest.mark.parametrize(
    ("value", "error"),
    [
        ({"px": 7.125}, TypeError),
        ({"px": [1, 7.125]}, TypeError),
        ({"px": float("nan")}, TypeError),
        ({"px": Decimal("7.125")}, TypeError),
        ({71250: _MARK}, TypeError),
        ({"k": {True: _MARK}}, TypeError),
        ({"k": (_MARK,)}, TypeError),
        ({"k": {_MARK}}, TypeError),
        ({"k": _MARK.encode()}, TypeError),
        ([_MARK], TypeError),
        ({"k": f"{_MARK}\x00"}, ValueError),
        ({f"{_MARK}\x00": 1}, ValueError),
        ({"k": f"{_MARK}\ud800"}, ValueError),
        (_nested(MAX_DEPTH + 1), ValueError),
        (_nested(MAX_DEPTH + 1, lambda v: [v]), ValueError),
        ({"k": _MARK * (MAX_PAYLOAD_CHARS // len(_MARK))}, ValueError),
    ],
    ids=[
        "float", "nested-float", "nan", "decimal", "int-key", "bool-key", "tuple", "set", "bytes",
        "top-level-list", "nul", "nul-key", "lone-surrogate", "too-deep", "too-deep-lists",
        "too-long",
    ],
)  # fmt: skip
def test_render_json_refuses_float_decimal_non_str_keys_and_past_bounds(
    value: Any, error: type[Exception]
) -> None:
    with pytest.raises(error) as exc:
        render_json(value)
    message = str(exc.value)
    assert _MARK not in message and "7.125" not in message and "71250" not in message


@pytest.mark.parametrize(
    "text",
    [
        '{"px": 7.125}', '{"px": 7125e-3}', '{"px": 1.0}', '{"px": 1E3}', '{"px": [NaN]}',
        '{"px": Infinity}', '{"px": -Infinity}', f'["{_MARK}"]', f'"{_MARK}"', "7125", "null",
    ],
)  # fmt: skip
def test_parse_json_refuses_fractional_numbers_and_constants(text: str) -> None:
    with pytest.raises(ValueError) as exc:
        parse_json(text)
    message = str(exc.value)
    assert _MARK not in message and "7.125" not in message and "7125" not in message


def test_parse_json_reads_jsonb_text_with_exact_integers() -> None:
    """`jsonb` re-spaces what it stores; integers of any size come back exact."""
    text = '{"n": 123456789012345678901234567890, "xs": [true, false, null], "o": {"s": "0.010"}}'
    assert parse_json(text) == {
        "n": 123456789012345678901234567890,
        "xs": [True, False, None],
        "o": {"s": "0.010"},
    }


@pytest.mark.parametrize("path", sorted(_PROFILES.glob("*.json")), ids=lambda p: p.stem)
def test_a_profile_document_is_a_snapshot_the_port_takes(path: Path) -> None:
    """The `AccountProfile` JSON form (decimals and ids as strings) passes the codec and names
    its own account, profile and version."""
    snapshot = parse_json(path.read_text())
    assert parse_json(render_json(snapshot)) == snapshot
    leg = _leg(
        exchange_account_id=UUID(str(snapshot["account_id"])),
        account_profile_id=UUID(str(snapshot["profile_id"])),
        profile_version=snapshot["version"],
        profile_snapshot=snapshot,
    )
    assert leg.profile_snapshot is snapshot


# -- the write dataclasses ---------------------------------------------------------------------

_BUILDERS: dict[type, Callable[..., object]] = {
    NewTradeGroup: _group,
    NewTradeGroupLeg: _leg,
    LegPatch: LegPatch,
    GroupPatch: GroupPatch,
}
_WRITES = (
    (NewTradeGroup, models.trade_groups),
    (NewTradeGroupLeg, models.trade_group_legs),
    (LegPatch, models.trade_group_legs),
    (GroupPatch, models.trade_groups),
)


def _written(kind: type) -> list[tuple[type, Column[Any]]]:
    """The oracle is the table: every column of `kind`'s SQL type a write dataclass sets."""
    return [
        (cls, column)
        for cls, table in _WRITES
        for column in table.columns
        if isinstance(column.type, kind) and column.name in {f.name for f in fields(cls)}
    ]


_MONEY = _written(Numeric)
_STAMPS = _written(DateTime)


def test_the_oracles_cover_every_money_and_time_column_written() -> None:
    assert len(_MONEY) == 5 + 5 + 5 and len(_STAMPS) == 3 + 3


@pytest.mark.parametrize(
    ("cls", "column"), _MONEY, ids=[f"{c.__name__}.{col.name}" for c, col in _MONEY]
)
def test_port_dataclasses_refuse_float_and_unfit_money(cls: type, column: Column[Any]) -> None:
    numeric = column.type
    assert isinstance(numeric, Numeric) and numeric.precision and numeric.scale is not None
    precision, scale = numeric.precision, numeric.scale
    largest = Decimal(f"{'9' * (precision - scale)}.{'9' * scale}")
    assert getattr(_BUILDERS[cls](**{column.name: largest}), column.name) == largest
    refused = [
        (7.125, TypeError), (7125, TypeError), (Decimal("NaN"), ValueError),
        (Decimal("-Infinity"), ValueError), (Decimal(f"7.{'1' * scale}5"), ValueError),
        (Decimal(f"7{'0' * (precision - scale)}"), ValueError),
    ]  # fmt: skip
    for value, error in refused:
        with pytest.raises(error, match=f"^{column.name} ") as exc:
            _BUILDERS[cls](**{column.name: value})
        assert str(value) not in str(exc.value)  # the column only: a value is P1 (21 Sec.12)


@pytest.mark.parametrize(
    ("cls", "column"), _STAMPS, ids=[f"{c.__name__}.{col.name}" for c, col in _STAMPS]
)
def test_patches_refuse_a_naive_time(cls: type, column: Column[Any]) -> None:
    assert getattr(cls(**{column.name: _T}), column.name) == _T
    with pytest.raises(ValueError, match=f"^{column.name} must be a timezone-aware"):
        cls(**{column.name: datetime(2026, 10, 20, 9)})


def test_new_group_takes_json_algo_params_and_refuses_a_float_in_them() -> None:
    params: JsonObject = {"slices": 4, "interval_s": 30, "max_px": "63100.5"}
    assert _group(algo="twap", algo_params=params).algo_params == params
    assert _group(algo="twap", algo_params={}).algo_params == {}
    with pytest.raises(TypeError, match="float"):
        _group(algo="twap", algo_params={"slices": 4, "participation": 0.125})


@pytest.mark.parametrize(
    "over",
    [
        {"exchange_account_id": _OTHER},
        {"account_profile_id": _OTHER},
        {"profile_version": 4},
        {"profile_snapshot": _SNAPSHOT | {"account_id": str(_OTHER)}},
        {"profile_snapshot": _SNAPSHOT | {"profile_id": str(_ACCOUNT)}},
        {"profile_snapshot": _SNAPSHOT | {"version": 4}},
        {"profile_snapshot": _SNAPSHOT | {"account_id": str(_ACCOUNT).upper()}},
        {"profile_snapshot": {k: v for k, v in _SNAPSHOT.items() if k != "version"}},
        {"profile_snapshot": _SNAPSHOT | {"version": None}},
        {"profile_snapshot": _SNAPSHOT | {"version": [3]}},
        {"profile_snapshot": _SNAPSHOT | {"version": True}, "profile_version": 1},
    ],
    ids=[
        "account", "profile", "version", "snapshot-account", "snapshot-profile",
        "snapshot-version", "upper-case-id", "no-version", "null-version", "list-version",
        "bool-version",
    ],
)  # fmt: skip
def test_new_leg_refuses_a_snapshot_naming_another_account_profile_or_version(
    over: dict[str, Any],
) -> None:
    with pytest.raises(ValueError, match=r"\(tgl_snapshot\)$") as exc:
        _leg(**over)
    assert str(_ACCOUNT) not in str(exc.value) and str(_PROFILE) not in str(exc.value)


def test_new_leg_reads_the_snapshot_as_tgl_snapshot_does() -> None:
    """`->>` compares text, so a version stored as a string passes the database and passes here;
    a float anywhere in the snapshot is refused before that."""
    assert _leg(profile_snapshot=_SNAPSHOT | {"version": "3"}).profile_version == 3
    with pytest.raises(TypeError, match="float"):
        _leg(profile_snapshot=_SNAPSHOT | {"leverage": 5.0})


@pytest.mark.parametrize("cls", [LegPatch, GroupPatch])
def test_empty_patch_is_refused(cls: type) -> None:
    with pytest.raises(ValueError, match="at least one column"):
        cls()
    with pytest.raises(ValueError, match="at least one column"):
        cls(status=None)


def test_confirmed_without_time_is_refused() -> None:
    with pytest.raises(ValueError, match=r"\(tgl_sl_conf\)$"):
        LegPatch(native_sl_confirmed=True)
    confirmed = LegPatch(native_sl_confirmed=True, native_sl_confirmed_at=_T)
    assert confirmed.changes() == {"native_sl_confirmed": True, "native_sl_confirmed_at": _T}
    assert LegPatch(native_sl_confirmed=False).changes() == {"native_sl_confirmed": False}


def test_a_patch_changes_what_it_sets_in_table_order_and_keeps_falsy_values() -> None:
    patch = LegPatch(closed_at=_T, status="closed", fees_paid=Decimal("0"), filled_qty=Decimal(0))
    assert list(patch.changes().items()) == [
        ("status", "closed"),
        ("filled_qty", Decimal(0)),
        ("fees_paid", Decimal("0")),
        ("closed_at", _T),
    ]
    assert GroupPatch(opened_at=_T, status="open").changes() == {"status": "open", "opened_at": _T}


def test_reprs_hide_the_ref_fingerprint_note_params_snapshot_and_rejection_text() -> None:
    values = (
        _group(intent_note=f"{_MARK} note", algo="twap", algo_params={_MARK: 1}),
        _leg(status="rejected", resolved_sl_price=None, rejection_code=f"{_MARK}-code",
             rejection_message=f"{_MARK} message"),
        LegPatch(rejection_code=f"{_MARK}-code", rejection_message=f"{_MARK} message"),
        _GROUP_ROW,
        _LEG_ROW,
        TradeGroupRecord(_GROUP_ROW, (_LEG_ROW,)),
        LegSnapshotRow(_LEG_ROW, _SNAPSHOT),
        UnprotectedLegRow(_LEG_ROW, "BTCUSDT", "Buy", "demo", False),
    )  # fmt: skip
    for value in values:
        text = repr(value)
        assert _MARK not in text and _REF not in text and _BODY not in text
        assert str(_SNAPSHOT["name"]) not in text  # the snapshot's own fields
    assert str(_GROUP) in repr(_GROUP_ROW)  # the ids still show


def test_errors_carry_a_name_never_a_value() -> None:
    conflict = TradeGroupStoreConflictError("ux_tgl_group_account")
    rule = TradeGroupStoreRuleError("tgl_sl_px")
    refused = TradeGroupStoreRefusedError(PROFILE_CHANGED)
    assert (conflict.constraint, str(conflict)) == ("ux_tgl_group_account",) * 2
    assert (rule.rule, str(rule)) == ("tgl_sl_px",) * 2
    assert (refused.reason, str(refused)) == ("profile_changed",) * 2
    for error in (
        conflict,
        rule,
        refused,
        TradeGroupStoreScopeDeniedError(),
        TradeGroupStoreStaleError(),
    ):
        assert isinstance(error, TradeGroupStoreError)
    assert get_args(TradeGroupRefusal) == (ACCOUNT_NOT_LIVE, DEFINITION_NOT_LIVE, PROFILE_CHANGED)


# -- names and literals, pinned to the schema --------------------------------------------------


def test_name_sets_match_the_tables() -> None:
    """Every name a refusal of a store write can carry, as Postgres names it: the model's CHECKs
    without the `ck_<table>_` convention prefix, the triggers' `USING CONSTRAINT` names, the
    domains' unnamed CHECKs (`<domain>_check`), the inline foreign keys and primary keys
    (`<table>_<column>_fkey`, `<table>_pkey`) and the named constraints."""
    checks = {name for table in _TABLES for name in _checks(table)}
    raised = _trigger_refusals()
    triggers = {name for table in _TABLES for name in raised[table.name]}
    domains = {
        f"{c.type.name}_check" for t in _TABLES for c in t.columns if isinstance(c.type, DOMAIN)
    }
    keys = {
        f"{t.name}_{fk.column_keys[0]}_fkey" if len(fk.column_keys) == 1 else str(fk.name)
        for t in _TABLES
        for fk in t.foreign_key_constraints
    }
    assert triggers == {
        "trg_tg_env", "trg_tg_write_once", "trg_tgl_env", "trg_tgl_profile", "trg_tgl_write_once",
    }  # fmt: skip
    assert domains == {"sha256_hex_check", "symbol_code_check"}
    assert TRADE_GROUP_RULES == checks | triggers | domains | keys
    uniques = {
        str(c.name) for t in _TABLES for c in t.constraints if isinstance(c, UniqueConstraint)
    }
    uniques |= {str(ix.name) for t in _TABLES for ix in t.indexes if ix.unique}
    assert TRADE_GROUP_CONFLICTS == uniques | {f"{t.name}_pkey" for t in _TABLES}
    assert not TRADE_GROUP_RULES & TRADE_GROUP_CONFLICTS
    assert not set(get_args(TradeGroupRefusal)) & (TRADE_GROUP_RULES | TRADE_GROUP_CONFLICTS)


@pytest.mark.parametrize(
    ("literal", "column"),
    [
        (TradeGroupStatus, models.trade_groups.c.status),
        (LegStatus, models.trade_group_legs.c.status),
        (AlgoKind, models.trade_groups.c.algo),
        (RequestedQtyMode, models.trade_groups.c.requested_qty_mode),
        (ExchangeEnv, models.trade_groups.c.env),
    ],
    ids=["trade_group_status", "leg_status", "algo_kind", "sizing_mode", "exchange_env"],
)
def test_enum_literals_match_db_models(literal: Any, column: Column[Any]) -> None:
    assert isinstance(column.type, ENUM)
    assert get_args(literal) == tuple(column.type.enums)


@pytest.mark.parametrize(
    ("literal", "check"),
    [
        (port.OrderSide, "tg_side"),
        (GroupOrigin, "tg_origin"),
        (LegFailurePolicy, "tg_policy"),
        (EntryType, "tg_entrytype"),
        (port.TriggerBy, "tg_trigby"),
    ],
)
def test_text_literals_match_their_checks(literal: Any, check: str) -> None:
    body = _checks(models.trade_groups)[check]
    assert set(get_args(literal)) == set(re.findall(r"'(\w+)'", body))


def test_the_failure_policies_are_db_models_in_24s_order() -> None:
    """`LEG_FAILURE_POLICIES` holds 24 Sec.9.1's order (the 0039 unit test pins it to the plan)."""
    assert get_args(LegFailurePolicy) == models.LEG_FAILURE_POLICIES


def test_side_and_trigger_are_the_order_stores_own() -> None:
    assert port.OrderSide is orders.OrderSide and port.TriggerBy is orders.TriggerBy


def test_literals_and_index_constants_match_db_models() -> None:
    where = {
        str(ix.name): str(ix.dialect_options["postgresql"]["where"])
        for table in _TABLES
        for ix in table.indexes
    }
    assert re.fullmatch(r"status IN \(('\w+',?)+\)", where["ix_tg_open"])
    assert set(re.findall(r"'(\w+)'", where["ix_tg_open"])) == OPEN_GROUP_STATUSES
    no_stop, flag = where["ix_tgl_no_sl"].split(" AND ")
    assert flag == "native_sl_confirmed = false"
    assert set(re.findall(r"'(\w+)'", no_stop)) == UNPROTECTED_LEG_STATUSES
    sl_px = _checks(models.trade_group_legs)["tgl_sl_px"]
    assert set(re.findall(r"'(\w+)'", sl_px)) == NO_STOP_LEG_STATUSES
    assert not UNPROTECTED_LEG_STATUSES & NO_STOP_LEG_STATUSES  # an open leg always has a stop


def test_row_dataclasses_list_every_column_but_the_two_exceptions() -> None:
    """`client_body_sha256` is compared in SQL and never read; `profile_snapshot` is read only
    with its leg (`LegSnapshotRow`). A new column fails here until it is decided."""
    group_columns = [c.name for c in models.trade_groups.columns]
    leg_columns = [c.name for c in models.trade_group_legs.columns]
    assert [f.name for f in fields(TradeGroupRow)] == [
        c for c in group_columns if c != "client_body_sha256"
    ]
    assert [f.name for f in fields(TradeGroupLegRow)] == [
        c for c in leg_columns if c != "profile_snapshot"
    ]


def test_inserts_set_every_column_but_what_the_database_or_an_update_writes() -> None:
    group_columns = {c.name for c in models.trade_groups.columns}
    leg_columns = {c.name for c in models.trade_group_legs.columns}
    group_fields = {f.name for f in fields(NewTradeGroup)}
    leg_fields = {f.name for f in fields(NewTradeGroupLeg)}
    assert group_fields <= group_columns and leg_fields <= leg_columns
    assert group_columns - group_fields == {
        "submitted_at", "opened_at", "closed_at", "created_at", "updated_at",
    }  # fmt: skip
    assert leg_columns - leg_fields == {
        "trade_group_id", "filled_qty", "avg_entry_price", "avg_exit_price",
        "native_sl_confirmed", "native_sl_confirmed_at", "realised_pnl", "fees_paid",
        "submitted_at", "closed_at", "created_at", "updated_at",
    }  # fmt: skip


def test_an_insert_takes_no_column_default_by_omission() -> None:
    """Every field is required, so the writer names each column: `leg_failure_policy`'s default
    is only 24 Sec.9.5's manual-ticket one."""
    for cls in (NewTradeGroup, NewTradeGroupLeg):
        assert all(f.default is MISSING and f.default_factory is MISSING for f in fields(cls))
    group = _group()
    named = {f.name: getattr(group, f.name) for f in fields(group)}
    del named["leg_failure_policy"]
    with pytest.raises(TypeError, match="leg_failure_policy"):
        NewTradeGroup(**named)


@pytest.mark.parametrize(
    ("function", "columns"),
    [("tg_write_once", WRITE_ONCE_GROUP_COLUMNS), ("tgl_write_once", WRITE_ONCE_LEG_COLUMNS)],
)
def test_write_once_lists_are_the_triggers_columns(function: str, columns: frozenset[str]) -> None:
    arms = re.findall(r"WHEN NEW\.(\w+) IS DISTINCT FROM OLD\.\1\b", _function(function))
    assert set(arms) == columns and len(arms) == len(columns)


def test_create_only_columns_are_the_plan_docs() -> None:
    (written,) = re.findall(r"([^.]*) are written when the group is created;", _DOC.read_text())
    assert set(re.findall(r"`(\w+)`", written)) == CREATE_ONLY_GROUP_COLUMNS


def test_updates_reach_no_write_once_create_only_or_sized_column() -> None:
    """Every column falls in exactly one class, so a new column forces a decision. The request
    columns and the leg's sized values are amended by E34-S03, never by these updates."""
    request = {
        "algo", "origin_rule_run_id", "requested_qty_mode", "requested_qty_value", "entry_price",
        "trigger_price", "trigger_by", "sl_price_hint", "tp_price_hint", "intent_note",
    }  # fmt: skip
    sized = {
        "resolved_leverage", "resolved_sl_price", "resolved_tp_price", "target_qty", "risk_usd",
        "sequence_no",
    }  # fmt: skip
    touched = {"created_at", "updated_at"}
    group_classes = (
        set(GROUP_PATCH_COLUMNS), WRITE_ONCE_GROUP_COLUMNS, CREATE_ONLY_GROUP_COLUMNS, request,
        touched,
    )  # fmt: skip
    leg_classes = (set(LEG_PATCH_COLUMNS), WRITE_ONCE_LEG_COLUMNS, sized, touched)
    for table, classes in (
        (models.trade_groups, group_classes),
        (models.trade_group_legs, leg_classes),
    ):
        columns = [c.name for c in table.columns]
        assert sorted(columns) == sorted(name for names in classes for name in names)
    assert GROUP_PATCH_COLUMNS == ("status", "submitted_at", "opened_at", "closed_at")
    for patch, table in (
        (LEG_PATCH_COLUMNS, models.trade_group_legs),
        (GROUP_PATCH_COLUMNS, models.trade_groups),
    ):
        assert [c.name for c in table.columns if c.name in patch] == list(patch)  # table order


# -- the boundary: stdlib and driver-free ports only ---------------------------------------------

_DRIVERS = frozenset({"asyncpg", "psycopg", "sqlalchemy", "duckdb", "pyarrow", "questdb"})


def _imports(module: str) -> set[str]:
    """The modules `module`'s source names in an import statement, relative ones resolved."""
    spec = importlib.util.find_spec(module)
    assert spec is not None and spec.origin is not None
    package = module if spec.submodule_search_locations else module.rpartition(".")[0]
    names: set[str] = set()
    for node in ast.walk(ast.parse(Path(spec.origin).read_text())):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            base = package.rsplit(".", node.level - 1)[0] if node.level else ""
            names.add(".".join(part for part in (base, node.module or "") if part))
    return names


def test_the_port_imports_stdlib_and_driver_free_ports_only() -> None:
    """M13 and M20 import the port, and import-linter forbids them any driver, indirectly too."""
    direct = _imports(port.__name__)
    assert {n for n in direct if n.startswith("candleviewer")} == {
        "candleviewer.domain.text",
        "candleviewer.storage.repositories.accounts",
        "candleviewer.storage.repositories.exchange_payload",
        "candleviewer.storage.repositories.orders",
    }
    assert {n.partition(".")[0] for n in direct} - {"candleviewer"} <= sys.stdlib_module_names
    reached, todo = set[str](), [port.__name__]
    while todo:
        module = todo.pop()
        if module not in reached:
            reached.add(module)
            todo += [n for n in _imports(module) if n.startswith("candleviewer.")]
    tops = {n.partition(".")[0] for module in reached for n in _imports(module)}
    assert not tops & _DRIVERS

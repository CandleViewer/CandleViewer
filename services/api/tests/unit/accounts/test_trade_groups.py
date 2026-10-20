"""The 24 Sec.9.1 trade-group models and their row adapter (E28-T01 #905).

The database's rules are pinned on real Postgres by `tests/integration/storage/`; these tests pin
the same rules on the read models (SR-E28-08: every layer), the write models' stricter rules, the
column-to-field mapping and the label maps against `db.models`, the leg snapshot (SR-E28-07,
decision D-10) and the exact round trip draft -> stored row -> model.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import fields
from datetime import UTC, datetime
from decimal import Context, Decimal
from pathlib import Path
from typing import Annotated, Any, get_args, get_origin
from uuid import UUID

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from pydantic import BaseModel, ValidationError
from sqlalchemy import CheckConstraint, Index, Table

from candleviewer.accounts import trade_groups as tg
from candleviewer.accounts.profiles import AccountProfile, TakeProfitRung, to_us
from candleviewer.accounts.trade_groups import (
    GROUP_FIELD_OF,
    LEG_FIELD_OF,
    MAX_NOTE_CHARS,
    GroupReplay,
    GroupUpdate,
    LegDraft,
    LegUpdate,
    LegWithProfile,
    ScopedTradeGroup,
    TakeProfitLeg,
    TradeGroup,
    TradeGroupAggregate,
    TradeGroupDraft,
    TradeGroupLeg,
    TradeGroupWithLegs,
    UnprotectedLeg,
    from_us,
    group_from_row,
    group_patch,
    group_values,
    leg_from_row,
    leg_patch,
    leg_profile_snapshot,
    leg_values,
    record_from_rows,
    shows_private_fields,
    take_profit_ladder,
    unprotected_leg_from_row,
)
from candleviewer.db import models
from candleviewer.domain.primitives import GroupId, Side
from candleviewer.storage.repositories.accounts import GrantScope, OwnerScope
from candleviewer.storage.repositories.trade_groups import (
    NO_STOP_LEG_STATUSES,
    UNPROTECTED_LEG_STATUSES,
    AlgoKind,
    GroupOrigin,
    GroupPatch,
    JsonObject,
    LegFailurePolicy,
    LegPatch,
    LegSnapshotRow,
    LegStatus,
    NewTradeGroup,
    NewTradeGroupLeg,
    TradeGroupLegRow,
    TradeGroupRecord,
    TradeGroupRow,
    TradeGroupStatus,
    UnprotectedLegRow,
    parse_json,
    render_json,
)

_API = Path(__file__).resolve().parents[3]
_FIXTURES = _API / "tests" / "fixtures"
_MODES = ("risk_based", "fixed_qty", "pct_equity", "fixed_notional")
_T = datetime(2026, 10, 20, 9, tzinfo=UTC)
_US = to_us(_T)
_GROUP, _LEG, _USER, _OTHER = UUID(int=1), UUID(int=2), UUID(int=3), UUID(int=9)
_REF = UUID("9b2f7c1e-4d3a-4f6b-8a0c-5e1d2c3b4a59")
_BODY = "ab" * 32  # synthetic 64-hex shape
#: A marker in every P1 value a test hands over: no repr may repeat it.
_MARK = "q7z"
_LEG_STATUSES: tuple[LegStatus, ...] = get_args(LegStatus)
_GROUP_STATUSES: tuple[TradeGroupStatus, ...] = get_args(TradeGroupStatus)


def _profile(mode: str = "risk_based", /, **changes: Any) -> AccountProfile:
    data = json.loads((_FIXTURES / "profiles" / f"{mode}.json").read_text(encoding="utf-8"))
    return AccountProfile.model_validate({**data, **changes})


_P = _profile()

_GROUP_BASE: dict[str, Any] = {
    "group_id": _GROUP, "client_group_ref": _REF, "definition_id": None, "environment": "demo",
    "symbol": "BTCUSDT", "side": "buy", "status": "open", "leg_failure_policy": "best_effort",
    "algo": "none", "algo_params": None, "note": None, "origin": "manual", "rule_id": None,
    "rule_run_id": None, "requested_qty_mode": "risk_based", "requested_qty_value": Decimal("1"),
    "entry_type": "limit", "entry_price": Decimal("63099.8"), "trigger_price": None,
    "trigger_by": None, "sl_price_hint": Decimal("62000"), "tp_price_hint": None,
    "is_paper": False, "submitted_at": _US, "opened_at": _US, "closed_at": None,
    "created_by": _USER, "created_at": _US, "updated_at": _US,
}  # fmt: skip
_LEG_BASE: dict[str, Any] = {
    "leg_id": _LEG, "group_id": _GROUP, "account_id": _P.account_id,
    "account_profile_id": _P.profile_id, "profile_version": 3, "status": "open",
    "sequence_no": 0, "target_qty": Decimal("0.010"), "filled_qty": Decimal("0.004"),
    "avg_entry_price": Decimal("63000"), "avg_exit_price": None, "resolved_leverage": Decimal("5"),
    "resolved_sl_price": Decimal("62000"), "resolved_tp_price": None,
    "native_sl_confirmed": True, "native_sl_confirmed_at": _US, "risk_usd": Decimal("11.5"),
    "realised_pnl": Decimal("0"), "fees_paid": Decimal("0.02"), "rejection_code": None,
    "rejection_message": None, "submitted_at": _US, "closed_at": None, "created_at": _US,
    "updated_at": _US,
}  # fmt: skip
_DRAFT_BASE: dict[str, Any] = {
    "group_id": _GROUP, "client_group_ref": _REF, "client_body_sha256": _BODY,
    "created_by": _USER, "environment": "demo", "symbol": "BTCUSDT", "side": "buy",
    "status": "submitting", "leg_failure_policy": "best_effort", "algo": "none",
    "algo_params": None, "note": None, "origin": "manual", "rule_id": None, "rule_run_id": None,
    "definition_id": None, "requested_qty_mode": "risk_based", "requested_qty_value": Decimal("1"),
    "entry_type": "limit", "entry_price": Decimal("63099.8"), "trigger_price": None,
    "trigger_by": None, "sl_price_hint": Decimal("62000"), "tp_price_hint": None,
    "is_paper": False,
}  # fmt: skip
_LEG_DRAFT_BASE: dict[str, Any] = {
    "leg_id": _LEG, "profile": _P, "status": "pending", "sequence_no": 0,
    "target_qty": Decimal("0.010"), "resolved_leverage": Decimal("5"),
    "resolved_sl_price": Decimal("62000"), "resolved_tp_price": None,
    "risk_usd": Decimal("11.5"), "rejection_code": None, "rejection_message": None,
}  # fmt: skip
_AGGREGATE_BASE: dict[str, Any] = {
    "target_qty": Decimal("0.03"), "filled_qty": Decimal("0.02"),
    "weighted_avg_entry": Decimal("63000"), "total_notional": Decimal("1260"),
    "unrealised_pnl": Decimal("-3.5"), "realised_pnl": Decimal("0"),
    "total_fees": Decimal("0.7"), "total_funding": Decimal("-0.01"), "legs_ok": 2,
    "legs_failed": 1, "legs_skipped": 1,
}  # fmt: skip


def _group(**over: Any) -> TradeGroup:
    return TradeGroup.model_validate(_GROUP_BASE | over)


def _leg(**over: Any) -> TradeGroupLeg:
    return TradeGroupLeg.model_validate(_LEG_BASE | over)


def _draft(**over: Any) -> TradeGroupDraft:
    return TradeGroupDraft.model_validate(_DRAFT_BASE | over)


def _leg_draft(**over: Any) -> LegDraft:
    return LegDraft.model_validate(_LEG_DRAFT_BASE | over)


def _leg_row(**over: Any) -> TradeGroupLegRow:
    """A stored leg of `_P` (its account, profile and version)."""
    base: dict[str, Any] = {
        "id": _LEG, "trade_group_id": _GROUP, "exchange_account_id": _P.account_id,
        "account_profile_id": _P.profile_id, "profile_version": _P.version, "status": "open",
        "sequence_no": 0, "target_qty": Decimal("0.010"), "filled_qty": Decimal("0.010"),
        "avg_entry_price": Decimal("63000"), "avg_exit_price": None,
        "resolved_leverage": Decimal("5.00"), "resolved_sl_price": Decimal("62000"),
        "resolved_tp_price": None, "native_sl_confirmed": False, "native_sl_confirmed_at": None,
        "risk_usd": None, "realised_pnl": Decimal("0"), "fees_paid": Decimal("0"),
        "rejection_code": None, "rejection_message": None, "submitted_at": _T,
        "closed_at": None, "created_at": _T, "updated_at": _T,
    }  # fmt: skip
    return TradeGroupLegRow(**(base | over))


def _group_row(**over: Any) -> TradeGroupRow:
    base: dict[str, Any] = {
        "id": _GROUP, "client_group_ref": str(_REF), "definition_id": None, "env": "demo",
        "symbol": "BTCUSDT", "side": "Sell", "status": "open",
        "leg_failure_policy": "abort_on_first", "algo": "twap",
        "algo_params": {"slices": 4}, "intent_note": "scale in", "origin": "manual",
        "origin_rule_id": None, "origin_rule_run_id": None, "requested_qty_mode": "fixed_qty",
        "requested_qty_value": Decimal("0.03"), "entry_type": "Conditional",
        "entry_price": None, "trigger_price": Decimal("64000"), "trigger_by": "MarkPrice",
        "sl_price_hint": None, "tp_price_hint": None, "is_paper": True, "submitted_at": _T,
        "opened_at": _T, "closed_at": None, "created_by": _USER, "created_at": _T,
        "updated_at": _T,
    }  # fmt: skip
    return TradeGroupRow(**(base | over))


def _snapshot_row(profile: AccountProfile = _P, **over: Any) -> LegSnapshotRow:
    """A stored leg of `profile` with its snapshot, as the store decodes it."""
    snapshot = parse_json(render_json(profile.model_dump(mode="json")))
    leg = _leg_row(
        exchange_account_id=profile.account_id,
        account_profile_id=profile.profile_id,
        profile_version=profile.version,
    )
    return LegSnapshotRow(leg=_replace_leg(leg, **over), profile_snapshot=snapshot)


def _replace_leg(row: TradeGroupLegRow, **over: Any) -> TradeGroupLegRow:
    return TradeGroupLegRow(**({f.name: getattr(row, f.name) for f in fields(row)} | over))


def _checks(table: Table) -> dict[str, str]:
    """Every model CHECK of the table by the name the database gives it, the body on one line."""
    return {
        str(c.name).removeprefix(f"ck_{table.name}_"): " ".join(str(c.sqltext).split())
        for c in table.constraints
        if isinstance(c, CheckConstraint)
    }


def _labels(body: str) -> set[str]:
    return set(re.findall(r"'(\w+)'", body))


def _index_where(table: Table, name: str) -> str:
    (index,) = (i for i in table.indexes if isinstance(i, Index) and i.name == name)
    return " ".join(str(index.dialect_options["postgresql"]["where"]).split())


# -- the mapping, pinned to the tables -----------------------------------------------------------


@pytest.mark.parametrize(
    ("field_of", "table", "model", "exception"),
    [
        (GROUP_FIELD_OF, models.trade_groups, TradeGroup, "client_body_sha256"),
        (LEG_FIELD_OF, models.trade_group_legs, TradeGroupLeg, "profile_snapshot"),
    ],
    ids=["trade_groups", "trade_group_legs"],
)
def test_every_column_is_a_field_or_a_named_exception(
    field_of: Mapping[str, str], table: Table, model: type[BaseModel], exception: str
) -> None:
    """A new column fails here until it is a field or a named exception."""
    columns = [c.name for c in table.columns]
    assert list(field_of) == [c for c in columns if c != exception]
    assert list(field_of.values()) == list(model.model_fields)


def test_the_renames_are_24s_role_names() -> None:
    """The id fields keep 24 Sec.9.1's role names; every other field is its column's name."""
    assert {k: v for k, v in GROUP_FIELD_OF.items() if k != v} == {
        "id": "group_id",
        "env": "environment",
        "intent_note": "note",
        "origin_rule_id": "rule_id",
        "origin_rule_run_id": "rule_run_id",
    }
    assert {k: v for k, v in LEG_FIELD_OF.items() if k != v} == {
        "id": "leg_id",
        "trade_group_id": "group_id",
        "exchange_account_id": "account_id",
    }


@pytest.mark.parametrize(
    ("labels", "inverse", "domain", "check"),
    [
        (tg._SIDE, tg._SIDE_OF, get_args(Side), "tg_side"),
        (tg._ENTRY, tg._ENTRY_OF, get_args(tg.EntryType), "tg_entrytype"),
        (tg._TRIGGER, tg._TRIGGER_OF, get_args(tg.TriggerBy), "tg_trigby"),
    ],
    ids=["side", "entry_type", "trigger_by"],
)
def test_vocabulary_maps_are_bijections_onto_the_checks(
    labels: Mapping[str, str], inverse: Mapping[str, str], domain: tuple[str, ...], check: str
) -> None:
    assert set(labels) == set(domain)
    assert set(labels.values()) == _labels(_checks(models.trade_groups)[check])
    assert len(set(labels.values())) == len(labels)
    assert {column: label for label, column in labels.items()} == inverse


def _literal(model: type[BaseModel], name: str) -> set[str]:
    return set(get_args(model.model_fields[name].annotation))


def test_the_read_models_take_the_columns_literals() -> None:
    assert _literal(TradeGroup, "status") == set(models.TRADE_GROUP_STATUSES)
    assert _literal(TradeGroupLeg, "status") == set(models.LEG_STATUSES)
    assert _literal(TradeGroup, "algo") == set(models.ALGO_KINDS)
    assert _literal(TradeGroup, "requested_qty_mode") == set(models.SIZING_MODES)
    assert _literal(TradeGroup, "origin") == _labels(_checks(models.trade_groups)["tg_origin"])
    for model in (TradeGroup, TradeGroupDraft):  # 24 Sec.9.1's order, as `tg_policy` lists them
        policy = model.model_fields["leg_failure_policy"].annotation
        assert get_args(policy) == models.LEG_FAILURE_POLICIES


# -- the read models repeat the CHECKs ------------------------------------------------------------

_TINY = Decimal("0.000000000000000001")
#: (rule, model, valid changes, invalid changes): each edge passes, the first value past it fails.
_CHECK_CASES: list[tuple[str, str, list[dict[str, Any]], list[dict[str, Any]]]] = [
    (
        "tg_limit_px", "group",
        [{"entry_price": _TINY}, {"entry_type": "market", "entry_price": None},
         {"entry_type": "market", "entry_price": Decimal("-1")}],
        [{"entry_price": None}, {"entry_price": Decimal("0")}, {"entry_price": Decimal("-1")}],
    ),
    (
        "tg_cond_px", "group",
        [{"entry_type": "conditional", "trigger_price": _TINY, "trigger_by": "mark"},
         {"entry_type": "market", "trigger_price": Decimal("-1"), "trigger_by": None}],
        [{"entry_type": "conditional", "trigger_price": Decimal("1"), "trigger_by": None},
         {"entry_type": "conditional", "trigger_price": Decimal("0"), "trigger_by": "last"},
         {"entry_type": "conditional", "trigger_price": None, "trigger_by": "index"}],
    ),
    (
        "tg_times", "group",
        [{"opened_at": _US, "closed_at": _US}, {"opened_at": None, "closed_at": _US}],
        [{"opened_at": _US, "closed_at": _US - 1}],
    ),
    (
        "tgl_qty_pos", "leg",
        [{"target_qty": _TINY, "filled_qty": Decimal("0")}],
        [{"target_qty": Decimal("0"), "filled_qty": Decimal("0")},
         {"target_qty": Decimal("-1"), "filled_qty": Decimal("0")}],
    ),
    (
        "tgl_filled_rng", "leg",
        [{"filled_qty": Decimal("0")}, {"filled_qty": Decimal("0.010")}],
        [{"filled_qty": Decimal("0.010") + _TINY}, {"filled_qty": -_TINY}],
    ),
    ("tgl_seq", "leg", [{"sequence_no": 0}, {"sequence_no": 100}],
     [{"sequence_no": -1}, {"sequence_no": 101}]),
    (
        "tgl_lev", "leg",
        [{"resolved_leverage": Decimal("1")}, {"resolved_leverage": Decimal("100")}],
        [{"resolved_leverage": Decimal("0.99")}, {"resolved_leverage": Decimal("100.01")}],
    ),
    (
        "tgl_sl_conf", "leg",
        [{"native_sl_confirmed": False, "native_sl_confirmed_at": None},
         {"native_sl_confirmed": False, "native_sl_confirmed_at": _US}],
        [{"native_sl_confirmed": True, "native_sl_confirmed_at": None}],
    ),
    ("tgl_fees_nonneg", "leg", [{"fees_paid": Decimal("0")}], [{"fees_paid": -_TINY}]),
    ("tgl_profile_version", "leg", [{"profile_version": 1}], [{"profile_version": 0}]),
    (
        "tgl_sl_px", "leg",
        [{"status": s, "resolved_sl_price": None} for s in sorted(NO_STOP_LEG_STATUSES)]
        + [{"status": "rejected", "resolved_sl_price": Decimal("-1")},
           {"status": "pending", "resolved_sl_price": _TINY}],
        [{"status": s, "resolved_sl_price": None}
         for s in _LEG_STATUSES if s not in NO_STOP_LEG_STATUSES]
        + [{"status": "filled", "resolved_sl_price": Decimal("0")}],
    ),
]  # fmt: skip


@pytest.mark.parametrize(
    ("rule", "model", "valid", "invalid"), _CHECK_CASES, ids=[case[0] for case in _CHECK_CASES]
)
def test_the_read_models_repeat_the_checks(
    rule: str, model: str, valid: list[dict[str, Any]], invalid: list[dict[str, Any]]
) -> None:
    """SR-E28-08: each CHECK holds on the read model, and nothing stricter (`IS TRUE` reads a NULL
    as a refusal, a bare CHECK as a pass)."""
    build = _group if model == "group" else _leg
    table = models.trade_groups if model == "group" else models.trade_group_legs
    assert rule in _checks(table)
    for changes in valid:
        build(**changes)
    for changes in invalid:
        with pytest.raises(ValidationError):
            build(**changes)


def test_a_stored_rejection_code_reads_as_stored_and_a_writer_sets_one_of_1_to_64() -> None:
    """No CHECK bounds the column, so the read model takes any stored code (one it refused would
    fail the C-2.6 scan closed); the writers' models take a 1..64-character taxonomy code."""
    for stored in ("", "x" * 65, "[redacted:oversize]"):
        assert _leg(rejection_code=stored).rejection_code == stored
    for code in ("", "x" * 65):
        with pytest.raises(ValidationError):
            _leg_draft(rejection_code=code)
        with pytest.raises(ValidationError):
            LegUpdate(rejection_code=code)
    assert _leg_draft(rejection_code="x" * 64).rejection_code == "x" * 64


def test_a_rule_refusal_names_its_check_and_no_value() -> None:
    with pytest.raises(ValidationError) as exc:
        _leg(status="open", resolved_sl_price=None)
    assert "(tgl_sl_px)" in str(exc.value)


def _is_decimal(annotation: object) -> bool:
    """`Decimal`, possibly `Annotated` and possibly `| None`."""
    for arg in (annotation, *get_args(annotation)):
        if get_origin(arg) is Annotated:
            arg = get_args(arg)[0]
        if arg is Decimal:
            return True
    return False


def _decimal_fields(model: type[BaseModel]) -> list[str]:
    return [name for name, info in model.model_fields.items() if _is_decimal(info.annotation)]


_FLOAT_CASES: list[tuple[type[BaseModel], dict[str, Any]]] = [
    (TradeGroup, _GROUP_BASE),
    (TradeGroupLeg, _LEG_BASE),
    (TradeGroupDraft, _DRAFT_BASE),
    (LegDraft, _LEG_DRAFT_BASE),
    (LegUpdate, {"status": "open"}),
    (TakeProfitLeg, {"price": Decimal("65000"), "qty_pct": Decimal("0.5")}),
    (TradeGroupAggregate, _AGGREGATE_BASE),
]


@pytest.mark.parametrize(
    ("model", "base"), _FLOAT_CASES, ids=[case[0].__name__ for case in _FLOAT_CASES]
)
def test_float_is_refused_by_every_decimal_field(
    model: type[BaseModel], base: dict[str, Any]
) -> None:
    """C2: a float is refused even where its value would be valid, never converted."""
    names = _decimal_fields(model)
    assert names
    for name in names:
        value = base.get(name)
        valid = float(value) if value is not None else 1.0
        model.model_validate(base | {name: Decimal(str(valid))})  # the same value as a Decimal
        with pytest.raises(ValidationError, match="never a float"):
            model.model_validate(base | {name: valid})


_EDGE = Decimal("99999999999999999999.999999999999999999")  # 20 whole digits, 18 places
_MONEY_CASES: list[tuple[type[BaseModel], dict[str, Any], str]] = [
    (TradeGroup, _GROUP_BASE, "sl_price_hint"),
    (TradeGroup, _GROUP_BASE, "requested_qty_value"),
    (TradeGroupLeg, _LEG_BASE | {"filled_qty": Decimal("0")}, "target_qty"),
    (TradeGroupLeg, _LEG_BASE, "avg_exit_price"),
    (TradeGroupLeg, _LEG_BASE, "realised_pnl"),
    (TradeGroupDraft, _DRAFT_BASE, "entry_price"),
    (LegDraft, _LEG_DRAFT_BASE, "risk_usd"),
    (LegUpdate, {}, "avg_entry_price"),
    (TakeProfitLeg, {"qty_pct": Decimal("1")}, "price"),
]


@pytest.mark.parametrize(
    ("model", "base", "field"),
    _MONEY_CASES,
    ids=[f"{case[0].__name__}.{case[2]}" for case in _MONEY_CASES],
)
def test_a_value_its_column_would_round_is_refused(
    model: type[BaseModel], base: dict[str, Any], field: str
) -> None:
    """numeric(38,18): 18 places and 20 whole digits fit; one more of either would be rounded or
    refused by Postgres, so the model refuses it. Trailing zeros need no scale."""
    for fits in (_EDGE, Decimal("1.0000000000000000000000"), Decimal("1E+19")):
        assert getattr(model.model_validate(base | {field: fits}), field) == fits
    for unfit in (Decimal("1.0000000000000000001"), Decimal("100000000000000000000")):
        with pytest.raises(ValidationError, match=r"numeric\(38,18\)"):
            model.model_validate(base | {field: unfit})


@pytest.mark.parametrize(
    ("model", "base"),
    [(TradeGroupLeg, _LEG_BASE), (LegDraft, _LEG_DRAFT_BASE)],
    ids=["TradeGroupLeg", "LegDraft"],
)
def test_resolved_leverage_fits_numeric_10_2(model: type[BaseModel], base: dict[str, Any]) -> None:
    for fits in ("99.99", "12.500", "1"):
        model.model_validate(base | {"resolved_leverage": Decimal(fits)})
    with pytest.raises(ValidationError, match=r"numeric\(10,2\)"):
        model.model_validate(base | {"resolved_leverage": Decimal("5.001")})


@pytest.mark.parametrize("value", ["NaN", "Infinity", "-Infinity", "sNaN"])
def test_no_money_value_is_nan_or_infinite(value: str) -> None:
    """`tg_finite` and `tgl_finite` refuse NaN in the database; the models refuse every
    non-finite value."""
    with pytest.raises(ValidationError):
        _group(sl_price_hint=value)
    with pytest.raises(ValidationError):
        _leg(realised_pnl=value)
    with pytest.raises(ValidationError):
        TradeGroupAggregate.model_validate(_AGGREGATE_BASE | {"total_funding": value})


# -- the write models ------------------------------------------------------------------------------

_NESTED_OK: JsonObject = {"k": {"k": {"k": {"k": {"k": {"k": {"k": {"k": 1}}}}}}}}
_NESTED_TOO_DEEP: JsonObject = {"k": _NESTED_OK}

_DRAFT_REFUSALS: list[tuple[str, dict[str, Any], str]] = [
    ("algo-none-with-params", {"algo_params": {"slices": 3}}, "algo none takes no algo_params"),
    ("replay-sim-live", {"origin": "replay_sim"}, "replay_sim group is a paper group"),
    ("rule-without-rule-id", {"origin": "rule"}, "rule_id is set exactly"),
    ("rule-id-without-rule", {"rule_id": _OTHER}, "rule_id is set exactly"),
    ("run-without-rule", {"rule_run_id": _OTHER}, "rule_run_id is set only"),
    ("note-too-long", {"note": "x" * (MAX_NOTE_CHARS + 1)}, "280 characters"),
    ("note-nul", {"note": f"{_MARK}\x00"}, "U+0000"),
    ("note-surrogate", {"note": f"{_MARK}\ud800"}, "unicode"),  # pydantic's own refusal
    ("params-float", {"algo": "twap", "algo_params": {"px": 7.125}}, "algo_params"),
    ("params-decimal", {"algo": "twap", "algo_params": {"px": Decimal("7.125")}}, "algo_params"),
    ("params-whole-float", {"algo": "twap", "algo_params": {"n": 2.0}}, "algo_params"),
    ("params-too-deep", {"algo": "twap", "algo_params": _NESTED_TOO_DEEP}, "nests deeper"),
    ("params-nul-key", {"algo": "twap", "algo_params": {"\x00": 1}}, "U+0000"),
    ("fingerprint-upper", {"client_body_sha256": "AB" * 32}, "client_body_sha256"),
    ("fingerprint-short", {"client_body_sha256": "ab" * 31}, "client_body_sha256"),
    ("symbol-lower", {"symbol": "btcusdt"}, "symbol"),
    ("limit-without-price", {"entry_price": None}, "tg_limit_px"),
    ("conditional-without-trigger-by",
     {"entry_type": "conditional", "trigger_price": Decimal("1")}, "tg_cond_px"),
    ("policy-unknown", {"leg_failure_policy": "compensate"}, "leg_failure_policy"),
    ("policy-null", {"leg_failure_policy": None}, "leg_failure_policy"),
]  # fmt: skip


@pytest.mark.parametrize(
    ("changes", "message"),
    [case[1:] for case in _DRAFT_REFUSALS],
    ids=[case[0] for case in _DRAFT_REFUSALS],
)
def test_draft_rules(changes: dict[str, Any], message: str) -> None:
    """The write model refuses what the database cannot state (24 Sec.9.1 "As built"), and
    whatever the store's codec or a CHECK would refuse, before any statement."""
    with pytest.raises(ValidationError, match=re.escape(message)):
        _draft(**changes)


def test_draft_rules_accept_what_they_allow() -> None:
    rule = _draft(origin="rule", rule_id=_OTHER, rule_run_id=UUID(int=10))
    assert (rule.rule_id, rule.rule_run_id) == (_OTHER, UUID(int=10))
    assert _draft(origin="replay_sim", is_paper=True).is_paper
    assert _draft(algo="twap", algo_params=_NESTED_OK).algo_params == _NESTED_OK
    assert _draft(algo="iceberg", algo_params=None).algo_params is None
    assert _draft(note="x" * MAX_NOTE_CHARS).note == "x" * MAX_NOTE_CHARS
    assert _draft(algo="oco", algo_params={"ok": True, "n": -3, "s": "7.125", "x": None})


def test_a_draft_names_its_failure_policy() -> None:
    """The column default is only 24 Sec.9.5's manual-ticket default, so a draft never takes it by
    omission (the fan-out applies Sec.9.5's default for the origin); each policy reaches the
    stored values unchanged, whatever the origin."""
    unnamed = {k: v for k, v in _DRAFT_BASE.items() if k != "leg_failure_policy"}
    with pytest.raises(ValidationError, match=r"leg_failure_policy\s+Field required"):
        TradeGroupDraft.model_validate(unnamed)
    for policy in models.LEG_FAILURE_POLICIES:
        for origin in ("manual", "rule"):
            rule_id = _OTHER if origin == "rule" else None
            draft = _draft(leg_failure_policy=policy, origin=origin, rule_id=rule_id)
            assert group_values(draft).leg_failure_policy == policy


def test_leg_draft_requires_a_stop_unless_rejected_cancelled_or_failed() -> None:
    for status in _LEG_STATUSES:
        if status in NO_STOP_LEG_STATUSES:
            assert _leg_draft(status=status, resolved_sl_price=None).resolved_sl_price is None
        else:
            with pytest.raises(ValidationError, match="tgl_sl_px"):
                _leg_draft(status=status, resolved_sl_price=None)


@pytest.mark.parametrize("mode", _MODES)
def test_leg_draft_takes_account_profile_version_and_snapshot_from_its_profile(
    mode: str,
) -> None:
    profile = _profile(mode)
    values = leg_values(_leg_draft(profile=profile))
    assert (values.exchange_account_id, values.account_profile_id, values.profile_version) == (
        profile.account_id,
        profile.profile_id,
        profile.version,
    )
    assert values.profile_snapshot == profile.model_dump(mode="json")
    assert parse_json(render_json(values.profile_snapshot)) == values.profile_snapshot


def test_a_leg_draft_whose_snapshot_cannot_be_stored_is_refused() -> None:
    """`jsonb` refuses U+0000; the draft refuses it before any statement."""
    with pytest.raises(ValidationError, match="U\\+0000"):
        _leg_draft(profile=_profile(name=f"{_MARK}\x00"))


def test_group_values_are_the_columns_in_their_labels() -> None:
    draft = _draft(
        side="sell", entry_type="conditional", entry_price=None, trigger_price=Decimal("64000"),
        trigger_by="index", note=f"{_MARK} note", algo="twap", algo_params={"slices": 4},
        definition_id=_OTHER, leg_failure_policy="all_or_none",
    )  # fmt: skip
    values = group_values(draft)
    assert isinstance(values, NewTradeGroup)
    assert (values.side, values.entry_type, values.trigger_by) == (
        "Sell",
        "Conditional",
        "IndexPrice",
    )
    assert values.client_group_ref == str(_REF) == str(_REF).lower()
    assert (values.id, values.env, values.intent_note, values.definition_id) == (
        _GROUP,
        "demo",
        f"{_MARK} note",
        _OTHER,
    )
    assert values.algo_params == {"slices": 4}
    assert values.leg_failure_policy == "all_or_none"


@pytest.mark.parametrize("model", [LegUpdate, GroupUpdate])
def test_an_update_that_sets_nothing_is_refused(model: type[BaseModel]) -> None:
    with pytest.raises(ValidationError, match="at least one field"):
        model.model_validate({})
    with pytest.raises(ValidationError, match="at least one field"):
        model.model_validate({"status": None})


def test_update_rules() -> None:
    with pytest.raises(ValidationError, match="tgl_sl_conf"):
        LegUpdate(native_sl_confirmed=True)
    assert LegUpdate(native_sl_confirmed=False).native_sl_confirmed is False
    with pytest.raises(ValidationError, match="tg_times"):
        GroupUpdate(opened_at=_US, closed_at=_US - 1)
    assert GroupUpdate(closed_at=_US - 1).closed_at == _US - 1  # opened_at is the database's
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        LegUpdate.model_validate({"status": "open", "target_qty": "1"})  # sized: E34-S03's
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        GroupUpdate.model_validate({"status": "open", "leg_failure_policy": "all_or_none"})


def test_patches_carry_the_update_in_stored_units() -> None:
    patch = leg_patch(
        LegUpdate(
            status="filled", filled_qty=Decimal("0.010"), native_sl_confirmed=True,
            native_sl_confirmed_at=_US, rejection_code=f"{_MARK}", submitted_at=_US - 5,
        )
    )  # fmt: skip
    assert isinstance(patch, LegPatch)
    assert patch.changes() == {
        "status": "filled",
        "filled_qty": Decimal("0.010"),
        "native_sl_confirmed": True,
        "native_sl_confirmed_at": _T,
        "rejection_code": _MARK,
        "submitted_at": from_us(_US - 5),
    }
    group = group_patch(GroupUpdate(status="closed", opened_at=_US, closed_at=_US))
    assert isinstance(group, GroupPatch)
    assert group.changes() == {"status": "closed", "opened_at": _T, "closed_at": _T}
    assert leg_patch(LegUpdate(native_sl_confirmed=False)).changes() == {
        "native_sl_confirmed": False
    }


def test_every_leg_update_field_is_a_patch_column() -> None:
    """An update reaches no write-once, create-only or sized column: its fields are the port's
    patch columns, which the store's statement tests bound."""
    assert set(LegUpdate.model_fields) == {f.name for f in fields(LegPatch)}
    assert set(GroupUpdate.model_fields) == {f.name for f in fields(GroupPatch)}


@settings(max_examples=200, deadline=None)
@given(us=st.integers(min_value=-(2**40), max_value=253_402_300_799_999_999))
def test_times_round_trip_exactly(us: int) -> None:
    moment = from_us(us)
    assert moment.tzinfo is UTC and to_us(moment) == us


# -- the leg snapshot (SR-E28-07, D-10) ------------------------------------------------------------

_SECRET_SHAPED = re.compile(r"secret|key|token|password|nonce|dek|kek|signature|cipher|enc", re.I)


def _walk(value: object) -> list[object]:
    if isinstance(value, dict):
        return [*value, *(item for v in value.values() for item in _walk(v))]
    if isinstance(value, list):
        return [item for v in value for item in _walk(v)]
    return [value]


def test_leg_snapshot_carries_no_secret_material() -> None:
    """SR-E28-07, PF-I04: the snapshot is the `AccountProfile` projection and nothing else; no
    name in it can be key material, and no number in it is a float."""
    snapshot = leg_values(_leg_draft()).profile_snapshot
    assert set(snapshot) == set(AccountProfile.model_fields)
    names = set(snapshot) | set(TakeProfitRung.model_fields)
    assert not {name for name in names if _SECRET_SHAPED.search(name)}
    assert not any(isinstance(item, float) for item in _walk(snapshot))
    for name in _decimal_fields(AccountProfile):
        assert snapshot[name] is None or isinstance(snapshot[name], str)
    assert isinstance(snapshot["profile_id"], str) and isinstance(snapshot["version"], int)


@pytest.mark.parametrize(
    "over",
    [
        {"exchange_account_id": _OTHER},
        {"account_profile_id": _OTHER},
        {"profile_version": _P.version + 1},
    ],
    ids=["another-account", "another-profile", "another-version"],
)
def test_leg_profile_snapshot_refuses_another_account_profile_or_version(
    over: dict[str, Any],
) -> None:
    with pytest.raises(ValueError, match="tgl_snapshot"):
        leg_profile_snapshot(_snapshot_row(**over))


def test_leg_profile_snapshot_reads_the_profile_it_was_sized_from() -> None:
    assert leg_profile_snapshot(_snapshot_row()) == _P
    gone = _snapshot_row(account_profile_id=None)  # its profile row was deleted: SET NULL
    assert leg_profile_snapshot(gone) == _P


def test_leg_profile_snapshot_refuses_a_document_that_is_not_a_profile() -> None:
    row = _snapshot_row()
    broken = {k: v for k, v in row.profile_snapshot.items() if k != "sl_offset_unit"}
    with pytest.raises(ValueError):
        leg_profile_snapshot(LegSnapshotRow(leg=row.leg, profile_snapshot=broken))


def test_golden_leg_snapshots_still_validate() -> None:
    """D-10: every snapshot written by this release reads back. A later `AccountProfile` change
    keeps them valid (and their values unchanged) or ships a read-side upcaster with a new
    golden file; this file is never regenerated to pass."""
    path = _FIXTURES / "trade_groups" / "leg_snapshots_v1.json"
    golden: dict[str, JsonObject] = json.loads(path.read_text(encoding="utf-8"))
    assert sorted(golden) == sorted(_MODES)
    for mode, snapshot in golden.items():
        stored = parse_json(render_json(snapshot))
        leg = _leg_row(
            exchange_account_id=UUID(str(stored["account_id"])),
            account_profile_id=UUID(str(stored["profile_id"])),
            profile_version=stored["version"],
        )
        profile = leg_profile_snapshot(LegSnapshotRow(leg=leg, profile_snapshot=stored))
        assert profile.sizing_mode == mode
        dumped = profile.model_dump(mode="json")
        assert {key: dumped[key] for key in snapshot} == snapshot


# -- the round trip: draft -> stored row -> model -------------------------------------------------

_SCALE_18 = Decimal(1).scaleb(-18)
_SCALE_2 = Decimal(1).scaleb(-2)
_NUMERIC = Context(prec=60)


def _as_numeric(value: object, scale: Decimal = _SCALE_18) -> object:
    """What Postgres returns for a numeric(p, s) value: the same number at the column's scale."""
    return value.quantize(scale, context=_NUMERIC) if isinstance(value, Decimal) else value


def _stored_group(values: NewTradeGroup) -> TradeGroupRow:
    """What the store reads back after inserting `values`: the times are the database's, money
    comes back at scale 18 and `algo_params` through the JSON codec."""
    row: dict[str, Any] = {
        f.name: _as_numeric(getattr(values, f.name, None)) for f in fields(TradeGroupRow)
    }
    row |= {"submitted_at": None, "opened_at": None, "closed_at": None}
    row |= {"created_at": _T, "updated_at": _T}
    if values.algo_params is not None:
        row["algo_params"] = parse_json(render_json(values.algo_params))
    return TradeGroupRow(**row)


def _stored_leg(values: NewTradeGroupLeg, group_id: UUID) -> TradeGroupLegRow:
    """What the store reads back after inserting `values`: the database's defaults, money at the
    column's scale."""
    defaults: dict[str, Any] = {
        "trade_group_id": group_id, "filled_qty": Decimal(0), "avg_entry_price": None,
        "avg_exit_price": None, "native_sl_confirmed": False, "native_sl_confirmed_at": None,
        "realised_pnl": Decimal(0), "fees_paid": Decimal(0), "submitted_at": None,
        "closed_at": None, "created_at": _T, "updated_at": _T,
    }  # fmt: skip
    row: dict[str, Any] = {
        f.name: _as_numeric(getattr(values, f.name)) if hasattr(values, f.name) else None
        for f in fields(TradeGroupLegRow)
    }
    row = row | defaults
    row["resolved_leverage"] = _as_numeric(values.resolved_leverage, _SCALE_2)
    return TradeGroupLegRow(**row)


_STORABLE = st.characters(codec="utf-8", exclude_characters="\x00")  # no lone surrogate
#: At most 28 significant digits: hypothesis scales its draws in the default 28-digit context, so
#: a wider bound comes back rounded (the 38-digit edge is pinned by its own test below).
_WIDE = Decimal("9999999999.999999999999999999")
_MONEY = st.decimals(min_value=_TINY, max_value=_WIDE, places=18)
_SIGNED_MONEY = st.decimals(min_value=_WIDE.copy_negate(), max_value=_WIDE, places=18)
_JSON_SCALAR = st.none() | st.booleans() | st.integers() | st.text(_STORABLE, max_size=8)
_PARAMS = st.dictionaries(st.text(_STORABLE, max_size=8), _JSON_SCALAR, max_size=4)


@st.composite
def _drafts(draw: st.DrawFn) -> TradeGroupDraft:
    entry: tg.EntryType = draw(st.sampled_from(get_args(tg.EntryType)))
    origin: GroupOrigin = draw(st.sampled_from(get_args(GroupOrigin)))
    algo: AlgoKind = draw(st.sampled_from(get_args(AlgoKind)))
    triggers = st.sampled_from(get_args(tg.TriggerBy))
    rule = origin == "rule"
    conditional = entry == "conditional"
    return TradeGroupDraft.model_validate(
        {
            "group_id": UUID(int=draw(st.integers(min_value=1, max_value=2**128 - 1))),
            "client_group_ref": UUID(int=draw(st.integers(min_value=0, max_value=2**128 - 1))),
            "client_body_sha256": draw(st.text("0123456789abcdef", min_size=64, max_size=64)),
            "created_by": _USER,
            "environment": draw(st.sampled_from(["live", "demo", "testnet"])),
            "symbol": draw(st.from_regex(r"\A[A-Z0-9]{4,20}\Z")),
            "side": draw(st.sampled_from(["buy", "sell"])),
            "status": draw(st.sampled_from(_GROUP_STATUSES)),
            "leg_failure_policy": draw(st.sampled_from(get_args(LegFailurePolicy))),
            "algo": algo,
            "algo_params": None if algo == "none" else draw(st.none() | _PARAMS),
            "note": draw(st.none() | st.text(_STORABLE, max_size=MAX_NOTE_CHARS)),
            "origin": origin,
            "rule_id": _OTHER if rule else None,
            "rule_run_id": draw(st.none() | st.just(UUID(int=10))) if rule else None,
            "definition_id": draw(st.none() | st.just(UUID(int=11))),
            "requested_qty_mode": draw(st.sampled_from(sorted(models.SIZING_MODES))),
            "requested_qty_value": draw(st.none() | _SIGNED_MONEY),
            "entry_type": entry,
            "entry_price": draw(_MONEY if entry == "limit" else st.none() | _SIGNED_MONEY),
            "trigger_price": draw(_MONEY if conditional else st.none() | _SIGNED_MONEY),
            "trigger_by": draw(triggers if conditional else st.none() | triggers),
            "sl_price_hint": draw(st.none() | _MONEY),
            "tp_price_hint": draw(st.none() | _MONEY),
            "is_paper": origin == "replay_sim" or draw(st.booleans()),
        }
    )


@st.composite
def _leg_drafts(draw: st.DrawFn) -> LegDraft:
    status: LegStatus = draw(st.sampled_from(_LEG_STATUSES))
    stop = st.none() | _MONEY if status in NO_STOP_LEG_STATUSES else _MONEY
    return LegDraft(
        leg_id=UUID(int=draw(st.integers(min_value=1, max_value=2**128 - 1))),
        profile=_profile(draw(st.sampled_from(_MODES))),
        status=status,
        sequence_no=draw(st.integers(min_value=0, max_value=100)),
        target_qty=draw(_MONEY),
        resolved_leverage=draw(st.decimals(min_value=1, max_value=100, places=2)),
        resolved_sl_price=draw(stop),
        resolved_tp_price=draw(st.none() | _MONEY),
        risk_usd=draw(st.none() | _SIGNED_MONEY),
        rejection_code=draw(st.none() | st.from_regex(r"\A[a-z_]{1,64}\Z")),
        rejection_message=draw(st.none() | st.text(_STORABLE, max_size=40)),
    )


@settings(max_examples=150, deadline=None)
@given(draft=_drafts())
def test_drafts_round_trip_through_the_adapters(draft: TradeGroupDraft) -> None:
    """Every field a draft sets reads back equal (`Decimal` equality at the column's scale)."""
    group = group_from_row(_stored_group(group_values(draft)))
    shared = set(TradeGroupDraft.model_fields) & set(TradeGroup.model_fields)
    assert shared == set(TradeGroupDraft.model_fields) - {"client_body_sha256"}
    assert {name: getattr(group, name) for name in shared} == {
        name: getattr(draft, name) for name in shared
    }
    assert (group.created_at, group.submitted_at) == (_US, None)


@settings(max_examples=150, deadline=None)
@given(draft=_leg_drafts())
def test_leg_drafts_round_trip_through_the_adapters(draft: LegDraft) -> None:
    values = leg_values(draft)
    stored = _stored_leg(values, _GROUP)
    leg = leg_from_row(stored)
    assert (leg.leg_id, leg.group_id, leg.account_id) == (
        draft.leg_id,
        _GROUP,
        draft.profile.account_id,
    )
    assert (leg.account_profile_id, leg.profile_version) == (
        draft.profile.profile_id,
        draft.profile.version,
    )
    for name in set(LegDraft.model_fields) - {"leg_id", "profile"}:
        assert getattr(leg, name) == getattr(draft, name), name
    snapshot = parse_json(render_json(values.profile_snapshot))
    assert leg_profile_snapshot(LegSnapshotRow(leg=stored, profile_snapshot=snapshot)) == (
        draft.profile
    )


def test_the_widest_values_round_trip_through_the_adapters() -> None:
    """20 whole digits and 18 places, both signs, and the widest leverage come back equal (a
    negation is `copy_negate`: unary minus rounds to the 28-digit context)."""
    low = _EDGE.copy_negate()
    draft = _draft(requested_qty_value=low, entry_price=_EDGE, sl_price_hint=_EDGE)
    group = group_from_row(_stored_group(group_values(draft)))
    assert (group.requested_qty_value, group.entry_price, group.sl_price_hint) == (
        low,
        _EDGE,
        _EDGE,
    )
    leg_draft = _leg_draft(target_qty=_EDGE, resolved_leverage=Decimal("99.99"), risk_usd=low)
    leg = leg_from_row(_stored_leg(leg_values(leg_draft), _GROUP))
    assert (leg.target_qty, leg.resolved_leverage, leg.risk_usd) == (_EDGE, Decimal("99.99"), low)


def test_a_stored_group_maps_its_labels_names_and_times() -> None:
    group = group_from_row(_group_row())
    assert (group.side, group.entry_type, group.trigger_by) == ("sell", "conditional", "mark")
    assert (group.group_id, group.client_group_ref, group.environment) == (_GROUP, _REF, "demo")
    assert (group.note, group.algo_params, group.created_at) == ("scale in", {"slices": 4}, _US)
    assert group.leg_failure_policy == "abort_on_first"
    market = group_from_row(_group_row(trigger_by=None, entry_type="Market", trigger_price=None))
    assert (market.entry_type, market.trigger_by) == ("market", None)


def test_an_unknown_label_is_a_key_error_and_a_naive_time_a_type_error() -> None:
    """Both are schema drift: the facade fails closed on them."""
    with pytest.raises(KeyError):
        group_from_row(_group_row(side="Long"))
    with pytest.raises(TypeError):
        leg_from_row(_leg_row(created_at=_T.replace(tzinfo=None)))


# -- values: never stored --------------------------------------------------------------------------


def test_take_profit_leg_is_reduce_only_and_a_ladder_sums_to_at_most_one_exactly() -> None:
    half = TakeProfitLeg(price=Decimal("65000"), qty_pct=Decimal("0.5"))
    assert half.reduce_only is True
    with pytest.raises(ValidationError):
        TakeProfitLeg.model_validate({"price": "65000", "qty_pct": "0.5", "reduce_only": False})
    for qty_pct in ("0", "1.000001", "-0.5"):
        with pytest.raises(ValidationError):
            TakeProfitLeg(price=Decimal("65000"), qty_pct=Decimal(qty_pct))
    with pytest.raises(ValidationError):
        TakeProfitLeg(price=Decimal("0"), qty_pct=Decimal("1"))
    assert take_profit_ladder([half, half]) == (half, half)
    assert take_profit_ladder([]) == ()
    over = TakeProfitLeg(price=Decimal("66000"), qty_pct=Decimal("0.5000000000000000000000000001"))
    with pytest.raises(ValueError, match="more than the whole leg"):
        take_profit_ladder([half, over])  # a 28-digit context would round this sum to 1
    fine = TakeProfitLeg(price=Decimal("66000"), qty_pct=Decimal("0." + "1" * 250))
    with pytest.raises(ValueError, match="too precise"):
        take_profit_ladder([fine])


@pytest.mark.parametrize(
    "changes",
    [
        {"filled_qty": Decimal("0.0300001")},
        {"weighted_avg_entry": None},
        {"filled_qty": Decimal("0")},
        {"weighted_avg_entry": Decimal("0")},
        {"target_qty": Decimal("-1"), "filled_qty": Decimal("-1")},
        {"total_fees": Decimal("-0.01")},
        {"total_notional": Decimal("-1")},
        {"legs_skipped": -1},
    ],
    ids=[
        "overfilled", "filled-without-average", "average-without-fill", "zero-average",
        "negative-target", "negative-fees", "negative-notional", "negative-count",
    ],
)  # fmt: skip
def test_aggregate_invariants(changes: dict[str, Any]) -> None:
    assert TradeGroupAggregate.model_validate(_AGGREGATE_BASE)
    with pytest.raises(ValidationError):
        TradeGroupAggregate.model_validate(_AGGREGATE_BASE | changes)


def test_an_aggregate_with_nothing_filled_has_no_average() -> None:
    nothing = TradeGroupAggregate.model_validate(
        _AGGREGATE_BASE | {"filled_qty": Decimal("0"), "weighted_avg_entry": None}
    )
    assert nothing.weighted_avg_entry is None


# -- containers ------------------------------------------------------------------------------------


@pytest.mark.parametrize("status", _LEG_STATUSES)
@pytest.mark.parametrize("confirmed", [False, True])
def test_unprotected_matches_ix_tgl_no_sl(status: LegStatus, confirmed: bool) -> None:
    where = _index_where(models.trade_group_legs, "ix_tgl_no_sl")
    assert where.endswith("AND native_sl_confirmed = false")
    assert _labels(where) == UNPROTECTED_LEG_STATUSES
    leg = _leg(
        status=status,
        native_sl_confirmed=confirmed,
        native_sl_confirmed_at=_US if confirmed else None,
    )
    assert leg.unprotected is (status in _labels(where) and not confirmed)


def test_a_group_with_legs_is_in_fan_out_order_with_its_accounts() -> None:
    first = _leg(leg_id=UUID(int=20), sequence_no=0, account_id=UUID(int=30))
    second = _leg(leg_id=UUID(int=22), sequence_no=1, account_id=UUID(int=31))
    tie = _leg(leg_id=UUID(int=21), sequence_no=1, account_id=UUID(int=32))
    record = TradeGroupWithLegs(group=_group(), legs=(second, first, tie))
    assert [leg.leg_id for leg in record.legs] == [UUID(int=20), UUID(int=21), UUID(int=22)]
    assert record.account_ids == (UUID(int=30), UUID(int=32), UUID(int=31))
    with pytest.raises(ValidationError, match="another group"):
        TradeGroupWithLegs(group=_group(), legs=(_leg(group_id=_OTHER),))
    with pytest.raises(ValidationError, match="listed twice"):
        TradeGroupWithLegs(group=_group(), legs=(first, first))
    assert TradeGroupWithLegs(group=_group(), legs=()).account_ids == ()


def test_record_from_rows_maps_the_group_and_its_legs() -> None:
    record = record_from_rows(TradeGroupRecord(group=_group_row(), legs=(_leg_row(),)))
    assert record.group.group_id == _GROUP and record.legs[0].leg_id == _LEG
    assert record.legs[0].resolved_leverage == Decimal("5")


def test_a_leg_with_a_profile_must_be_its_snapshot() -> None:
    leg = leg_from_row(_leg_row())
    assert LegWithProfile(leg=leg, profile=_P).profile == _P
    with pytest.raises(ValidationError, match="tgl_snapshot"):
        LegWithProfile(leg=leg, profile=_profile("fixed_qty"))


def test_an_unprotected_leg_row_maps_its_group_fields() -> None:
    row = UnprotectedLegRow(
        leg=_leg_row(), symbol="ETHUSDT", side="Buy", env="live", is_paper=False
    )
    leg = unprotected_leg_from_row(row)
    assert isinstance(leg, UnprotectedLeg) and leg.leg.unprotected
    assert (leg.symbol, leg.side, leg.environment, leg.is_paper) == (
        "ETHUSDT",
        "buy",
        "live",
        False,
    )


def test_shows_private_fields_for_owner_and_creator_only() -> None:
    """SR-E28-21: the projection drops `created_by`, `note` and `client_group_ref` for anyone but
    an Owner or the group's creator."""
    group = _group()
    assert shows_private_fields(OwnerScope(_OTHER), group)
    assert shows_private_fields(GrantScope(_USER, frozenset({_P.account_id})), group)
    assert not shows_private_fields(GrantScope(_OTHER, frozenset({_P.account_id})), group)
    scoped = ScopedTradeGroup(
        record=TradeGroupWithLegs(group=group, legs=()), shows_private_fields=False
    )
    assert scoped.shows_private_fields is False


def test_repr_hides_note_ref_fingerprint_and_rejection_text() -> None:
    marked = {
        "note": f"{_MARK} note", "algo": "twap", "algo_params": {_MARK: 1},
    }  # fmt: skip
    rejected = {"rejection_code": f"{_MARK}_code", "rejection_message": f"{_MARK} message"}
    texts = [
        repr(_group(**marked)),
        repr(_draft(**marked)),
        repr(_leg(**rejected)),
        repr(_leg_draft(status="rejected", resolved_sl_price=None, **rejected)),
        repr(LegUpdate.model_validate(rejected)),
        repr(group_values(_draft(**marked))),
    ]
    for text in texts:
        assert _MARK not in text and str(_REF) not in text and _BODY not in text
    assert "group_id" in texts[0] and "status" in texts[2]


def test_group_replay_is_a_frozen_id() -> None:
    replay = GroupReplay(GroupId(_GROUP))
    assert replay.group_id == _GROUP
    with pytest.raises(AttributeError):
        replay.group_id = GroupId(_OTHER)  # type: ignore[misc]  # frozen on purpose

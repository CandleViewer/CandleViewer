"""A stored group's REST document, 22's `TradeGroup` (E28-T05 #909, slice S2e): only the members 22
declares (never a snapshot or a fingerprint), `created_by`, `note` and `client_group_ref` only where
the scope shows them (SR-E28-21), every decimal plain (C6), `atomicity` for the policies 22 can
name, and the totals' arithmetic. No I/O; the contract is imported here, as tests are not
import-linted.
"""

from __future__ import annotations

import json
from decimal import Decimal
from typing import Any
from uuid import UUID

import pytest

from candleviewer.accounts import trade_groups as tg
from candleviewer.api._generated import openapi_models as api
from candleviewer.api.trade_group_projection import group_document
from tests.contract._admin_support import SPEC, validate_example
from tests.unit.accounts.test_trade_groups import _GROUP_BASE, _LEG_BASE, _US

_SCHEMAS = SPEC["components"]["schemas"]
_PRIVATE = {"created_by", "note", "client_group_ref"}
_NOTE = "planted note"


def _leg(n: int, **over: Any) -> tg.TradeGroupLeg:
    return tg.TradeGroupLeg.model_validate(
        _LEG_BASE | {"leg_id": UUID(int=0x100 + n), "sequence_no": n} | over
    )


def _scoped(
    legs: tuple[tg.TradeGroupLeg, ...], *, private: bool = True, **over: Any
) -> tg.ScopedTradeGroup:
    group = tg.TradeGroup.model_validate(_GROUP_BASE | {"note": _NOTE} | over)
    record = tg.TradeGroupWithLegs(group=group, legs=legs)
    return tg.ScopedTradeGroup(record=record, shows_private_fields=private)


def test_a_group_is_a_22_trade_group_with_only_the_members_22_declares_and_plain_decimals() -> None:
    odd = {
        "target_qty": Decimal("0.010000000000000000"), "resolved_leverage": Decimal("1E+2"),
        "risk_usd": Decimal("1E-18"), "realised_pnl": Decimal("-12.50"),
        "avg_entry_price": Decimal("12345678901234567890.123456789012345678"),
    }  # fmt: skip
    sized = _leg(0, **odd)
    refused = _leg(
        1, status="rejected", resolved_sl_price=None, submitted_at=None, filled_qty=Decimal(0),
        rejection_code="risk_limit_breached", rejection_message="the daily cap is reached",
    )  # fmt: skip
    unpriced = _leg(2, risk_usd=None, filled_qty=Decimal(0))
    ids = (UUID(int=0xC1), UUID(int=0xC2))
    doc: dict[str, Any] = group_document(_scoped((sized, refused, unpriced)), {sized.leg_id: ids})
    validate_example("/components/schemas/TradeGroup", doc)
    api.TradeGroup.model_validate(doc)
    first, second, third = doc["legs"]
    assert set(doc) <= set(_SCHEMAS["TradeGroup"]["properties"]) and doc["algo"] == {"kind": "none"}
    assert set(first) <= set(_SCHEMAS["TradeGroupLeg"]["properties"])
    assert set(first["resolved"]) <= set(_SCHEMAS["ResolvedLegParams"]["properties"])
    assert first["orders"] == [str(i) for i in ids] and first["error"] is None
    assert second["resolved"] is None and second["orders"] == []  # no stop: never sized
    assert third["risk_usd"] is None and "risk_usd" not in third["resolved"]  # 22: never null
    assert second["error"] == {"code": "risk_limit_breached", "message": "the daily cap is reached"}
    assert (first["resolved"]["qty"], first["resolved"]["leverage"]) == ("0.01", "100")
    assert (first["risk_usd"], first["realised_pnl"]) == ("0.000000000000000001", "-12.5")
    assert first["avg_entry_price"] == "12345678901234567890.123456789012345678"
    assert doc["totals"] == {
        "requested_legs": 3, "submitted_legs": 2, "rejected_legs": 1, "filled_qty": "0.004",
        "target_qty": "0.03", "realised_pnl": "-12.5",
    }  # fmt: skip


def test_group_document_renders_every_member_from_its_own_value() -> None:
    """A distinct value in each member: a member read from another, or inverted, shows."""
    at, d, u = "2026-10-20T09:00:00.{:06d}Z".format, Decimal, [UUID(int=0xA0 + n) for n in range(8)]
    leg = _leg(
        7, leg_id=u[1], group_id=u[0], account_id=u[2], account_profile_id=u[3], status="error",
        target_qty=d("3.3"), filled_qty=d("1.1"), avg_entry_price=d("101.5"),
        avg_exit_price=d("102.5"), resolved_leverage=d("7"), resolved_sl_price=d("90.5"),
        resolved_tp_price=d("120.5"), risk_usd=d("12.5"), realised_pnl=d("-4.5"),
        fees_paid=d("0.25"), rejection_code="c1", rejection_message="m1",
        native_sl_confirmed_at=_US + 4, submitted_at=_US + 5, closed_at=_US + 6,
        created_at=_US + 7, updated_at=_US + 8,
    )  # fmt: skip
    group = _scoped(
        (leg,), group_id=u[0], symbol="ETHUSDT", side="sell", status="closing", algo="twap",
        leg_failure_policy="all_or_none", rule_id=u[4], is_paper=True, created_by=u[5],
        client_group_ref=u[6], created_at=_US + 1, updated_at=_US + 2, closed_at=_US + 3,
    )  # fmt: skip
    assert group_document(group, {u[1]: (u[7],)}) == {
        "id": str(u[0]), "symbol": "ETHUSDT", "side": "sell", "status": "closing",
        "algo": {"kind": "twap"}, "atomicity": "all_or_none", "rule_id": str(u[4]),
        "is_paper": True, "created_at": at(1), "updated_at": at(2), "closed_at": at(3),
        "created_by": str(u[5]), "note": _NOTE, "client_group_ref": str(u[6]),
        "totals": {"requested_legs": 1, "submitted_legs": 1, "rejected_legs": 1,
                   "filled_qty": "1.1", "target_qty": "3.3", "realised_pnl": "-4.5"},
        "legs": [{
            "id": str(u[1]), "trade_group_id": str(u[0]), "exchange_account_id": str(u[2]),
            "account_profile_id": str(u[3]), "status": "error", "sequence_no": 7,
            "resolved": {"qty": "3.3", "leverage": "7", "stop_loss_price": "90.5",
                         "take_profit_price": "120.5", "risk_usd": "12.5"},
            "orders": [str(u[7])], "target_qty": "3.3", "filled_qty": "1.1",
            "avg_entry_price": "101.5", "avg_exit_price": "102.5", "risk_usd": "12.5",
            "native_sl_confirmed": True, "fees_paid": "0.25", "native_sl_confirmed_at": at(4),
            "realised_pnl": "-4.5", "error": {"code": "c1", "message": "m1"},
            "submitted_at": at(5), "closed_at": at(6), "created_at": at(7), "updated_at": at(8),
        }],
    }  # fmt: skip


@pytest.mark.parametrize("private", [True, False])
def test_the_private_fields_are_served_only_where_the_scope_shows_them(private: bool) -> None:
    """SR-E28-21: the Owner and the group's creator; any other reader sees none of the three,
    nor their values anywhere in the document."""
    doc = group_document(_scoped((_leg(0),), private=private), {})
    values = (str(_GROUP_BASE["created_by"]), _NOTE, str(_GROUP_BASE["client_group_ref"]))
    assert set(doc) & _PRIVATE == (_PRIVATE if private else set())
    if private:
        assert (doc["created_by"], doc["note"], doc["client_group_ref"]) == values
    else:
        assert not any(value in json.dumps(doc) for value in values)


@pytest.mark.parametrize(
    ("policy", "atomicity"),
    [("best_effort", "best_effort"), ("all_or_none", "all_or_none"), ("abort_on_first", None)],
)
def test_atomicity_is_the_policy_22_can_name_and_absent_for_abort_on_first(
    policy: str, atomicity: str | None
) -> None:
    """22's `atomicity` has two values, so a third is left out (E34's gap), never relabelled."""
    doc = group_document(_scoped((_leg(0),), leg_failure_policy=policy), {})
    assert doc.get("atomicity") == atomicity and ("atomicity" in doc) is (atomicity is not None)


def test_the_totals_count_every_leg_the_submitted_and_the_rejected_and_sum_exactly() -> None:
    """requested: every leg; submitted: `submitted_at` set; rejected: `rejected` or `error`
    (`cancelled` is neither); the sums keep all 38 digits, which a 28-digit sum would round."""
    wide = Decimal("12345678901234567890.123456789012345678")
    legs = (
        _leg(0, status="pending", submitted_at=None, target_qty=wide, filled_qty=Decimal(0)),
        _leg(1, status="submitted", realised_pnl=Decimal("-1.5")),
        _leg(2, status="rejected", resolved_sl_price=None, submitted_at=None),
        _leg(3, status="error", resolved_sl_price=None),
        _leg(4, status="cancelled"),
    )
    assert tg.group_totals(legs) == tg.GroupTotals(
        requested_legs=5, submitted_legs=3, rejected_legs=2,
        filled_qty=Decimal("0.016"), target_qty=Decimal("12345678901234567890.163456789012345678"),
        realised_pnl=Decimal("-1.5"),
    )  # fmt: skip
    assert tg.group_totals(()) == tg.GroupTotals(0, 0, 0, Decimal(0), Decimal(0), Decimal(0))

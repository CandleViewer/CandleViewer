"""The amended stop's rules (E29-T04 #913, slice 4; the orchestrator's Q3 and Q4 rulings): what an
amend may change on TP/SL, and the one loosening check, for a long and a short, against the order's
current stop and the key's record in force (Full mode, same side). A property test pins that the
ratchet never accepts a looser stop for either side."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

import pytest
from hypothesis import given
from hypothesis import strategies as st

from candleviewer.oms.errors import RULE_NATIVE_STOP_REQUIRED, RULE_REDUCE_ONLY_TPSL
from candleviewer.oms.stop_ratchet import (
    LOOSER_THAN_ORDER,
    LOOSER_THAN_RECORD,
    RULE_TPSL_AFTER_FILL,
    RULE_TPSL_CLEAR_UNSUPPORTED,
    RULE_TPSL_PARTIAL_MODE,
    STOP_NOT_A_PRICE,
    loosens,
    ratchet_refusal,
    tpsl_scope_refusal,
)
from candleviewer.storage.repositories.recorded_stops import RecordedStopRow

_AT = datetime(2026, 10, 24, 9, 0, tzinfo=UTC)
_ID = UUID("00000000-0000-4000-8000-00000000a001")


def _record(price: str, **over: Any) -> RecordedStopRow:
    """A stop-loss row in force, Full mode, for a long, unless `over` says otherwise."""
    row = RecordedStopRow(
        id=_ID,
        exchange_account_id=_ID,
        symbol="BTCUSDT",
        position_idx=0,
        position_side="Buy",
        kind="stop_loss",
        source="trading_stop",
        order_id=None,
        tpsl_mode="Full",
        trigger_price=Decimal(price),
        size=None,
        trailing_distance=None,
        trailing_active_price=None,
        exchange_order_id=None,
        status="in_force",
        audit_record_id=_ID,
        actor_user_id=None,
        created_at=_AT,
        answered_at=_AT,
        in_force_at=_AT,
        closed_at=None,
        released_at=None,
        position_marker=None,
    )
    return replace(row, **over)


# --- loosens: the direction rule ------------------------------------------------------------------


@pytest.mark.parametrize(
    ("side", "requested", "looser"),
    [
        ("Buy", "57000", True),  # a long's stop moved down: away from the market
        ("Buy", "58000", False),  # equal never loosens
        ("Buy", "59000", False),  # tighter
        ("Sell", "63000", True),  # a short's stop moved up: away from the market
        ("Sell", "62000", False),
        ("Sell", "61000", False),
    ],
)
def test_loosens_reads_the_direction_from_the_side(side: Any, requested: str, looser: bool) -> None:
    held = Decimal("58000") if side == "Buy" else Decimal("62000")
    assert loosens(side, held, Decimal(requested)) is looser


def test_loosens_refuses_a_side_it_does_not_know() -> None:
    with pytest.raises(ValueError, match="Buy or Sell"):
        loosens("buy", Decimal(1), Decimal(2))  # type: ignore[arg-type]  # the wrong vocabulary


# --- ratchet_refusal: against the order's stop and the record in force --------------------------


@pytest.mark.parametrize(
    ("side", "current", "requested", "reason"),
    [
        ("Buy", "58000", "57999.5", LOOSER_THAN_ORDER),
        ("Buy", "58000", "58000", None),
        ("Buy", "58000", "58500", None),
        ("Sell", "62000", "62000.5", LOOSER_THAN_ORDER),
        ("Sell", "62000", "62000", None),
        ("Sell", "62000", "61500", None),
    ],
)
def test_the_ratchet_against_the_orders_stop(
    side: Any, current: str, requested: str, reason: str | None
) -> None:
    got = ratchet_refusal(
        side=side, requested=Decimal(requested), current=Decimal(current), in_force=()
    )
    assert got == reason


@pytest.mark.parametrize(
    ("side", "record", "requested", "reason"),
    [
        ("Buy", "58500", "58200", LOOSER_THAN_RECORD),  # tighter than the order, looser than force
        ("Buy", "58500", "58500", None),
        ("Buy", "58500", "58800", None),
        ("Sell", "61500", "61800", LOOSER_THAN_RECORD),
        ("Sell", "61500", "61500", None),
        ("Sell", "61500", "61200", None),
    ],
)
def test_the_ratchet_against_the_record_in_force(
    side: Any, record: str, requested: str, reason: str | None
) -> None:
    current = Decimal("58000") if side == "Buy" else Decimal("62000")
    rows = [_record(record, position_side=side)]
    got = ratchet_refusal(side=side, requested=Decimal(requested), current=current, in_force=rows)
    assert got == reason


@pytest.mark.parametrize(
    "over",
    [
        {"position_side": "Sell"},
        {"kind": "take_profit"},
        {"tpsl_mode": "Partial", "size": Decimal("0.01")},
        {"status": "pending", "in_force_at": None},
    ],
    ids=["other_side", "take_profit", "partial", "not_in_force"],
)
def test_the_ratchet_reads_only_full_mode_stop_losses_in_force_on_the_same_side(
    over: dict[str, Any],
) -> None:
    rows = [_record("59000", **over)]
    got = ratchet_refusal(side="Buy", requested=Decimal("58200"), current=None, in_force=rows)
    assert got is None


@pytest.mark.parametrize("requested", ["0", "-1", "NaN", "Infinity"])
def test_a_requested_stop_that_is_no_price_above_zero_is_refused(requested: str) -> None:
    got = ratchet_refusal(side="Buy", requested=Decimal(requested), current=None, in_force=())
    assert got == STOP_NOT_A_PRICE


def test_a_held_stop_that_is_no_price_above_zero_fails_closed() -> None:
    got = ratchet_refusal(side="Buy", requested=Decimal("58000"), current=Decimal("0"), in_force=())
    assert got == STOP_NOT_A_PRICE


def test_an_order_with_no_stop_and_no_record_is_checked_for_the_price_only() -> None:
    got = ratchet_refusal(side="Sell", requested=Decimal("1"), current=None, in_force=())
    assert got is None


_PRICES = st.decimals(min_value=Decimal("0.0001"), max_value=Decimal("1000000"), places=4)


@given(
    side=st.sampled_from(["Buy", "Sell"]),
    current=st.none() | _PRICES,
    records=st.lists(_PRICES, max_size=3),
    requested=_PRICES,
)
def test_the_ratchet_never_accepts_a_looser_stop_for_either_side(
    side: Any, current: Decimal | None, records: list[Decimal], requested: Decimal
) -> None:
    """Q4's invariant: whatever it accepts is at least as tight as the order's stop and as every
    Full-mode stop-loss in force on the same side; whatever is at least that tight it accepts."""
    rows = [_record(str(price), position_side=side) for price in records]
    got = ratchet_refusal(side=side, requested=requested, current=current, in_force=rows)
    held = [*([] if current is None else [current]), *records]
    tight_enough = all(
        (requested >= price) if side == "Buy" else (requested <= price) for price in held
    )
    assert (got is None) is tight_enough


# --- tpsl_scope_refusal: Q3 -----------------------------------------------------------------------

_SL = Decimal("58500")
_TP = Decimal("65000")


def _scope(requested: dict[str, Decimal | None], **over: Any) -> str | None:
    facts: dict[str, Any] = {"reduce_only": False, "tpsl_mode": "Full", "filled_qty": Decimal(0)}
    return tpsl_scope_refusal(requested, **(facts | over))


def test_a_tpsl_change_on_an_unfilled_full_mode_entry_is_in_scope() -> None:
    assert _scope({"stop_loss": _SL, "take_profit": _TP}) is None


def test_an_amend_naming_neither_side_is_not_this_checks() -> None:
    assert _scope({}, reduce_only=True, tpsl_mode="Partial", filled_qty=Decimal(1)) is None


@pytest.mark.parametrize(
    ("requested", "over", "rule"),
    [
        ({"stop_loss": _SL}, {"filled_qty": Decimal("0.001")}, RULE_TPSL_AFTER_FILL),
        ({"take_profit": _TP}, {"tpsl_mode": "Partial"}, RULE_TPSL_PARTIAL_MODE),
        ({"take_profit": _TP}, {"reduce_only": True}, RULE_REDUCE_ONLY_TPSL),
        ({"take_profit": None}, {}, RULE_TPSL_CLEAR_UNSUPPORTED),
        ({"take_profit": Decimal(0)}, {}, RULE_TPSL_CLEAR_UNSUPPORTED),
        ({"stop_loss": None}, {}, RULE_NATIVE_STOP_REQUIRED),
        ({"stop_loss": Decimal(0)}, {}, RULE_NATIVE_STOP_REQUIRED),
        ({"stop_loss": Decimal(-5)}, {}, RULE_NATIVE_STOP_REQUIRED),
    ],
    ids=["filled", "partial", "reduce_only", "tp_null", "tp_zero", "sl_null", "sl_zero", "sl_neg"],
)
def test_q3_refusals_name_their_rule(
    requested: dict[str, Decimal | None], over: dict[str, Any], rule: str
) -> None:
    assert _scope(requested, **over) == rule


def test_a_stop_clear_is_native_stop_required_before_any_scope_rule() -> None:
    """C-2.6 for good: a cleared stop on an entry names the native-stop rule, never a scope one."""
    got = _scope({"stop_loss": None}, tpsl_mode="Partial", filled_qty=Decimal(1))
    assert got == RULE_NATIVE_STOP_REQUIRED

"""The amended stop's rules (E29-T04 #913, slice 4; the orchestrator's Q3 and Q4 rulings): Q3's
scope, and the one ratchet for a long and a short against the order's current stop and the key's
record in force (Full mode, same side); a property test pins that it never accepts a looser stop."""

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

_AT, _ID = datetime(2026, 10, 24, 9, 0, tzinfo=UTC), UUID(int=1)
_D = Decimal


def _record(price: str, **over: Any) -> RecordedStopRow:
    """A stop-loss row in force, Full mode, for a long, unless `over` says otherwise."""
    ids: dict[str, Any] = {"id": _ID, "exchange_account_id": _ID, "audit_record_id": _ID}
    times: dict[str, Any] = {"created_at": _AT, "answered_at": _AT, "in_force_at": _AT}
    nones: dict[str, Any] = dict.fromkeys(
        ("order_id", "size", "trailing_distance", "trailing_active_price", "exchange_order_id",
         "actor_user_id", "closed_at", "released_at", "position_marker"),
    )  # fmt: skip
    row = RecordedStopRow(
        **ids, **times, **nones, symbol="BTCUSDT", position_idx=0, position_side="Buy",
        kind="stop_loss", source="trading_stop", tpsl_mode="Full", trigger_price=_D(price),
        status="in_force",
    )  # fmt: skip
    return replace(row, **over)


def test_loosens_refuses_a_side_it_does_not_know() -> None:
    with pytest.raises(ValueError, match="Buy or Sell"):
        loosens("buy", _D(1), _D(2))  # type: ignore[arg-type]  # the wrong vocabulary on purpose


@pytest.mark.parametrize(
    ("side", "record", "requested", "reason"),
    [("Buy", None, "57999.5", LOOSER_THAN_ORDER), ("Buy", None, "58000", None),
     ("Buy", None, "58500", None), ("Sell", None, "62000.5", LOOSER_THAN_ORDER),
     ("Sell", None, "62000", None), ("Sell", None, "61500", None),
     ("Buy", "58500", "58200", LOOSER_THAN_RECORD), ("Buy", "58500", "58500", None),
     ("Buy", "58500", "58800", None), ("Sell", "61500", "61800", LOOSER_THAN_RECORD),
     ("Sell", "61500", "61500", None), ("Sell", "61500", "61200", None)],
)  # fmt: skip
def test_the_ratchet_against_the_orders_stop_and_the_record_in_force(
    side: Any, record: str | None, requested: str, reason: str | None
) -> None:
    """Long and short: looser refused, equal and tighter accepted, against either held stop."""
    current = _D("58000") if side == "Buy" else _D("62000")
    rows = [] if record is None else [_record(record, position_side=side)]
    got = ratchet_refusal(side=side, requested=_D(requested), current=current, in_force=rows)
    assert got == reason


@pytest.mark.parametrize(
    "over",
    [{"position_side": "Sell"}, {"kind": "take_profit"}, {"tpsl_mode": "Partial", "size": _D(1)},
     {"status": "pending", "in_force_at": None}],
    ids=["other_side", "take_profit", "partial", "not_in_force"],
)  # fmt: skip
def test_the_ratchet_reads_only_full_mode_stop_losses_in_force_on_the_same_side(
    over: dict[str, Any],
) -> None:
    rows = [_record("59000", **over)]
    assert ratchet_refusal(side="Buy", requested=_D("58200"), current=None, in_force=rows) is None


@pytest.mark.parametrize(
    ("requested", "current", "record"),
    [("0", None, None), ("-1", None, None), ("NaN", None, None), ("Infinity", None, None),
     ("58000", "0", None), ("58000", None, "NaN")],
)  # fmt: skip
def test_a_stop_that_is_no_price_above_zero_fails_closed(
    requested: str, current: str | None, record: str | None
) -> None:
    rows = [] if record is None else [_record(record)]
    held = None if current is None else _D(current)
    got = ratchet_refusal(side="Buy", requested=_D(requested), current=held, in_force=rows)
    assert got == STOP_NOT_A_PRICE


_PRICES = st.decimals(min_value=_D("0.0001"), max_value=_D("1000000"), places=4)


@given(
    side=st.sampled_from(["Buy", "Sell"]),
    current=st.none() | _PRICES,
    records=st.lists(_PRICES, max_size=3),
    requested=_PRICES,
)
def test_the_ratchet_never_accepts_a_looser_stop_for_either_side(
    side: Any, current: Decimal | None, records: list[Decimal], requested: Decimal
) -> None:
    """Q4's invariant: it accepts exactly the stops at least as tight as the order's and as every
    Full-mode stop-loss in force on the same side."""
    rows = [_record(str(price), position_side=side) for price in records]
    got = ratchet_refusal(side=side, requested=requested, current=current, in_force=rows)
    held = [*([] if current is None else [current]), *records]
    tight = all((requested >= p) if side == "Buy" else (requested <= p) for p in held)
    assert (got is None) is tight


def _scope(requested: dict[str, Decimal | None], **over: Any) -> str | None:
    facts: dict[str, Any] = {"reduce_only": False, "tpsl_mode": "Full", "filled_qty": _D(0)}
    return tpsl_scope_refusal(requested, **(facts | over))


@pytest.mark.parametrize(
    ("requested", "over", "rule"),
    [({"stop_loss": _D(58500), "take_profit": _D(65000)}, {}, None),
     ({}, {"reduce_only": True, "tpsl_mode": "Partial", "filled_qty": _D(1)}, None),
     ({"stop_loss": _D(58500)}, {"filled_qty": _D("0.001")}, RULE_TPSL_AFTER_FILL),
     ({"take_profit": _D(65000)}, {"tpsl_mode": "Partial"}, RULE_TPSL_PARTIAL_MODE),
     ({"take_profit": _D(65000)}, {"reduce_only": True}, RULE_REDUCE_ONLY_TPSL),
     ({"take_profit": None}, {}, RULE_TPSL_CLEAR_UNSUPPORTED),
     ({"take_profit": _D(0)}, {}, RULE_TPSL_CLEAR_UNSUPPORTED),
     ({"stop_loss": None}, {}, RULE_NATIVE_STOP_REQUIRED),
     ({"stop_loss": _D(0)}, {}, RULE_NATIVE_STOP_REQUIRED),
     ({"stop_loss": None}, {"tpsl_mode": "Partial", "filled_qty": _D(1)},
      RULE_NATIVE_STOP_REQUIRED)],
    ids=["in_scope", "neither_side", "filled", "partial", "reduce_only", "tp_null", "tp_zero",
         "sl_null", "sl_zero", "sl_clear_before_any_scope_rule"],
)  # fmt: skip
def test_q3_scope(
    requested: dict[str, Decimal | None], over: dict[str, Any], rule: str | None
) -> None:
    """An unfilled Full-mode entry's change is in scope; each refusal names its rule, a cleared
    stop the native-stop rule first (C-2.6 for good)."""
    assert _scope(requested, **over) == rule

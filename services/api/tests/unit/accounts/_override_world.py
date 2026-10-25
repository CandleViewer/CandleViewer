"""The world the never-widen comparator's tests judge in (ADR-0040 (proposed, #4461) Decision 1).

B is the `fixed_qty` profile fixture at the ADR's Gherkin numbers: 0.100 BTC, a 20 000 USDT
position cap, BTCUSDT at 64010. The instrument is BTCUSDT as recorded (C-13.5): tick 0.10, lot
0.001, minimum 0.001 BTC and 5 USDT. B's own leg `L_B` is long 0.1 BTC (6401 USDT) at 10x with the
1 % stop at 63369.9 (640.1 from entry) and the 2R take-profit at 65290.2; its risk at the stop,
both taker fees (0.055 %) included, is 64.01 + 7.0411 = 71.0511 USDT, under the 500 USDT daily cap.
"""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path
from typing import Any, Final

from candleviewer.accounts.override_comparator import (
    AccountFigures,
    Admitted,
    LegOverrides,
    Refused,
    ResolvedLeg,
    Violation,
    judge_leg,
)
from candleviewer.accounts.profiles import AccountProfile
from candleviewer.domain.events import Instrument
from candleviewer.exchange.bybit.instruments import parse_instruments
from tests._corpus import rest

_FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "profiles"
D = Decimal

#: B: the fixture as the account's default (B is the default profile, ADR-0040 D7), with three
#: open positions allowed (one is too few to test the bound's edge).
BOUND_VALUES: Final[dict[str, Any]] = {
    **json.loads((_FIXTURES / "fixed_qty.json").read_text(encoding="utf-8")),
    "is_default": True,
    "fixed_qty": "0.1",
    "max_open_positions": 3,
}
ALTERNATE_ID: Final = "0b5f6d0e-28a1-4c1e-9e01-0000000000f1"
OTHER_ACCOUNT: Final = "7d3c9a10-28a1-4c1e-9e01-0000000000ff"


def profile(**changes: Any) -> AccountProfile:
    """B with `changes`."""
    return AccountProfile.model_validate({**BOUND_VALUES, **changes})


def alternate(**changes: Any) -> AccountProfile:
    """An alternate of B's account, identical to B but its identity, with `changes`."""
    return profile(**{"profile_id": ALTERNATE_ID, "name": "Alt", "is_default": False, **changes})


def _btcusdt() -> Instrument:
    rows = rest("rest/instruments_before.json")["result"]["list"]
    parsed = parse_instruments(rows, fetched_at_us=0)
    return next(i for i in parsed.instruments if i.symbol == "BTCUSDT")


BOUND: Final = profile()
BTCUSDT: Final = _btcusdt()
FIGURES: Final = AccountFigures(
    equity=D("100000"),
    available_margin=D("50000"),
    committed_risk=D("0"),
    realised_loss_today=D("0"),
    open_positions_after=1,
    open_orders_after=1,
    orders_in_minute_after=1,
    taker_fee_rate=D("0.00055"),
    maintenance_margin_rate=D("0.005"),
)
BASELINE_VALUES: Final[dict[str, Any]] = {
    "account_id": BOUND_VALUES["account_id"],
    "profile_id": BOUND_VALUES["profile_id"],
    "symbol": "BTCUSDT",
    "side": "buy",
    "ref_price": D("64010"),
    "qty": D("0.1"),
    "leverage": D("10"),
    "stop_price": D("63369.9"),
    "tpsl_mode": "Full",
    "take_profit_price": D("65290.2"),
    "time_in_force": "IOC",
    "reduce_only": False,
    "margin_mode": "isolated",
    "position_mode": "one_way",
    "position_idx": 0,
    "slippage_tolerance_bps": 5,
}
BASELINE: Final = ResolvedLeg.model_validate(BASELINE_VALUES)


def leg(**changes: Any) -> ResolvedLeg:
    """`L`: B's own leg with `changes`."""
    return ResolvedLeg.model_validate({**BASELINE_VALUES, **changes})


def judge(
    resulting: ResolvedLeg | None = None,
    *,
    bound: AccountProfile = BOUND,
    baseline: ResolvedLeg = BASELINE,
    instrument: Instrument = BTCUSDT,
    figures: AccountFigures = FIGURES,
    alternate: AccountProfile | None = None,
    requested: tuple[LegOverrides, ...] = (),
) -> Admitted | Refused:
    return judge_leg(
        bound,
        resulting if resulting is not None else BASELINE,
        baseline=baseline,
        instrument=instrument,
        figures=figures,
        alternate=alternate,
        requested=requested,
    )


def figures(**changes: Any) -> AccountFigures:
    return FIGURES.model_copy(update=changes)


def refused(result: Admitted | Refused) -> list[tuple[str, str, str]]:
    """(field, rule, reason) of each violation, in the order the comparator names them."""
    assert isinstance(result, Refused), result
    return [(v.field, v.rule, v.reason) for v in result.violations]


def admitted(result: Admitted | Refused) -> Admitted:
    assert isinstance(result, Admitted), result
    return result


def violations(result: Admitted | Refused) -> tuple[Violation, ...]:
    assert isinstance(result, Refused), result
    return result.violations

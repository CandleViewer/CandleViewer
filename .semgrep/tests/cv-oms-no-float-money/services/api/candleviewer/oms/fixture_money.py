# Fixture for cv-oms-no-float-money (E29-X02): a float made of a money value, or stored under a
# money name, in an OMS module; the durations, counts and clocks the OMS keeps as floats stay
# quiet. A marker sits on the finding's line.
from __future__ import annotations

import math
from decimal import Decimal

from candleviewer.domain.primitives import Px, Qty


def converted(order, row, leg, fill, position, payload):
    a = float(order.price)  # ruleid: cv-oms-no-float-money
    b = float(row["qty"])  # ruleid: cv-oms-no-float-money
    c = float(leg.notional_usdt)  # ruleid: cv-oms-no-float-money
    d = float(fill.exec_fees)  # ruleid: cv-oms-no-float-money
    e = float(payload["avgPrice"])  # ruleid: cv-oms-no-float-money
    f = float(str(position.unrealised_pnl))  # ruleid: cv-oms-no-float-money
    g = float(order.sl)  # ruleid: cv-oms-no-float-money
    return a, b, c, d, e, f, g


def stored(raw, quote, record):
    price = float(raw)  # ruleid: cv-oms-no-float-money
    record.margin: float = float(quote)  # ruleid: cv-oms-no-float-money
    record["balance"] = float(raw)  # ruleid: cv-oms-no-float-money
    leg = dict(qty=float(raw))  # ruleid: cv-oms-no-float-money
    rung = {"take_profit": float(quote)}  # ruleid: cv-oms-no-float-money
    return price, leg, rung


def decimals(raw, level: Px, tick, step: Qty | None = None):
    a = float(Decimal(raw))  # ruleid: cv-oms-no-float-money
    b = float(level.quantize(tick))  # ruleid: cv-oms-no-float-money
    c = float(level)  # ruleid: cv-oms-no-float-money
    d = float(step)  # ruleid: cv-oms-no-float-money
    figure: Decimal = Decimal(raw)
    e = float(figure)  # ruleid: cv-oms-no-float-money
    return a, b, c, d, e


def _seconds(name: str, value: float) -> float:
    if isinstance(value, bool) or not (math.isfinite(value) and value > 0):
        raise ValueError(f"{name} must be a finite number of seconds above zero")
    return float(value)  # ok: cv-oms-no-float-money


class Fold:
    def __init__(self, interval_s, gather_s, timeout_s, monotonic, standing, count: int):
        self._interval = float(interval_s)  # ok: cv-oms-no-float-money
        self._deadline = monotonic() + float(gather_s)  # ok: cv-oms-no-float-money
        self._timeout_s = float(timeout_s)  # ok: cv-oms-no-float-money
        self._stale = lambda: float(standing.stale_count)  # ok: cv-oms-no-float-money
        self._count = float(count)  # ok: cv-oms-no-float-money
        price_age_s = float(standing.age)  # ok: cv-oms-no-float-money
        self._check = float(standing.margin_check_interval_s)  # ok: cv-oms-no-float-money
        self._never = float("inf")  # ok: cv-oms-no-float-money
        self._slot = float(standing.slot)  # ok: cv-oms-no-float-money
        self._tpsl = float(standing.tpsl_count)  # ok: cv-oms-no-float-money
        del price_age_s

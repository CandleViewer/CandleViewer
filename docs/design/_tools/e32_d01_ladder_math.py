#!/usr/bin/env python3
"""E32-D01: the worked ladder, take-profit, R and rounding examples the research quotes.

Standalone, offline, no network, ``Decimal`` only. Every number the research report
(``docs/design/research/e32-brackets-ladders.md``) quotes from a worked example is computed here
from the recorded instrument fixture (BTCUSDT tick 0.10, step 0.001, min 0.001;
``packages/fixtures/bybit/2026-10-05/rest/instruments_after.json``) under the plan's rules:
24 §9.3.1 (a stop rounds away from the entry), 24 §1.3 rule 1 (a buy limit rounds down, a sell
limit up — the rule for a take-profit, which on a long is a sell limit), 24 §9.3.3 (a TP ladder
floors each leg and the last leg absorbs the remainder), 24 §10.6 (a scaled ladder: evenly spaced
prices, each rounded conservatively, floored quantities, the remainder on the level nearest
``price_start``, levels below the minimum dropped and redistributed; the batch cap is a parameter,
default 10 per 24 §10.6 — Bybit's batch-place page states 20 for linear, report C11), US-ALGO-003
sc. 3 (a ladder that cannot be split is refused), US-ALGO-009 (risk is projected for the
fully-filled ladder, never the first leg) and report F7 (22's per-child offset stop: level 1's
stop sits above level 2's price, so the position is stopped out before level 2 fills). The
linear / geometric weight formula is PROPOSED: 24 §10.6 names none (report G2).

Usage: python3 -I docs/design/_tools/e32_d01_ladder_math.py [--md | --json]
Exit 0 always: a refused ladder is a result, not an error.
"""

from __future__ import annotations

import json
import sys
from dataclasses import asdict, dataclass
from decimal import ROUND_CEILING, ROUND_FLOOR, ROUND_HALF_UP, Decimal

TICK, STEP, MIN_QTY = Decimal("0.10"), Decimal("0.001"), Decimal("0.001")
BATCH_CAP = 10  # per batch request (24 §10.6); Bybit's batch-place page: 20 for linear (C11)
ENTRY, STOP, QTY, EQUITY = (
    Decimal("64010.0"),
    Decimal("63900.0"),
    Decimal("0.250"),
    Decimal("12500"),
)


def _snap(value: Decimal, unit: Decimal, rounding: str) -> Decimal:
    return ((value / unit).to_integral_value(rounding=rounding) * unit).quantize(unit)


def round_px(px: Decimal, *, up: bool) -> Decimal:
    return _snap(px, TICK, ROUND_CEILING if up else ROUND_FLOOR)


def away_from_entry(px: Decimal, entry: Decimal) -> Decimal:
    """24 §9.3.1: a protective price never rounds towards the entry."""
    return round_px(px, up=px > entry)


def floor_qty(qty: Decimal) -> Decimal:
    return _snap(qty, STEP, ROUND_FLOOR)


def risk_usdt(qty: Decimal, entry: Decimal, stop: Decimal) -> Decimal:
    return (qty * abs(entry - stop)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def pct_of_equity(amount: Decimal) -> Decimal:
    return (amount / EQUITY * 100).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


@dataclass(frozen=True)
class Level:
    level: int
    price: str
    qty: str
    notional: str
    cum_qty: str
    cum_notional: str
    avg_entry: str


def weights(n: int, distribution: str, skew: Decimal) -> list[Decimal]:
    if distribution == "linear":  # PROPOSED: far end = skew x the near end, straight line between
        raw = [1 + (skew - 1) * Decimal(i) / Decimal(n - 1) for i in range(n)]
    elif distribution == "geometric":
        raw = [skew**i for i in range(n)]
    else:
        raw = [Decimal(1)] * n
    total = sum(raw, Decimal(0))
    return [w / total for w in raw]


def scaled_ladder(
    total: Decimal,
    p_start: Decimal,
    p_end: Decimal,
    n: int,
    distribution: str,
    skew: Decimal,
    batch_cap: int = BATCH_CAP,
) -> tuple[list[Level], dict[str, str]]:
    """A buy ladder from ``p_start`` to ``p_end`` (24 §10.6); buy limits round down (24 §1.3)."""
    prices = [
        round_px(p_start + (p_end - p_start) * Decimal(i) / Decimal(n - 1), up=False)
        for i in range(n)
    ]
    qtys = [floor_qty(total * w) for w in weights(n, distribution, skew)]
    kept = [i for i, q in enumerate(qtys) if q >= MIN_QTY]
    if len(kept) < n:  # drop and redistribute proportionally among the survivors
        sub = weights(len(kept), distribution, skew)
        qtys = [
            floor_qty(total * sub[kept.index(i)]) if i in kept else Decimal(0) for i in range(n)
        ]
    qtys[0] += total - sum(qtys, Decimal(0))  # the remainder goes to the level nearest price_start
    rows, cum_q, cum_n = [], Decimal(0), Decimal(0)
    for i, (p, q) in enumerate(zip(prices, qtys, strict=True), start=1):
        if q == 0:
            continue
        cum_q, cum_n = cum_q + q, cum_n + p * q
        rows.append(
            Level(
                i,
                f"{p:,.1f}",
                f"{q:.3f}",
                f"{p * q:,.2f}",
                f"{cum_q:.3f}",
                f"{cum_n:,.2f}",
                f"{cum_n / cum_q:,.1f}",
            )
        )
    totals = {
        "total_qty": f"{cum_q:.3f}",
        "total_notional": f"{cum_n:,.2f}",
        "avg_entry": f"{cum_n / cum_q:,.1f}",
    }
    totals["batches"] = str(-(-len(rows) // batch_cap))  # requests at the cap (24 §10.6: 10)
    totals["batch_cap"] = str(batch_cap)
    return rows, totals


def per_child_offset_stop(prices: list[Decimal], offset_ticks: int) -> dict[str, str | bool]:
    """Report F7: the per-child offset stop of 22's ``scaledEntry`` example.

    22 puts one ``stop_loss: {ticks: 150}`` on the group, resolved per child. On a buy ladder
    level 1's own stop then sits ``offset_ticks`` under level 1; when that is above level 2's
    price, the position-level stop (tpslMode=Full) fires before level 2 can fill."""
    level_1_stop = away_from_entry(prices[0] - offset_ticks * TICK, prices[0])
    return {
        "offset_ticks": str(offset_ticks),
        "level_1_stop": f"{level_1_stop:,.1f}",
        "level_2_price": f"{prices[1]:,.1f}",
        "stopped_out_before_level_2_fills": level_1_stop > prices[1],
    }


def tp_ladder(filled: Decimal, rungs: list[tuple[Decimal, Decimal]]) -> dict[str, object]:
    """24 §9.3.3 on a long: leg = floor(filled x pct), the last leg takes the remainder.

    TP price = entry + r x R, rounded away from the entry: a long's take-profit is a sell limit, so
    24 §1.3 rule 1 rounds it up (the stop's own rule is 24 §9.3.1)."""
    one_r = ENTRY - STOP
    legs = [floor_qty(filled * pct) for pct, _ in rungs]
    legs[-1] += filled - sum(legs, Decimal(0))
    if any(q < MIN_QTY for q in legs):
        return {
            "refused": True,
            "reason": "a leg is below the 0.001 minimum",
            "single_target_r": str(rungs[-1][1]),
        }
    out = []
    for (pct, r), q in zip(rungs, legs, strict=True):
        px = away_from_entry(ENTRY + r * one_r, ENTRY)
        out.append(
            {
                "pct": f"{pct * 100:.0f}",
                "r": str(r),
                "qty": f"{q:.3f}",
                "price": f"{px:,.1f}",
                "gain": f"{q * (px - ENTRY):,.2f}",
            }
        )
    return {"refused": False, "legs": out, "total": f"{sum(legs, Decimal(0)):.3f}"}


def dca_ladder() -> dict[str, object]:
    """US-ALGO-009: three safety buys at -0.5 / -1.0 / -1.8 %, size multiplier 1.5.

    One shared stop 2.5 % under the entry; risk is projected for the fully-filled ladder."""
    base = Decimal("0.100")
    levels = [(ENTRY, base)]
    for i, off in enumerate((Decimal("0.005"), Decimal("0.010"), Decimal("0.018")), start=1):
        levels.append(
            (round_px(ENTRY * (1 - off), up=False), floor_qty(base * Decimal("1.5") ** i))
        )
    stop = away_from_entry(ENTRY * Decimal("0.975"), ENTRY)
    tot_q = sum((q for _, q in levels), Decimal(0))
    avg = sum((p * q for p, q in levels), Decimal(0)) / tot_q
    full = risk_usdt(tot_q, avg, stop)
    first = risk_usdt(base, ENTRY, stop)
    return {
        "levels": [{"price": f"{p:,.1f}", "qty": f"{q:.3f}"} for p, q in levels],
        "shared_stop": f"{stop:,.1f}",
        "total_qty": f"{tot_q:.3f}",
        "avg_entry": f"{avg:,.1f}",
        "risk_full": f"{full:,.2f}",
        "risk_full_pct": f"{pct_of_equity(full)}",
        "risk_first_leg": f"{first:,.2f}",
    }


def build() -> dict[str, object]:
    one_r = risk_usdt(QTY, ENTRY, STOP)
    rows, totals = scaled_ladder(
        Decimal("1.000"), Decimal("63900"), Decimal("63700"), 5, "linear", Decimal("1.4")
    )
    mock_q = [Decimal(x) for x in ("0.12", "0.16", "0.20", "0.24", "0.28")]
    mock_p = [Decimal(x) for x in ("63900", "63850", "63800", "63750", "63700")]
    mock_notional = sum((p * q for p, q in zip(mock_p, mock_q, strict=True)), Decimal(0))
    return {
        "fixture": {"tick": str(TICK), "step": str(STEP), "min_qty": str(MIN_QTY)},
        "r": {
            "entry": f"{ENTRY:,.1f}",
            "stop": f"{STOP:,.1f}",
            "qty": f"{QTY:.3f}",
            "ticks": str(int((ENTRY - STOP) / TICK)),
            "one_r_usdt": f"{one_r:.2f}",
            "risk_pct_equity": f"{pct_of_equity(one_r)}",
            "tp_2r": f"{away_from_entry(ENTRY + 2 * (ENTRY - STOP), ENTRY):,.1f}",
            "tp_3r": f"{away_from_entry(ENTRY + 3 * (ENTRY - STOP), ENTRY):,.1f}",
        },
        "rounding": {
            "long_stop_typed": "63,899.96",
            "long_stop": f"{away_from_entry(Decimal('63899.96'), ENTRY):,.1f}",
            "long_tp_typed": "64,299.94",
            "long_tp": f"{away_from_entry(Decimal('64299.94'), ENTRY):,.1f}",
            "nearest_would_be": f"{_snap(Decimal('63899.96'), TICK, ROUND_HALF_UP):,.1f}",
        },
        "scaled": {
            "rows": [asdict(r) for r in rows],
            "totals": totals,
            "per_child_offset_stop": per_child_offset_stop(
                [Decimal(r.price.replace(",", "")) for r in rows], 150
            ),
        },
        "scaled_mock_check": {"mock_total": f"{mock_notional:,.2f}", "mock_claims": "63,790"},
        "tp_ladder": tp_ladder(
            QTY,
            [
                (Decimal("0.25"), Decimal(1)),
                (Decimal("0.25"), Decimal(2)),
                (Decimal("0.5"), Decimal(3)),
            ],
        ),
        "tp_ladder_refused": tp_ladder(
            Decimal("0.002"),
            [
                (Decimal("0.25"), Decimal(1)),
                (Decimal("0.25"), Decimal(2)),
                (Decimal("0.5"), Decimal(3)),
            ],
        ),
        "dca": dca_ladder(),
    }


def main(argv: list[str]) -> int:
    data = build()
    if "--json" in argv:
        print(json.dumps(data, indent=2))
        return 0
    if "--md" in argv:
        rows, _ = scaled_ladder(
            Decimal("1.000"), Decimal("63900"), Decimal("63700"), 5, "linear", Decimal("1.4")
        )
        print("| # | price | qty | notional | cum. qty | cum. notional | avg entry |")
        print("| --- | --- | --- | --- | --- | --- | --- |")
        for r in rows:
            cells = (r.level, r.price, r.qty, r.notional, r.cum_qty, r.cum_notional, r.avg_entry)
            print("| " + " | ".join(str(c) for c in cells) + " |")
        return 0
    for key, value in data.items():
        print(key, json.dumps(value))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

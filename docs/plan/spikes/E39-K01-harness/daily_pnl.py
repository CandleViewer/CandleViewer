"""E39-K01 THROWAWAY harness: four daily-PnL sources and the hybrid, on a seeded synthetic trail.

Not production code (DoR 5.1); every number is SYNTHETIC, domain-level only, never Bybit payloads,
keys or account ids. Assumptions A1-A8: ../E39-K01.md section 3. Usage: README.md.
"""

from __future__ import annotations

import hashlib
import json
import random
import sys
import time
from dataclasses import dataclass, field
from decimal import ROUND_HALF_EVEN, Decimal
from pathlib import Path
from typing import Any

SEED = 880
H, DAY = 3600, 86400
END = 3 * DAY
CAP = Decimal(250)  # risk_policy seed max_daily_loss_usd (21-database-schema.md:4312)
TOL = CAP * Decimal("0.005")  # 0.5 % of the cap = 1.25 (reported beside criterion 1)
CRIT1 = Decimal("0.005")  # criterion 1 (BQ-1 ruling): |div| <= 0.5 % of closed-PnL over the window
MAKER, TAKER = Decimal("0.0002"), Decimal("0.00055")  # ASSUMED base-tier rates
FUNDING_EVERY = {"BTCUSDT": 8 * H, "ETHUSDT": 4 * H}  # the funding-history fixtures' cadences
START_PX = {"BTCUSDT": Decimal(60000), "ETHUSDT": Decimal(3000)}
TICK = {"BTCUSDT": Decimal("0.1"), "ETHUSDT": Decimal("0.01")}
GAP = (DAY + 14 * H, DAY + 14 * H + 20 * 60)  # account A's private-stream reconnect gap
TRANSFER = ("B", DAY + 10 * H + 1800, Decimal(1000))  # wallet-only cash movement
# Offset change requested D1 12:00 (21-database-schema.md:4329). The key in progress runs on to the
# first new-offset boundary >= its old end, so it is 24 h to < 48 h, never shorter (finding 5.6).
OFFSET_CHANGE = (DAY + 12 * H, 60)
OFFSET_CASES = (-720, -60, 60, 840)  # the transitional cases the finding tabulates (minutes)
LATE_RECORD = 2 * H + 600  # the backfilled close's record posts late (beyond A2), see scripted()
Q8, Q4 = Decimal("1e-8"), Decimal("1e-4")
RESULTS = Path(__file__).resolve().parent.parent / "E39-K01-results.json"


def q(x: Decimal, e: Decimal = Q8) -> Decimal:
    return x.quantize(e, rounding=ROUND_HALF_EVEN)


@dataclass
class Fill:
    acct: str
    sym: str
    ts: int
    delta: Decimal  # signed qty, + buy
    rate: Decimal
    kind: str = "Trade"
    lag: int = 0  # seconds until the closed-PnL record is posted (its updatedTime)
    provisional: bool = False  # the Gherkin case: the fee is known only `lag` seconds later


@dataclass
class Pos:
    qty: Decimal = Decimal(0)  # signed
    avg: Decimal = Decimal(0)
    open_fee: Decimal = Decimal(0)  # unattributed opening fee (a cost, positive)
    funding: Decimal = Decimal(0)  # unattributed funding cash flow (+ received)


Snap = tuple[int, str, str, Decimal, Decimal, Decimal, Decimal]


@dataclass
class Trail:
    fills: list[dict[str, Any]] = field(default_factory=list)
    funding: list[tuple[str, str, int, Decimal]] = field(default_factory=list)
    records: list[dict[str, Any]] = field(default_factory=list)
    marks: dict[str, list[Decimal]] = field(default_factory=dict)
    #: (ts, acct, sym, qty, avg, pending opening fee, pending funding) after each change
    snaps: list[Snap] = field(default_factory=list)


def windows(off: int = OFFSET_CHANGE[1], req: int = OFFSET_CHANGE[0],
            end: int = END) -> list[tuple[str, int, int]]:  # fmt: skip
    """Day keys: UTC (offset 0) until the change; the key in progress at `req` keeps running to
    the first boundary of the new offset that is >= its old end, then whole days on the new grid."""
    old_end = (req // DAY + 1) * DAY
    first = old_end + (-off * 60 - old_end) % DAY  # first new-offset boundary >= old_end
    out, start, i = [], 0, 0
    while start < end:
        nxt = start + DAY if start + DAY < old_end else max(first, start + DAY)
        nxt = min(nxt, end)
        out.append((f"K{i}", start, nxt))
        start, i = nxt, i + 1
    return out


def transitional_hours(off: int, req: int = OFFSET_CHANGE[0]) -> int:
    """Length in hours of the key in progress when the offset changes at `req`."""
    w = next(x for x in windows(off, req, req + 3 * DAY) if x[1] <= req < x[2])
    return (w[2] - w[1]) // H


def marks(rng: random.Random) -> dict[str, list[Decimal]]:
    out = {}
    for sym, px in START_PX.items():
        path = [px]
        for _ in range(END // 60 + 1):
            px = q(px * (1 + Decimal(rng.randint(-8, 8)) / 10000), TICK[sym])
            path.append(px)
        out[sym] = path
    return out


def scripted() -> list[Fill]:
    """Account A, BTCUSDT: the named scenarios (carried, gap, flip, boundary, ADL, offset)."""
    d0, d1, d2 = 0, DAY, 2 * DAY
    return [
        Fill("A", "BTCUSDT", d0 + 20 * H, Decimal("0.4"), TAKER),  # carried over K0 -> K1
        Fill("A", "BTCUSDT", d1 + 1 * H + 1800, Decimal("-0.4"), TAKER, lag=40),
        Fill("A", "BTCUSDT", d1 + 9 * H, Decimal("-0.1"), MAKER),  # short into a rising mark
        Fill("A", "BTCUSDT", d1 + 13 * H + 3540, Decimal("0.04"), MAKER, lag=90, provisional=True),
        # In the gap: a backfilled LOSS (no execPnl); its record is late, so it stays unconfirmed
        # over two hour-ends (finding 5.5, M4).
        Fill("A", "BTCUSDT", d1 + 14 * H + 300, Decimal("0.06"), TAKER, lag=LATE_RECORD),
        Fill("A", "BTCUSDT", d1 + 18 * H, Decimal("-0.3"), MAKER),
        Fill("A", "BTCUSDT", d1 + 21 * H, Decimal("0.6"), TAKER, lag=20),  # flip short -> long
        Fill("A", "BTCUSDT", d1 + 23 * H + 3560, Decimal("-0.3"), TAKER, lag=90),  # boundary
        Fill("A", "BTCUSDT", d2 + 3 * H, Decimal("0.3"), TAKER),
        Fill("A", "BTCUSDT", d2 + 6 * H + 600, Decimal("-0.3"), Decimal(0), "AdlTrade", lag=15),
        Fill("A", "BTCUSDT", d2 + 15 * H, Decimal("-0.4"), TAKER),
        Fill("A", "BTCUSDT", d2 + 22 * H + 3570, Decimal("0.4"), TAKER, lag=80, provisional=True),
    ]


def randoms(rng: random.Random, mk: dict[str, list[Decimal]]) -> list[Fill]:
    out: list[Fill] = []
    for acct, sym in (("A", "ETHUSDT"), ("B", "BTCUSDT"), ("B", "ETHUSDT")):
        t = rng.randint(600, 3 * H)
        while True:
            hold = rng.randint(300, 9 * H)
            parts = rng.randint(1, 3)
            if t + hold + parts * 600 >= END - 600:
                break
            px = mk[sym][t // 60]
            qty = q(Decimal(rng.randint(5000, 25000)) / px, Decimal("0.001"))
            side = Decimal(rng.choice((1, -1)))
            out.append(Fill(acct, sym, t, side * qty, rng.choice((MAKER, TAKER))))
            left, tc = qty, t + hold
            for k in range(parts):
                part = left if k == parts - 1 else q(qty / parts, Decimal("0.001"))
                out.append(Fill(acct, sym, tc, -side * part, rng.choice((MAKER, TAKER)),
                                lag=rng.randint(0, 90)))  # fmt: skip
                left, tc = left - part, tc + rng.randint(60, 600)
            t = tc + rng.randint(600, 4 * H)
    return out


def build(seed: int = SEED) -> Trail:
    rng = random.Random(seed)
    tr = Trail(marks=marks(rng))
    fills = sorted(scripted() + randoms(rng, tr.marks), key=lambda f: (f.ts, f.acct, f.sym))
    rates = {(s, t): Decimal(rng.randint(-5, 15)) / 100000
             for s, every in FUNDING_EVERY.items() for t in range(every, END, every)}  # fmt: skip
    events: list[tuple[int, int, Any]] = [(f.ts, 1, f) for f in fills] + [
        (t, 0, (s, t)) for (s, t) in rates
    ]
    pos: dict[tuple[str, str], Pos] = {}
    for _, kind, ev in sorted(events, key=lambda e: (e[0], e[1])):
        if kind == 0:
            sym, t = ev  # (symbol, settlement ts)
            for (acct, s), p in sorted(pos.items()):
                if s == sym and p.qty:
                    amt = q(-p.qty * rates[(s, t)] * tr.marks[s][t // 60])
                    p.funding += amt
                    tr.funding.append((acct, s, t, amt))
                    tr.snaps.append((t, acct, s, p.qty, p.avg, p.open_fee, p.funding))
            continue
        f: Fill = ev
        p = pos.setdefault((f.acct, f.sym), Pos())
        px = tr.marks[f.sym][f.ts // 60]
        fee = q(abs(f.delta) * px * f.rate)
        closing = min(abs(f.delta), abs(p.qty)) if p.qty and (p.qty > 0) != (f.delta > 0) else 0
        closing = Decimal(closing)
        close_fee = q(fee * closing / abs(f.delta))
        row = {"acct": f.acct, "sym": f.sym, "ts": f.ts, "fee": fee, "gross": Decimal(0),
               "provisional": f.provisional,
               "backfilled": GAP[0] <= f.ts < GAP[1] and f.acct == "A"}  # fmt: skip
        if closing:
            share = closing / abs(p.qty)
            gross = q((px - p.avg) * closing * (1 if p.qty > 0 else -1))
            ofee, fund = q(p.open_fee * share), q(p.funding * share)
            p.open_fee, p.funding = p.open_fee - ofee, p.funding - fund
            exact = gross - ofee - close_fee + fund
            # The stream's own view of this record until the record posts (`lag` s later):
            # - exact, when every input is known (execPnl and the closing execFee are on the push);
            # - provisional (2.1: the opening-fee and funding attribution lag): the opening fee at
            #   the taker-rate bound on the opening value, received funding not credited;
            # - backfilled (no execPnl): price PnL from the projection's average entry, the same
            #   bounds, and a gain not credited at all until a record confirms it.
            ofee_bound = q(closing * p.avg * TAKER)
            bounded = gross - ofee_bound - close_fee + min(Decimal(0), fund)
            if row["backfilled"]:
                local = min(Decimal(0), bounded)
            elif f.provisional:
                local = bounded
            else:
                local = exact
            tr.records.append({"acct": f.acct, "sym": f.sym, "close_ts": f.ts, "kind": f.kind,
                               "updated": f.ts + f.lag, "exact": exact, "pnl": q(exact, Q4),
                               "local": local, "unconfirmed": row["backfilled"],
                               "fees": ofee + close_fee, "fund": fund})  # fmt: skip
            row["gross"] = gross
            p.qty += f.delta if abs(f.delta) <= abs(p.qty) else -p.qty
            rest = abs(f.delta) - closing
        else:
            rest = abs(f.delta)
        if rest:
            sign = 1 if f.delta > 0 else -1
            p.avg = (p.avg * abs(p.qty) + px * rest) / (abs(p.qty) + rest) if p.qty else px
            p.qty += sign * rest
            p.open_fee += fee - close_fee
        if p.qty == 0:
            p.avg, p.open_fee, p.funding = Decimal(0), Decimal(0), Decimal(0)
        tr.fills.append(row)
        tr.snaps.append((f.ts, f.acct, f.sym, p.qty, p.avg, p.open_fee, p.funding))
    return tr


def upnl(tr: Trail, acct: str, t: int, net: bool = False) -> Decimal:
    """Mark-to-market of the open positions at t; `net` also books their pending opening fees
    and paid funding (the costs closed-PnL will attribute at the close). Received funding is not
    credited before it is realised (finding 5.2)."""
    last: dict[str, tuple[Decimal, ...]] = {}
    for ts, a, s, *rest in tr.snaps:
        if a == acct and ts <= t:
            last[s] = tuple(rest)
    out = Decimal(0)
    for s, (qty, avg, ofee, fund) in last.items():
        held = (min(Decimal(0), fund) - ofee) if net and qty else Decimal(0)
        out += q((tr.marks[s][t // 60] - avg) * qty) + held
    return out


def rebuilt_held(tr: Trail, acct: str, t: int, reach: int, bound: bool = True) -> Decimal | None:
    """Held costs (opening fee + paid funding) of the open positions as a rebuild at t reading back
    to `reach` sees them (finding 5.8 (c)). Opened before `reach`: the taker-bound opening fee, and
    None (risk_state_unavailable) once a settlement fell since; bound=False counts both as 0."""
    out = Decimal(0)
    for s in START_PX:
        sn = [x for x in tr.snaps if x[1] == acct and x[2] == s and x[0] <= t]
        if not sn or not sn[-1][3]:
            continue
        _, _, _, qty, avg, ofee, fund = sn[-1]
        opened = next((sn[i + 1][0] for i in range(len(sn) - 2, -1, -1) if not sn[i][3]), sn[0][0])
        if opened >= reach:
            out += ofee - min(Decimal(0), fund)
        elif bound and any(a == acct and x == s and opened < ts <= t for a, x, ts, _ in tr.funding):
            return None
        elif bound:
            out += q(abs(qty) * avg * TAKER)
    return out


def carried_upnl(tr: Trail, acct: str, ws: int, t: int) -> Decimal:
    """Net uPnL at ws of positions unchanged since before it (BQ-3 (b) subtracts it)."""
    out = Decimal(0)
    for s in START_PX:
        before = [x for x in tr.snaps if x[1] == acct and x[2] == s and x[0] < ws]
        since = [x for x in tr.snaps if x[1] == acct and x[2] == s and ws <= x[0] <= t]
        if before and before[-1][3] and not any(x[3] != before[-1][3] for x in since):
            _, _, _, qty, avg, ofee, fund = before[-1]
            out += q((tr.marks[s][ws // 60] - avg) * qty) + min(Decimal(0), fund) - ofee
    return out


def hour(tr: Trail, acct: str, w: tuple[str, int, int], t: int) -> dict[str, Any]:
    _, ws, we = w

    def inw(ts: int) -> bool:
        return ws <= ts < we and ts <= t

    fills = [r for r in tr.fills if r["acct"] == acct and inw(r["ts"])]
    fund = sum((a for (ac, _, ts, a) in tr.funding if ac == acct and inw(ts)), Decimal(0))
    recs = [r for r in tr.records if r["acct"] == acct]
    gross = sum((r["gross"] for r in fills), Decimal(0))
    lost = sum((r["gross"] for r in fills if r["backfilled"]), Decimal(0))
    fees = sum((r["fee"] for r in fills), Decimal(0))
    local = gross - lost - fees  # from the stored rows: no funding, NULL closed_pnl on backfill
    cash = gross - fees + fund  # L2: the stream, complete
    # transaction-log (TRADE + SETTLEMENT rows, transfers excluded by type): the settled cash
    # ledger, `change` = cashFlow (= execPnl, 2.1) - fee + funding, dated by transactionTime = exec
    # time; REST rows carry cashFlow, so a backfilled fill is complete. A8: no posting lag modelled.
    txlog = cash
    by_close = [r for r in recs if inw(r["close_ts"])]
    l3 = sum((r["exact"] for r in by_close), Decimal(0))  # attributed at the close
    l4 = sum((r["pnl"] for r in by_close), Decimal(0))  # venue rounding
    by_upd = [r for r in recs if ws <= r["updated"] < we and r["close_ts"] <= t]
    l5 = sum((r["pnl"] for r in by_upd), Decimal(0))  # dated by updatedTime
    closed = sum((r["pnl"] for r in by_upd if r["updated"] <= t), Decimal(0))  # visible at t
    steps = {"backfill_null_execpnl": lost, "funding_missing": fund, "attribution": l3 - cash,
             "rounding": l4 - l3, "boundary": l5 - l4, "fee_lag": closed - l5}  # fmt: skip
    u, u0 = upnl(tr, acct, t), upnl(tr, acct, ws) if ws else Decimal(0)
    xfer = TRANSFER[2] if TRANSFER[0] == acct and inw(TRANSFER[1]) else Decimal(0)
    wallet = cash + xfer + (u - u0)  # equity delta since the window start
    # Hybrid: the stream's own closed-PnL view per close, dated by the closing fill's exec time;
    # the 30 s reconciliation replaces a close's figure by the venue record only if it is lower.
    # A settled fee may raise the figure; an engaged lockout stays engaged (SR-E39-09/-11).
    # Once the fee settles (with the record) the stream holds the exact figure again.
    hyb = [min(r["exact"], r["pnl"]) if r["updated"] <= t else r["local"] for r in by_close]
    hybrid = sum(hyb, Decimal(0))
    pend = [r for r in by_close if r["updated"] > t]
    prov = sum((r["local"] - r["exact"] for r in pend if not r["unconfirmed"]), Decimal(0))
    unbf = sum((r["local"] - r["exact"] for r in pend if r["unconfirmed"]), Decimal(0))
    unconfirmed = sum(bool(r["unconfirmed"]) and r["updated"] > t for r in by_close)
    un = upnl(tr, acct, t, net=True)  # open positions, pending fees and funding included
    blocking = hybrid + min(Decimal(0), un)
    day_mtm = hybrid + min(Decimal(0), un - carried_upnl(tr, acct, ws, t))
    blocking_settled = l4 + min(Decimal(0), un)  # BQ-5: the same figure on settled records

    def neg(d: dict[str, Decimal]) -> dict[str, str]:
        return {k: str(v) for k, v in d.items() if v}

    return {
        "t": t // H, "acct": acct, "day": w[0], "closed_pnl": str(closed), "local": str(local),
        "wallet": str(wallet) if wallet else "0", "hybrid": str(hybrid), "settled": str(l4),
        "txlog": str(txlog), "div_txlog": str(txlog - closed),
        "causes_txlog": neg({k: -v for k, v in steps.items() if k not in
                             ("backfill_null_execpnl", "funding_missing")}),
        "div_local": str(local - closed), "div_wallet": str(wallet - closed),
        "div_hybrid": str(hybrid - closed), "div_hybrid_settled": str(hybrid - l4),
        "causes_hybrid": neg({"rounding": hybrid - l4 - prov - unbf,
                              "provisional_fee": prov, "unconfirmed_backfill": unbf,
                              "boundary": l4 - l5,
                              "fee_lag": l5 - closed}),
        "unconfirmed_closes": unconfirmed,
        "causes_local": neg({k: -v for k, v in steps.items()}),
        "causes_wallet": neg({"transfer": xfer, "unrealised": u - u0,
                              **{k: -v for k, v in steps.items() if k not in
                                 ("backfill_null_execpnl", "funding_missing")}}),
        "provisional_bound": str(-prov) if prov else "0",
        "unconfirmed_bound": str(-unbf) if unbf else "0", "blocking": str(blocking),
        "pess_only_breach": blocking <= -CAP < day_mtm,
        "blocking_day_mtm": str(day_mtm), "blocking_settled": str(blocking_settled),
        "bound_only_breach": blocking <= -CAP < blocking_settled,
        "fees_paid": str(fees), "funding_paid": str(fund),
        "fees_attributed": str(sum((r["fees"] for r in by_close), Decimal(0))),
        "funding_attributed": str(sum((r["fund"] for r in by_close), Decimal(0))),
    }  # fmt: skip


def episodes(rows: list[dict[str, Any]], key: str, causes: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for acct in ("A", "B"):
        cur: dict[str, Any] | None = None
        for r in (x for x in rows if x["acct"] == acct):
            if abs(Decimal(str(r[key]))) > TOL:
                if cur is None or cur["day"] != r["day"]:
                    cur = {"acct": acct, "day": r["day"], "from": r["t"], "max": Decimal(0),
                           "causes": {}}  # fmt: skip
                    out.append(cur)
                cur["to"] = r["t"]
                cur["max"] = max(cur["max"], abs(Decimal(str(r[key]))))
                for c, v in r[causes].items():
                    cc = cur["causes"]
                    cc[c] = max(cc.get(c, Decimal(0)), abs(Decimal(v)))
            else:
                cur = None
    for e in out:
        cs = e["causes"]
        e["named_cause"] = max(cs, key=lambda c: cs[c]) if cs else "none"
        e["max"], e["causes"] = str(e["max"]), {c: str(v) for c, v in sorted(cs.items())}
    return out


def report(seed: int = SEED) -> dict[str, Any]:
    tr = build(seed)
    ws = windows()
    rows = []
    for acct in ("A", "B"):
        for t in range(H, END + 1, H):
            w = next(x for x in ws if x[1] < t <= x[2])
            rows.append(hour(tr, acct, w, t))
    summary = {}
    for key, src in (("div_local", "local"), ("div_wallet", "wallet"), ("div_txlog", "txlog"),
                     ("div_hybrid", "hybrid"), ("div_hybrid_settled", "hybrid")):  # fmt: skip
        vals = [Decimal(str(r[key])) for r in rows]
        worst = max(vals, key=abs)
        # "source above reference" mixes dating with under-counting; "above settled" compares
        # with the venue's eventual figure dated by exec time, so it is a true loss under-count.
        above = [Decimal(r[src]) - Decimal(r["settled"]) for r in rows]
        ref = [Decimal(r["settled" if key.endswith("settled") else "closed_pnl"]) for r in rows]
        # Criterion 1's denominator (BQ-1) read per hour: |div| against that hour's reference.
        over = [abs(v) > CRIT1 * abs(d) for v, d in zip(vals, ref, strict=True)]
        pcts = [abs(v) / abs(d) * 100 for v, d in zip(vals, ref, strict=True) if d]
        summary[key] = {"max_abs_usd": str(abs(worst)),
                        "pct_of_cap": str(q(abs(worst) / CAP * 100, Q4)),
                        "hours_over_tol": sum(abs(v) > TOL for v in vals),
                        "hours_over_crit1": sum(over),
                        "max_pct_of_reference": str(q(max(pcts), Q4)),
                        "hours_source_above_reference": sum(v > TOL for v in vals),
                        "hours_source_above_settled": sum(v > TOL for v in above)}  # fmt: skip
    ends = [r for r in rows if any(r["t"] * H == w[2] for w in ws)]
    return {
        "label": "SYNTHETIC - seeded simulator, not exchange data",
        "synthetic": True,
        "criterion_1": criterion_1(tr, ends),
        "fees_funding_window": fees_funding(tr),
        "lockouts": lockouts(tr, rows, ws),
        "seed": seed, "cap_usd": str(CAP), "tolerance_usd": str(TOL), "windows": ws,
        "counts": {"fills": len(tr.fills), "closed_pnl_records": len(tr.records),
                   "funding_rows": len(tr.funding),
                   "backfilled_fills": sum(bool(r["backfilled"]) for r in tr.fills)},
        "summary": summary,
        "day_end": [{k: r[k] for k in ("acct", "day", "closed_pnl", "settled", "local", "wallet",
                                       "txlog", "hybrid")} for r in ends],
        "max_provisional_bound_usd": str(max(Decimal(str(r["provisional_bound"])) for r in rows)),
        "max_unconfirmed_bound_usd": str(max(Decimal(str(r["unconfirmed_bound"])) for r in rows)),
        "backfilled_closes": [{k: str(r[k]) for k in ("close_ts", "updated", "exact", "local")}
                              for r in tr.records if r["unconfirmed"]],
        "offset_cases": [{"offset_min": o, "transitional_key_h": transitional_hours(o),
                          "keys": windows(o)} for o in OFFSET_CASES],
        "unconfirmed_hours": sum(bool(r["unconfirmed_closes"]) for r in rows),
        "pess_only_breach_hours": sum(bool(r["pess_only_breach"]) for r in rows),
        "episodes": {"local": episodes(rows, "div_local", "causes_local"),
                     "wallet": episodes(rows, "div_wallet", "causes_wallet"),
                     "txlog": episodes(rows, "div_txlog", "causes_txlog"),
                     "hybrid": episodes(rows, "div_hybrid", "causes_hybrid")},
        "breach_hours": sum(Decimal(str(r["blocking"])) <= -CAP for r in rows),
        "hours": rows,
    }  # fmt: skip


SOURCES = ("local", "wallet", "txlog", "hybrid")


def pct(num: Decimal, den: Decimal) -> str:
    return str(q(abs(num) / abs(den) * 100, Q4)) if den else "n/a"


def judge(r: dict[str, Any], keys: tuple[str, ...]) -> dict[str, Any]:
    """BQ-1 ruling: the pass/fail rule is |source - closed-PnL| <= 0.5 % of closed-PnL over the
    window; USD and % of the cap are reported beside it."""
    closed = Decimal(r["closed_pnl"])
    out: dict[str, Any] = {k: r[k] for k in keys}
    for s in SOURCES:
        div = Decimal(r[s]) - closed
        out[s] = {"div_usd": str(div), "pct_of_closed_pnl": pct(div, closed),
                  "pct_of_cap": pct(div, CAP), "pass": abs(div) <= CRIT1 * abs(closed)}  # fmt: skip
    return out


def criterion_1(tr: Trail, ends: list[dict[str, Any]]) -> dict[str, Any]:
    """The rule over the whole 3-day window per account, and per day key (its verdict differs)."""
    whole = [judge(hour(tr, a, ("W", 0, END), END), ("acct", "closed_pnl")) for a in ("A", "B")]
    return {"whole_window": whole,
            "per_day_key": [judge(r, ("acct", "day", "closed_pnl")) for r in ends]}  # fmt: skip


def fees_funding(tr: Trail) -> list[dict[str, str]]:
    """BQ-1: transaction-log (fees and funding as paid) against the closed-PnL records (fees and
    funding as attributed at the close), over the whole window, per account."""
    out = []
    for acct in ("A", "B"):
        r = hour(tr, acct, ("W", 0, END), END)
        out.append({"acct": acct, "txlog_fees": r["fees_paid"], "txlog_funding": r["funding_paid"],
                    "closed_pnl_fees": r["fees_attributed"],
                    "closed_pnl_funding": r["funding_attributed"]})  # fmt: skip
    return out


def lockouts(tr: Trail, rows: list[dict[str, Any]], ws: list[Any]) -> dict[str, Any]:
    """Sticky lockout hours on the decision (BQ-3 (a)), day-mark-to-market (BQ-3 (b)) and the
    decision's figure on settled records (BQ-5: what the provisional and unconfirmed bounds cost).
    """
    figs = {"pessimistic_a": "blocking", "day_mtm_b": "blocking_day_mtm",
            "settled": "blocking_settled"}  # fmt: skip
    hours = dict.fromkeys(figs, 0)
    onset: dict[str, list[dict[str, Any]]] = {k: [] for k in figs}
    for acct in ("A", "B"):
        for w in ws:
            kr = [r for r in rows if r["acct"] == acct and r["day"] == w[0]]
            for name, col in figs.items():
                first = next((r["t"] for r in kr if Decimal(r[col]) <= -CAP), None)
                if first is not None:
                    hours[name] += sum(r["t"] >= first for r in kr)
                    onset[name].append({"acct": acct, "day": w[0], "from_hour": first})
    relock, carried = [], []
    for acct in ("A", "B"):
        for w in ws[1:]:
            c = carried_upnl(tr, acct, w[1], w[1])
            carried.append({"acct": acct, "day": w[0], "carried_net_upnl": str(c),
                            "pct_of_cap": str(q(c / CAP * 100, Q4))})  # fmt: skip
            r = next(x for x in rows if x["acct"] == acct and x["day"] == w[0])
            if Decimal(r["blocking"]) <= -CAP < Decimal(r["hybrid"]):
                relock.append({"acct": acct, "day": w[0], "hour": r["t"]})
    return {"locked_hours": hours, "lock_onsets": onset,
            "bound_only_breach_hours": sum(bool(r["bound_only_breach"]) for r in rows),
            "carried_at_boundary": carried, "carried_loser_relocks": relock}  # fmt: skip


def dump(rep: dict[str, Any]) -> bytes:
    """Compact, diff-friendly JSON: one line per key, per hour row and per episode source."""
    out = []
    for k in sorted(rep):
        v = rep[k]
        if k == "hours":
            body = ",\n  ".join(json.dumps(x, sort_keys=True) for x in v)
            out.append(f' "{k}": [\n  {body}\n ]')
        elif k == "episodes":
            rows = [f'"{s}": {json.dumps(v[s], sort_keys=True)}' for s in sorted(v)]
            body = ",\n  ".join(rows)
            out.append(f' "{k}": {{\n  {body}\n }}')
        else:
            out.append(f" {json.dumps(k)}: {json.dumps(v, sort_keys=True)}")
    return ("{\n" + ",\n".join(out) + "\n}\n").encode()


def latency(n: int = 200_000) -> dict[str, float]:
    """p50/p95 in microseconds of the hot-path read for each candidate (cache hits only)."""
    rng = random.Random(1)
    keys = [(e, f"acct{i}", False) for i in range(64) for e in ("live", "demo")]
    counters = {k: Decimal(rng.randint(-300, 300)) for k in keys}
    upnl_c = {k: Decimal(rng.randint(-200, 200)) for k in keys}
    records = [Decimal(rng.randint(-5000, 5000)) / 100 for _ in range(400)]
    cache: dict[Any, tuple[float, Decimal]] = {}

    def cached_rest(k: Any) -> Decimal:  # DayRiskFigures shape, 5 s TTL hit
        hit = cache.get(k)
        if hit is None or time.monotonic() - hit[0] > 5.0:
            hit = cache[k] = (time.monotonic(), max(Decimal(0), -sum(records, Decimal(0))))
        return hit[1]

    out = {}
    for name, fn, reps in (
        ("stream_counter", lambda k: counters[k] + min(Decimal(0), upnl_c[k]), n),
        ("cached_rest_hit", cached_rest, n),
        (
            "closed_pnl_sum_400_records",
            lambda k: max(Decimal(0), -sum(records, Decimal(0))),
            n // 50,
        ),
    ):  # the last is the miss's local work, no network
        samples = []
        for i in range(reps):
            t0 = time.perf_counter_ns()
            fn(keys[i % len(keys)])
            samples.append(time.perf_counter_ns() - t0)
        samples.sort()
        out[name + "_p50_us"] = round(samples[len(samples) // 2] / 1000, 3)
        out[name + "_p95_us"] = round(samples[int(len(samples) * 0.95)] / 1000, 3)
    return out


def main(argv: list[str]) -> int:
    if "--latency" in argv:
        print(json.dumps(latency(), indent=1))
        return 0
    a, b = dump(report()), dump(report())
    if "--check" in argv:
        print("deterministic" if a == b else "NOT deterministic", hashlib.sha256(a).hexdigest())
        return 0 if a == b else 1
    RESULTS.write_bytes(a)
    print(RESULTS.name, hashlib.sha256(a).hexdigest())
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

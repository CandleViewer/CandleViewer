# E28 sizing vectors: the hand recomputation (E28-Q01, #904)

QA's own derivation of `golden_sizing_vectors.json`, from the story and spec text alone. Every
number was worked by hand; each product and quotient was then checked on a desk calculator (`bc`,
which truncates). No sizer was written or run: E28-T03 is not built yet. When it lands, its values
are compared with these, and a mismatch is raised as a Bug before the sizer merges (#904).
`sizing_recomputation.csv` is the spreadsheet: one row per vector, with every intermediate value.

## The rules

Lines are those of `main` at `15c57e52`. "11" is `docs/plan/11-user-stories.md`, "24" is
`docs/plan/24-internal-schemas.md`, and "T03" is the E28-T03 brief in `docs/plan/backlog/E28.json`.

| Id  | Rule                                                                                                    | Source                   |
| --- | ------------------------------------------------------------------------------------------------------- | ------------------------ |
| R1  | The reference price is the order's price (every vector is a limit order)                                | 24:2511-2514             |
| R2  | Stop: `ref ∓ n × tick` (ticks), `ref × (1 ∓ v)` (percent), `ref ∓ ATR × m` (atr)                        | 24:2556                  |
| R3  | No ATR: the stop is `fallback_sl_offset_pct` as a percent stop, and `stop_fallback` is set              | 24:2556                  |
| R4  | The stop is rounded to the tick away from entry: down for a long, up for a short                        | 24:2556                  |
| R5  | `stop_dist = abs(ref − stop)`                                                                           | 24:2518                  |
| R6  | Raw quantity per mode                                                                                   | 24:2522-2531             |
| R7  | `risk_based`: `qty = risk / (stop_dist + ref × taker × 2)`                                              | 24:2533-2537             |
| R8  | The caps only ever lower the quantity, in §9.3.2's order                                                | 24:2558; T03             |
| R9  | The quantity is floored to the quantity step                                                            | 24:2397, 2542; 11:550    |
| R10 | Under `min_order_qty`, or a notional under `max(min_notional, min_leg_notional)`: skip                  | 24:2545-2547             |
| R11 | A notional over `available_margin × leverage × 0.98`: fail `insufficient_margin`                        | 24:2548-2549; T03 AC 9   |
| R12 | A symbol outside the allow-list (an empty list allows nothing): skip `symbol_not_allowed`               | 24:2506-2507; 11:575-577 |
| R13 | TP rungs: `floor(qty × qty_pct)`, the last takes the remainder; a price at `r` is `ref ± r × stop_dist` | 24:2560                  |
| R14 | Risk in USDT, 1R, is `qty × stop_dist`; initial margin is `notional / leverage`                         | T03 notes; T03 AC 2      |

A quotient that does not end is written to 28 significant digits, cut and never rounded up, so its
floor is the floor of the exact value. Decimals compare by value: trailing zeros mean nothing.

R11's code is spelt `insufficient_margin`, as step 8 writes it (24:2549) and as 22's problem codes
are spelt, in lower snake case (the `x-error-codes` catalogue, 22:480; the preview's
`rejection.code`, 22:21356). T03 (its outcome typing and AC 9) and 24's skips-and-failures text
(24:2704, which T03 cites as §9.6) write `INSUFFICIENT_MARGIN`, `OmsErrorCode`'s spelling
(24:1998). That is a documented conflict, to be listed in #904's black-box plan (slice B), not a
reading.

## The readings

Where the text leaves a choice, these vectors take one reading; each is an open question for the
E28-T03 review.

- **Q1, the fee (R7):** `fee.taker` has no source in `size_leg`'s inputs, and T03 AC 1's 0.416
  holds only with a zero fee. The fee is an input: 0 everywhere but V02, at 0.00055 (the taker rate
  of `packages/fixtures/accounts/_base/fee_rate.json`).
- **Q2, the leverage cap (R8):** §9.3.2 clamps the quantity at `max_leverage_cap` without a
  formula. Read: `qty ≤ max_leverage_cap × equity / ref`. Since `leverage ≤ max_leverage_cap`
  (`ap_lev_cap`) and the available margin is at most the equity, R11's limit is at most 0.98 of
  this cap's, so a quantity the cap cuts fails R11 unless the floor takes off more than 2 % (V13).
- **Q3, the other caps (R8):** `max_position_pct_equity` bounds the notional
  (`qty ≤ pct × equity / ref`). The daily-loss room is the tighter of `max_daily_loss` and
  `max_daily_loss_pct × equity`, less the day's loss, and bounds the loss at the stop
  (`qty ≤ room / stop_dist`). Measuring that loss without fees is **contested**: step 5's own
  reason is that the real loss at the stop includes both taker fees (24:2533-2534). No value here
  depends on it: only V02 has a fee, and its room binds neither way (2.5, or 300 / 190.4 =
  1.575…, against 0.262…). A limit order is held to `max_order_qty`.
- **Q4, the margin (R11):** §9.3.2 lists "available margin × 0.98" as a clamp; step 8 and T03 AC 9
  make it a failure. These vectors fail it.
- **Q5, the figures of T03 AC 2:** its notional 5000 and margin 500 are the figures before the
  floor; the sized leg's are 4992.0 and 499.2 (V05).
- **Q6, the ladder:** it is sized on a full fill. A rung that floors to zero is not covered:
  §9.3.3 does not say what becomes of it (V03 would have one). Nor does §9.3.3 resolve a
  take-profit in ticks, percent or ATR, which `tp_offset_unit` allows (24:2410, 24:2560), so
  V10's and V14's 100-tick take-profits are unpinned.
- **Q7, what a skip or a failure reports:** these vectors pin the floored `qty` of a skip or a
  failure (V04, V08, V13), and a notional for V08 and V13, while §9.3's `LegSizing.skip(code)` and
  `fail(code)` carry only a code (24:2547, 24:2549), and T03 AC 3 asks only that the minimum be
  reported (V04's `min_order_qty`). The floored qty, the minimum, or both?

## The vectors

BTCUSDT is tick 0.10 and ETHUSDT 0.01; SOLUSDT is 0.010. All three take steps of 0.001, a minimum
of 0.001, at most 100.000 and a 5 USDT minimum notional: the rows of the 2026-10-05 capture that
`instruments.json` selects (documented shape, #1778 A).

**V01, risk-based, the story's example (P-RISK, 0.5 %, 1200 ticks; equity 10000; buy at 64000.0).**
Stop 64000.0 − 1200 × 0.10 = 63880.0 (R2), so stop_dist = 120.0. Risk 10000 × 0.005 = 50, and
qty = 50 / 120 = 0.41666… (R7, no fee). Caps: 10 × 10000 / 64000.0 = 1.5625; 50000 / 64000.0 =
0.78125; room min(1000, 300) / 120.0 = 2.5; 100.000: none binds. Floor: 0.416 (R9). Notional
0.416 × 64000.0 = 26624.0, not over 49000 (R11). Risk 0.416 × 120.0 = 49.92, within the 50 budget;
margin 26624.0 / 5 = 5324.8. Ladder: floor(0.208) = 0.208, then 0.416 − 0.208 = 0.208, at 64120.0
and 64240.0 (R13).

**V02, the fee correction.** As V01, at a 0.00055 fee: 64000.0 × 0.00055 × 2 = 70.4 per unit, and
50 / (120.0 + 70.4) = 50 / 190.4 = 0.26260504… (R7). Floor 0.262; notional 16768.0; risk
0.262 × 120.0 = 31.44, or 0.262 × 190.4 = 49.8848 with both fees, within 50.

**V03, exactly the minimum lot.** Equity 30: risk 0.15, qty 0.15 / 120.0 = 0.00125. Caps: 0.0046875;
0.78125; room min(1000, 0.9) / 120.0 = 0.0075. Floor 0.001, the minimum: the leg is sized (R10).
Notional 64.0, not over 30 × 5 × 0.98 = 147; risk 0.12; margin 12.8.

**V04, one step below.** Equity 20: risk 0.1, qty 0.1 / 120.0 = 0.000833…; floor 0.000, under the
0.001 minimum: skip `below_min_notional`, reporting the minimum 0.001 (R10; 11:554-556).

**V05, percent of equity, the story's example (P-PCT, 5 % at 10x; ATR 400.0 × 1.5).** Stop 64000.0 −
600.0 = 63400.0 (R2). qty = 10000 × 0.05 × 10 / 64000.0 = 5000 / 64000.0 = 0.078125 (R6). Caps:
1.5625; 1 × 10000 / 64000.0 = 0.15625; room 200 / 600.0 = 0.333…: none binds. Floor 0.078; notional
4992.0, over the 10 minimum and under 98000; risk 0.078 × 600.0 = 46.8; margin 4992.0 / 10 = 499.2.

**V06, the ATR fallback (P-PCT, no ATR; ETHUSDT at 2512.37).** Stop 2512.37 × 0.98 = 2462.1226,
rounded down to 2462.12 (R3, R4), so stop_dist = 50.25. qty = 5000 / 2512.37 = 1.99015272…; caps
39.80…, 3.98…, room 200 / 50.25 = 3.98…: none binds. Floor 1.990; notional 1.990 × 2512.37 =
4999.6163; risk 1.990 × 50.25 = 99.9975; margin 499.96163; `stop_fallback` is set.

**V07, fixed quantity, a short (P-QTY, 0.01, a 1 % stop; sell at 64123.4).** Stop 64123.4 × 1.01 =
64764.634, rounded up to 64764.7 (R4), so stop_dist = 641.3. qty = 0.01 (R6); caps 1.559…,
0.5 × 10000 / 64123.4 = 0.0779…, 20000 / 64123.4 = 0.311…, room 500 / 641.3 = 0.779…: none binds.
Floor 0.010; notional 641.234; risk 6.413; margin 64.1234. The 2R take-profit is
64123.4 − 2 × 641.3 = 62840.8 (R13).

**V08, under the minimum notional (P-QTY, allow-list SOLUSDT; buy at 150.000).** Stop 150.000 × 0.99 =
148.500; qty 0.01, no cap binds; floor 0.010, over the 0.001 minimum. Notional 0.010 × 150.000 = 1.5,
under max(5, 0) = 5: skip `below_min_notional`, reporting the 5 USDT minimum (R10).

**V09, the ladder's remainder (P-RISK, equity 9980).** Risk 49.9, qty 49.9 / 120.0 = 0.41583…; caps
1.559375, 0.78125, room min(1000, 299.4) / 120.0 = 2.495: none binds. Floor 0.415; notional 26560.0;
risk 49.8. The rungs, 50 % and 50 % (100 % exactly): floor(0.2075) = 0.207, then the last takes
0.415 − 0.207 = 0.208, so the ladder totals 0.415 (R13).

**V10, the day's remaining room (P-NOTIONAL, allow-list `*USDT`; SOLUSDT at 150.000; 248 lost today).**
Stop 150.000 − 50 × 0.010 = 149.500, so stop_dist = 0.500. qty = 1000 / 150.000 = 6.666… (R6). Caps:
2 × 10000 / 150.000 = 133.3…; 5000 / 150.000 = 33.3…; room (250 − 248) / 0.500 = 4: the day's room
binds (Q3). Floor 4.000; notional 600.0, under 19600; risk 4.000 × 0.500 = 2.0, the whole room.

**V11, extreme equity (P-PCT, equity 1 000 000 000).** qty = 10^9 × 0.05 × 10 / 64000.0 = 7812.5.
Caps: 156250; 15625; room 2 × 10^7 / 600.0 = 33333.3…; `max_order_qty` 100.000 binds (Q3). Floor
100.000; notional 6400000.0, under 9.8 × 10^9; risk 60000.0; margin 640000.

**V12, the empty allow-list (P-NOTIONAL as stored).** `all_symbols` is false and the allow-list is
empty, so BTCUSDT is not allowed: skip `symbol_not_allowed` before any price is read (R12).

**V13, the leverage cap, then the margin (P-RISK, a 100-tick stop; equity 4000).** Stop 63990.0, so
stop_dist = 10.0; risk 20, qty 20 / 10.0 = 2. Caps: 10 × 4000 / 64000.0 = 0.625 binds (Q2);
0.78125; room min(1000, 120) / 10.0 = 12. Floor 0.625; notional 40000.0, over 4000 × 5 × 0.98 =
19600: fail `insufficient_margin` (R11). Under Q2's other reading, the cap bounds only the
leverage setting (11:679-680; 24:2419), and `max_position_notional` binds instead at 0.78125:
floor 0.781, notional 49984.0, the same failure. The qty and the binding cap rest on Q2; the
outcome does not.

**V14, fixed notional, unclamped (P-NOTIONAL, allow-list `*USDT`; SOLUSDT at 150.000; no loss
today).** Stop 150.000 − 50 × 0.010 = 149.500 (R2), so stop_dist = 0.500. qty = 1000 / 150.000 =
6.666… (R6; 24:2525). Caps: 2 × 10000 / 150.000 = 133.3…; 5000 / 150.000 = 33.3…; room
250 / 0.500 = 500; 100.000: none binds. Floor 6.666 (R9); notional 6.666 × 150.000 = 999.9, over
max(5, 5) and under 10000 × 2 × 0.98 = 19600 (R10, R11); risk 6.666 × 0.500 = 3.333; margin
999.9 / 2 = 499.95 (R14). V10's room cuts any raw quantity of 4 or more to 4.000; this one pins
the mode's formula. Its 100-tick take-profit is not pinned: §9.3.3 resolves only an `r_multiple`
take-profit and the ladder (24:2560).

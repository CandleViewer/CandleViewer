/**
 * The worked example's sizing port (E28-S01; SR-052, SR-E28-09): `24` §9.3 steps 3 to 8b, the one
 * permitted copy of the server's arithmetic (`candleviewer.accounts.sizer.size_leg`), for keystroke
 * latency only. It never decides anything: the editor sends the policy, and the server re-sizes every
 * order (SR-052). Out of the port, because the example has already chosen what they decide: step 1
 * (the symbol gate), step 2 (the reference price), 8c (the liquidation buffer, SR-E28-26, the server's
 * on save) and 9 (take-profits). Vitest holds it to the frozen golden vectors, so drift fails CI.
 * Step 8's `minimum` and its `below_min_notional` code are kept for that parity only: no surface
 * renders them as a pre-save hint or a one-click minimum (BQ-05 as ruled, D02 D5). The editor shows
 * the served `sizing_below_min_order` warning after a save, and nothing of its own.
 */
import type { AccountProfileInput } from "../api";
import * as D from "./dec";

type Dec = D.Dec;

/** The policy in the sizer's units: every percent a fraction (`24` §9.2; `"0.5"` % is 0.005). */
export interface SizingPolicy {
  readonly mode: "fixed_qty" | "fixed_notional" | "pct_equity" | "risk_based";
  readonly qty: Dec | null;
  readonly notional: Dec | null;
  readonly pctEquity: Dec | null;
  readonly riskPct: Dec | null;
  readonly riskUsd: Dec | null;
  readonly minLegNotional: Dec;
  readonly leverage: Dec;
  /** `null`: the profile names no stop (allowed outside `risk_based`); no stop is made up. */
  readonly stopUnit: "ticks" | "percent" | "atr" | null;
  /** Whole ticks, or a fraction of the reference price. */
  readonly stopValue: Dec;
  readonly atrMultiple: Dec;
  readonly fallbackPct: Dec;
  readonly maxLeverageCap: Dec | null;
  readonly maxPositionPctEquity: Dec | null;
  readonly maxPositionNotional: Dec | null;
  readonly maxDailyLoss: Dec | null;
  readonly maxDailyLossPct: Dec | null;
}

/** The symbol's served filters (`getInstruments`). */
export interface InstrumentFilters {
  readonly tickSize: Dec;
  readonly qtyStep: Dec;
  readonly minOrderQty: Dec;
  readonly minNotional: Dec;
  readonly maxOrderQty: Dec;
  readonly maxLeverage: Dec;
}

export interface ExampleInputs {
  readonly side: "buy" | "sell";
  /** The example's reference price (a limit price), above 0. */
  readonly ref: Dec;
  /** `null` when the served equity is unknown or stale: no number is guessed. */
  readonly equity: Dec | null;
  readonly availableMargin: Dec | null;
  readonly takerFeeRate: Dec;
  /** The day's realised loss and the committed risk, as the server nets them (BQ-11). */
  readonly dailyLossUsed: Dec;
  readonly committedRisk: Dec;
  /** A warm reading of the stop's ATR period, or `null` (the stop falls back). */
  readonly atr: Dec | null;
  readonly instrument: InstrumentFilters;
}

export type CapName =
  | "max_leverage_cap"
  | "max_position_pct_equity"
  | "max_position_notional"
  | "max_daily_loss"
  | "max_daily_loss_pct"
  | "max_order_qty";

export type ExampleCode =
  | "invalid_stop_distance"
  | "leverage_unavailable"
  | "figure_unknown"
  | "cap_breached"
  | "below_min_notional"
  | "insufficient_margin";

export interface Example {
  readonly outcome: "ok" | "skip" | "fail";
  readonly code: ExampleCode | null;
  /** `null` when the policy names no stop: the example is `figure_unknown`. */
  readonly stop: {
    readonly price: Dec;
    readonly distance: Dec;
    readonly fallback: boolean;
  } | null;
  readonly qty: Dec | null;
  readonly notional: Dec | null;
  readonly riskUsdt: Dec | null;
  readonly riskWithFeesUsdt: Dec | null;
  readonly initialMargin: Dec | null;
  readonly binding: CapName | null;
  readonly minimum: readonly ["min_order_qty" | "min_notional" | "min_leg_notional", Dec] | null;
}

/** The comparator's R6 share of the available margin (`override_comparator.MARGIN_SHARE`). */
export const MARGIN_SHARE = D.decOf("0.98");
const HUNDRED = D.int(100);

/** A field half typed (`"1."`, `""`): the policy is incomplete, so no example is drawn. */
class Incomplete extends Error {}

/** An optional field: absent is `null`; present and unreadable is incomplete. */
function plain(value: string | null | undefined): Dec | null {
  if (value === null || value === undefined) return null;
  const read = D.dec(value);
  if (read === null) throw new Incomplete();
  return read;
}
const pct = (value: string | null | undefined): Dec | null => {
  const read = plain(value);
  return read === null ? null : D.div(read, HUNDRED);
};
/** A required field, or one the contract defaults when left out (`ProfileStopLoss`). */
function must(value: string | null | undefined, fallback?: string): Dec {
  const read = plain(value ?? fallback);
  if (read === null) throw new Incomplete();
  return read;
}

/**
 * The editor's policy (`AccountProfileInput`, percents as shown) in the sizer's units, or `null`
 * while a field is half typed or a divisor is not above 0: the editor shows no example, never a
 * crash. With no `stop_loss` (allowed outside `risk_based`) the policy names no stop.
 */
export function policyOf(p: AccountProfileInput): SizingPolicy | null {
  try {
    return readPolicy(p);
  } catch (error) {
    if (error instanceof Incomplete) return null;
    throw error;
  }
}

function readPolicy(p: AccountProfileInput): SizingPolicy {
  const s = p.sizing;
  const stop = p.stop_loss ?? null;
  const caps = p.risk_caps;
  const leverage = must(p.leverage);
  if (leverage <= D.ZERO) throw new Incomplete(); // the margin step divides by it
  // the contract's `ProfileStopLoss` defaults for a member the chosen unit does not use
  const stopValue = stop === null ? D.ZERO : must(stop.value, "10");
  return {
    mode: s.mode,
    qty: plain(s.qty),
    notional: plain(s.notional_usd),
    pctEquity: pct(s.pct),
    riskPct: pct(s.risk_per_trade_pct),
    riskUsd: plain(s.risk_per_trade_usd),
    minLegNotional: must(s.min_leg_notional_usd),
    leverage,
    stopUnit: stop === null ? null : stop.unit,
    stopValue: stop?.unit === "percent" ? D.div(stopValue, HUNDRED) : stopValue,
    atrMultiple: stop === null ? D.ZERO : must(stop.atr_multiple, "2"),
    fallbackPct: stop === null ? D.ZERO : D.div(must(stop.fallback_pct, "2"), HUNDRED),
    maxLeverageCap: plain(caps?.max_leverage_cap),
    maxPositionPctEquity: pct(caps?.max_position_pct_equity),
    maxPositionNotional: plain(caps?.max_position_notional_usd),
    maxDailyLoss: plain(caps?.max_daily_loss_usd),
    maxDailyLossPct: pct(caps?.max_daily_loss_pct),
  };
}

/** Step 3 (§9.3.1): below a long's entry, above a short's, on the tick away from entry. */
export function resolveStop(p: SizingPolicy, x: ExampleInputs): Example["stop"] {
  if (p.stopUnit === null) return null;
  const tick = x.instrument.tickSize;
  let offset: Dec;
  let fallback = false;
  if (p.stopUnit === "ticks") offset = D.mul(p.stopValue, tick);
  else if (p.stopUnit === "percent") offset = D.mul(x.ref, p.stopValue);
  else if (x.atr === null) [offset, fallback] = [D.mul(x.ref, p.fallbackPct), true];
  else offset = D.mul(x.atr, p.atrMultiple);
  const price =
    x.side === "buy"
      ? D.toGrid(D.sub(x.ref, offset), tick)
      : D.toGrid(D.add(x.ref, offset), tick, true);
  return { price, distance: D.abs(D.sub(x.ref, price)), fallback };
}

/** Steps 4 and 5: `[basis, per unit]` (no per unit for `fixed_qty`), or `null` for an unknown figure. */
function rawQty(
  p: SizingPolicy,
  x: ExampleInputs,
  distance: Dec,
  fee: Dec,
): [Dec, Dec | null] | null {
  if (p.mode === "fixed_qty") return p.qty === null ? null : [p.qty, null];
  if (p.mode === "fixed_notional") return p.notional === null ? null : [p.notional, x.ref];
  if (p.mode === "pct_equity") {
    if (x.equity === null || p.pctEquity === null) return null;
    return [D.mul(D.mul(x.equity, p.pctEquity), p.leverage), x.ref];
  }
  let budget = p.riskUsd;
  if (budget === null && p.riskPct !== null && x.equity !== null) {
    budget = D.mul(x.equity, p.riskPct);
  }
  return budget === null ? null : [budget, D.add(distance, fee)];
}

/** Step 6 (§9.3.2): each cap as the most quantity it admits, in the server's order. */
function caps(p: SizingPolicy, x: ExampleInputs, distance: Dec, fee: Dec): [CapName, Dec][] | null {
  const e = x.equity;
  if (e === null) return null;
  const out: [CapName, Dec][] = [];
  if (p.maxLeverageCap !== null) {
    out.push(["max_leverage_cap", D.div(D.mul(p.maxLeverageCap, e), x.ref)]);
  }
  if (p.maxPositionPctEquity !== null) {
    out.push(["max_position_pct_equity", D.div(D.mul(p.maxPositionPctEquity, e), x.ref)]);
  }
  if (p.maxPositionNotional !== null) {
    out.push(["max_position_notional", D.div(p.maxPositionNotional, x.ref)]);
  }
  const rooms: [CapName, Dec][] = [];
  if (p.maxDailyLoss !== null) rooms.push(["max_daily_loss", p.maxDailyLoss]);
  if (p.maxDailyLossPct !== null) rooms.push(["max_daily_loss_pct", D.mul(p.maxDailyLossPct, e)]);
  const tightest = rooms.reduce<[CapName, Dec] | null>(
    (best, room) => (best === null || room[1] < best[1] ? room : best),
    null,
  );
  if (tightest !== null) {
    const left = D.sub(D.sub(tightest[1], x.dailyLossUsed), x.committedRisk);
    out.push([tightest[0], D.positive(D.div(left, D.add(distance, fee)))]);
  }
  out.push(["max_order_qty", x.instrument.maxOrderQty]);
  return out;
}

/** `24` §9.3 steps 3 to 8b for one example order. */
export function sizeExample(p: SizingPolicy, x: ExampleInputs): Example {
  const stop = resolveStop(p, x);
  const none = {
    qty: null,
    notional: null,
    riskUsdt: null,
    riskWithFeesUsdt: null,
    initialMargin: null,
    binding: null,
    minimum: null,
  } as const;
  const fail = (code: ExampleCode): Example => ({ outcome: "fail", code, stop, ...none });
  if (stop === null) return fail("figure_unknown");
  if (stop.price <= D.ZERO || stop.distance <= D.ZERO) return fail("invalid_stop_distance");
  if (p.leverage > x.instrument.maxLeverage) return fail("leverage_unavailable");
  // Entry at `ref`, exit at the further of `ref` and the stop (ADR-0040 OPEN-4).
  const fee = D.mul(D.add(x.ref, D.max(x.ref, stop.price)), x.takerFeeRate);
  const sized = rawQty(p, x, stop.distance, fee);
  const limits = caps(p, x, stop.distance, fee);
  if (sized === null || limits === null) return fail("figure_unknown");
  const [basis, perUnit] = sized;
  let clamped = D.positive(perUnit === null ? basis : D.div(basis, perUnit));
  let binding: CapName | null = null;
  for (const [cap, limit] of limits) {
    if (D.positive(limit) < clamped) [clamped, binding] = [D.positive(limit), cap];
  }
  const qty = D.toGrid(clamped, x.instrument.qtyStep); // step 7: always floor to the lot
  const notional = D.mul(qty, x.ref);
  const figures = {
    qty,
    notional,
    riskUsdt: D.mul(qty, stop.distance),
    riskWithFeesUsdt: D.mul(qty, D.add(stop.distance, fee)),
    binding,
  };
  const minimum = missed(qty, notional, p, x.instrument); // step 8
  if (minimum !== null) {
    const outcome = binding === null ? "skip" : "fail";
    const code = binding === null ? "below_min_notional" : "cap_breached";
    return { outcome, code, stop, ...figures, initialMargin: null, minimum };
  }
  const initialMargin = D.div(D.mul(qty, x.ref, true), p.leverage, true); // rounded up
  const ok = { stop, ...figures, initialMargin, minimum: null };
  if (x.availableMargin === null) return { outcome: "fail", code: "figure_unknown", ...ok };
  if (initialMargin > D.mul(x.availableMargin, MARGIN_SHARE)) {
    return { outcome: "fail", code: "insufficient_margin", ...ok }; // step 8b (R6)
  }
  return { outcome: "ok", code: null, ...ok };
}

function missed(
  qty: Dec,
  notional: Dec,
  p: SizingPolicy,
  inst: InstrumentFilters,
): Example["minimum"] {
  if (qty < inst.minOrderQty) return ["min_order_qty", inst.minOrderQty];
  const floor: NonNullable<Example["minimum"]> =
    p.minLegNotional > inst.minNotional
      ? ["min_leg_notional", p.minLegNotional]
      : ["min_notional", inst.minNotional];
  return notional < floor[1] ? floor : null;
}

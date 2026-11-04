/**
 * An instrument's grids (`22` `Instrument`, from the instrument-info cache): the tick a price
 * must sit on, the lot a quantity must sit on, the exchange minimums, and the two roundings the
 * server's sizer applies (`24` §9.3, `accounts/sizer.py` `_to_grid` / `_missed`):
 *
 * - a quantity is **floored** to the lot, so a sized order never exceeds its budget or a clamp;
 * - a stop is rounded **away from entry** (below a long's reference: floor; above a short's:
 *   ceil), so the distance never shrinks and realised risk never exceeds the budget (`24`
 *   §9.3.1);
 * - a take-profit is rounded **toward entry** (a long's floor, a short's ceil), so a target is
 *   never further than asked (`24` §9.3.3).
 *
 * All arithmetic is exact (`decimal.ts`); nothing here is a JS `number`.
 */
import {
  ZERO,
  eq,
  gt,
  lt,
  mul,
  parseDecimal,
  sign,
  stepsIn,
  timesInt,
  type Decimal,
  type RoundingMode,
} from "./decimal.js";
import type { Instrument, OrderSide } from "./model.js";

/** An optional filter the instrument row did not carry; its field is then `null` (not known). */
export type MissingFilter =
  "min_order_qty" | "min_notional_value" | "max_order_qty" | "max_leverage";

/** The parsed filters of one instrument. */
export interface InstrumentGrid {
  readonly symbol: string;
  readonly tickSize: Decimal;
  readonly qtyStep: Decimal;
  /** The exchange's minimum quantity; `null` (not known) when the row has none. */
  readonly minOrderQty: Decimal | null;
  /** The exchange's maximum quantity; `null` (no cap known) when the row has none. */
  readonly maxOrderQty: Decimal | null;
  /** The exchange's minimum notional (USDT); `null` (not known) when the row has none. */
  readonly minNotional: Decimal | null;
  readonly maxLeverage: Decimal | null;
  /** `status` is `Trading` and the row is not delisted; an absent status is not tradable. */
  readonly tradable: boolean;
  /** Which optional filters were absent and took their default: the mirror is then partial. */
  readonly missing: readonly MissingFilter[];
}

function positive(text: unknown): Decimal | null {
  const value = parseDecimal(text);
  return value !== null && sign(value) > 0 ? value : null;
}

function nonNegative(text: unknown): Decimal | null {
  const value = parseDecimal(text);
  return value !== null && sign(value) >= 0 ? value : null;
}

/**
 * The grids of a `22` `Instrument`, or `null` when its tick or lot is not a positive decimal (a
 * malformed row the ticket cannot price against). An optional filter that is absent is `null` (not
 * known, never guessed) and is listed in `missing`; one present but malformed — JSON `null` included, which is
 * not "absent" — makes the row unusable too (fail closed), as does a self-contradicting row (a
 * minimum quantity off the lot, or a lot or minimum quantity above the maximum).
 */
export function parseInstrument(inst: Instrument): InstrumentGrid | null {
  const tickSize = positive(inst.tick_size);
  const qtyStep = positive(inst.qty_step);
  if (tickSize === null || qtyStep === null) return null;
  const missing: MissingFilter[] = [];
  const optional = (
    text: string | undefined,
    name: MissingFilter,
    read: (t: unknown) => Decimal | null,
  ): Decimal | null | undefined => {
    if (text === undefined) {
      missing.push(name);
      return undefined;
    }
    return read(text);
  };
  const minOrderQty = optional(inst.min_order_qty, "min_order_qty", positive);
  const minNotional = optional(inst.min_notional_value, "min_notional_value", nonNegative);
  const maxOrderQty = optional(inst.max_order_qty, "max_order_qty", positive);
  const maxLeverage = optional(inst.max_leverage, "max_leverage", positive);
  if (
    minOrderQty === null ||
    minNotional === null ||
    maxOrderQty === null ||
    maxLeverage === null
  ) {
    return null;
  }
  // A self-contradicting row is unusable too: a minimum off the lot, or a lot or minimum above
  // the maximum quantity, leaves no quantity the exchange would accept.
  if (minOrderQty !== undefined && !eq(toStep(minOrderQty, qtyStep, "floor"), minOrderQty)) {
    return null;
  }
  if (maxOrderQty !== undefined) {
    if (gt(qtyStep, maxOrderQty)) return null;
    if (minOrderQty !== undefined && gt(minOrderQty, maxOrderQty)) return null;
  }
  return {
    symbol: inst.symbol,
    tickSize,
    qtyStep,
    minOrderQty: minOrderQty ?? null,
    maxOrderQty: maxOrderQty ?? null,
    minNotional: minNotional ?? null,
    maxLeverage: maxLeverage ?? null,
    // Only `Trading` is tradable: `PreLaunch`, `Delivering`, `Closed` and an absent status are not
    // (deliberately conservative; the server is the authority either way).
    tradable: inst.status === "Trading" && inst.delisted !== true,
    missing,
  };
}

/** `value` on the `step` grid under `mode`, at the step's scale (`step` is positive). */
export function toStep(value: Decimal, step: Decimal, mode: RoundingMode): Decimal {
  const count = stepsIn(value, step, mode);
  if (count === null) throw new RangeError("a grid step must be positive");
  return timesInt(step, count);
}

/** Whether `value` is a whole multiple of `step`. */
export function isOnStep(value: Decimal, step: Decimal): boolean {
  return eq(toStep(value, step, "floor"), value);
}

/** A price on the instrument's tick. */
export const isOnTick = (grid: InstrumentGrid, price: Decimal): boolean =>
  isOnStep(price, grid.tickSize);

/** A quantity on the instrument's lot. */
export const isOnLot = (grid: InstrumentGrid, qty: Decimal): boolean => isOnStep(qty, grid.qtyStep);

/** A quantity floored to the lot (`24` §9.3 step 7: always floor). */
export const floorQty = (grid: InstrumentGrid, qty: Decimal): Decimal =>
  toStep(qty, grid.qtyStep, "floor");

/** A price floored or ceiled to the tick. */
export const priceToTick = (grid: InstrumentGrid, price: Decimal, mode: RoundingMode): Decimal =>
  toStep(price, grid.tickSize, mode);

/**
 * A stop price on the tick, away from entry: a buy's stop sits below its reference (floor), a
 * sell's above (ceil), so the stop distance never shrinks below what was asked (`24` §9.3.1).
 */
export const roundStop = (grid: InstrumentGrid, side: OrderSide, price: Decimal): Decimal =>
  priceToTick(grid, price, side === "buy" ? "floor" : "ceil");

/**
 * A take-profit price on the tick, toward entry: a buy's target sits above (floor), a sell's
 * below (ceil), so a target is never further than asked (`24` §9.3.3).
 */
export const roundTarget = (grid: InstrumentGrid, side: OrderSide, price: Decimal): Decimal =>
  priceToTick(grid, price, side === "buy" ? "floor" : "ceil");

/** Which minimum a leg misses, and its floor (`accounts/sizer.py` `_missed`). */
export type MinimumKind = "min_order_qty" | "min_notional" | "min_leg_notional";
export interface MissedMinimum {
  readonly kind: MinimumKind;
  readonly floor: Decimal;
}
/**
 * The row did not carry a minimum the check needs (`missing`), so whether the leg meets it is not
 * known: distinct from `null` (every floor met), never answered with a guessed default.
 */
export interface UnknownMinimum {
  readonly kind: "unknown";
  readonly filter: "min_order_qty" | "min_notional_value";
}

/**
 * The first minimum a quantity at `price` misses, `null` when it meets them all, or `unknown` when
 * the row lacks a minimum reached before any miss: the exchange's minimum quantity first, then the
 * notional floor — the profile's `min_leg_notional_usd` when it is above the exchange's, else the
 * exchange's (the server's order of checks).
 */
export function missedMinimum(
  grid: InstrumentGrid,
  qty: Decimal,
  price: Decimal,
  minLegNotional: Decimal = ZERO,
): MissedMinimum | UnknownMinimum | null {
  if (grid.minOrderQty === null) return { kind: "unknown", filter: "min_order_qty" };
  if (lt(qty, grid.minOrderQty)) return { kind: "min_order_qty", floor: grid.minOrderQty };
  if (grid.minNotional === null) return { kind: "unknown", filter: "min_notional_value" };
  const floor: MissedMinimum = gt(minLegNotional, grid.minNotional)
    ? { kind: "min_leg_notional", floor: minLegNotional }
    : { kind: "min_notional", floor: grid.minNotional };
  return lt(mul(qty, price), floor.floor) ? floor : null;
}

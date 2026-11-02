/**
 * Liquidation proximity (E29-S01 #911, BQ-11): E29-D02 §5.3's tiers as drawn (D01 D5). Every
 * threshold is a named constant here and nowhere else; the defaults are the owner's to set (OQ-1,
 * AM-5), so a change is a one-line edit of this module.
 *
 * - Isolated: the share of the entry buffer left, `(mark − liq) / (entry − liq)` for a long and
 *   `(liq − mark) / (liq − entry)` for a short: Watch ≤ 50 %, Near ≤ 30 %, Critical ≤ 15 %.
 * - Cross and portfolio: the account's `wallet` `account_mm_rate` (`23` §15.4): Watch ≥ 50 %, Near
 *   ≥ 70 %, Critical ≥ 85 %.
 * - Any mode: Critical within 1 % of liquidation (the distance floor).
 * - A tier is left 5 points past its threshold (hysteresis), one tier at a time. The floor has no
 *   band of its own: none is ruled yet (#911 ask 4, OQ-1, AM-5), so past 1 % only the share's or
 *   the rate's band holds a row.
 *
 * The cell shows glyph, word and the distance from liquidation ("! Near 1.2", D02 §5.3): never
 * colour alone. Crossings up into Near and into Critical are events, once each (D02 §5.3's
 * announcement column; RT-12, RT-05): a row re-arms when it leaves the tier.
 */
import {
  abs,
  add,
  cmp,
  dec,
  div,
  mul,
  parseDecimal,
  round,
  sub,
  toPlain,
  type Decimal,
} from "./decimal";
import type { MarginMode, Side } from "./rowMapping";

export type LiqTier = "none" | "watch" | "near" | "critical";

/** D02 §5.3, isolated: the share of the entry buffer left, in percent. */
export const ISOLATED_WATCH_SHARE_PCT = dec("50");
export const ISOLATED_NEAR_SHARE_PCT = dec("30");
export const ISOLATED_CRITICAL_SHARE_PCT = dec("15");
/** D02 §5.3, cross and portfolio: the account's maintenance-margin rate, in percent. */
export const CROSS_WATCH_MM_RATE_PCT = dec("50");
export const CROSS_NEAR_MM_RATE_PCT = dec("70");
export const CROSS_CRITICAL_MM_RATE_PCT = dec("85");
/** D02 §5.3: Critical within this distance of liquidation, in percent, in any mode. */
export const CRITICAL_DISTANCE_FLOOR_PCT = dec("1");
/** D01 D5: a tier is left only this many points past its threshold. */
export const HYSTERESIS_POINTS = dec("5");
/** D02 §5.2: the distance prints at one place ("9.5"), the share and the rate at none ("27 %"). */
export const DISTANCE_SCALE = 1;
export const PERCENT_SCALE = 0;

/** D02 §5.3's cell anatomy per tier: glyph, word, and the D5 label the name and tooltip spell. */
export const TIER_TEXT = {
  watch: { glyph: "△", word: "Watch", label: "Watch" },
  near: { glyph: "!", word: "Near", label: "Near liquidation" },
  critical: { glyph: "!!", word: "Critical", label: "Critical — near liquidation" },
} as const;

const RANK: Readonly<Record<LiqTier, number>> = { none: 0, watch: 1, near: 2, critical: 3 };
const BELOW: Readonly<Record<Exclude<LiqTier, "none">, LiqTier>> = {
  watch: "none",
  near: "watch",
  critical: "near",
};
const HUNDRED = dec("100");

export interface LiqInputs {
  readonly side: Side;
  readonly entry: string | null;
  readonly mark: string | null;
  readonly liqPrice: string | null;
  readonly marginMode: MarginMode | null;
  /** The account's `account_mm_rate` (a ratio, `"0.72"`), cross and portfolio only. */
  readonly mmRate: string | null;
  /** `23` §15.4: whether the `wallet` balance of `mmRate` is stale; `null` when not known. */
  readonly mmRateStale?: boolean | null;
  readonly mmRateStaleSinceMs?: number | null;
}

export interface LiqReading {
  readonly tier: LiqTier;
  /** What set the tier's metric: the buffer share, the margin rate, or only the floor applies. */
  readonly basis: "buffer" | "mm_rate" | "floor" | "none";
  /** `|mark − liq| / mark` in percent at one place, or `null` without a liquidation price. */
  readonly distancePct: string | null;
  /** Isolated: the buffer share left, in whole percent. */
  readonly sharePct: string | null;
  /** Cross and portfolio: the account's margin rate, in whole percent. */
  readonly mmRatePct: string | null;
  /**
   * An `mm_rate` reading's balance is stale (`23` §15.4's `stale`, since `mmRateStaleSinceMs`),
   * so its tier may lag (the cell's treatment is the closing PR's); `null` for any other basis,
   * and for a rate that is not the `wallet`'s (the REST balance's first paint).
   */
  readonly mmRateStale: boolean | null;
  readonly mmRateStaleSinceMs: number | null;
}

interface Metrics {
  readonly distance: Decimal | null;
  readonly share: Decimal | null;
  readonly rate: Decimal | null;
}

/** A positive price, or `null`: Bybit's `0` and `""` mean none. */
function price(value: string | null): Decimal | null {
  const d = parseDecimal(value);
  return d !== null && d.units > 0n ? d : null;
}

function metricsOf(inputs: LiqInputs): Metrics {
  const mark = price(inputs.mark);
  const liq = price(inputs.liqPrice);
  const entry = price(inputs.entry);
  const distance =
    mark !== null && liq !== null ? div(mul(abs(sub(mark, liq)), HUNDRED), mark, 12) : null;
  let share: Decimal | null = null;
  if (inputs.marginMode === "isolated" && mark !== null && liq !== null && entry !== null) {
    const left = inputs.side === "long" ? sub(mark, liq) : sub(liq, mark);
    const buffer = inputs.side === "long" ? sub(entry, liq) : sub(liq, entry);
    share = buffer.units > 0n ? div(mul(left, HUNDRED), buffer, 12) : null;
  }
  const crossLike = inputs.marginMode === "cross" || inputs.marginMode === "portfolio";
  const ratio = crossLike ? parseDecimal(inputs.mmRate) : null;
  return { distance, share, rate: ratio === null ? null : mul(ratio, HUNDRED) };
}

const atMost = (a: Decimal, b: Decimal): boolean => cmp(a, b) <= 0;
const atLeast = (a: Decimal, b: Decimal): boolean => cmp(a, b) >= 0;

/** The tier the metrics name with no history: the floor, then the share or the rate. */
function rawTier(m: Metrics): LiqTier {
  if (m.distance !== null && atMost(m.distance, CRITICAL_DISTANCE_FLOOR_PCT)) return "critical";
  if (m.share !== null) {
    if (atMost(m.share, ISOLATED_CRITICAL_SHARE_PCT)) return "critical";
    if (atMost(m.share, ISOLATED_NEAR_SHARE_PCT)) return "near";
    if (atMost(m.share, ISOLATED_WATCH_SHARE_PCT)) return "watch";
    return "none";
  }
  if (m.rate !== null) {
    if (atLeast(m.rate, CROSS_CRITICAL_MM_RATE_PCT)) return "critical";
    if (atLeast(m.rate, CROSS_NEAR_MM_RATE_PCT)) return "near";
    if (atLeast(m.rate, CROSS_WATCH_MM_RATE_PCT)) return "watch";
  }
  return "none";
}

const SHARE_AT = {
  watch: ISOLATED_WATCH_SHARE_PCT,
  near: ISOLATED_NEAR_SHARE_PCT,
  critical: ISOLATED_CRITICAL_SHARE_PCT,
};
const RATE_AT = {
  watch: CROSS_WATCH_MM_RATE_PCT,
  near: CROSS_NEAR_MM_RATE_PCT,
  critical: CROSS_CRITICAL_MM_RATE_PCT,
};

/**
 * Whether a row held in `tier` may step down: its metric is 5 points past the tier's threshold.
 * Only a row whose raw tier is lower asks, so it is past the distance floor already: the floor has
 * no band (unruled, #911 ask 4), and hysteresis stays as drawn until one is.
 */
function mayLeave(tier: Exclude<LiqTier, "none">, m: Metrics): boolean {
  if (m.share !== null) return cmp(m.share, add(SHARE_AT[tier], HYSTERESIS_POINTS)) > 0;
  if (m.rate !== null) return cmp(m.rate, sub(RATE_AT[tier], HYSTERESIS_POINTS)) < 0;
  return true; // no metric left: nothing holds the row in the tier
}

/** The tier after `previous`, with D01 D5's hysteresis: up at once, down one tier at a time. */
function settleTier(previous: LiqTier, m: Metrics): LiqTier {
  const raw = rawTier(m);
  if (RANK[raw] >= RANK[previous]) return raw;
  let tier = previous;
  while (tier !== "none" && RANK[tier] > RANK[raw] && mayLeave(tier, m)) tier = BELOW[tier];
  return tier;
}

const pct = (d: Decimal | null, scale: number): string | null =>
  d === null ? null : toPlain(round(d, scale));

/** A reading at `tier` (already settled) from the row's inputs. */
function readingOf(tier: LiqTier, m: Metrics, inputs: LiqInputs): LiqReading {
  const basis =
    m.share !== null
      ? "buffer"
      : m.rate !== null
        ? "mm_rate"
        : m.distance !== null
          ? "floor"
          : "none";
  const stale = basis === "mm_rate" ? (inputs.mmRateStale ?? null) : null;
  return {
    tier,
    basis,
    distancePct: pct(m.distance, DISTANCE_SCALE),
    sharePct: pct(m.share, PERCENT_SCALE),
    mmRatePct: pct(m.rate, PERCENT_SCALE),
    mmRateStale: stale,
    mmRateStaleSinceMs: stale === true ? (inputs.mmRateStaleSinceMs ?? null) : null,
  };
}

/** The reading of a row whose tier was `previous` (`none` for a row seen first): hysteresis applies. */
export function readLiq(inputs: LiqInputs, previous: LiqTier = "none"): LiqReading {
  const m = metricsOf(inputs);
  return readingOf(settleTier(previous, m), m, inputs);
}

export type LiqCrossing = "near" | "critical";

/** One event per crossing up into Near or into Critical (D02 §5.3); never on a step down. */
export function crossingOf(previous: LiqTier, next: LiqTier): LiqCrossing | null {
  if (RANK[next] <= RANK[previous]) return null;
  return next === "critical" ? "critical" : next === "near" ? "near" : null;
}

/**
 * The tier of every row across commits, so hysteresis holds and a crossing is told once: a row
 * seen for the first time takes its raw tier with no event (it crossed nothing in this view); a row
 * that leaves the view is forgotten, so it re-arms.
 */
export class LiqTierTracker {
  private tiers = new Map<string, LiqTier>();

  update(key: string, inputs: LiqInputs): { reading: LiqReading; crossing: LiqCrossing | null } {
    const before = this.tiers.get(key);
    const reading = readLiq(inputs, before ?? "none");
    this.tiers.set(key, reading.tier);
    return { reading, crossing: before === undefined ? null : crossingOf(before, reading.tier) };
  }

  /** Forgets every row not in `keys` (closed, withdrawn or filtered out of the feed). */
  retain(keys: ReadonlySet<string>): void {
    for (const key of [...this.tiers.keys()]) if (!keys.has(key)) this.tiers.delete(key);
  }

  clear(): void {
    this.tiers.clear();
  }
}

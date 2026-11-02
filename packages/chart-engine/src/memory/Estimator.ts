// estimateLoad (26 §7/§8, E11-S15 BQ-S15-05/06): what a load would hold, one item per §7 row, by the
// formulas the allocators charge (a power-of-two ring at its capacity, RG16F at 4 B a texel), so the
// estimate and the engine's own counters agree. Pure: it allocates none of the stores it models. The
// engine never starts or refuses a load; `requiresConfirmation` feeds the app's confirm surface.
import { CANDLE_STRIDE } from "../layers/candle/ring.js";
import { BAR_BYTES, DEFAULT_MAX_BARS } from "../model/BarStore.js";
import { pow2 } from "../model/counters.js";
import { CELL_BYTES, DEFAULT_MAX_CELLS } from "../model/FootprintStore.js";
import { HEATMAP_ROWS } from "../model/HeatmapRing.js";
import { MAX_BARS_CEILING, MEMORY_BUDGET_CEILING_MB, MEMORY_BUDGET_FLOOR_MB } from "./config.js";

const MIB = 2 ** 20;
/** The BarStore's initial capacity (`BarStoreOptions.initialCapacity` default). */
const INITIAL_SLOTS = 1024;
/** One candle instance on the GPU (§7 row): `CandleRing`'s int32 words, one per store slot. */
const CANDLE_INSTANCE_BYTES = CANDLE_STRIDE * Int32Array.BYTES_PER_ELEMENT;
/** One footprint glyph run per cell (§7 row; provisional until E18). */
const GLYPH_RUN_BYTES = 12;
/** RG16F: two 16-bit channels a texel (`HeatmapRing.bytes`). */
const HEATMAP_TEXEL_BYTES = 4;
/** `HeatmapRing.colTime`: one Float64 per column. */
const COLUMN_TIME_BYTES = 8;
/** Both SDF families in one 1024 × 1024 R8 atlas (`text/config.ts`). */
const ATLAS_BYTES = 1024 * 1024;
/** Profile, indicators and drawings: a fixed allowance. */
const MISC_BYTES = 8 * MIB;
/** The default framebuffer is padded to this many px per axis during a drag (§7 upper bound). */
const FRAMEBUFFER_PAD_PX = 128;
const RGBA8_BYTES = 4;
const DEFAULT_CELLS_PER_BAR = 40;

/** §8 `LoadEstimateParams`. */
export interface LoadEstimateParams {
  bars: number;
  maxBars?: number; // default 200_000
  footprintBars?: number; // 0 when no footprint layer
  cellsPerBar?: number; // default 40
  heatmapFineColumns?: number; // 0 when no heatmap layer
  heatmapCoarseColumns?: number;
  heatmapRows?: number; // default 512
  backingStorePx: readonly [number, number];
}

/** §8 `LoadEstimate`. */
export interface LoadEstimate {
  items: readonly { item: string; bytes: number }[];
  totalBytes: number;
  budgetBytes: number; // budgetMb × 2^20
  requiresConfirmation: boolean; // totalBytes > 0.7 × budgetBytes
}

/** The §7 rows, in table order. */
export const ESTIMATE_ITEMS = [
  "bars",
  "candleBuffers",
  "footprint",
  "footprintGlyphs",
  "heatmapFine",
  "heatmapCoarse",
  "atlas",
  "misc",
  "framebuffer",
] as const;

/** BarStore slots for `bars` (§7 `slots(bars)`): the store never holds fewer than its initial ring,
 * and at maxBars it holds the ceiling capacity, ≥ maxBars / 4 spare (`BarStore.capFor`). */
export function barSlots(bars: number, maxBars: number): number {
  if (bars >= maxBars) return pow2(maxBars + Math.max(1, maxBars >> 2));
  return Math.max(pow2(bars), pow2(Math.min(INITIAL_SLOTS, maxBars)));
}

function count(value: number | undefined, fallback: number, name: string, min = 0): number {
  if (value === undefined) return fallback;
  if (!Number.isSafeInteger(value) || value < min) {
    throw new RangeError(`chart-engine: estimateLoad ${name} must be an integer ≥ ${min}`);
  }
  return value;
}

const padded = (px: number): number => Math.ceil(px / FRAMEBUFFER_PAD_PX) * FRAMEBUFFER_PAD_PX;

/**
 * The bytes a load would hold, per §7 row, against `budgetMb` (the chart's `memoryBudgetMb`).
 * Throws `RangeError` on a non-integer or negative count, a `maxBars` outside [1, MAX_BARS_CEILING],
 * a non-finite or negative `cellsPerBar`, or a `budgetMb` outside the F-08 range. The footprint
 * bars are capped at `maxBars` and its cells at the store's DEFAULT_MAX_CELLS.
 */
export function estimateLoad(params: LoadEstimateParams, budgetMb: number): LoadEstimate {
  const bars = count(params.bars ?? Number.NaN, 0, "bars");
  const maxBars = count(params.maxBars, DEFAULT_MAX_BARS, "maxBars", 1);
  if (maxBars > MAX_BARS_CEILING) {
    throw new RangeError(`chart-engine: estimateLoad maxBars must be ≤ ${MAX_BARS_CEILING}`);
  }
  // A FootprintStore refuses more bars than maxBars (its "ceiling" reject), so it never holds more.
  const fpBars = Math.min(count(params.footprintBars, 0, "footprintBars"), maxBars);
  const perBar = params.cellsPerBar ?? DEFAULT_CELLS_PER_BAR;
  if (!(Number.isFinite(perBar) && perBar >= 0)) {
    throw new RangeError("chart-engine: estimateLoad cellsPerBar must be finite and ≥ 0");
  }
  const fine = count(params.heatmapFineColumns, 0, "heatmapFineColumns");
  const coarse = count(params.heatmapCoarseColumns, 0, "heatmapCoarseColumns");
  const rows = count(params.heatmapRows, HEATMAP_ROWS, "heatmapRows");
  const px = params.backingStorePx as readonly unknown[] | undefined;
  if (!Array.isArray(px) || px.length !== 2) {
    throw new RangeError("chart-engine: estimateLoad backingStorePx must be [width, height]");
  }
  const w = count((px[0] as number | undefined) ?? Number.NaN, 0, "backingStorePx[0]");
  const h = count((px[1] as number | undefined) ?? Number.NaN, 0, "backingStorePx[1]");
  if (
    !Number.isSafeInteger(budgetMb) ||
    budgetMb < MEMORY_BUDGET_FLOOR_MB ||
    budgetMb > MEMORY_BUDGET_CEILING_MB
  ) {
    throw new RangeError(
      `chart-engine: budgetMb must be an integer in [${MEMORY_BUDGET_FLOOR_MB}, ${MEMORY_BUDGET_CEILING_MB}]`,
    );
  }

  const slots = barSlots(bars, maxBars);
  // A FootprintStore holds at most DEFAULT_MAX_CELLS, so a finite but huge `cellsPerBar` (1e308)
  // charges the store ceiling rather than an Infinity total.
  const cells = fpBars === 0 ? 0 : Math.min(DEFAULT_MAX_CELLS, Math.ceil(fpBars * perBar));
  const bytes = [
    slots * BAR_BYTES,
    slots * CANDLE_INSTANCE_BYTES,
    fpBars === 0 ? 0 : cells * CELL_BYTES + (fpBars + 1) * 4,
    cells * GLYPH_RUN_BYTES,
    fine === 0 ? 0 : fine * rows * HEATMAP_TEXEL_BYTES + fine * COLUMN_TIME_BYTES,
    coarse * rows * HEATMAP_TEXEL_BYTES,
    ATLAS_BYTES,
    MISC_BYTES,
    w === 0 || h === 0 ? 0 : padded(w) * padded(h) * RGBA8_BYTES,
  ];
  let totalBytes = 0;
  const items = ESTIMATE_ITEMS.map((item, i) => {
    const b = bytes[i] as number;
    totalBytes += b;
    return Object.freeze({ item, bytes: b });
  });
  const budgetBytes = budgetMb * MIB;
  return Object.freeze({
    items: Object.freeze(items),
    totalBytes,
    budgetBytes,
    requiresConfirmation: totalBytes > 0.7 * budgetBytes,
  });
}

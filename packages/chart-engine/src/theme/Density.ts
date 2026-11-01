// E11-T04 (BQ-T04-05; AC2): the chart density record, E11-D05 §6 / E11-D02 D6 cited whole. One
// mode selects the whole record; no API sets one member (D6 rule 1), so cell padding, the two text
// classes and the LOD bias always change together (D6 rule 5). Values are engine constants
// (D05 §6.1 option b); they travel as metrics, never as colours (D05 §4.4 rule 2).

import { ThemeIngestError } from "./ThemeIngest.js";

export type DensityMode = "comfortable" | "compact" | "dense";

/** A text size class: 0 → `type.num.xs` 10 px, 1 → `type.num.sm` 11 px, 2 → `type.num.base` 13 px. */
export type SizeClass = 0 | 1 | 2;

/** Class → CSS px (E11-D02 §6), before the text scale (D6 rule 6, G3: out of scope here). */
export const SIZE_CLASS_PX: readonly [number, number, number] = Object.freeze([
  10, 11, 13,
] as const);

/** The axis density gap `G` in CSS px (E11-D02 D6; replaces E11-S06's interim constant, G-51). */
export interface AxisGap {
  readonly timePx: number;
  readonly pricePx: number;
}

/** D05 §6's four members, plus the derived axis gap. Frozen; there is no setter for a member. */
export interface DensityRecord {
  readonly mode: DensityMode;
  readonly cellPadPx: number;
  readonly fontSizeClass: SizeClass;
  readonly axisFontSizeClass: SizeClass;
  /** px added to every LOD_PROFILE_M0 height; never negative; dense = compact (D6 rule 2). */
  readonly lodBias: number;
  readonly axisGap: AxisGap;
}

const rec = (
  mode: DensityMode,
  cellPadPx: number,
  fontSizeClass: SizeClass,
  axisFontSizeClass: SizeClass,
  lodBias: number,
  timePx: number,
  pricePx: number,
): DensityRecord =>
  Object.freeze({
    mode,
    cellPadPx,
    fontSizeClass,
    axisFontSizeClass,
    lodBias,
    axisGap: Object.freeze({ timePx, pricePx }),
  });

const RECORDS: Readonly<Record<DensityMode, DensityRecord>> = Object.freeze({
  comfortable: rec("comfortable", 4, 1, 2, 1, 96, 48),
  compact: rec("compact", 2, 0, 1, 0, 80, 40),
  dense: rec("dense", 1, 0, 0, 0, 64, 32),
});

export const DENSITY_MODES: readonly DensityMode[] = Object.freeze([
  "comfortable",
  "compact",
  "dense",
]);

/** The whole record for `mode`; an unknown mode throws ENGINE_THEME_INVALID naming `density`. */
export function densityRecord(mode: unknown): DensityRecord {
  if (typeof mode !== "string" || !Object.hasOwn(RECORDS, mode)) {
    throw new ThemeIngestError("density", "invalid");
  }
  return RECORDS[mode as DensityMode];
}

/** Holds the active record (PR-4 wires it to `setDensity`); `set` swaps the whole record or, on a bad mode, nothing. */
export class DensityState {
  #current: DensityRecord = RECORDS.comfortable; // §8 `ChartOptions.density` default

  get current(): DensityRecord {
    return this.#current;
  }

  set(mode: DensityMode): DensityRecord {
    this.#current = densityRecord(mode);
    return this.#current;
  }
}

// E24-S08 (#783) slice 1: the basis a tick yields for a source (`24` §7: `basis = <source> − index`,
// `premium_pct = basis / index × 100`). Exact decimals through `decimal.ts` (ruled (6612480577), a recorded deviation until E24-T04 serves a live basis); `null` when
// the source price or the index is missing, so a missing field is never drawn as 0.
import { percentOf, subtractDecimals } from "./decimal";
import type { BasisSource } from "./settings";
import type { BasisTick } from "./ticker";

export interface BasisReading {
  readonly source: BasisSource;
  readonly basis: string;
  /** Three decimals, as D03 §2 draws it ("basis %", never "premium"). */
  readonly pct: string;
}

export const PCT_PLACES = 3;

export function basisOf(tick: BasisTick, source: BasisSource): BasisReading | null {
  const price = source === "last" ? tick.last : tick.mark;
  if (price === null || tick.index === null) return null;
  const basis = subtractDecimals(price, tick.index);
  if (basis === null) return null;
  const pct = percentOf(basis, tick.index, PCT_PLACES);
  return pct === null ? null : { source, basis, pct };
}

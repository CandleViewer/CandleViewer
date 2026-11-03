// E24-S08 (#783) slice 1: the basis a tick yields for a source (`24` §7: `basis = <source> − index`,
// `premium_pct = basis / index × 100`). Exact decimals through `decimal.ts` (PROPOSED, BQ 2); `null` when
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
  const pct = percentOf(basis ?? "", tick.index, PCT_PLACES);
  return basis === null || pct === null ? null : { source, basis, pct };
}

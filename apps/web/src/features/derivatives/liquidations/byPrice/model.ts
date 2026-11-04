// E24-S07 (#782) slice 2: what the recorded layer draws from one answer, and who may switch it.
// - BQ 7 (ruled 6624627875): the estimated badge comes from the answer's `estimated` flag alone, never a constant;
//   (b) is exact, so the server sends `false` and no chip is drawn (BQ 8). A refused answer never reaches here.
// - BQ 5: the window is the UTC day clamped to `meta.coverage`. A later `covered_from` is #780's partial-coverage
//   state, never a full-day claim; `no_coverage` is "not recorded", never "no liquidations", and draws no bucket.
// - BQ 10 / D03 D-7: a Viewer switches it for the session only (T1); under view-as it is T2 `rbac.view_as`, its
//   reason the panel's one notice (G-T2.5). The server still enforces `settings:write` (C-12.4).
import type { ViewAsState } from "../../../../shell/bootstrap/store";
import type { ByPriceAnswer, ByPriceBucket } from "./byPriceRead";

/** `22` `Settings.deriv.liq_by_price`'s client default (AC: off by default). */
export const DEFAULT_LIQ_BY_PRICE = false;

export type ByPriceCoverage =
  /** The store answers for the whole window from its `from`. */
  | { readonly kind: "full"; readonly fromMs: number }
  /** The store answers from `fromMs` only (later than the window's start). */
  | { readonly kind: "partial"; readonly fromMs: number }
  /** Nothing stored for the window: `firstAvailableMs` `null` when nothing is stored at all. */
  | { readonly kind: "not-recorded"; readonly firstAvailableMs: number | null };

export interface ByPriceLayer {
  readonly symbol: string;
  /** Drawn iff the answer's flag is true. */
  readonly estimated: boolean;
  readonly coverage: ByPriceCoverage;
  /** As served, largest first; empty when not recorded. */
  readonly buckets: readonly ByPriceBucket[];
}

const ms = (iso: string | null): number | null => {
  if (iso === null) return null;
  const t = Date.parse(iso);
  return Number.isFinite(t) ? t : null;
};

export function coverageOf(answer: ByPriceAnswer): ByPriceCoverage {
  const c = answer.meta.coverage;
  const coveredFrom = ms(c.covered_from);
  if (c.no_coverage || coveredFrom === null)
    return { kind: "not-recorded", firstAvailableMs: ms(c.first_available_ts) };
  const from = ms(answer.from) ?? coveredFrom;
  return coveredFrom > from
    ? { kind: "partial", fromMs: coveredFrom }
    : { kind: "full", fromMs: from };
}

export function layerOf(answer: ByPriceAnswer): ByPriceLayer {
  const coverage = coverageOf(answer);
  return {
    symbol: answer.symbol,
    estimated: answer.estimated,
    coverage,
    buckets: coverage.kind === "not-recorded" ? [] : answer.items,
  };
}

export type ToggleAccess =
  /** T1, saved through `PATCH /settings` (`settings:write`). */
  | { readonly kind: "persisted" }
  /** T1 for the session only: a Viewer (the viewer view state, D03 D-7). */
  | { readonly kind: "session" }
  /** T2 `rbac.view_as`: the reason is the panel's one notice, `noticeId`. */
  | { readonly kind: "view-as"; readonly user: string; readonly noticeId: string };

/** View-as is checked before the permission leg, as the server decides it first (E09-D09 §3.1). */
export function toggleAccess(
  viewAs: ViewAsState,
  permissions: readonly string[],
  noticeId: string,
): ToggleAccess {
  if (viewAs.kind === "held") return { kind: "view-as", user: viewAs.targetName, noticeId };
  return permissions.includes("settings:write") ? { kind: "persisted" } : { kind: "session" };
}

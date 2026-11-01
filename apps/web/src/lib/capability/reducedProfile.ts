/**
 * The reduced profile's content as a config object (E15-K01 #371, BQ-11), for E15-S08 to apply and E15-S01 to
 * read. On E15's surfaces it sheds exactly the three things E15-D12 BQ-12 RULED (`14-screens-catalogue.md`
 * SCR-153; `docs/design/E15/E15-D12.md` §6): the heatmap depth one tier, the update rate of panels not in use
 * (200 ms) and a cap on new panels (existing panels stay), applied only on the user's click. It never sheds
 * anything in `neverShed`. `maxPanes` is the only value taken from a measurement: 6, the ceiling of the
 * host's iGPU leg at 4x CPU on the main thread, indicators density (p95 at 6 panes 9.84 ms, at 8 panes
 * 14.24 ms against 13.83; the true ceiling there lies between 6 and 7; E15-K01 §3.2, §7). That leg is below the
 * reference class and missed the budget at 8, so under E15-K01's evidence rule the value is **inconclusive**:
 * PROPOSED, re-measured on the owner leg OL-3. At runtime S01 caps new panes at the smaller of it and the
 * probe's `recommendedMaxPanes`. Owner (architect) approval pending.
 */

export interface ReducedProfileConfig {
  /** Heatmap depth, in tiers relative to the full profile's. */
  readonly heatmapDepthTier: -1;
  /** Update cadence of panels not in use. */
  readonly idlePanelCadenceMs: 200;
  /** Cap on new panes; existing panes stay. PROPOSED, inconclusive on a below-class host (E15-K01 §7). */
  readonly maxPanes: number;
  readonly appliedOn: "user-click";
  readonly neverShed: readonly string[];
}

export const REDUCED_PROFILE_CONFIG: ReducedProfileConfig = Object.freeze({
  heatmapDepthTier: -1,
  idlePanelCadenceMs: 200,
  maxPanes: 6,
  appliedOn: "user-click",
  neverShed: Object.freeze([
    "environment-badge",
    "arm-state",
    "positions-and-orders",
    "error-states",
    "protection-states",
    "stale-and-disconnected-marks",
    "alerts-and-fills",
    "safety-cluster",
    "scr-152-region",
    "scr-153-rows",
  ]),
});

/**
 * The cap S01 applies to adding a pane under the reduced profile. The argument may come from a stored record,
 * so anything not a finite number counts as 0 and the result is a whole pane count in 0..`maxPanes`.
 */
export function reducedPaneCap(recommendedMaxPanes: number): number {
  const probe = Number.isFinite(recommendedMaxPanes) ? Math.floor(recommendedMaxPanes) : 0;
  return Math.max(0, Math.min(REDUCED_PROFILE_CONFIG.maxPanes, probe));
}

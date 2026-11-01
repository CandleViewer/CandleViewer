/**
 * The reduced profile's content as a config object (E15-K01 #371, BQ-11), for E15-S08 to apply and E15-S01 to
 * read. On E15's surfaces it sheds exactly the three things E15-D12 BQ-12 RULED (`14-screens-catalogue.md`
 * SCR-153; `docs/design/E15/E15-D12.md` §6): the heatmap depth one tier, the update rate of panels not in use
 * (200 ms) and a cap on new panels (existing panels stay), applied only on the user's click. It never sheds
 * anything in `neverShed`. `maxPanes` is the only measured value: 6, the weak leg's ceiling (iGPU, 4x CPU, main
 * thread, indicators density: p95 at 6 panes 9.84 ms, at 8 panes 14.24 ms against 13.83; E15-K01 §3, §7); at
 * runtime S01 caps new panes at the smaller of it and the probe's `recommendedMaxPanes`. PROPOSED; owner
 * (architect) approval pending.
 */

export interface ReducedProfileConfig {
  /** Heatmap depth, in tiers relative to the full profile's. */
  readonly heatmapDepthTier: -1;
  /** Update cadence of panels not in use. */
  readonly idlePanelCadenceMs: 200;
  /** Cap on new panes; existing panes stay. Measured (E15-K01 §7). */
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

/** The cap S01 applies to adding a pane under the reduced profile. */
export function reducedPaneCap(recommendedMaxPanes: number): number {
  return Math.min(REDUCED_PROFILE_CONFIG.maxPanes, recommendedMaxPanes);
}

import { describe, expect, it } from "vitest";
import { REDUCED_PROFILE_CONFIG, reducedPaneCap } from "../../../src/lib/capability/reducedProfile";

describe("REDUCED_PROFILE_CONFIG (SCR-153, E15-D12 §6)", () => {
  it("reducedProfile_sheds_the_three_d12_items_only", () => {
    expect(REDUCED_PROFILE_CONFIG.heatmapDepthTier).toBe(-1);
    expect(REDUCED_PROFILE_CONFIG.idlePanelCadenceMs).toBe(200);
    // E15-K01 BQ-11 ruling: no detector-evaluation knob (unsourced); D12 BQ-12's three sheds are the rule
    expect(Object.keys(REDUCED_PROFILE_CONFIG).sort()).toEqual(
      ["appliedOn", "heatmapDepthTier", "idlePanelCadenceMs", "maxPanes", "neverShed"].sort(),
    );
    expect(REDUCED_PROFILE_CONFIG.appliedOn).toBe("user-click");
    expect(REDUCED_PROFILE_CONFIG.maxPanes).toBe(6); // PROPOSED, inconclusive below class: E15-K01 §7
  });

  it("reducedProfile_never_sheds_safety_or_trading_state", () => {
    for (const k of [
      "environment-badge",
      "arm-state",
      "positions-and-orders",
      "protection-states",
      "safety-cluster",
    ])
      expect(REDUCED_PROFILE_CONFIG.neverShed).toContain(k);
  });

  it("reducedProfile_is_frozen", () => {
    expect(Object.isFrozen(REDUCED_PROFILE_CONFIG)).toBe(true);
    expect(Object.isFrozen(REDUCED_PROFILE_CONFIG.neverShed)).toBe(true);
  });

  it("reducedPaneCap_takes_the_smaller_of_config_and_probe", () => {
    expect(reducedPaneCap(0)).toBe(0);
    expect(reducedPaneCap(16)).toBe(REDUCED_PROFILE_CONFIG.maxPanes);
  });

  it("reducedPaneCap_clamps_values_from_a_bad_record", () => {
    expect(reducedPaneCap(Number.NaN)).toBe(0);
    expect(reducedPaneCap(-5)).toBe(0);
    expect(reducedPaneCap(Number.POSITIVE_INFINITY)).toBe(0);
    expect(reducedPaneCap(3.7)).toBe(3);
  });
});

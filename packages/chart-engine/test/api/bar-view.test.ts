// E11-T03: the store's read facade is the §8 `BarView` that `IndicatorPlugin.compute` receives.
import { describe, expect, expectTypeOf, it } from "vitest";
import { CHART_DEFAULTS } from "../../src/api/chart.js";
import type { BarView } from "../../src/api/types.js";
import { BarStore, DEFAULT_MAX_BARS } from "../../src/model/index.js";

describe("BarView", () => {
  it("BarStore.view() is assignable to the §8 BarView", () => {
    expectTypeOf(new BarStore().view()).toExtend<BarView>();
  });

  it("the store's maxBars default is §8 ChartOptions.maxBars's", () => {
    expect(DEFAULT_MAX_BARS).toBe(CHART_DEFAULTS.maxBars);
  });
});

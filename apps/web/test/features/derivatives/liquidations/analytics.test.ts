// E24-S05 (#780) PR 4: the feed's analytics carry ids and enums only, never a value.
import { describe, expect, it, vi } from "vitest";
import { createLiqAnalytics } from "../../../../src/features/derivatives/liquidations/analytics";

describe("createLiqAnalytics", () => {
  it("reports print_clicked and backfill_failed without prices, sizes or notionals", () => {
    const report = vi.fn();
    const a = createLiqAnalytics(report);
    a.printClicked("BTCUSDT", "long", 8);
    a.backfillFailed("BTCUSDT", 503, "coverage_unavailable");
    expect(report.mock.calls).toEqual([
      [{ name: "liquidation.print_clicked", symbol: "BTCUSDT", side: "long", cluster_size: 8 }],
      [
        {
          name: "liquidation.backfill_failed",
          symbol: "BTCUSDT",
          status: 503,
          code: "coverage_unavailable",
        },
      ],
    ]);
  });

  it("dispatches cv:analytics on window by default", () => {
    const seen = vi.fn();
    window.addEventListener("cv:analytics", seen);
    createLiqAnalytics().backfillFailed("BTCUSDT", null, null);
    window.removeEventListener("cv:analytics", seen);
    expect(seen).toHaveBeenCalledTimes(1);
  });
});

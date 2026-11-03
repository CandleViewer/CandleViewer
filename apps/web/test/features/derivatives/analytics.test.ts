// E24-S01 (#776) slice 1: the backfill-failed event carries a bounded `code` token, never free text.
import { describe, expect, it, vi } from "vitest";
import { createOiAnalytics } from "../../../src/features/derivatives/oi/analytics";

describe("OI analytics", () => {
  it("passes a token-shaped error code and reduces anything else to other", () => {
    const report = vi.fn();
    const analytics = createOiAnalytics(report);
    analytics.backfillFailed("BTCUSDT", 400, "invalid_time_range");
    analytics.backfillFailed("BTCUSDT", 500, "Bad Thing: <x>");
    analytics.backfillFailed("BTCUSDT", 500, "a".repeat(41));
    analytics.backfillFailed("BTCUSDT", null, null);
    expect(report.mock.calls.map(([d]) => (d as { code: unknown }).code)).toEqual([
      "invalid_time_range",
      "other",
      "other",
      null,
    ]);
    expect(report.mock.calls[0]?.[0]).toMatchObject({ name: "oi_panel.backfill_failed" });
  });

  it("counts a server contract breach with the anomaly's name and no value", () => {
    const report = vi.fn();
    createOiAnalytics(report).backfillAnomaly("BTCUSDT", "cursor_missing");
    expect(report).toHaveBeenCalledWith({
      name: "oi_panel.backfill_anomaly",
      symbol: "BTCUSDT",
      anomaly: "cursor_missing",
    });
  });
});

// E24-S06 (#781) slice 1: the two settings and the one source of the feed's and the bars' threshold (BQ-1).
import { describe, expect, it } from "vitest";
import {
  DEFAULT_LIQ_BAR_SETTINGS,
  feedMinNotional,
  parseThreshold,
} from "../../../../../src/features/derivatives/liquidations/bars/settings";

describe("liquidation bar settings", () => {
  it("defaults to bars with no filter, and sends the feed no filter at zero in any spelling", () => {
    expect(DEFAULT_LIQ_BAR_SETTINGS).toEqual({ mode: "bars", minNotionalUsd: "0" });
    expect(
      ["0", "0.00", "000"].map((v) => feedMinNotional({ mode: "bars", minNotionalUsd: v })),
    ).toEqual([null, null, null]);
  });

  it("gives the feed the very value the bars state", () => {
    expect(feedMinNotional({ mode: "bars", minNotionalUsd: "50000" })).toBe("50000");
  });

  it("accepts a non-negative decimal and trims it; anything else is refused", () => {
    expect(parseThreshold(" 50000.5 ")).toBe("50000.5");
    expect(["", "-1", "1e5", "abc", "1.", "1,000"].map(parseThreshold)).toEqual([
      null,
      null,
      null,
      null,
      null,
      null,
    ]);
  });
});

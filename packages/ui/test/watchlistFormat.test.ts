import { describe, expect, it } from "vitest";
import {
  formatCountdown,
  formatFundingPct,
  formatSignedPct,
  formatSigFigs,
  formatSpreadBps,
  formatUtcTime,
  formatWatchlistPrice,
} from "../src/components/internal/watchlistFormat.js";

// E08-D07 D9: tabular mono, `price_scale`, sign and ▲/▼, U+2212, turnover to 3 significant figures, bps.
const MINUS = "−";

describe("formatWatchlistPrice (D9: Last at the instrument's price_scale)", () => {
  it("groups thousands at the price scale: 64,012.50", () => {
    expect(formatWatchlistPrice(64012.5, 2)).toBe("64,012.50");
  });

  it("keeps every decimal of a fine scale: 0.12345 at 5", () => {
    expect(formatWatchlistPrice(0.12345, 5)).toBe("0.12345");
  });

  it("rounds to a whole number at scale 0", () => {
    expect(formatWatchlistPrice(64012.5, 0)).toBe("64,013");
  });

  it("writes a negative with U+2212, never a hyphen", () => {
    expect(formatWatchlistPrice(-1.5, 1)).toBe(`${MINUS}1.5`);
  });

  it("reads an absent or non-finite value as the dash", () => {
    expect(formatWatchlistPrice(undefined, 2)).toBe("—");
    expect(formatWatchlistPrice(Number.NaN, 2)).toBe("—");
  });
});

describe("formatSignedPct (D9: 24h % and OI Δ, 2 dp, sign and glyph)", () => {
  it("a rise: ▲ and +0.42%", () => {
    expect(formatSignedPct(0.42)).toEqual({ text: "+0.42%", glyph: "▲", sign: "positive" });
  });

  it("a fall: ▼ and U+2212", () => {
    expect(formatSignedPct(-0.18)).toEqual({ text: `${MINUS}0.18%`, glyph: "▼", sign: "negative" });
  });

  it("zero is 0.00% with no sign and no glyph", () => {
    expect(formatSignedPct(0)).toEqual({ text: "0.00%", glyph: "", sign: "zero" });
  });

  it("a value that rounds to zero is zero, never −0.00%", () => {
    expect(formatSignedPct(-0.004)).toEqual({ text: "0.00%", glyph: "", sign: "zero" });
  });

  it("pads to two decimals: +2.10%", () => {
    expect(formatSignedPct(2.1).text).toBe("+2.10%");
  });
});

describe("formatFundingPct (D9: 4 dp with sign, never coloured)", () => {
  it("+0.0100%", () => {
    expect(formatFundingPct(0.01)).toBe("+0.0100%");
  });

  it("a negative rate with U+2212", () => {
    expect(formatFundingPct(-0.008)).toBe(`${MINUS}0.0080%`);
  });

  it("zero has no sign", () => {
    expect(formatFundingPct(0)).toBe("0.0000%");
  });
});

describe("formatSigFigs (D9: turnover to 3 significant figures, K, M, B, the full number for the name)", () => {
  it("1.20B, named 1,200,000,000", () => {
    expect(formatSigFigs(1.2e9)).toEqual({ text: "1.20B", full: "1,200,000,000" });
  });

  it("840M and 310M", () => {
    expect([formatSigFigs(8.4e8).text, formatSigFigs(3.1e8).text]).toEqual(["840M", "310M"]);
  });

  it("12.3K", () => {
    expect(formatSigFigs(12345).text).toBe("12.3K");
  });

  it("a value that rounds up to the next unit takes it: 999,600 is 1.00M", () => {
    expect(formatSigFigs(999_600).text).toBe("1.00M");
  });

  it("999,400 stays 999K", () => {
    expect(formatSigFigs(999_400).text).toBe("999K");
  });

  it("below a thousand: no unit", () => {
    expect([formatSigFigs(950).text, formatSigFigs(95.44).text, formatSigFigs(0).text]).toEqual([
      "950",
      "95.4",
      "0",
    ]);
  });

  it("the full number is rounded to a whole and grouped", () => {
    expect(formatSigFigs(1_234_567.8).full).toBe("1,234,568");
  });
});

describe("formatSpreadBps (D9: bps, 2 dp, never coloured)", () => {
  it("0.02 and 0.70", () => {
    expect([formatSpreadBps(0.0234), formatSpreadBps(0.7)]).toEqual(["0.02", "0.70"]);
  });
});

describe("formatCountdown (D22: whole seconds left as hh:mm:ss)", () => {
  it("05:28:51", () => {
    expect(formatCountdown(((5 * 60 + 28) * 60 + 51) * 1000 + 400)).toBe("05:28:51");
  });

  it("one second left", () => {
    expect(formatCountdown(1000)).toBe("00:00:01");
  });

  it("nothing left (under a second, zero or past): undefined, the row's Settling…", () => {
    expect([formatCountdown(999), formatCountdown(0), formatCountdown(-5000)]).toEqual([
      undefined,
      undefined,
      undefined,
    ]);
  });
});

describe("formatUtcTime (the countdown's target, in its name)", () => {
  it("16:00:00 UTC", () => {
    expect(formatUtcTime(Date.UTC(2026, 9, 30, 16, 0, 0))).toBe("16:00:00 UTC");
  });
});

// E24-S04 (#779): the predicted rate's model: fail-closed classification (the misrepresentation control,
// E24-X02's abuse case), the n/a rule, the matching of the server's annualised value to the shown rate,
// and the formulas as display transforms of the server's numbers.
import { describe, expect, it } from "vitest";
import { parseItem } from "../../../src/features/funding/history";
import { buildReadout, isAccruing, sameDecimal } from "../../../src/features/funding/predicted";
import { buildFundingSeries, servesAnnualised } from "../../../src/features/funding/series";
import { annualisedFormula, annualisedPercent } from "../../../src/features/funding/ui/format";

const T = "2023-11-15T08:00:00Z";

describe("classifying an item (fail closed)", () => {
  it("is settled only with predicted false and no estimated flag", () => {
    expect(parseItem({ t: T, funding_rate: "0.0001", predicted: false, estimated: false })).toEqual(
      {
        settled: { tMs: Date.parse(T), rate: "0.0001" },
      },
    );
  });

  it.each([
    ["flag stripped", { t: T, funding_rate: "0.0001" }],
    ["non-boolean flag", { t: T, funding_rate: "0.0001", predicted: "false" }],
    ["null flag", { t: T, funding_rate: "0.0001", predicted: null }],
    [
      "estimated without predicted",
      { t: T, funding_rate: "0.0001", predicted: false, estimated: true },
    ],
    ["predicted true", { t: T, funding_rate: "0.0001", predicted: true, estimated: true }],
  ])("a payload with %s never reads as settled", (_name, item) => {
    expect(parseItem(item)).toHaveProperty("predicted");
    expect(parseItem(item)).not.toHaveProperty("settled");
  });

  it("drops an item without a readable rate instead of guessing", () => {
    expect(parseItem({ t: T, predicted: true })).toBeNull();
    expect(parseItem({ t: T, funding_rate: "x", predicted: false })).toBeNull();
  });

  it("carries the server's annualised value as sent and never computes one", () => {
    expect(
      parseItem({ t: T, funding_rate: "0.0001", predicted: false, annualised_pct: "10.95" }),
    ).toEqual({ settled: { tMs: Date.parse(T), rate: "0.0001", annualisedPct: "10.95" } });
    expect(parseItem({ t: T, funding_rate: "0.0001", predicted: true })).toEqual({
      predicted: { tMs: Date.parse(T), rate: "0.0001", annualisedPct: null },
    });
  });

  it("a settled item without a time is malformed, a predicted one without a time is kept", () => {
    expect(parseItem({ funding_rate: "0.0001", predicted: false, estimated: false })).toBeNull();
    expect(parseItem({ funding_rate: "0.0001", predicted: true, estimated: true })).toEqual({
      predicted: { tMs: null, rate: "0.0001", annualisedPct: null },
    });
  });

  it("treats the ticker's rate as accruing by contract (BQ-2)", () => {
    expect(isAccruing("ticker")).toBe(true);
    expect(isAccruing({ predicted: false, estimated: false })).toBe(false);
  });
});

describe("the readout", () => {
  const predicted = { tMs: null, rate: "0.0001", annualisedPct: "10.95" };
  const base = { tickerRate: "0.0001", historyReady: true, predicted, intervalMinutes: 480 };

  it("shows the accruing rate with the server's annualised value while the rates agree", () => {
    expect(buildReadout(base)).toEqual({
      kind: "predicted",
      rate: "0.0001",
      intervalMinutes: 480,
      annualisedPct: "10.95",
    });
    expect(buildReadout({ ...base, tickerRate: "0.00010" })).toMatchObject({
      annualisedPct: "10.95",
    });
  });

  it("omits the annualised value once the ticker has moved or the interval is unknown", () => {
    expect(buildReadout({ ...base, tickerRate: "0.00012" })).toMatchObject({ annualisedPct: null });
    expect(buildReadout({ ...base, intervalMinutes: null })).toMatchObject({ annualisedPct: null });
  });

  it("is n/a with no ticker rate, or with REST answered and no predicted item, never carried over", () => {
    expect(buildReadout({ ...base, tickerRate: null })).toEqual({ kind: "na" });
    expect(buildReadout({ ...base, predicted: null })).toEqual({ kind: "na" });
    // REST not answered yet: the ticker's rate is still shown, as predicted
    expect(buildReadout({ ...base, predicted: null, historyReady: false })).toMatchObject({
      kind: "predicted",
      annualisedPct: null,
    });
  });

  it("compares decimals on their digits", () => {
    expect(sameDecimal("0.0001", "0.00010")).toBe(true);
    expect(sameDecimal("-0", "0")).toBe(true);
    expect(sameDecimal("0.0001", "0.0002")).toBe(false);
  });
});

describe("the annualised display", () => {
  it("formats the server's value with its sign as text, half-up, never through a float", () => {
    expect(annualisedPercent("10.95")).toEqual({
      text: "+10.95 % p.a.",
      spoken: "plus 10.95 percent per year",
    });
    expect(annualisedPercent("-547.5").text).toBe("−547.50 % p.a.");
    expect(annualisedPercent("10.955").text).toBe("+10.96 % p.a.");
    expect(annualisedPercent("0").text).toBe("0.00 % p.a.");
  });

  it("writes the formula with the symbol's own factor (8 h and 4 h)", () => {
    expect(annualisedFormula("0.0001", 480, "10.95")).toBe(
      "0.0100 % × (525600 / 480) = 10.95 % p.a.",
    );
    expect(annualisedFormula("0.0001", 240, "21.90")).toBe(
      "0.0100 % × (525600 / 240) = 21.90 % p.a.",
    );
    expect(annualisedFormula("-0.005", 480, "-547.5")).toBe(
      "−0.5000 % × (525600 / 480) = −547.50 % p.a.",
    );
  });
});

describe("the series", () => {
  const settled = [{ tMs: 1, rate: "0.0001" }];

  it("keeps the predicted rate out of the settled steps", () => {
    const series = buildFundingSeries({
      settled,
      intervalMinutes: 480,
      coverage: null,
      predicted: { tMs: 2, rate: "0.0002", annualisedPct: null },
    });
    expect(series.steps).toHaveLength(1);
    expect(series.predicted?.rate).toBe("0.0002");
  });

  it("serves the annualised toggle only with a value and an interval", () => {
    const without = buildFundingSeries({ settled, intervalMinutes: 480, coverage: null });
    expect(servesAnnualised(without)).toBe(false);
    const withPct = buildFundingSeries({
      settled: [{ tMs: 1, rate: "0.0001", annualisedPct: "10.95" }],
      intervalMinutes: 480,
      coverage: null,
    });
    expect(servesAnnualised(withPct)).toBe(true);
    expect(servesAnnualised({ ...withPct, intervalMs: null })).toBe(false);
  });
});

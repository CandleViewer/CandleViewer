import { describe, expect, it } from "vitest";
import {
  DEFAULT_PRECISION,
  formatDisplayNumber,
  type NumericFormat,
  type SignDisplay,
} from "../src/components/internal/numberDisplay.js";

type Row = readonly [number, NumericFormat, SignDisplay | undefined, string, string];

// value, format, signDisplay, text, sign
const TABLE: readonly Row[] = [
  [420, "price", undefined, "420.00", "positive"],
  [-420, "price", undefined, "-420.00", "negative"],
  [0, "price", undefined, "0.00", "zero"],
  [1234567.891, "price", undefined, "1,234,567.89", "positive"],
  [420, "price", "always", "+420.00", "positive"],
  [-420, "price", "never", "420.00", "negative"],
  [0, "price", "always", "0.00", "zero"],
  [-0, "price", "always", "0.00", "zero"],
  [-0.001, "price", "auto", "0.00", "zero"],
  [0.25, "qty", undefined, "0.250", "positive"],
  [-0.25, "qty", "never", "0.250", "negative"],
  [12000, "qty", undefined, "12,000.000", "positive"],
  [12.5, "pct", undefined, "12.50%", "positive"],
  [-0.07, "pct", "always", "-0.07%", "negative"],
  [0, "pct", "always", "0.00%", "zero"],
  [420, "pnl", undefined, "+420.00", "positive"],
  [420, "pnl", "never", "+420.00", "positive"],
  [-420, "pnl", "auto", "-420.00", "negative"],
  [0, "pnl", "always", "0.00", "zero"],
  [950.56, "notional", undefined, "950.6", "positive"],
  [1_200_000, "notional", undefined, "1.2M", "positive"],
  [-1_200_000, "notional", "always", "-1.2M", "negative"],
  [1_500, "notional", "always", "+1.5K", "positive"],
  [999_960, "notional", undefined, "1.0M", "positive"],
  [999.96, "notional", undefined, "1.0K", "positive"],
  [-999.96, "notional", "always", "-1.0K", "negative"],
  [999.94, "notional", undefined, "999.9", "positive"],
  [2.5e9, "notional", undefined, "2.5B", "positive"],
  [3e12, "notional", undefined, "3.0T", "positive"],
  [0, "notional", "always", "0.0", "zero"],
];

describe("formatDisplayNumber", () => {
  it.each(TABLE)("%d as %s (%s) is %s", (value, format, signDisplay, text, sign) => {
    const out = formatDisplayNumber(value, format, signDisplay ? { signDisplay } : {});
    expect(out.text).toBe(text);
    expect(out.sign).toBe(sign);
  });

  it("groups with ',' and '.' without Intl", () => {
    expect(formatDisplayNumber(1234.5, "price", { precision: 1 }).text).toBe("1,234.5");
  });

  it("honours an explicit precision", () => {
    expect(formatDisplayNumber(1.23456, "price", { precision: 4 }).text).toBe("1.2346");
    expect(formatDisplayNumber(7, "qty", { precision: 0 }).text).toBe("7");
    expect(formatDisplayNumber(1_234_000, "notional", { precision: 2 }).text).toBe("1.23M");
  });

  it("gives an abbreviated value its expanded reading, sign included", () => {
    expect(formatDisplayNumber(1_200_000, "notional").expanded).toBe("1,200,000");
    expect(formatDisplayNumber(-1_234_567.5, "notional", { signDisplay: "always" }).expanded).toBe(
      "-1,234,567.5",
    );
    expect(formatDisplayNumber(1_500, "notional", { signDisplay: "always" }).expanded).toBe(
      "+1,500",
    );
    expect(formatDisplayNumber(950, "notional").expanded).toBeUndefined();
  });

  it("keeps values beyond 15 significant digits exact as whole numbers", () => {
    expect(formatDisplayNumber(1e16, "price").text).toBe("10,000,000,000,000,000.00");
    expect(formatDisplayNumber(1e16, "qty", { precision: 0 }).text).toBe("10,000,000,000,000,000");
    expect(formatDisplayNumber(1e16, "notional").expanded).toBe("10,000,000,000,000,000");
  });

  it("renders a dash with no sign for a non-finite value", () => {
    for (const v of [Number.NaN, Infinity, -Infinity]) {
      expect(formatDisplayNumber(v, "pnl")).toEqual({ text: "—", expanded: "no value" });
    }
  });

  it("clamps precision to 0..15 instead of throwing at render", () => {
    expect(formatDisplayNumber(1.5, "price", { precision: -1 }).text).toBe("2");
    expect(formatDisplayNumber(1, "price", { precision: 20 }).text).toBe(`1.${"0".repeat(15)}`);
    expect(formatDisplayNumber(1.25, "price", { precision: 1.9 }).text).toBe("1.3");
    expect(formatDisplayNumber(1, "price", { precision: Number.NaN }).text).toBe("1");
  });

  it("reads an abbreviation to max(precision, 2) decimals", () => {
    expect(formatDisplayNumber(1_234_567.891, "notional").expanded).toBe("1,234,567.89");
    expect(formatDisplayNumber(1_234_567.891, "notional", { precision: 3 }).expanded).toBe(
      "1,234,567.891",
    );
  });

  it("defaults the decimals per format", () => {
    expect(DEFAULT_PRECISION).toEqual({ price: 2, qty: 3, pct: 2, pnl: 2, notional: 1 });
  });
});

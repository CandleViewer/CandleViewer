// E24-S08 (#783) slice 1: exact decimal subtraction and rounded percentage on served strings.
import { describe, expect, it } from "vitest";
import { percentOf, subtractDecimals } from "../../../src/features/basis/decimal";

describe("subtractDecimals", () => {
  it("is exact on the recorded sample (last − index)", () => {
    expect(subtractDecimals("82751.20", "82782.37")).toBe("-31.17");
  });
  it("keeps the finer operand's decimals and never touches a float", () => {
    expect(subtractDecimals("0.3", "0.1")).toBe("0.2");
    expect(subtractDecimals("0.30000000000000004", "0.1")).toBe("0.20000000000000004");
    expect(subtractDecimals("1", "0.25")).toBe("0.75");
    expect(subtractDecimals("5", "5")).toBe("0");
    expect(subtractDecimals("0.50", "0.50")).toBe("0.00");
  });
  it("handles signs and magnitudes past 2^53", () => {
    expect(subtractDecimals("-1.5", "-2.5")).toBe("1.0");
    expect(subtractDecimals("-0.1", "0.1")).toBe("-0.2");
    expect(subtractDecimals("9007199254740993", "1")).toBe("9007199254740992");
  });
  it("returns null for a non-decimal", () => {
    expect(subtractDecimals("", "1")).toBeNull();
    expect(subtractDecimals("1e3", "1")).toBeNull();
    expect(subtractDecimals("1", "NaN")).toBeNull();
  });
});

describe("percentOf", () => {
  it("matches D03's sample: −31.17 over 82782.37 is −0.038 %", () => {
    expect(percentOf("-31.17", "82782.37", 3)).toBe("-0.038");
  });
  it("rounds half away from zero", () => {
    expect(percentOf("1", "8", 1)).toBe("12.5");
    expect(percentOf("1", "8", 0)).toBe("13");
    expect(percentOf("-1", "8", 0)).toBe("-13");
    expect(percentOf("1", "3", 3)).toBe("33.333");
  });
  it("carries no sign on a result that rounds to zero", () => {
    expect(percentOf("-0.0001", "82782.37", 3)).toBe("0.000");
  });
  it("is null for a zero denominator or a non-decimal", () => {
    expect(percentOf("1", "0", 3)).toBeNull();
    expect(percentOf("1", "0.00", 3)).toBeNull();
    expect(percentOf("x", "1", 3)).toBeNull();
    expect(percentOf("1", "", 3)).toBeNull();
  });
  it("is sign-correct for a negative denominator", () => {
    expect(percentOf("1", "-4", 1)).toBe("-25.0");
  });
});

// E24-S01 (#776) slice 2: D03 §2's formats — formatting only, the decimals as sent.
import { describe, expect, it } from "vitest";
import {
  compact,
  groupedDecimal,
  signedDecimal,
  tableTime,
  utcDateTime,
  utcTime,
} from "../../../src/features/derivatives/oi/ui/format";

describe("OI formats", () => {
  it("groups the decimal as sent, the sign as text", () => {
    expect(groupedDecimal("57911.602")).toBe("57,911.602");
    expect(groupedDecimal("1234567")).toBe("1,234,567");
    expect(groupedDecimal("-1234.50")).toBe("−1,234.50");
    expect(groupedDecimal("0.5")).toBe("0.5");
  });

  it("compacts the OI level with one decimal and says it in words", () => {
    expect(compact("4792254559.42")).toEqual({ text: "4.8B", spoken: "4.8 billion" });
    expect(compact("2396127279.71").text).toBe("2.4B");
    expect(compact("1100000").text).toBe("1.1M");
    expect(compact("-41210.10")).toEqual({ text: "−41.2k", spoken: "minus 41.2 thousand" });
    expect(compact("999.5")).toEqual({ text: "999.5", spoken: "999.5" });
  });

  it("rounds on the string's digits and carries into the next scale at the boundaries", () => {
    expect(compact("999950000")).toEqual({ text: "1.0B", spoken: "1.0 billion" });
    expect(compact("999949999.99").text).toBe("999.9M");
    expect(compact("999950").text).toBe("1.0M");
    expect(compact("999949").text).toBe("999.9k");
    expect(compact("999999").text).toBe("1.0M");
    expect(compact("1000").text).toBe("1.0k");
    expect(compact("1050").text).toBe("1.1k");
    expect(compact("1049.99").text).toBe("1.0k");
    expect(compact("000123456").text).toBe("123.5k");
    expect(compact("-999950000").text).toBe("\u22121.0B");
    expect(compact("123456789012345678901234").text).toBe("123456789012345.7B"); // no float, no exponent
    expect(compact("not a number").text).toBe("not a number");
  });

  it("signs a delta as text, zero unsigned", () => {
    expect(signedDecimal("4.354")).toBe("+4.354");
    expect(signedDecimal("-1240")).toBe("−1,240");
    expect(signedDecimal("0")).toBe("0");
    expect(signedDecimal("0.000")).toBe("0.000");
    expect(signedDecimal("-0.000")).toBe("0.000"); // negative zero has no minus
    expect(signedDecimal("-0")).toBe("0");
  });

  it("writes UTC times and dates", () => {
    const t = Date.parse("2026-10-21T09:14:02Z");
    expect(utcTime(t)).toBe("09:14:02 UTC");
    expect(utcDateTime(t)).toBe("21 Oct 09:14 UTC");
    expect(tableTime(t)).toBe("2026-10-21 09:14:02");
  });
});

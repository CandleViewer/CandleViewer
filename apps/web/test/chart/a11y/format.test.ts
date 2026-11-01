import { describe, expect, it } from "vitest";
import {
  MINUS,
  decimalsOf,
  displayDecimal,
  formatBarSentence,
  formatBarTime,
  formatBarTimeFull,
  qtyToDecimal,
  scaledToDecimal,
  signedDecimal,
  ticksToDecimal,
  tsvDecimal,
  tsvTime,
} from "../../../src/chart/a11y/format";

/** A seeded LCG: the property-style sweeps below are deterministic (C-13.7). */
function lcg(seed: number): () => number {
  let s = seed >>> 0;
  return () => {
    s = (Math.imul(s, 1664525) + 1013904223) >>> 0;
    return s / 2 ** 32;
  };
}

const T = Date.UTC(2026, 9, 20, 13, 58, 7) * 1000;

describe("number formatting", () => {
  it("decimalsOf reads a step's digits, exponent form included", () => {
    expect(decimalsOf(0.5)).toBe(1);
    expect(decimalsOf(0.01)).toBe(2);
    expect(decimalsOf(1)).toBe(0);
    expect(decimalsOf(1e-7)).toBe(7);
    expect(decimalsOf(2.5e-8)).toBe(9);
    expect(() => decimalsOf(0)).toThrow(RangeError);
  });

  it("scaledToDecimal places the point, pads and keeps the sign", () => {
    expect(scaledToDecimal(12345, 2)).toBe("123.45");
    expect(scaledToDecimal(5, 3)).toBe("0.005");
    expect(scaledToDecimal(-5, 3)).toBe("-0.005");
    expect(scaledToDecimal(42, 0)).toBe("42");
    expect(() => scaledToDecimal(0.5, 1)).toThrow(RangeError);
  });

  it("ticksToDecimal refuses a tick or an origin the digits cannot show", () => {
    expect(() => ticksToDecimal(1, 64000, 0.05, 1)).toThrow(RangeError);
    expect(() => ticksToDecimal(1, 0.05, 0.1, 1)).toThrow(RangeError);
    expect(ticksToDecimal(1, 64000, 0.05, 2)).toBe("64000.05");
  });

  it("ticksToDecimal refuses a non-representable price at BTC magnitude (review fold)", () => {
    expect(() => ticksToDecimal(0, 64000.25, 0.1, 1)).toThrow(RangeError);
    expect(() => ticksToDecimal(1, 100000.05, 0.1, 1)).toThrow(RangeError);
    expect(() => ticksToDecimal(0, 64000, 0.25, 1)).toThrow(RangeError);
    expect(() => ticksToDecimal(0, 99999.005, 0.01, 2)).toThrow(RangeError);
    expect(() => ticksToDecimal(0, 64000.1, 0.05, 1)).toThrow(RangeError);
  });

  it("property: BTC-magnitude origins that the digits show pass exactly, others throw", () => {
    const rnd = lcg(5278);
    const cases: [number, number][] = [
      [1, 0.1],
      [1, 0.5],
      [2, 0.01],
      [2, 0.5],
    ];
    for (let n = 0; n < 1_000; n++) {
      const [decimals, tick] = cases[n % cases.length] as [number, number];
      const unit = 10 ** decimals;
      const intOrigin = 60_000 * unit + Math.floor(rnd() * 40_000 * unit);
      const origin = intOrigin / unit; // the nearest double to the decimal, as a feed would send it
      const ticks = Math.floor(rnd() * 200) - 100;
      const tickInt = Math.round(tick * unit);
      const got = ticksToDecimal(ticks, origin, tick, decimals);
      expect(got).toBe(scaledToDecimal(intOrigin + ticks * tickInt, decimals));
      // one extra digit on the origin is not representable at `decimals`
      const off = (intOrigin * 10 + 5) / (unit * 10);
      expect(() => ticksToDecimal(ticks, off, tick, decimals)).toThrow(RangeError);
    }
  });

  it("ticksToDecimal never re-quantises a float (0.1-tick trap)", () => {
    expect(ticksToDecimal(3, 64000, 0.1, 1)).toBe("64000.3");
    expect(ticksToDecimal(21, 64000, 0.5, 1)).toBe("64010.5");
    expect(ticksToDecimal(-3, 0.3, 0.1, 1)).toBe("0.0");
    expect(qtyToDecimal(0.1, 3)).toBe("0.100");
  });

  it("property: ticksToDecimal equals exact integer arithmetic for random prices", () => {
    const rnd = lcg(1316);
    for (let n = 0; n < 2_000; n++) {
      const decimals = Math.floor(rnd() * 4);
      const unit = 10 ** decimals;
      const tick = Math.max(1, Math.floor(rnd() * 50));
      const origin = Math.floor(rnd() * 1e7);
      const ticks = Math.floor(rnd() * 2e5) - 1e5;
      const exact = BigInt(origin) + BigInt(ticks) * BigInt(tick);
      const neg = exact < 0n;
      const digits = (neg ? -exact : exact).toString().padStart(decimals + 1, "0");
      const want =
        (neg ? "-" : "") +
        (decimals === 0
          ? digits
          : `${digits.slice(0, -decimals)}.${digits.slice(digits.length - decimals)}`);
      expect(ticksToDecimal(ticks, origin / unit, tick / unit, decimals)).toBe(want);
    }
  });

  it("displayDecimal groups thousands and shows U+2212; zero has no sign", () => {
    expect(displayDecimal("64010.5")).toBe("64,010.5");
    expect(displayDecimal("-1234567.25")).toBe(`${MINUS}1,234,567.25`);
    expect(displayDecimal("999")).toBe("999");
    expect(displayDecimal("-0.000")).toBe("0.000");
    expect(() => displayDecimal("1e5")).toThrow(RangeError);
    expect(() => displayDecimal("64,010")).toThrow(RangeError);
  });

  it("property: grouping round-trips to the same decimal", () => {
    const rnd = lcg(45);
    for (let n = 0; n < 1_000; n++) {
      const value = scaledToDecimal(Math.floor((rnd() - 0.5) * 1e12), Math.floor(rnd() * 4));
      const back = displayDecimal(value).replaceAll(",", "").replace(MINUS, "-");
      expect(back).toBe(/^-[0.]+$/.test(value) ? value.slice(1) : value);
    }
  });

  it("signedDecimal always signs; TSV keeps ASCII and drops a negative zero's sign", () => {
    expect(signedDecimal("118")).toBe("+118");
    expect(signedDecimal("-14")).toBe(`${MINUS}14`);
    expect(signedDecimal("0")).toBe("+0");
    expect(tsvDecimal("-14.5")).toBe("-14.5");
    expect(tsvDecimal("-0.00")).toBe("0.00");
  });
});

describe("time formatting (UTC, locale-stable)", () => {
  it("hh:mm at ≥ 1 min, hh:mm:ss below", () => {
    expect(formatBarTime(T, 60_000)).toBe("13:58");
    expect(formatBarTime(T, 15_000)).toBe("13:58:07");
  });
  it("the full name and the TSV time", () => {
    expect(formatBarTimeFull(T)).toBe("2026-10-20 13:58:07 UTC");
    expect(tsvTime(T)).toBe("2026-10-20T13:58:07Z");
  });
});

describe("formatBarSentence (Gherkin 1: one coherent utterance)", () => {
  const bar = {
    timeUs: T,
    open: "64010.0",
    high: "64031.5",
    low: "64002.0",
    close: "64028.0",
    volume: "212",
    delta: "118",
  };
  it("reads time, open, high, low, close, volume and delta in one sentence", () => {
    expect(formatBarSentence(bar, 60_000)).toBe(
      "13:58, open 64,010.0, high 64,031.5, low 64,002.0, close 64,028.0, volume 212, delta +118",
    );
  });
  it("omits delta when the bar has no footprint", () => {
    expect(formatBarSentence({ ...bar, delta: undefined }, 60_000)).toBe(
      "13:58, open 64,010.0, high 64,031.5, low 64,002.0, close 64,028.0, volume 212",
    );
  });
});

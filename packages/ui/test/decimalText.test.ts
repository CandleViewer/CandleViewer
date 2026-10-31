import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";
import {
  MAX_PLACES,
  MINUS,
  formatDecimal,
  parseDecimal,
  roundDecimal,
  type DecimalSign,
} from "../src/components/internal/decimalText.js";

/** mulberry32: a seeded 32-bit generator, so every property run draws the same cases. */
function seeded(seed: number): () => number {
  let state = seed >>> 0;
  return () => {
    state = (state + 0x6d2b79f5) >>> 0;
    let t = state;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

const SEED = 911;
const CASES = 4000;

interface Case {
  readonly text: string;
  readonly places: number | undefined;
  readonly plus: boolean;
}

/** A wire decimal: up to 20 whole digits (leading zeros included), up to 12 decimals, either sign. */
function drawCase(random: () => number): Case {
  const digit = (): string => String(Math.floor(random() * 10));
  const run = (length: number): string => Array.from({ length }, digit).join("");
  const whole = run(1 + Math.floor(random() * 20));
  const decimals = Math.floor(random() * 13);
  const fraction = decimals === 0 ? "" : `.${run(decimals)}`;
  const minus = random() < 0.5 ? "-" : "";
  const places = random() < 0.2 ? undefined : Math.floor(random() * 13);
  return { text: `${minus}${whole}${fraction}`, places, plus: random() < 0.5 };
}

/**
 * The reference, written apart from the code under test: round half away from zero as floor(|n| / d + 1/2) on one
 * BigInt fraction, and group the whole part with Intl's en-US grouping instead of a regular expression.
 */
function reference({ text, places, plus }: Case): {
  text: string;
  magnitude: string;
  sign: DecimalSign;
} {
  const negative = text.startsWith("-");
  const [whole = "", fraction = ""] = (negative ? text.slice(1) : text).split(".");
  const numerator = BigInt(`${whole}${fraction}`);
  const denominator = 10n ** BigInt(fraction.length);
  const shown = places ?? fraction.length;
  const scaled = (2n * numerator * 10n ** BigInt(shown) + denominator) / (2n * denominator);
  const padded = scaled.toString().padStart(shown + 1, "0");
  const grouped = new Intl.NumberFormat("en-US").format(
    BigInt(padded.slice(0, padded.length - shown)),
  );
  const magnitude = shown === 0 ? grouped : `${grouped}.${padded.slice(padded.length - shown)}`;
  const sign: DecimalSign = scaled === 0n ? "zero" : negative ? "negative" : "positive";
  const lead = sign === "negative" ? MINUS : sign === "positive" && plus ? "+" : "";
  return { text: `${lead}${magnitude}`, magnitude, sign };
}

/** A shown text back to the wire's form: no grouping, an ASCII minus. */
const wire = (text: string): string =>
  text.replaceAll(",", "").replace(MINUS, "-").replace("+", "");

describe("formatDecimal", () => {
  it.each([
    ["8", undefined, false, "8", "positive"],
    ["8.00", undefined, true, "+8.00", "positive"],
    ["-121.5", 2, true, `${MINUS}121.50`, "negative"],
    ["1234567.891", 2, false, "1,234,567.89", "positive"],
    ["0.005", 2, true, "+0.01", "positive"],
    ["-0.005", 2, true, `${MINUS}0.01`, "negative"],
    ["-0.004", 2, true, "0.00", "zero"],
    ["0", 2, true, "0.00", "zero"],
    ["-0", undefined, true, "0", "zero"],
    ["-0.00", undefined, false, "0.00", "zero"],
    ["2.5", 0, false, "3", "positive"],
    ["-2.5", 0, false, `${MINUS}3`, "negative"],
    ["2.4999", 0, false, "2", "positive"],
    ["999.995", 2, false, "1,000.00", "positive"],
    ["007.50", undefined, false, "7.50", "positive"],
    ["63880.0", 1, false, "63,880.0", "positive"],
    ["0.250", 3, false, "0.250", "positive"],
    ["12", 3, false, "12.000", "positive"],
  ] as const)("%s at %s places (plus: %s) shows %s", (text, places, plus, shown, sign) => {
    const out = formatDecimal(text, { ...(places === undefined ? {} : { places }), plus });
    expect(out?.text).toBe(shown);
    expect(out?.sign).toBe(sign);
  });

  it("keeps the magnitude unsigned for a spoken reading", () => {
    expect(formatDecimal("-121.5", { places: 2, plus: true })?.magnitude).toBe("121.50");
    expect(formatDecimal("8", { places: 2, plus: true })?.magnitude).toBe("8.00");
  });

  it("is exact beyond a double's 15 significant digits", () => {
    expect(formatDecimal("123456789012345678.123456789", { places: 8 })?.text).toBe(
      "123,456,789,012,345,678.12345679",
    );
    expect(formatDecimal("-9007199254740993.5", { places: 0 })?.text).toBe(
      `${MINUS}9,007,199,254,740,994`,
    );
  });

  it.each([
    "",
    " 1",
    "1 ",
    "+1",
    ".5",
    "1.",
    "1e5",
    "1E5",
    "1,000",
    "NaN",
    "Infinity",
    "0x10",
    "--1",
    "1.2.3",
  ])("refuses %j: not the wire's decimal", (text) => {
    expect(formatDecimal(text)).toBeNull();
    expect(parseDecimal(text)).toBeNull();
  });

  it("clamps places to a whole number in 0..MAX_PLACES instead of throwing at render", () => {
    expect(formatDecimal("1.5", { places: -1 })?.text).toBe("2");
    expect(formatDecimal("1.25", { places: 1.9 })?.text).toBe("1.3");
    expect(formatDecimal("1", { places: Number.NaN })?.text).toBe("1");
    expect(formatDecimal("1", { places: 99 })?.text).toBe(`1.${"0".repeat(MAX_PLACES)}`);
  });

  it("parses and rounds on the scaled integer", () => {
    expect(parseDecimal("-12.340")).toEqual({ units: -12340n, scale: 3 });
    expect(roundDecimal({ units: -12345n, scale: 3 }, 2)).toEqual({ units: -1235n, scale: 2 });
    expect(roundDecimal({ units: 15n, scale: 1 }, 3)).toEqual({ units: 1500n, scale: 3 });
  });

  it("never calls Number(), parseFloat or parseInt on a money string (source scan)", () => {
    const source = readFileSync(
      resolve(import.meta.dirname, "../src/components/internal/decimalText.ts"),
      "utf-8",
    ).replace(/\/\/.*$|\/\*[\s\S]*?\*\//gm, "");
    expect(source).not.toMatch(/\bNumber\(|parseFloat|parseInt|Number\.parse|\+\s*text\b/);
  });
});

describe("formatDecimal properties (seeded, against an independent BigInt reference)", () => {
  const cases = ((): Case[] => {
    const random = seeded(SEED);
    return Array.from({ length: CASES }, () => drawCase(random));
  })();
  const options = ({ places, plus }: Case) => ({
    ...(places === undefined ? {} : { places }),
    plus,
  });

  it("matches the reference on every drawn case", () => {
    for (const c of cases) expect(formatDecimal(c.text, options(c)), c.text).toEqual(reference(c));
  });

  it("round-trips: the shown text, de-grouped, is a wire decimal of the rounded value", () => {
    for (const c of cases) {
      const shown = formatDecimal(c.text, options(c));
      const back = parseDecimal(wire(shown?.text ?? ""));
      const parsed = parseDecimal(c.text);
      expect(back, c.text).not.toBeNull();
      if (back === null || parsed === null) continue;
      expect(back, c.text).toEqual(roundDecimal(parsed, c.places ?? parsed.scale));
    }
  });

  it("is idempotent: formatting the shown value again at the same places changes nothing", () => {
    for (const c of cases) {
      const once = formatDecimal(c.text, options(c))?.text ?? "";
      expect(formatDecimal(wire(once), options(c))?.text, c.text).toBe(once);
    }
  });

  it("never signs a zero and never shows an ASCII hyphen-minus", () => {
    for (const c of cases) {
      const shown = formatDecimal(c.text, options(c));
      expect(shown?.text, c.text).not.toContain("-");
      if (shown?.sign === "zero") expect(shown.text, c.text).toMatch(/^[0-9.,]+$/);
    }
  });
});

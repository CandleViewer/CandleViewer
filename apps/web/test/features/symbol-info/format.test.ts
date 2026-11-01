/**
 * E08-D06 §5 (F1-F5, F8): the positional minimal-form formatter, over the shared policy corpus
 * (`packages/fixtures/golden/policy/corpus.json`), the exponent forms the serialiser can print (F2, CR-3) and a
 * seeded round-trip property (no `number` anywhere). The repo has no fast-check, so the property uses a fixed-seed PRNG.
 */
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { policy } from "@candleviewer/protocol";
import { describe, expect, it } from "vitest";
import {
  formatAtStep,
  formatRule,
  group,
  minimal,
  parseDecimal,
  sameValue,
  toPositional,
  type Dec,
} from "../../../src/features/symbol-info/format";

interface Case {
  readonly instrument: { readonly tick_size: string; readonly qty_step: string };
  readonly price: string;
  readonly qty: string;
  readonly expected_rounded_price: string;
  readonly expected_rounded_qty: string;
}
const CORPUS = JSON.parse(
  readFileSync(
    resolve(import.meta.dirname, "../../../../../packages/fixtures/golden/policy/corpus.json"),
    "utf8",
  ),
) as { readonly cases: readonly Case[] };

const dec = (input: string): Dec => {
  const parsed = parseDecimal(input);
  if (!parsed.ok) throw new Error(`unparsable ${input}`);
  return parsed.dec;
};
const ungroup = (text: string | null): string => (text ?? "").replaceAll(",", "");

describe("formatRule (F3, F8)", () => {
  it.each([
    ["0.10", "0.1"],
    ["100.000", "100"],
    ["100.00", "100"],
    ["0.001", "0.001"],
    ["0.005", "0.005"],
    ["5", "5"],
    ["0", "0"],
    ["0.00", "0"],
    ["-0.0", "0"],
    ["1000000", "1,000,000"],
    ["1234.5600", "1,234.56"],
    ["999999.00", "999,999"],
  ])("shows %s as %s", (input, shown) => {
    expect(formatRule(input)).toEqual({ text: shown, malformed: null });
  });

  it("never loses a significant digit of a 30-digit value (no float)", () => {
    expect(formatRule("0.123456789012345678901234567890").text).toBe(
      "0.12345678901234567890123456789",
    );
    expect(formatRule("12345678901234567890.10").text).toBe("12,345,678,901,234,567,890.1");
  });

  it.each([
    ["1E-7", "0.0000001"],
    ["1e-7", "0.0000001"],
    ["5E-4", "0.0005"],
    ["1.5E-7", "0.00000015"],
    ["1E+3", "1,000"],
    ["1.50E+2", "150"],
    ["0E-8", "0"],
    ["-2E-3", "-0.002"],
  ])("expands the exponent form %s to %s and reports kind exponent", (input, shown) => {
    expect(formatRule(input)).toEqual({ text: shown, malformed: "exponent" });
  });

  it.each([
    "",
    " 1",
    "1 ",
    "abc",
    "1,5",
    "1.",
    ".5",
    "1e",
    "1E+",
    "NaN",
    "Infinity",
    "--1",
    "1E999",
  ])("reads %j as unparsable: no text, never a guess", (input) => {
    expect(formatRule(input)).toEqual({ text: null, malformed: "unparsable" });
  });

  it("treats an absent value as a dash with nothing to report", () => {
    expect(formatRule(undefined)).toEqual({ text: null, malformed: null });
    expect(formatRule(null)).toEqual({ text: null, malformed: null });
  });
});

describe("formatAtStep (F4, F5)", () => {
  it.each([
    ["82751.2", "0.1", "82,751.2"],
    ["82782.37", "0.1", "82,782.37"], // the index keeps its second decimal, never rounded to the tick
    ["64010", "0.1", "64,010.0"],
    ["50000.0", "0.10", "50,000.0"],
    ["0.250", "0.001", "0.250"],
    ["57911.602", "0.001", "57,911.602"],
    ["3210.4749", "0.01", "3,210.4749"],
  ])("shows %s at step %s as %s", (value, step, shown) => {
    expect(formatAtStep(value, step).text).toBe(shown);
  });

  it("shows a value's own decimals as delivered until the step is known", () => {
    expect(formatAtStep("82751.20", null).text).toBe("82,751.20");
    expect(formatAtStep("82751.20", "garbage").text).toBe("82,751.20");
  });

  it("expands an exponent value and reports it", () => {
    expect(formatAtStep("1E-7", "0.0000001")).toEqual({ text: "0.0000001", malformed: "exponent" });
  });

  it("is a dash for an absent or unparsable value", () => {
    expect(formatAtStep(undefined, "0.1").text).toBeNull();
    expect(formatAtStep("x", "0.1")).toEqual({ text: null, malformed: "unparsable" });
  });
});

describe("group (F8)", () => {
  it.each([
    ["1", "1"],
    ["999", "999"],
    ["1000", "1,000"],
    ["-1234567.891", "-1,234,567.891"],
    ["0.1234567", "0.1234567"],
  ])("groups %s as %s, the integer part only", (input, shown) => {
    expect(group(input)).toBe(shown);
  });
});

describe("the policy corpus", () => {
  it("has cases", () => {
    expect(CORPUS.cases.length).toBeGreaterThan(100);
  });

  it("shows every tick and step in minimal form, equal in value, and the rounded example at step precision", () => {
    for (const c of CORPUS.cases) {
      const { tick_size: tick, qty_step: step } = c.instrument;
      for (const rule of [tick, step]) {
        const shown = ungroup(formatRule(rule).text);
        expect(sameValue(dec(shown), dec(rule))).toBe(true);
        expect(shown.endsWith("0") && shown.includes(".")).toBe(false);
      }
      // The rounded example runs through the shared rule source on the positional minimal text.
      const price = policy.roundPrice(c.price, toPositional(minimal(dec(tick))));
      const qty = policy.roundQty(c.qty, toPositional(minimal(dec(step))));
      expect(sameValue(dec(price), dec(c.expected_rounded_price))).toBe(true);
      expect(sameValue(dec(qty), dec(c.expected_rounded_qty))).toBe(true);
      for (const [value, rule] of [
        [price, tick],
        [qty, step],
      ] as const) {
        const shown = ungroup(formatAtStep(value, rule).text);
        expect(sameValue(dec(shown), dec(value))).toBe(true);
        expect(dec(shown).scale).toBe(
          Math.max(minimal(dec(rule)).scale, minimal(dec(value)).scale),
        );
      }
    }
  });

  it("formats an exponent spelling of every tick and step as the positional one", () => {
    for (const c of CORPUS.cases) {
      for (const rule of [c.instrument.tick_size, c.instrument.qty_step]) {
        const d = minimal(dec(rule));
        const spelled = `${d.unscaled.toString()}E-${String(d.scale)}`;
        expect(formatRule(spelled).text).toBe(formatRule(rule).text);
      }
    }
  });
});

/** A fixed-seed generator (mulberry32): the property runs the same on every machine. */
function prng(seed: number): () => number {
  let a = seed;
  return () => {
    a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

describe("round trip (property, seeded)", () => {
  it("keeps the value through minimal, positional and grouping, and through an exponent spelling", () => {
    const next = prng(4704);
    const digits = (n: number): string =>
      Array.from({ length: n }, () => String(Math.floor(next() * 10))).join("");
    for (let i = 0; i < 2000; i += 1) {
      const sign = next() < 0.2 ? "-" : "";
      const whole = digits(1 + Math.floor(next() * 14)).replace(/^0+(?=\d)/, "");
      const fraction = next() < 0.3 ? "" : digits(1 + Math.floor(next() * 14));
      const input = `${sign}${whole}${fraction === "" ? "" : `.${fraction}`}`;
      const original = dec(input);
      const shown = formatRule(input);
      expect(shown.malformed).toBeNull();
      const text = ungroup(shown.text);
      expect(sameValue(dec(text), original)).toBe(true);
      // minimal: no trailing fraction zero, and idempotent
      expect(/\.\d*0$/.test(text)).toBe(false);
      expect(formatRule(text).text).toBe(shown.text);
      // the exponent spelling of the same value formats alike (a zero has no sign)
      const exp = `${original.unscaled.toString()}E-${String(original.scale)}`;
      expect(formatRule(exp).text).toBe(shown.text);
      // at a step, the value is unchanged and the decimals are the larger of the two
      const at = ungroup(formatAtStep(input, "0.001").text);
      expect(sameValue(dec(at), original)).toBe(true);
      expect(dec(at).scale).toBe(Math.max(3, minimal(original).scale));
    }
  });
});

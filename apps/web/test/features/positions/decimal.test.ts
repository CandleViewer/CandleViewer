/**
 * E29-S01 (#911) `decimal.ts`: exact decimal arithmetic on wire strings. Unit cases, seeded
 * properties against an independent `BigInt` reference at a fixed 30-place scale, and a source scan
 * that no positions module parses money through a JS `number` (the ticket's "Decimal-safe money").
 */
import { readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import {
  abs,
  add,
  cmp,
  dec,
  div,
  isZero,
  mul,
  neg,
  normalise,
  parseDecimal,
  round,
  sameAmount,
  sign,
  sub,
  sum,
  toPlain,
} from "../../../src/features/positions/model/decimal";

/** mulberry32: a seeded, reproducible stream (C-13.7). */
function rng(seed: number): () => number {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

const REF = 30;
/** The reference: the value times 10^30, by string surgery alone. */
function ref(text: string): bigint {
  const negative = text.startsWith("-");
  const [whole = "0", fraction = ""] = (negative ? text.slice(1) : text).split(".");
  const v = BigInt(whole + fraction.padEnd(REF, "0"));
  return negative ? -v : v;
}
const fromRef = (v: bigint, scale: number): bigint => v / 10n ** BigInt(REF - scale);
function refRound(n: bigint, d: bigint): bigint {
  const q = n / d;
  const r = n - q * d;
  if (2n * (r < 0n ? -r : r) < (d < 0n ? -d : d)) return q;
  return n < 0n === d < 0n ? q + 1n : q - 1n;
}

function randomDecimal(next: () => number): string {
  const digits = (n: number): string =>
    Array.from({ length: n }, () => Math.floor(next() * 10).toString()).join("");
  const whole = String(BigInt(digits(1 + Math.floor(next() * 12)))); // no leading zeros
  const places = Math.floor(next() * 9);
  const text = places === 0 ? whole : `${whole}.${digits(places)}`;
  return next() < 0.5 && /[1-9]/.test(text) ? `-${text}` : text;
}

const units = (text: string, scale: number): bigint => {
  const d = parseDecimal(text);
  if (d === null) throw new Error(text);
  return d.units * 10n ** BigInt(scale - d.scale);
};

describe("parseDecimal", () => {
  it("reads the wire's plain decimals exactly", () => {
    expect(parseDecimal("63980.0")).toEqual({ units: 639800n, scale: 1 });
    expect(parseDecimal("-121.50")).toEqual({ units: -12150n, scale: 2 });
    expect(parseDecimal("0")).toEqual({ units: 0n, scale: 0 });
  });

  it.each([1.5, "1e3", "1.", ".5", "+1", " 1", "1,000", "0x10", "", "NaN", null, undefined])(
    "refuses %s",
    (value) => {
      expect(parseDecimal(value)).toBeNull();
    },
  );

  it("refuses a value too long to be a numeric(38,18)", () => {
    expect(parseDecimal("9".repeat(70))).toBeNull();
  });

  it("dec throws on a literal typo", () => {
    expect(() => dec("1e5")).toThrow(TypeError);
  });
});

describe("arithmetic", () => {
  it("adds, subtracts and multiplies across scales", () => {
    expect(toPlain(add(dec("8.00"), dec("2.7")))).toBe("10.70");
    expect(toPlain(sub(dec("64012"), dec("63980.0")))).toBe("32.0");
    expect(toPlain(mul(dec("0.250"), dec("64012.0")))).toBe("16003.0000");
    expect(
      toPlain(sum([dec("8.00"), dec("2.70"), dec("-121.50"), dec("-92.00"), dec("-3.04")])),
    ).toBe("-205.84");
  });

  it("orders by value whatever the scale", () => {
    expect(cmp(dec("0.50"), dec("0.5"))).toBe(0);
    expect(cmp(dec("-1"), dec("0.01"))).toBe(-1);
    expect(cmp(dec("10"), dec("9.999"))).toBe(1);
    expect(sameAmount("0.250", "0.25")).toBe(true);
    expect(sameAmount("0.250", "x")).toBe(false);
  });

  it("rounds half away from zero", () => {
    expect(toPlain(round(dec("1.25"), 1))).toBe("1.3");
    expect(toPlain(round(dec("-1.25"), 1))).toBe("-1.3");
    expect(toPlain(round(dec("1.24"), 1))).toBe("1.2");
    expect(toPlain(round(dec("9.545"), 1))).toBe("9.5");
    expect(toPlain(round(dec("2"), 2))).toBe("2.00");
  });

  it("divides at a scale, and refuses a zero divisor", () => {
    expect(toPlain(div(dec("27"), dec("85"), 4) ?? dec("0"))).toBe("0.3176");
    expect(toPlain(div(dec("-81"), dec("95"), 4) ?? dec("0"))).toBe("-0.8526");
    expect(div(dec("1"), dec("0.00"), 2)).toBeNull();
  });

  it("signs, negates and normalises", () => {
    expect(sign(dec("-0.1"))).toBe(-1);
    expect(sign(dec("0.000"))).toBe(0);
    expect(isZero(dec("0.000"))).toBe(true);
    expect(toPlain(abs(dec("-3.04")))).toBe("3.04");
    expect(toPlain(neg(dec("0")))).toBe("0");
    expect(toPlain(normalise(dec("63980.000")))).toBe("63980");
    expect(toPlain(normalise(dec("-0.0500")))).toBe("-0.05");
    expect(toPlain(dec("-0.001"))).toBe("-0.001");
  });
});

describe("properties against a BigInt reference (seeded)", () => {
  const SEEDS = [1, 7, 911, 20261031];
  const CASES = 400;

  it.each(SEEDS)("seed %i: parse then print is the identity on canonical text", (seed) => {
    const next = rng(seed);
    for (let i = 0; i < CASES; i += 1) {
      const text = randomDecimal(next);
      expect(toPlain(parseDecimal(text) ?? dec("0"))).toBe(text);
    }
  });

  it.each(SEEDS)("seed %i: add, sub and cmp agree with the reference", (seed) => {
    const next = rng(seed);
    for (let i = 0; i < CASES; i += 1) {
      const a = randomDecimal(next);
      const b = randomDecimal(next);
      expect(units(toPlain(add(dec(a), dec(b))), REF)).toBe(ref(a) + ref(b));
      expect(units(toPlain(sub(dec(a), dec(b))), REF)).toBe(ref(a) - ref(b));
      const want = ref(a) === ref(b) ? 0 : ref(a) < ref(b) ? -1 : 1;
      expect(cmp(dec(a), dec(b))).toBe(want);
    }
  });

  it.each(SEEDS)("seed %i: div and round agree with the reference", (seed) => {
    const next = rng(seed);
    for (let i = 0; i < CASES; i += 1) {
      const a = randomDecimal(next);
      const b = randomDecimal(next);
      const scale = Math.floor(next() * 7);
      const got = div(dec(a), dec(b), scale);
      if (ref(b) === 0n) {
        expect(got).toBeNull();
        continue;
      }
      expect(got?.units).toBe(refRound(ref(a) * 10n ** BigInt(scale), ref(b)));
      const rounded = round(dec(a), scale);
      expect(rounded.units).toBe(refRound(ref(a), 10n ** BigInt(REF - scale)));
      expect(fromRef(ref(toPlain(rounded)), scale)).toBe(rounded.units);
    }
  });
});

describe("no money through a JS number", () => {
  const ROOT = join(import.meta.dirname, "../../../src/features/positions");
  const files = (dir: string): string[] =>
    readdirSync(dir, { withFileTypes: true }).flatMap((e) =>
      e.isDirectory()
        ? files(join(dir, e.name))
        : e.name.endsWith(".ts")
          ? [join(dir, e.name)]
          : [],
    );

  it("no positions module calls Number(), parseFloat or parseInt", () => {
    const offenders = files(ROOT).filter((file) =>
      /\b(?:parseFloat|parseInt)\s*\(|\bNumber\s*\(/.test(readFileSync(file, "utf8")),
    );
    expect(offenders).toEqual([]);
  });
});

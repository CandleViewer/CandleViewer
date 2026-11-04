import fc from "fast-check";
import { describe, expect, it } from "vitest";
import {
  MAX_DIGITS,
  MAX_SCALE,
  ONE,
  ZERO,
  abs,
  add,
  cmp,
  dec,
  div,
  divInt,
  eq,
  gt,
  gte,
  isZero,
  lt,
  lte,
  max,
  min,
  mul,
  neg,
  normalise,
  parseDecimal,
  roundTo,
  sign,
  stepsIn,
  sub,
  timesInt,
  toPlain,
  type Decimal,
  type RoundingMode,
} from "../src/index.js";

const SEED = 984;
const MODES: readonly RoundingMode[] = ["floor", "ceil", "trunc", "half_away"];

/** A decimal of up to 30 digits at scale 0..12. */
const arbDecimal: fc.Arbitrary<Decimal> = fc
  .record({
    units: fc.bigInt({ min: -(10n ** 30n), max: 10n ** 30n }),
    scale: fc.integer({ min: 0, max: 12 }),
  })
  .map(({ units, scale }) => ({ units, scale }));

describe("parseDecimal", () => {
  it.each([
    ["0", 0n, 0],
    ["-0.50", -50n, 2],
    ["64000.10", 6400010n, 2],
    ["0.0001", 1n, 4],
  ])("parseDecimal_wire_%s_readsExactly", (text, units, scale) => {
    expect(parseDecimal(text)).toEqual({ units, scale });
  });

  it.each([
    ["1e3"],
    ["1e9"],
    ["+1"],
    [".5"],
    ["1."],
    [" 1"],
    ["NaN"],
    [""],
    ["1".repeat(MAX_DIGITS + 3)],
  ])("parseDecimal_notAWireDecimal_%s_isNull", (text) => {
    expect(parseDecimal(text)).toBeNull();
  });

  it("parseDecimal_nonString_isNull", () => {
    expect(parseDecimal(1.5)).toBeNull();
    expect(parseDecimal(null)).toBeNull();
    expect(parseDecimal(10n)).toBeNull();
  });

  it("dec_typo_throws", () => {
    expect(() => dec("1,5")).toThrow(TypeError);
  });

  it("parseDecimal_toPlain_roundTrips", () => {
    fc.assert(
      fc.property(arbDecimal, (d) => {
        expect(parseDecimal(toPlain(d))).toEqual(d);
      }),
      { seed: SEED },
    );
  });
});

describe("arithmetic", () => {
  it("add_floatTrap_isExact", () => {
    expect(toPlain(add(dec("0.1"), dec("0.2")))).toBe("0.3");
  });

  it("sub_mul_neg_abs_sign_areExact", () => {
    expect(toPlain(sub(dec("64000.1"), dec("0.15")))).toBe("63999.95");
    expect(toPlain(mul(dec("0.312"), dec("64000.0")))).toBe("19968.0000");
    expect(toPlain(neg(dec("1.5")))).toBe("-1.5");
    expect(toPlain(abs(dec("-2.25")))).toBe("2.25");
    expect([sign(dec("-1")), sign(ZERO), sign(ONE)]).toEqual([-1, 0, 1]);
    expect(isZero(dec("0.000"))).toBe(true);
  });

  it("compare_acrossScales_isNumeric", () => {
    expect(cmp(dec("0.50"), dec("0.5"))).toBe(0);
    expect(eq(dec("1.0"), ONE)).toBe(true);
    expect(lt(dec("0.09"), dec("0.1"))).toBe(true);
    expect(lte(dec("0.1"), dec("0.10"))).toBe(true);
    expect(gt(dec("-0.1"), dec("-0.2"))).toBe(true);
    expect(gte(dec("2"), dec("1.99"))).toBe(true);
    expect(toPlain(min(dec("3"), dec("2.5")))).toBe("2.5");
    expect(toPlain(max(dec("3"), dec("2.5")))).toBe("3");
  });

  it("min_max_equalValues_returnTheFirstArgument", () => {
    const a = dec("2.50");
    const b = dec("2.5");
    expect(min(a, b)).toBe(a);
    expect(max(a, b)).toBe(a);
  });

  it("add_sub_areInverse", () => {
    fc.assert(
      fc.property(arbDecimal, arbDecimal, (a, b) => {
        expect(cmp(sub(add(a, b), b), a)).toBe(0);
      }),
      { seed: SEED },
    );
  });

  it("toPlain_neverWritesNegativeZero", () => {
    expect(toPlain({ units: 0n, scale: 2 })).toBe("0.00");
    expect(toPlain({ units: -5n, scale: 3 })).toBe("-0.005");
  });

  it("normalise_dropsTrailingZerosOnly", () => {
    expect(toPlain(normalise(dec("63980.0")))).toBe("63980");
    expect(toPlain(normalise(dec("0.0500")))).toBe("0.05");
    expect(toPlain(normalise(dec("100")))).toBe("100");
  });
});

describe("rounding", () => {
  it.each([
    [7n, 2n, "floor", 3n],
    [7n, 2n, "ceil", 4n],
    [7n, 2n, "trunc", 3n],
    [7n, 2n, "half_away", 4n],
    [-7n, 2n, "floor", -4n],
    [-7n, 2n, "ceil", -3n],
    [-7n, 2n, "trunc", -3n],
    [-7n, 2n, "half_away", -4n],
    [7n, -2n, "floor", -4n],
    [5n, 3n, "half_away", 2n],
    [4n, 3n, "half_away", 1n],
    [6n, 3n, "floor", 2n],
  ] as const)("divInt_%s_over_%s_%s_is_%s", (n, d, mode, expected) => {
    expect(divInt(n, d, mode)).toBe(expected);
  });

  it("divInt_floorAndCeil_bracketTheQuotient", () => {
    const nonZero = fc.bigInt({ min: -(10n ** 20n), max: 10n ** 20n }).filter((d) => d !== 0n);
    fc.assert(
      fc.property(fc.bigInt({ min: -(10n ** 30n), max: 10n ** 30n }), nonZero, (n, d) => {
        const lo = divInt(n, d, "floor");
        const hi = divInt(n, d, "ceil");
        // lo <= n/d <= hi, hi - lo in {0, 1}, compared without division
        const pos = d > 0n;
        expect(pos ? lo * d <= n : lo * d >= n).toBe(true);
        expect(pos ? hi * d >= n : hi * d <= n).toBe(true);
        expect(hi - lo === 0n || hi - lo === 1n).toBe(true);
        expect([lo, hi]).toContain(divInt(n, d, "half_away"));
        expect([lo, hi]).toContain(divInt(n, d, "trunc"));
      }),
      { seed: SEED },
    );
  });

  it("roundTo_widerScale_isExact", () => {
    expect(toPlain(roundTo(dec("1.5"), 3, "floor"))).toBe("1.500");
  });

  it.each([
    ["1.2349", 3, "floor", "1.234"],
    ["1.2341", 3, "ceil", "1.235"],
    ["-1.2345", 3, "half_away", "-1.235"],
    ["-1.2349", 3, "trunc", "-1.234"],
  ] as const)("roundTo_%s_at_%s_%s_is_%s", (text, scale, mode, expected) => {
    expect(toPlain(roundTo(dec(text), scale, mode))).toBe(expected);
  });

  it.each([[-1], [1.5], [Number.NaN], [Number.POSITIVE_INFINITY], [1e9], [MAX_SCALE + 1]])(
    "roundTo_and_div_scale_%s_throws",
    (scale) => {
      const message = `a decimal scale must be an integer from 0 to ${MAX_SCALE}`;
      expect(() => roundTo(ONE, scale, "floor")).toThrow(new RangeError(message));
      expect(() => div(ONE, ONE, scale, "floor")).toThrow(new RangeError(message));
    },
  );

  it("roundTo_and_div_atMaxScale_work", () => {
    expect(roundTo(ONE, MAX_SCALE, "floor").scale).toBe(MAX_SCALE);
    expect(div(ONE, dec("3"), MAX_SCALE, "floor")?.scale).toBe(MAX_SCALE);
  });

  it("div_byZero_isNull", () => {
    expect(div(ONE, ZERO, 4, "floor")).toBeNull();
    expect(stepsIn(ONE, ZERO, "floor")).toBeNull();
  });

  it("div_atScale_appliesTheMode", () => {
    expect(toPlain(div(dec("10"), dec("3"), 4, "floor") ?? ZERO)).toBe("3.3333");
    expect(toPlain(div(dec("10"), dec("3"), 4, "ceil") ?? ZERO)).toBe("3.3334");
    expect(toPlain(div(dec("37.44"), dec("120.0"), 3, "floor") ?? ZERO)).toBe("0.312");
  });

  it("stepsIn_and_timesInt_putAValueOnItsGrid", () => {
    expect(stepsIn(dec("0.3129"), dec("0.001"), "floor")).toBe(312n);
    expect(toPlain(timesInt(dec("0.005"), 3n))).toBe("0.015");
  });

  it("div_anyMode_staysWithinOneUnitOfTheTruth", () => {
    const nonZero = arbDecimal.filter((d) => d.units !== 0n);
    fc.assert(
      fc.property(arbDecimal, nonZero, fc.constantFrom(...MODES), (a, b, mode) => {
        const q = div(a, b, 6, mode);
        expect(q).not.toBeNull();
        if (q === null) return;
        // |q·b − a| < 1e-6·|b|: the quotient is within one unit at scale 6
        const err = abs(sub(mul(q, b), a));
        expect(lt(err, abs(mul(b, dec("0.000001"))))).toBe(true);
      }),
      { seed: SEED },
    );
  });
});

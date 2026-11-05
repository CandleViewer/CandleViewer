import fc from "fast-check";
import { describe, expect, it } from "vitest";
import {
  dec,
  eq,
  floorQty,
  gt,
  gte,
  isOnLot,
  isOnStep,
  isOnTick,
  lt,
  lte,
  missedMinimum,
  mul,
  parseInstrument,
  priceToTick,
  roundStop,
  roundTarget,
  sub,
  toPlain,
  toStep,
  type Decimal,
  type Instrument,
  type InstrumentGrid,
  type OrderSide,
} from "../src/index.js";
import { CLOSED_LUNA, INSTRUMENTS } from "./fixtures.js";

const SEED = 984;

function grid(inst: Instrument): InstrumentGrid {
  const parsed = parseInstrument(inst);
  if (parsed === null) throw new Error(`fixture ${inst.symbol} did not parse`);
  return parsed;
}

const GRIDS = INSTRUMENTS.map(grid);
const BTC = grid(INSTRUMENTS[0] as Instrument);
const SOL = grid(INSTRUMENTS[2] as Instrument);

/** A positive decimal: up to 12 integer digits at scale 0..8. */
const arbPositive: fc.Arbitrary<Decimal> = fc
  .record({ units: fc.bigInt({ min: 1n, max: 10n ** 20n }), scale: fc.integer({ min: 0, max: 8 }) })
  .map(({ units, scale }) => ({ units, scale }));
/** A grid step: 1, 2, 5 or 25 units at scale 0..6 (0.005, 0.25, 0.10 and the like). */
const arbStep: fc.Arbitrary<Decimal> = fc
  .record({ units: fc.constantFrom(1n, 2n, 5n, 10n, 25n), scale: fc.integer({ min: 0, max: 6 }) })
  .map(({ units, scale }) => ({ units, scale }));
const arbSide = fc.constantFrom<OrderSide>("buy", "sell");
const arbGrid = fc.constantFrom(...GRIDS);

describe("parseInstrument", () => {
  it("parseInstrument_fourRecordedInstruments_readTheirFilters", () => {
    expect(GRIDS.map((g) => [g.symbol, toPlain(g.tickSize), toPlain(g.qtyStep)])).toEqual([
      ["BTCUSDT", "0.10", "0.001"],
      ["ETHUSDT", "0.01", "0.001"],
      ["SOLUSDT", "0.005", "0.001"],
      ["LUNAUSDT", "0.0001", "0.001"],
    ]);
    for (const g of GRIDS) {
      expect(g.minOrderQty && toPlain(g.minOrderQty)).toBe("0.001");
      expect(toPlain(g.maxOrderQty ?? dec("0"))).toBe("100.000");
      expect(g.minNotional && toPlain(g.minNotional)).toBe("5");
      expect(toPlain(g.maxLeverage ?? dec("0"))).toBe("100.00");
      expect(g.tradable).toBe(true);
      expect(g.missing).toEqual([]);
    }
  });

  it("parseInstrument_closedRow_isNotTradable", () => {
    expect(grid(CLOSED_LUNA).tradable).toBe(false);
  });

  it("parseInstrument_delistedRow_isNotTradable", () => {
    expect(grid({ ...BTC_ROW(), delisted: true }).tradable).toBe(false);
  });

  it("parseInstrument_absentOptionalFilters_areNullAndListed", () => {
    const g = grid({ category: "linear", symbol: "XUSDT", tick_size: "0.5", qty_step: "0.01" });
    expect(g.minOrderQty).toBeNull();
    expect(g.maxOrderQty).toBeNull();
    expect(g.minNotional).toBeNull();
    expect(g.maxLeverage).toBeNull();
    expect(g.tradable).toBe(false); // no status: fails closed
    expect(g.missing).toEqual([
      "min_order_qty",
      "min_notional_value",
      "max_order_qty",
      "max_leverage",
    ]);
  });

  it.each([
    ["min_order_qty"],
    ["min_notional_value"],
    ["max_order_qty"],
    ["max_leverage"],
  ] as const)("parseInstrument_optionalFilter_%s_jsonNull_rejectsTheRow", (field) => {
    // JSON null is not "absent": the row is refused (fail closed), never defaulted
    const row = { ...BTC_ROW(), [field]: null } as unknown as Instrument;
    expect(parseInstrument(row)).toBeNull();
  });

  it.each([
    ["lot above the maximum", { qty_step: "1", min_order_qty: "1", max_order_qty: "0.5" }],
    ["minimum above the maximum", { min_order_qty: "200", max_order_qty: "100.000" }],
    ["minimum off the lot", { qty_step: "0.001", min_order_qty: "0.0015" }],
  ] as const)("parseInstrument_selfContradicting_%s_isNull", (_name, patch) => {
    expect(parseInstrument({ ...BTC_ROW(), ...patch })).toBeNull();
  });

  it.each([["PreLaunch"], ["Delivering"]] as const)(
    "parseInstrument_status_%s_isNotTradable",
    (status) => {
      expect(grid({ ...BTC_ROW(), status }).tradable).toBe(false);
    },
  );

  it.each([
    ["tick_size", "0"],
    ["tick_size", "-0.1"],
    ["qty_step", "1e-3"],
    ["min_order_qty", "0"],
    ["min_notional_value", "-5"],
    ["max_order_qty", "abc"],
    ["max_leverage", "0"],
  ] as const)("parseInstrument_malformed_%s_%s_isNull", (field, value) => {
    expect(parseInstrument({ ...BTC_ROW(), [field]: value })).toBeNull();
  });
});

function BTC_ROW(): Instrument {
  return INSTRUMENTS[0] as Instrument;
}

describe("grids", () => {
  it("toStep_zeroStep_throws", () => {
    expect(() => toStep(dec("1"), dec("0"), "floor")).toThrow(RangeError);
  });

  it("isOnTick_SOL_halfCentTick", () => {
    expect(isOnTick(SOL, dec("142.335"))).toBe(true);
    expect(isOnTick(SOL, dec("142.336"))).toBe(false);
    expect(isOnTick(SOL, dec("142.3350000"))).toBe(true);
  });

  it("isOnLot_BTC", () => {
    expect(isOnLot(BTC, dec("0.312"))).toBe(true);
    expect(isOnLot(BTC, dec("0.3125"))).toBe(false);
  });

  it("floorQty_BTC_flooredToTheLot", () => {
    expect(toPlain(floorQty(BTC, dec("0.31299")))).toBe("0.312");
  });

  it("priceToTick_floorAndCeil", () => {
    expect(toPlain(priceToTick(SOL, dec("142.337"), "floor"))).toBe("142.335");
    expect(toPlain(priceToTick(SOL, dec("142.337"), "ceil"))).toBe("142.340");
  });

  it("roundStop_BTCLongOffTick_floorsAwayFromEntry", () => {
    // a long at 64000.0 with a 120.04 offset: 63879.96 is off the 0.10 tick, so 63879.90
    expect(toPlain(roundStop(BTC, "buy", sub(dec("64000.0"), dec("120.04"))))).toBe("63879.90");
    // on the tick already (E28 vector T01's 63880.0): unchanged
    expect(toPlain(roundStop(BTC, "buy", dec("63880.0")))).toBe("63880.00");
  });

  it("roundStop_awayFromEntry_onBothSides", () => {
    expect(toPlain(roundStop(SOL, "buy", dec("140.004")))).toBe("140.000");
    expect(toPlain(roundStop(SOL, "sell", dec("140.001")))).toBe("140.005");
  });

  it("roundTarget_towardEntry_onBothSides", () => {
    expect(toPlain(roundTarget(SOL, "buy", dec("150.004")))).toBe("150.000");
    expect(toPlain(roundTarget(SOL, "sell", dec("130.001")))).toBe("130.005");
  });
});

describe("missedMinimum", () => {
  it("missedMinimum_belowMinQty_namesItFirst", () => {
    expect(missedMinimum(BTC, dec("0.0005"), dec("64000"))).toEqual({
      kind: "min_order_qty",
      floor: BTC.minOrderQty,
    });
  });

  it("missedMinimum_belowBothMinimums_namesTheQuantityFirst", () => {
    // 0.0005 × 4000 = 2 USDT is below the notional floor too; the quantity minimum is checked first
    expect(missedMinimum(BTC, dec("0.0005"), dec("4000"))?.kind).toBe("min_order_qty");
  });

  it("missedMinimum_legFloorEqualToExchange_isTheExchangeFloor", () => {
    // a tie keeps the exchange's floor: the leg floor wins only when it is strictly higher
    expect(missedMinimum(BTC, dec("0.001"), dec("4000"), dec("5"))?.kind).toBe("min_notional");
  });

  it("missedMinimum_belowExchangeNotional", () => {
    // 0.001 × 4000.00 = 4 < 5 USDT
    expect(missedMinimum(BTC, dec("0.001"), dec("4000.00"))?.kind).toBe("min_notional");
  });

  it("missedMinimum_profileLegFloorAboveExchange_isTheLegFloor", () => {
    expect(missedMinimum(BTC, dec("0.001"), dec("64000"), dec("100"))).toEqual({
      kind: "min_leg_notional",
      floor: dec("100"),
    });
  });

  it("missedMinimum_profileLegFloorBelowExchange_isTheExchangeFloor", () => {
    expect(missedMinimum(BTC, dec("0.001"), dec("4000"), dec("1"))?.kind).toBe("min_notional");
  });

  it("missedMinimum_atTheFloors_isNull", () => {
    expect(missedMinimum(BTC, dec("0.001"), dec("5000"))).toBeNull();
  });

  it("missedMinimum_absentMinOrderQty_isUnknown", () => {
    const row = { ...BTC_ROW() }; // a copy: the fixture row is shared
    delete row.min_order_qty;
    const g = grid(row);
    expect(missedMinimum(g, dec("1"), dec("64000"))).toEqual({
      kind: "unknown",
      filter: "min_order_qty",
    });
  });

  it("missedMinimum_absentMinNotional_isUnknownOnceTheQuantityIsMet", () => {
    const row = { ...BTC_ROW() }; // a copy: the fixture row is shared
    delete row.min_notional_value;
    const g = grid(row);
    // a known quantity miss is still named; past it, the notional floor is not known
    expect(missedMinimum(g, dec("0.0005"), dec("64000"))?.kind).toBe("min_order_qty");
    expect(missedMinimum(g, dec("1"), dec("64000"), dec("100"))).toEqual({
      kind: "unknown",
      filter: "min_notional_value",
    });
  });
});

describe("grid properties (four recorded instruments and random grids)", () => {
  it("floorQty_isALotMultiple_atMostTheInput_withinOneLot", () => {
    fc.assert(
      fc.property(arbGrid, arbPositive, (g, qty) => {
        const floored = floorQty(g, qty);
        expect(isOnLot(g, floored)).toBe(true);
        expect(lte(floored, qty)).toBe(true);
        expect(lt(sub(qty, floored), g.qtyStep)).toBe(true);
      }),
      { seed: SEED },
    );
  });

  it("toStep_anyStep_floorAndCeilBracketTheValue", () => {
    fc.assert(
      fc.property(arbPositive, arbStep, (value, step) => {
        const lo = toStep(value, step, "floor");
        const hi = toStep(value, step, "ceil");
        expect(isOnStep(lo, step) && isOnStep(hi, step)).toBe(true);
        expect(lte(lo, value) && gte(hi, value)).toBe(true);
        expect(lte(sub(hi, lo), step)).toBe(true);
        expect(isOnStep(value, step)).toBe(eq(hi, lo));
      }),
      { seed: SEED },
    );
  });

  it("roundStop_neverNarrowsTheDistance_andStaysWithinOneTick", () => {
    fc.assert(
      fc.property(arbGrid, arbSide, arbPositive, (g, side, raw) => {
        const stop = roundStop(g, side, raw);
        expect(isOnTick(g, stop)).toBe(true);
        // a buy's stop is below its entry: rounding moves it down (further); a sell's up
        expect(side === "buy" ? lte(stop, raw) : gte(stop, raw)).toBe(true);
        expect(lt(side === "buy" ? sub(raw, stop) : sub(stop, raw), g.tickSize)).toBe(true);
      }),
      { seed: SEED },
    );
  });

  it("roundTarget_neverWidensTheDistance_andStaysWithinOneTick", () => {
    fc.assert(
      fc.property(arbGrid, arbSide, arbPositive, (g, side, raw) => {
        const target = roundTarget(g, side, raw);
        expect(isOnTick(g, target)).toBe(true);
        // a buy's target is above its entry: rounding moves it down (nearer); a sell's up
        expect(side === "buy" ? lte(target, raw) : gte(target, raw)).toBe(true);
        expect(lt(side === "buy" ? sub(raw, target) : sub(target, raw), g.tickSize)).toBe(true);
      }),
      { seed: SEED },
    );
  });

  it("missedMinimum_null_impliesEveryFloorIsMet", () => {
    fc.assert(
      fc.property(arbGrid, arbPositive, arbPositive, (g, qty, price) => {
        const missed = missedMinimum(g, qty, price);
        if (missed === null) {
          expect(g.minOrderQty !== null && gte(qty, g.minOrderQty)).toBe(true);
          expect(g.minNotional !== null && gte(mul(qty, price), g.minNotional)).toBe(true);
        } else if (missed.kind !== "unknown") {
          expect(gt(missed.floor, dec("0"))).toBe(true);
        }
      }),
      { seed: SEED },
    );
  });
});

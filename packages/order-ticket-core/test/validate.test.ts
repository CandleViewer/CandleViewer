import fc from "fast-check";
import { describe, expect, it } from "vitest";
import {
  ALWAYS_UNMIRRORED,
  FIELD_ORDER,
  OFFSET_UNITS,
  SIZING_MODES,
  dec,
  isOnTick,
  parseInstrument,
  toPlain,
  validate,
  type InstrumentGrid,
  type OrderDraft,
  type OrderIntent,
  type OrderSide,
  type PositionRead,
  type TicketContext,
  type ValidationResult,
} from "../src/index.js";
import { BTC, MARKET, ctx, draft, exitDraft, held, off, qty } from "./drafts.js";

const SEED = 984;
const GRID = parseInstrument(BTC) as InstrumentGrid;
/** The gaps a result names beyond the server rules that are never mirrored yet. */
const gaps = (r: ValidationResult) => r.unmirrored.filter((g) => !ALWAYS_UNMIRRORED.includes(g));

describe("validate: the result", () => {
  it("validate_aValidDraft_isClearButPartial_whileServerRulesAreUnmirrored (BQ 1)", () => {
    const result = validate(draft(), ctx());
    expect(result).toMatchObject({ status: "clear_partial", failures: [], exactness: "partial" });
    expect(result.unmirrored).toEqual([...ALWAYS_UNMIRRORED].sort());
    expect(result.classification).toEqual({ entry: true, reason: "not_reduce_only" });
  });

  it("validate_returnsEveryFailure_inTheTicketsFieldOrder", () => {
    const bad = draft({
      intent: "reverse",
      price: "60000.05",
      timeInForce: "PostOnly",
      ...qty("0.0125"),
      stopLoss: null,
      takeProfit: off("atr", "2"),
      trigger: { price: "0", direction: "rise" },
    });
    const result = validate(bad, ctx());
    expect(result.failures.map((f) => `${f.field} ${f.rule} ${f.code}`)).toEqual([
      "trigger.price price_invalid validation_failed",
      "price tick_size tick_size_violation",
      "qty qty_step lot_size_violation",
      "stop_loss native_stop_required validation_failed",
      "take_profit stop_unit_unsupported validation_failed",
      "intent intent_mismatch validation_failed",
    ]);
  });

  it("validate_aMissingFilter_isPartial_neverAssumedToPass", () => {
    const rest = { ...BTC };
    delete rest.max_order_qty;
    delete rest.min_notional_value;
    delete rest.max_leverage;
    const result = validate(draft(qty("1000")), ctx({ instrument: rest }));
    expect(gaps(result)).toEqual([
      "instrument.max_leverage",
      "instrument.max_order_qty",
      "instrument.min_notional_value",
    ]);
    expect(result.failures.map((f) => f.rule)).not.toContain("max_order_qty");
  });

  it("validate_theLeverageCheck_isListedWhenItsInputsAreNotHeld (#5886 fold 3)", () => {
    // `Instrument.max_leverage` is served: the check is mirrored, never always unmirrored.
    expect(ALWAYS_UNMIRRORED).not.toContain("max_leverage");
    const clear = validate(draft(), ctx());
    expect(clear).toMatchObject({ failures: [], unmirrored: [...ALWAYS_UNMIRRORED].sort() });
    expect(gaps(validate(draft(), ctx({ profile: null })))).toEqual(["max_leverage"]);
    const junk = { profile: { leverage: "0" } } as TicketContext["profile"];
    expect(gaps(validate(draft(), ctx({ profile: junk })))).toEqual(["max_leverage"]);
    const noGrid = validate(draft(), ctx({ instrument: { ...BTC, tick_size: "0" } }));
    expect(noGrid.unmirrored).not.toContain("instrument.max_leverage");
    // A reduce-only order is not sized, so its leverage is neither judged nor listed.
    const rest = { ...BTC };
    delete rest.max_leverage;
    const exit = validate(exitDraft("0.5"), ctx({ instrument: rest, position: held("long", "1") }));
    expect(gaps(exit)).toEqual([]);
    expect(
      gaps(validate(exitDraft("0.5"), ctx({ profile: null, position: held("long", "1") }))),
    ).toEqual([]);
  });

  it("validate_aNonBooleanReduceOnly_isAnEntry_soItsStopIsAsked (#5886 fold 1)", () => {
    for (const value of ["false", "true", 1, 0, null, undefined, { value: true }]) {
      const d = { ...exitDraft("0.5"), reduceOnly: value } as unknown as OrderDraft;
      const result = validate(d, ctx({ position: held("long", "1") }));
      expect(result.classification, String(value)).toEqual({
        entry: true,
        reason: "reduce_only_invalid",
      });
      // An entry with no stop is refused; the intent is not judged on an unknown effect, and
      // nothing reduce-only (tpsl, sizing mode, position) is asked of it.
      expect(result.failures.map((f) => f.rule)).toEqual([
        "native_stop_required",
        "reduce_only_invalid",
      ]);
      const withStop = validate({ ...d, stopLoss: off("ticks", "9") } as OrderDraft, ctx());
      expect(withStop.failures.map((f) => f.rule)).toEqual(["reduce_only_invalid"]);
    }
  });

  it("validate_aStopOrTargetPastZero_withNoReference_isListed (#5886 fold 2)", () => {
    // `pct_equity` sizing: unlike `fixed_qty`, it does not list the reference price itself, so
    // only the stop / target past-zero check can put `reference_price` in the list (#5886 m1).
    const sized = {
      sizing: { mode: "pct_equity", pct: "1", round_to_lot: true },
    } as Partial<OrderDraft>;
    const none = ctx({ ticker: null });
    const stop = validate(draft({ ...MARKET, ...sized, stopLoss: off("percent", "150") }), none);
    expect(stop).toMatchObject({ failures: [], exactness: "partial" });
    expect(stop.unmirrored).toContain("reference_price");
    const sell = { ...MARKET, ...sized, side: "sell", stopLoss: off("ticks", "9") } as const;
    const target = validate(draft({ ...sell, takeProfit: off("ticks", "700000") }), none);
    expect(target.unmirrored).toContain("reference_price");
    expect(target.failures.map((f) => f.rule)).not.toContain("take_profit_side");
    // With no instrument grid a tick is unknown: a ticks stop is listed, a percent one judged raw.
    const noGrid = ctx({ instrument: { ...BTC, tick_size: "0" } });
    const ticks = validate(draft({ ...sized, stopLoss: off("ticks", "600000") }), noGrid);
    expect(ticks.failures.map((f) => f.rule)).not.toContain("invalid_stop_distance");
    expect(ticks.unmirrored).toContain("instrument");
    const tp = validate(
      draft({ ...sized, side: "sell", takeProfit: off("ticks", "700000") }),
      noGrid,
    );
    expect(tp.failures.map((f) => f.rule)).not.toContain("take_profit_side");
    expect(tp.unmirrored).toContain("instrument");
    const pct = validate(draft({ stopLoss: off("percent", "100") }), noGrid);
    expect(pct.failures.find((f) => f.rule === "invalid_stop_distance")?.params).toEqual({
      kind: "non_positive",
      side: "long",
    });
  });

  it("validate_aStringReduceOnly_withPctEquitySizing_isOnlyReduceOnlyInvalid (#5886 m2)", () => {
    const d = {
      ...draft({
        stopLoss: off("ticks", "9"),
        sizing: { mode: "pct_equity", pct: "1", round_to_lot: true },
      }),
      reduceOnly: "true",
    } as unknown as OrderDraft;
    const result = validate(d, ctx());
    expect(result.failures.map((f) => `${f.field}:${f.rule}`)).toEqual([
      "reduce_only:reduce_only_invalid",
    ]);
  });

  it("validate_anAbsentMinimum_isListed_andNeverGuessed (S1 grids: null, not a default)", () => {
    // Half a lot: the old default minimum (one lot) would have refused it; an unknown one cannot.
    const rest = { ...BTC };
    delete rest.min_order_qty;
    delete rest.min_notional_value;
    const result = validate(draft(qty("0.0005")), ctx({ instrument: rest }));
    expect(gaps(result)).toEqual(["instrument.min_notional_value", "instrument.min_order_qty"]);
    expect(result.failures.map((f) => f.rule)).toEqual(["qty_step"]);
  });

  it("validate_aMarketOrder_cannotMirrorTheMarketCeiling", () => {
    const result = validate(draft(MARKET), ctx());
    expect(result.status).toBe("clear_partial");
    expect(gaps(result)).toEqual(["instrument.max_mkt_order_qty"]);
  });

  it("validate_noTicker_skipsTheBookChecks_andSaysSo", () => {
    const none = ctx({ ticker: null });
    expect(validate(draft(MARKET), none).unmirrored).toContain("reference_price");
    expect(gaps(validate(draft({ timeInForce: "PostOnly" }), none))).toEqual(["ticker.book_top"]);
    expect(validate(draft({ ...MARKET, stopLoss: off("price", "1") }), none).failures).toEqual([]);
    const target = validate(draft({ ...MARKET, takeProfit: off("price", "1") }), none);
    expect(target).toMatchObject({ failures: [], exactness: "partial" });
  });

  it("validate_aMarketOrder_fallsBackToTheLastPrice_thenTheTrigger", () => {
    const lastOnly = ctx({ ticker: { last_price: "60000.0" } });
    const rules = (d: OrderDraft, c: TicketContext) => validate(d, c).failures.map((f) => f.rule);
    const below = draft({ ...MARKET, stopLoss: off("price", "60001") });
    expect(rules(below, lastOnly)).toEqual(["invalid_stop_distance"]);
    const trigger = { price: "50000.0", direction: "fall" } as const;
    const triggered = draft({ ...MARKET, trigger, stopLoss: off("price", "50001") });
    expect(rules(triggered, ctx())).toEqual(["invalid_stop_distance"]);
  });

  it("validate_anUnreadPosition_isPartial", () => {
    const result = validate(draft(), ctx({ position: { status: "unknown" } }));
    expect(result.status).toBe("clear_partial");
    expect(gaps(result)).toEqual(["position"]);
  });

  it("validate_anInstrumentWithNoGrid_stillReportsTheOtherRules", () => {
    const result = validate(
      draft({ stopLoss: null }),
      ctx({ instrument: { ...BTC, qty_step: "0" } }),
    );
    const rules = result.failures.map((f) => f.rule);
    expect(rules).toEqual(["symbol_not_trading", "native_stop_required"]);
    expect(gaps(result)).toEqual(["instrument"]);
  });

  it("validate_isPure_andItsResultIsPlainData", () => {
    const d = draft({ stopLoss: null });
    const c = ctx();
    const before = structuredClone({ d, c });
    const first = validate(d, c);
    expect({ d, c }).toEqual(before);
    expect(validate(d, c)).toEqual(first);
    expect(structuredClone(first)).toEqual(first);
  });
});

/** Random drafts across every field the rules read, valid and not. */
const sides = fc.constantFrom<OrderSide>("buy", "sell");
const amount = fc
  .integer({ min: -5, max: 200_000 })
  .map((n) => toPlain({ units: BigInt(n), scale: 3 }));
const priceText = fc
  .integer({ min: -10, max: 1_300_000 })
  .map((n) => toPlain({ units: BigInt(n), scale: 2 }));
const offset = fc.option(
  fc.record({
    unit: fc.constantFrom(...OFFSET_UNITS),
    value: fc.oneof(amount, priceText),
    atr_period: fc.constant(14),
  }),
);
const positionRead: fc.Arbitrary<PositionRead> = fc.oneof(
  fc.constant<PositionRead>({ status: "unknown" }),
  fc.constant<PositionRead>({ status: "known", position: null }),
  fc
    .tuple(fc.constantFrom("long" as const, "short" as const), amount)
    .map(([side, size]) => held(side, size)),
);
const drafts: fc.Arbitrary<OrderDraft> = fc
  .record({
    side: sides,
    orderType: fc.constantFrom("market" as const, "limit" as const),
    intent: fc.constantFrom<OrderIntent>("entry", "scale_in", "scale_out", "flatten", "reverse"),
    price: fc.option(priceText),
    timeInForce: fc.constantFrom("GTC" as const, "PostOnly" as const, null),
    reduceOnly: fc.boolean(),
    mode: fc.constantFrom(...SIZING_MODES),
    qty: amount,
    stopLoss: offset,
    takeProfit: offset,
  })
  .map(({ mode, qty: q, ...r }) => {
    const values = { qty: q, notional_usd: q, pct: "10", risk_per_trade_usd: "40" };
    return draft({ ...r, sizing: { mode, ...values, round_to_lot: true } });
  });
const contexts: fc.Arbitrary<TicketContext> = positionRead.map((position) => ctx({ position }));

describe("validate: invariants (property, seed 984)", () => {
  it("anEntryWithNoStop_alwaysFailsNativeStopRequired (C-2.6)", () => {
    fc.assert(
      fc.property(drafts, contexts, (d, c) => {
        const result = validate(d, c);
        const flagged = result.failures.some((f) => f.rule === "native_stop_required");
        expect(flagged).toBe(result.classification.entry && d.stopLoss === null);
        if (flagged) expect(result.status).toBe("blocked");
      }),
      { seed: SEED, numRuns: 1500 },
    );
  });

  it("pctPosition_isAlwaysRefused (BQ 14 AMEND)", () => {
    fc.assert(
      fc.property(drafts, contexts, (d, c) => {
        const sizing = { mode: "pct_position", pct: "50", round_to_lot: true } as const;
        const result = validate({ ...d, sizing }, c);
        expect(result.failures.map((f) => f.rule)).toContain("sizing_mode_unsupported");
      }),
      { seed: SEED, numRuns: 300 },
    );
  });

  it("failures_areInFieldOrder_blockedMeansSome_andNothingClaimsExact", () => {
    fc.assert(
      fc.property(drafts, contexts, (d, c) => {
        const result = validate(d, c);
        const positions = result.failures.map((f) => FIELD_ORDER.indexOf(f.field));
        expect(positions).toEqual([...positions].sort((a, b) => a - b));
        expect(positions.every((p) => p >= 0)).toBe(true);
        expect(result.status === "blocked").toBe(result.failures.length > 0);
        expect(result.unmirrored).toEqual(expect.arrayContaining([...ALWAYS_UNMIRRORED]));
        expect(result.exactness).toBe("partial");
        expect(result.status).not.toBe("clear_exact");
      }),
      { seed: SEED, numRuns: 1500 },
    );
  });

  it("aLimitPrice_failsTheTickRule_exactlyWhenOffTheTick", () => {
    fc.assert(
      fc.property(fc.integer({ min: 1, max: 10_000_000 }), (n) => {
        const price = toPlain({ units: BigInt(n), scale: 2 });
        const result = validate(draft({ price, stopLoss: off("ticks", "5") }), ctx());
        const flagged = result.failures.some((f) => f.rule === "tick_size");
        expect(flagged).toBe(!isOnTick(GRID, dec(price)));
      }),
      { seed: SEED, numRuns: 500 },
    );
  });

  it("aReduceOnlyExit_withinAKnownPosition_needsNoStop", () => {
    fc.assert(
      fc.property(
        fc.integer({ min: 1, max: 1000 }),
        fc.integer({ min: 0, max: 1000 }),
        (size, cut) => {
          const qty = Math.max(1, Math.min(size, cut));
          const result = validate(
            exitDraft(toPlain({ units: BigInt(qty), scale: 3 })),
            ctx({ position: held("long", toPlain({ units: BigInt(size), scale: 3 })) }),
          );
          expect(result.classification.entry).toBe(false);
          expect(result.failures.map((f) => f.rule)).not.toContain("native_stop_required");
        },
      ),
      { seed: SEED, numRuns: 300 },
    );
  });
});

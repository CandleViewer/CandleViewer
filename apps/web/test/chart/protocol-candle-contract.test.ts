// Scenario: Protocol types are assignable without adapters (E11-T01). As generated today they are
// NOT, which is design delta BQ-1 (packages/chart-engine README): this test pins exactly why, so
// the day packages/protocol emits a columnar bars payload the negative assertions fail and this
// file flips to the positive one. The checks are type-level and enforced by `pnpm typecheck`.
import { describe, expect, expectTypeOf, it } from "vitest";
import type { CandleData } from "@candleviewer/chart-engine";
import type { DecodedBars, generated, StructuredBars } from "@candleviewer/protocol";

type BarsBatch = generated.ws.BarsSymbolBarTypeParam;
type BarsBatchItem = BarsBatch["bars"][number];

describe("Scenario: Protocol types are assignable without adapters", () => {
  it("BQ-1: the generated BarsBatch payload is not assignable to CandleData as generated", () => {
    expectTypeOf<BarsBatch>().not.toExtend<CandleData>();
    expectTypeOf<StructuredBars>().not.toExtend<CandleData>();
    expectTypeOf<DecodedBars>().not.toExtend<CandleData>();
    expect(true).toBe(true);
  });

  it("BQ-1 reason: rows of decimal strings vs columns of integer ticks", () => {
    // Row-oriented: an array of bar objects, where CandleData is one typed array per field.
    expectTypeOf<BarsBatch["bars"]>().toEqualTypeOf<BarsBatchItem[]>();
    expectTypeOf<CandleData["open"]>().toEqualTypeOf<Int32Array>();
    // Prices and volume are arbitrary-precision decimal strings, not Int32Array ticks.
    expectTypeOf<BarsBatchItem["o"]>().toEqualTypeOf<string>();
    expectTypeOf<BarsBatchItem["v"]>().toEqualTypeOf<string>();
    // Times are epoch milliseconds (`t_ms`), where CandleData.time is Float64Array microseconds.
    expectTypeOf<BarsBatchItem["t_ms"]>().toEqualTypeOf<number>();
    expectTypeOf<CandleData["time"]>().toEqualTypeOf<Float64Array>();
    // No price origin or tick size travels with the payload.
    expectTypeOf<BarsBatch>().not.toHaveProperty("priceOrigin");
    expectTypeOf<BarsBatch>().not.toHaveProperty("tickSize");
    // The binary decoder keeps rows too, with bigint times and decimal-string prices.
    expectTypeOf<DecodedBars["bars"][number]["open"]>().toEqualTypeOf<string>();
    expectTypeOf<DecodedBars["bars"][number]["tsMs"]>().toEqualTypeOf<bigint>();
    expect(true).toBe(true);
  });
});

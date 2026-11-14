import { describe, expect, expectTypeOf, it } from "vitest";
import { generated } from "../src/index.js";

// #782 (E24-S07) slice 0: the client's reading of the recorded liquidations by price (C-6.2),
// per the orchestrator's ruling of 06:52Z 2026-11-04 on #782. 22 declares `getLiquidationsByPrice`
// with a required `estimated` flag, Decimal-string buckets per liquidated side and the window's
// `meta.coverage`, and the settings leaf `deriv.liq_by_price`. The expectTypeOf checks bind under
// `pnpm typecheck` (tsconfig.json includes test/), not the vitest run: a member 22 stops declaring
// is a type error there. The runtime expect keeps the samples in use.
type Operations = generated.rest.operations;
type Schemas = generated.rest.components["schemas"];
type Read = Operations["getLiquidationsByPrice"];
type Answer = Read["responses"][200]["content"]["application/json"];
type Bucket = Schemas["LiquidationPriceBucket"];
type Coverage = Schemas["LiquidationsByPriceMeta"]["coverage"];
type Deriv = NonNullable<Schemas["Settings"]["deriv"]>;

const answer = {
  symbol: "BTCUSDT",
  from: "2026-09-14T00:00:00Z",
  to: "2026-09-14T11:00:00Z",
  bucket_ticks: 20,
  tick_size: "0.10",
  estimated: false,
  items: [
    {
      price_lo: "62880.00",
      price_hi: "62882.00",
      long_notional_usd: "202473.60",
      short_notional_usd: "0",
      prints: 1,
    },
  ],
  meta: {
    coverage: {
      first_available_ts: "2026-09-14T06:30:00.250Z",
      covered_from: "2026-09-14T06:30:00.250Z",
      covered_to: "2026-09-14T11:00:00Z",
      no_coverage: false,
    },
  },
} satisfies Answer;

describe("liquidations by price contract (consumer side, 22 getLiquidationsByPrice)", () => {
  it("asks for a window start, a bucket width and a count, never a page", () => {
    type Query = Read["parameters"]["query"];
    expectTypeOf<keyof Query>().toEqualTypeOf<"symbol" | "from" | "bucket_ticks" | "top">();
    expectTypeOf<Query["from"]>().toEqualTypeOf<string | undefined>();
    expectTypeOf<Query["top"]>().toEqualTypeOf<number | undefined>();
  });

  it("reads a required estimated flag, so a stripped flag is not an answer", () => {
    expectTypeOf<Answer["estimated"]>().toEqualTypeOf<boolean>();
    // @ts-expect-error -- BQ 7: an answer without `estimated` is not the contract's answer.
    const stripped: Answer = { ...answer, estimated: undefined };
    expect(stripped.symbol).toBe("BTCUSDT");
    expect(answer.estimated).toBe(false);
  });

  it("reads Decimal strings per liquidated side, never a venue side", () => {
    expectTypeOf<keyof Bucket>().toEqualTypeOf<
      "price_lo" | "price_hi" | "long_notional_usd" | "short_notional_usd" | "prints"
    >();
    expectTypeOf<Bucket["long_notional_usd"]>().toEqualTypeOf<Schemas["Decimal"]>();
    expectTypeOf<Bucket["prints"]>().toEqualTypeOf<number>();
    expect(answer.items[0]?.long_notional_usd).toBe("202473.60");
  });

  it("tells not recorded from none recorded through meta.coverage", () => {
    expectTypeOf<Coverage["no_coverage"]>().toEqualTypeOf<boolean>();
    expectTypeOf<Coverage["covered_from"]>().toEqualTypeOf<string | null>();
    expect(answer.meta.coverage.no_coverage).toBe(false);
  });

  it("switches the recorded layer with its own leaf", () => {
    expectTypeOf<Deriv["liq_by_price"]>().toEqualTypeOf<boolean | undefined>();
  });
});

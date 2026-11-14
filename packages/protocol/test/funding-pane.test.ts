import { describe, expect, expectTypeOf, it } from "vitest";
import { generated } from "../src/index.js";

// #778 (E24-S03): the client's reading of the funding pane's contract (C-6.2). 22 declares the
// interval and the instrument's rate bounds on `getFundingHistory`, its `meta.coverage`, the
// server-computed `FundingEstimate` on `Position` and the `deriv` settings group. The
// expectTypeOf checks bind under `pnpm typecheck` (tsconfig.json includes test/), not the vitest
// run: a member 22 stops declaring is a type error there. The runtime expect keeps the samples
// in use.
type Operations = generated.rest.operations;
type Components = generated.rest.components;
type Schemas = Components["schemas"];
type Funding = Operations["getFundingHistory"]["responses"][200]["content"]["application/json"];
type Coverage = NonNullable<Schemas["FundingPageMeta"]["coverage"]>;
type Estimate = Schemas["FundingEstimate"];
type Deriv = NonNullable<Schemas["Settings"]["deriv"]>;

const coverage = {
  first_available_ts: "2026-01-01T00:00:00Z",
  covered_from: "2026-09-14T00:00:00Z",
  covered_to: null,
  no_coverage: true,
  gaps: [{ from: "2026-09-14T00:00:00Z", to: "2026-09-14T16:00:00Z" }],
} satisfies Coverage;

const estimate = {
  amount: "12.40",
  direction: "pay",
  funding_rate: "0.0001",
  settles_at: "2026-09-14T16:00:00Z",
  computed_at: "2026-09-14T15:55:48Z",
} satisfies Estimate;

const deriv = {
  oi_mode: "absolute",
  oi_quadrant_colouring: true,
  funding_style: "bars",
  funding_annualised: false,
  basis_source: "last",
  liq_mode: "heatmap",
  liq_min_notional_usd: "50000",
  zones_enabled: false,
} satisfies Deriv;

describe("funding pane contract (consumer side, 22 getFundingHistory, Position, Settings)", () => {
  it("reads the interval and the nullable rate bounds", () => {
    expectTypeOf<Funding["funding_interval_minutes"]>().toEqualTypeOf<number | undefined>();
    expectTypeOf<Funding["upper_funding_rate"]>().toEqualTypeOf<
      Schemas["Decimal"] | null | undefined
    >();
    expectTypeOf<Funding["lower_funding_rate"]>().toEqualTypeOf<
      Schemas["Decimal"] | null | undefined
    >();
    expectTypeOf<NonNullable<Funding["meta"]>["coverage"]>().toEqualTypeOf<Coverage | undefined>();
  });

  it("displays the server's annualised_pct on every item, never computing it", () => {
    type Item = NonNullable<Funding["items"]>[number];
    expectTypeOf<Item["annualised_pct"]>().toEqualTypeOf<Schemas["Decimal"] | undefined>();
  });

  it("tells not recorded from none settled through meta.coverage", () => {
    expectTypeOf<Coverage["no_coverage"]>().toEqualTypeOf<boolean>();
    expectTypeOf<Coverage["first_available_ts"]>().toEqualTypeOf<string | null>();
    expect(coverage.no_coverage).toBe(true);
  });

  it("formats a server-computed charge carried on the position, never computing one", () => {
    expectTypeOf<Schemas["Position"]["funding_estimate"]>().toEqualTypeOf<
      Estimate | null | undefined
    >();
    expectTypeOf<Estimate["direction"]>().toEqualTypeOf<"pay" | "receive" | "none">();
    expect([estimate.amount, estimate.direction]).toEqual(["12.40", "pay"]);
  });

  it("persists the deriv display preferences as Settings leaves", () => {
    expectTypeOf<Deriv["funding_style"]>().toEqualTypeOf<"line" | "bars" | undefined>();
    expectTypeOf<Deriv["basis_source"]>().toEqualTypeOf<"last" | "mark" | undefined>();
    expectTypeOf<keyof Deriv>().toEqualTypeOf<
      | "oi_mode"
      | "oi_quadrant_colouring"
      | "funding_style"
      | "funding_annualised"
      | "basis_source"
      | "liq_mode"
      | "liq_min_notional_usd"
      | "zones_enabled"
    >();
    expectTypeOf<Deriv["liq_mode"]>().toEqualTypeOf<"bars" | "heatmap" | undefined>();
    expectTypeOf<Deriv["zones_enabled"]>().toEqualTypeOf<boolean | undefined>();
    expectTypeOf<Deriv["oi_mode"]>().toEqualTypeOf<"absolute" | "delta" | undefined>();
    expect(Object.keys(deriv)).toHaveLength(8);
  });
});

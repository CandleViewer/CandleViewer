/**
 * E28-S01 (#971), SR-E28-09: the worked example's sizing port against the frozen golden vectors, QA's
 * 14 (`tests/fixtures/e28/golden_sizing_vectors.json`) and E28-T03's own
 * (`services/api/tests/unit/accounts/golden/e28_sizer_vectors.json`), read unchanged, with the same
 * profiles (`profiles.json` over `services/api/tests/fixtures/profiles/`) and instruments
 * (`instruments.json`'s capture) the server's golden test uses. Every vector is either matched to the
 * last decimal or named below with the step the port leaves to the server, so a new vector fails here
 * until it is classified: drift between the port and the sizer fails CI.
 */
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";
import * as D from "../../../../../src/features/admin/profiles/sizing/dec";
import {
  policyOf,
  sizeExample,
  type ExampleInputs,
  type SizingPolicy,
} from "../../../../../src/features/admin/profiles/sizing/workedExample";
import type { AccountProfileInput } from "../../../../../src/features/admin/profiles/api";
import { input } from "../fixtures";

const ROOT = resolve(import.meta.dirname, "../../../../../../..");
const read = (path: string): unknown => JSON.parse(readFileSync(resolve(ROOT, path), "utf8"));

type Json = Record<string, unknown>;
interface Vector {
  readonly id: string;
  readonly profile: { readonly id: string; readonly set: Json };
  readonly intent: {
    readonly symbol: string;
    readonly side: string;
    readonly order_type: string;
    readonly price: string | null;
  };
  readonly wallet: { readonly equity: string; readonly available_margin: string };
  readonly market: Json;
  readonly expected: Json;
  readonly also?: Json;
}

const QA = read("tests/fixtures/e28/golden_sizing_vectors.json") as Vector[];
const OWN = read("services/api/tests/unit/accounts/golden/e28_sizer_vectors.json") as Vector[];
const PROFILES = read("tests/fixtures/e28/profiles.json") as Record<
  string,
  { from: string; set: Json }
>;
const INSTRUMENTS = (
  read("packages/fixtures/bybit/2026-10-05/rest/instruments_before.json") as {
    result: { list: Json[] };
  }
).result.list;

/**
 * The steps the port leaves to the server (its header): the symbol gate (1), the reference price of a
 * market or marketable order (2), and the liquidation buffer (8c). Each vector named once, with why.
 */
const SERVER_ONLY: Readonly<Record<string, string>> = {
  V12: "step 1: an empty allow-list allows nothing",
  T03: "step 1: a denied symbol",
  T04: "step 1: trading disabled",
  T05: "step 2: a market order at mid",
  T09: "step 2: a market order with no price",
  T12: "step 2: a limit priced against mid",
  T21: "step 2: a market order at last",
  T27: "step 8c: the stop beyond the liquidation buffer",
  T29: "step 8c: the stop beyond the liquidation buffer",
};

const str = (v: unknown): string | null => (typeof v === "string" ? v : null);
const decOrNull = (v: unknown): D.Dec | null => (typeof v === "string" ? D.decOf(v) : null);

/** The vector's profile in the sizer's own units (`24` §9.2): every percent a fraction. */
function serverProfile(v: Vector): Json {
  const entry = PROFILES[v.profile.id];
  if (entry === undefined) throw new Error(`no profile ${v.profile.id}`);
  const frozen = read(`services/api/tests/fixtures/profiles/${entry.from}`) as Json;
  return { ...frozen, ...entry.set, ...v.profile.set };
}

/** The sizer's profile as the port reads it. */
function policyFor(v: Vector): SizingPolicy {
  const p = serverProfile(v);
  return {
    mode: p["sizing_mode"] as SizingPolicy["mode"],
    qty: decOrNull(p["fixed_qty"]),
    notional: decOrNull(p["fixed_notional"]),
    pctEquity: decOrNull(p["pct_equity"]),
    riskPct: decOrNull(p["risk_pct_equity"]),
    riskUsd: decOrNull(p["risk_fixed_amount"]),
    minLegNotional: D.decOf(String(p["min_leg_notional"])),
    leverage: D.decOf(String(p["leverage"])),
    stopUnit: p["sl_offset_unit"] as SizingPolicy["stopUnit"],
    stopValue: D.decOf(String(p["sl_offset_value"])),
    atrMultiple: D.decOf(String(p["sl_atr_multiple"])),
    fallbackPct: D.decOf(String(p["fallback_sl_offset_pct"])),
    maxLeverageCap: decOrNull(p["max_leverage_cap"]),
    maxPositionPctEquity: decOrNull(p["max_position_pct_equity"]),
    maxPositionNotional: decOrNull(p["max_position_notional"]),
    maxDailyLoss: decOrNull(p["max_daily_loss"]),
    maxDailyLossPct: decOrNull(p["max_daily_loss_pct"]),
  };
}

function inputsFor(v: Vector): ExampleInputs {
  const row = INSTRUMENTS.find((r) => r["symbol"] === v.intent.symbol) as Json;
  const lot = row["lotSizeFilter"] as Json;
  const m = v.market;
  return {
    side: v.intent.side.toLowerCase() === "buy" ? "buy" : "sell",
    ref: D.decOf(String(v.intent.price)),
    equity: D.decOf(v.wallet.equity),
    availableMargin: D.decOf(v.wallet.available_margin),
    takerFeeRate: D.decOf(String(m["taker_fee_rate"])),
    dailyLossUsed: D.decOf(String(m["daily_loss_used"])),
    committedRisk: D.ZERO,
    atr: decOrNull(m["atr"]),
    instrument: {
      tickSize: D.decOf(String((row["priceFilter"] as Json)["tickSize"])),
      qtyStep: D.decOf(String(lot["qtyStep"])),
      minOrderQty: D.decOf(String(lot["minOrderQty"])),
      minNotional: D.decOf(String(lot["minNotionalValue"])),
      maxOrderQty: D.decOf(String(lot["maxOrderQty"])),
      maxLeverage: D.decOf(String((row["leverageFilter"] as Json)["maxLeverage"])),
    },
  };
}

const CAPS: Readonly<Record<string, readonly string[]>> = {
  none: [],
  leverage: ["max_leverage_cap"],
  pct_equity: ["max_position_pct_equity"],
  notional: ["max_position_notional"],
  daily_loss: ["max_daily_loss", "max_daily_loss_pct"],
  instrument: ["max_order_qty"],
};

const ALL = [...QA, ...OWN];
const PORTED = ALL.filter((v) => SERVER_ONLY[v.id] === undefined);

describe("the sizing port against the golden vectors", () => {
  it("test_every_vector_is_ported_or_named_as_the_servers", () => {
    expect(ALL.length).toBeGreaterThanOrEqual(44);
    const unknown = Object.keys(SERVER_ONLY).filter((id) => !ALL.some((v) => v.id === id));
    expect(unknown).toEqual([]);
    expect(PORTED.length).toBe(ALL.length - Object.keys(SERVER_ONLY).length);
  });

  it.each(PORTED.map((v) => [v.id, v] as const))(
    "test_port_matches_vector_%s_to_the_last_decimal",
    (_id, v) => {
      const got = sizeExample(policyFor(v), inputsFor(v));
      const want = v.expected;
      const also = v.also ?? {};
      expect([got.outcome, got.code]).toEqual([want["outcome"], str(want["code"])]);
      const record: Json = { ...also, ...want };
      const figures = {
        qty: got.qty,
        notional: got.notional,
        risk_usdt: got.riskUsdt,
        risk_with_fees_usdt: got.riskWithFeesUsdt,
        initial_margin: got.initialMargin,
      } as const;
      for (const [name, value] of Object.entries(figures)) {
        const expected = str(record[name]);
        if (expected !== null)
          expect(value === null ? null : D.show(value), name).toBe(D.show(D.decOf(expected)));
      }
      if (typeof want["stop"] === "string") {
        expect(got.stop && [D.show(got.stop.price), got.stop.fallback]).toEqual([
          D.show(D.decOf(want["stop"])),
          also["stop_fallback"] === true,
        ]);
      }
      for (const kind of ["min_order_qty", "min_notional", "min_leg_notional"] as const) {
        const value = str(also[kind]);
        if (value !== null)
          expect(got.minimum && [got.minimum[0], D.show(got.minimum[1])]).toEqual([
            kind,
            D.show(D.decOf(value)),
          ]);
      }
      const label = str(also["binding_cap"]);
      if (label !== null) {
        const names = CAPS[label] ?? [];
        expect(
          names.length === 0 ? got.binding === null : names.includes(String(got.binding)),
        ).toBe(true);
      }
    },
  );
});

/** The same profile as the editor sends it (`AccountProfileInput`): every percent as shown. */
function editorInput(v: Vector): AccountProfileInput {
  const p = serverProfile(v);
  const text = (k: string): string | null => (typeof p[k] === "string" ? (p[k] as string) : null);
  const shown = (k: string): string | null => {
    const value = text(k);
    return value === null ? null : D.show(D.mul(D.decOf(value), D.int(100)));
  };
  const unit = String(p["sl_offset_unit"]);
  return input(String(p["name"]), {
    leverage: String(p["leverage"]),
    sizing: {
      mode: p["sizing_mode"],
      qty: text("fixed_qty"),
      notional_usd: text("fixed_notional"),
      pct: shown("pct_equity"),
      risk_per_trade_pct: shown("risk_pct_equity"),
      risk_per_trade_usd: text("risk_fixed_amount"),
      min_leg_notional_usd: String(p["min_leg_notional"]),
    },
    stop_loss: {
      unit,
      value: unit === "percent" ? shown("sl_offset_value") : String(p["sl_offset_value"]),
      atr_period: 14,
      atr_multiple: String(p["sl_atr_multiple"]),
      fallback_pct: shown("fallback_sl_offset_pct"),
    },
    risk_caps: {
      max_leverage_cap: text("max_leverage_cap"),
      max_position_pct_equity: shown("max_position_pct_equity"),
      max_position_notional_usd: text("max_position_notional"),
      max_daily_loss_usd: text("max_daily_loss"),
      max_daily_loss_pct: shown("max_daily_loss_pct"),
      max_open_positions: 3,
      max_concurrent_orders: 20,
      max_orders_per_minute: 30,
    },
  } as unknown as Partial<AccountProfileInput>);
}

const showPolicy = (p: SizingPolicy | null): Record<string, unknown> | null =>
  p === null
    ? null
    : Object.fromEntries(
        Object.entries(p).map(([k, v]) => [k, typeof v === "bigint" ? D.show(v) : v]),
      );

describe("policyOf", () => {
  const profiles = [...new Map(QA.map((v) => [v.profile.id, v])).values()];

  it.each(profiles.map((v) => [v.profile.id, v] as const))(
    "test_policy_of_reads_the_editor_form_of_%s_as_the_sizer_does",
    (_id, v) => {
      expect(showPolicy(policyOf(editorInput(v)))).toEqual(showPolicy(policyFor(v)));
    },
  );

  it("test_policy_of_a_half_typed_or_zero_field_is_incomplete_never_a_throw", () => {
    expect(policyOf(input("x", { leverage: "1." }))).toBeNull();
    expect(policyOf(input("x", { leverage: "0" }))).toBeNull();
    const halfStop = {
      unit: "ticks",
      value: "",
      atr_period: 14,
      atr_multiple: "2",
      fallback_pct: "2",
    };
    expect(
      policyOf(input("x", { stop_loss: halfStop } as Partial<AccountProfileInput>)),
    ).toBeNull();
  });

  it("test_no_stop_loss_makes_up_no_stop_and_the_example_is_figure_unknown", () => {
    const p = policyOf(
      input("x", {
        sizing: { mode: "fixed_notional", notional_usd: "1000", min_leg_notional_usd: "5" },
        stop_loss: null,
      } as unknown as Partial<AccountProfileInput>),
    );
    expect(p?.stopUnit).toBeNull();
    const v = QA.find((x) => x.id === "V01") as Vector;
    const got = sizeExample(p as SizingPolicy, inputsFor(v));
    expect([got.outcome, got.code, got.stop, got.qty]).toEqual([
      "fail",
      "figure_unknown",
      null,
      null,
    ]);
  });

  it("test_policy_of_reads_percents_as_fractions_and_ticks_as_counts", () => {
    const p = policyOf(input("x")) as SizingPolicy;
    expect(D.show(p.riskPct ?? D.ZERO)).toBe("0.005");
    expect(D.show(p.stopValue)).toBe("1200");
    expect(D.show(p.fallbackPct)).toBe("0.02");
    expect(D.show(p.maxDailyLossPct ?? D.ZERO)).toBe("0.03");
    expect(p.maxDailyLoss).toBeNull();
    const pctStop = policyOf(
      input("y", {
        stop_loss: {
          unit: "percent",
          value: "1.5",
          atr_period: 14,
          atr_multiple: "2",
          fallback_pct: "2",
        },
      }),
    );
    expect(D.show(pctStop?.stopValue ?? D.ZERO)).toBe("0.015");
  });

  it("test_the_us_prof_002_example_reads_about_0_416_btc", () => {
    // D03 §4.2: 10 000 USDT, 0.5 %, a 120 USDT stop (1 200 ticks of 0.1), V01's figures, no fee.
    const v = QA.find((x) => x.id === "V01") as Vector;
    const got = sizeExample(policyOf(input("x")) as SizingPolicy, inputsFor(v));
    expect([D.show(got.qty ?? D.ZERO), D.show(got.riskUsdt ?? D.ZERO)]).toEqual(["0.416", "49.92"]);
  });

  it("test_unknown_equity_is_figure_unknown_never_zero", () => {
    const v = QA.find((x) => x.id === "V01") as Vector;
    const got = sizeExample(policyOf(input("x")) as SizingPolicy, {
      ...inputsFor(v),
      equity: null,
    });
    expect([got.outcome, got.code, got.qty]).toEqual(["fail", "figure_unknown", null]);
  });
});

describe("dec", () => {
  it("test_dec_parses_shows_and_rounds_both_ways", () => {
    expect(D.dec("1e3")).toBeNull();
    expect(D.show(D.decOf("-0.50"))).toBe("-0.5");
    expect(D.show(D.div(D.int(1), D.int(3)))).toBe("0.333333333333333333333333333333");
    expect(D.show(D.div(D.int(1), D.int(3), true))).toBe("0.333333333333333333333333333334");
    expect(D.show(D.div(D.int(-1), D.int(3)))).toBe("-0.333333333333333333333333333334");
    expect(D.show(D.toGrid(D.decOf("64764.634"), D.decOf("0.1"), true))).toBe("64764.7");
    expect(() => D.div(D.int(1), D.ZERO)).toThrow(RangeError);
    expect(() => D.decOf("x")).toThrow(RangeError);
  });
});

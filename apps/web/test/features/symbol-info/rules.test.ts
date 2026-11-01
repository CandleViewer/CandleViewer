/** E08-D06 §3, §4.1, §4.4, §5: the contract band's rows from `InstrumentDetail`, the sentences and the examples. */
import type { generated } from "@candleviewer/protocol";
import { describe, expect, it } from "vitest";
import {
  buildRules,
  identityLine,
  statusOf,
  type RuleRow,
} from "../../../src/features/symbol-info/rules";
import * as copy from "../../../src/features/symbol-info/copy";

type Detail = generated.rest.components["schemas"]["InstrumentDetail"];

const NOW = Date.parse("2026-11-01T12:00:00Z");
/** `exactOptionalPropertyTypes`: an absent field is a missing key, not `undefined`. */
const without = (d: Detail, ...keys: (keyof Detail)[]): Detail => {
  const copy = { ...d };
  for (const key of keys) delete copy[key];
  return copy;
};

/** BTCUSDT as `instruments_after.json` delivers it ("0.10", "100.000", "100.00"). */
const BTC: Detail = {
  symbol: "BTCUSDT",
  category: "linear",
  contract_type: "LinearPerpetual",
  base_coin: "BTC",
  quote_coin: "USDT",
  settle_coin: "USDT",
  status: "Trading",
  launch_time: "2020-04-01T00:00:00Z",
  tick_size: "0.10",
  qty_step: "0.001",
  min_order_qty: "0.001",
  max_order_qty: "100.000",
  min_notional_value: "5",
  max_leverage: "100.00",
  leverage_step: "0.01",
  funding_interval_minutes: 480,
  revision: 7,
  updated_at: "2026-11-01T10:00:00Z",
};
const row = (detail: Detail, key: RuleRow["key"]): RuleRow => {
  const found = buildRules(detail, NOW).rows.find((r) => r.key === key);
  if (found === undefined) throw new Error(key);
  return found;
};

describe("buildRules", () => {
  it("builds the identity line and drops a missing part", () => {
    expect(identityLine(BTC)).toBe(
      "BTC / USDT · USDT perpetual · settled in USDT · listed 2020-04-01",
    );
    expect(identityLine(without(BTC, "launch_time", "settle_coin"))).toBe(
      "BTC / USDT · USDT perpetual",
    );
    expect(identityLine({ ...BTC, launch_time: "nope", contract_type: "Other" })).toBe(
      "BTC / USDT · settled in USDT",
    );
    expect(
      identityLine({ symbol: "XUSDT", category: "linear", tick_size: "1", qty_step: "1" }),
    ).toBeNull();
  });

  it("shows rule values in minimal form with the unit, the sentence and the example", () => {
    expect(row(BTC, "tick_size").value).toEqual({
      kind: "value",
      text: "0.1",
      unit: "USDT",
      sentence: "Price must be a multiple of 0.1.",
      example: "100.04 → 100.0 (nearest)",
    });
    expect(row(BTC, "qty_step").value).toEqual({
      kind: "value",
      text: "0.001",
      unit: "BTC",
      sentence: "Quantity must be a multiple of 0.001.",
      example: "1.0009 → 1.000 (always down)",
    });
    expect(row(BTC, "min_order_qty").value).toMatchObject({
      text: "0.001",
      sentence: "Quantity must be at least 0.001.",
    });
    expect(row(BTC, "max_order_qty").value).toMatchObject({
      text: "100",
      unit: "BTC",
      sentence: "Quantity must not exceed 100.",
    });
    expect(row(BTC, "min_notional_value").value).toMatchObject({
      text: "5",
      unit: "USDT",
      sentence: "Order notional must be at least 5.",
      example: "1.0 × 0.001 = 0.001 → refused",
    });
    expect(row(BTC, "max_leverage").value).toMatchObject({
      text: "100",
      unit: "×",
      sentence: "Leverage is set in steps of 0.01.",
    });
  });

  it("rounds the examples through the shared rule source on a half-tick instrument", () => {
    const sol = { ...BTC, symbol: "SOLUSDT", tick_size: "0.005", qty_step: "0.1" };
    expect(row(sol, "tick_size").value).toMatchObject({ example: "5.002 → 5.000 (nearest)" });
    expect(row(sol, "qty_step").value).toMatchObject({ example: "100.09 → 100.0 (always down)" });
  });

  it("expands an exponent tick and reports it as malformed of kind exponent", () => {
    const view = buildRules({ ...BTC, tick_size: "1E-7" }, NOW);
    expect(view.rows.find((r) => r.key === "tick_size")?.value).toMatchObject({
      text: "0.0000001",
      sentence: "Price must be a multiple of 0.0000001.",
    });
    expect(view.malformed).toEqual([{ field: "tick_size", kind: "exponent" }]);
  });

  it("shows a dash for an unreadable value and reports it once", () => {
    const view = buildRules({ ...without(BTC, "min_order_qty"), qty_step: "abc" }, NOW);
    expect(view.rows.find((r) => r.key === "qty_step")?.value).toEqual({
      kind: "dash",
      malformed: "unparsable",
    });
    expect(view.rows.find((r) => r.key === "min_order_qty")?.value).toEqual({
      kind: "dash",
      malformed: null,
    });
    expect(view.malformed).toEqual([{ field: "qty_step", kind: "unparsable" }]);
  });

  it("reads the adapter's zero minimum value as a dash, with no example", () => {
    expect(row({ ...BTC, min_notional_value: "0" }, "min_notional_value").value).toEqual({
      kind: "dash",
      malformed: null,
    });
    expect(row({ ...BTC, min_notional_value: "0.00" }, "min_notional_value").value.kind).toBe(
      "dash",
    );
  });

  it("gives no refused example when the minimum order would pass", () => {
    const value = row({ ...BTC, min_notional_value: "0.0001" }, "min_notional_value").value;
    expect(value).toMatchObject({ kind: "value", example: null });
  });

  it("always reads market-order maximum as not available yet (CR-1)", () => {
    expect(row(BTC, "max_mkt_order_qty").value).toEqual({ kind: "not_available_yet" });
  });

  it("never renders a number for a field the contract does not serve", () => {
    const bare = buildRules(
      { symbol: "XUSDT", category: "linear", tick_size: "1", qty_step: "1" },
      NOW,
    );
    for (const key of [
      "min_order_qty",
      "max_order_qty",
      "min_notional_value",
      "max_leverage",
      "funding_interval",
    ] as const) {
      const value = bare.rows.find((r) => r.key === key)?.value;
      expect(value).toEqual({ kind: "dash", malformed: null });
    }
    expect(bare.rows.find((r) => r.key === "max_mkt_order_qty")?.value.kind).toBe(
      "not_available_yet",
    );
    expect(bare.tiers).toEqual({ kind: "not_available_yet" });
    expect(bare.identity).toBeNull();
    expect(bare.malformed).toEqual([]);
    const optional = bare.rows.filter((r) => r.key !== "tick_size" && r.key !== "qty_step");
    expect(JSON.stringify(optional.map((r) => r.value))).not.toMatch(/"text"/);
  });

  it("words the funding interval and its tag", () => {
    expect(row(BTC, "funding_interval")).toMatchObject({
      value: { kind: "value", text: "8 h" },
      tag: "can change",
    });
    expect(row({ ...BTC, funding_interval_minutes: 30 }, "funding_interval").value).toMatchObject({
      text: "30 min",
    });
    expect(row({ ...BTC, funding_interval_minutes: 0 }, "funding_interval").value.kind).toBe(
      "dash",
    );
  });

  it("reads the status: unknown is not trading (D-5)", () => {
    expect(statusOf("Trading")).toEqual({ word: "Trading", trading: true, code: "Trading" });
    expect(statusOf("PreLaunch").word).toBe("Pre-launch");
    expect(statusOf("Settling")).toEqual({ word: null, trading: false, code: "Settling" });
    expect(statusOf(undefined).trading).toBe(false);
    expect(statusOf("toString").word).toBeNull();
    expect(row({ ...BTC, status: "Closed" }, "status").value).toMatchObject({ text: "Closed" });
  });

  it("says 'checked', never 'changed', for updated_at (D-2)", () => {
    expect(buildRules(BTC, NOW).provenance).toBe("Rules revision 7 · checked 2 h ago");
    expect(buildRules(without(BTC, "revision", "updated_at"), NOW).provenance).toBe("checked —");
    expect(buildRules({ ...BTC, updated_at: "2026-11-01T11:59:30Z" }, NOW).provenance).toContain(
      "30 s ago",
    );
    expect(buildRules({ ...BTC, updated_at: "2026-11-01T11:15:00Z" }, NOW).provenance).toContain(
      "45 min ago",
    );
  });

  it("adds the overdue notice from stale_since and nothing otherwise (D-3)", () => {
    expect(buildRules(BTC, NOW).overdue).toBeNull();
    expect(buildRules({ ...BTC, stale_since: null }, NOW).overdue).toBeNull();
    expect(buildRules({ ...BTC, stale_since: "2026-10-31T22:00:00Z" }, NOW).overdue).toBe(
      "Instrument list updated 14 h ago — the scheduled refresh is overdue.",
    );
  });

  it("reads empty tiers as not available yet, never an empty table (D-8)", () => {
    expect(buildRules({ ...BTC, risk_limit_tiers: [] }, NOW).tiers).toEqual({
      kind: "not_available_yet",
    });
    expect(copy.TIERS_UNAVAILABLE).toBe("Risk-limit tiers: not available yet");
  });

  it("collapses tiers to 3 rows, expands to 8, then scrolls (D-8)", () => {
    const tiers = Array.from({ length: 12 }, (_, i) => ({
      tier: i + 1,
      risk_limit_value: `${String((i + 1) * 2000000)}.00`,
      max_leverage: "100.00",
    }));
    const view = buildRules({ ...BTC, risk_limit_tiers: tiers }, NOW).tiers;
    expect(view).toMatchObject({
      kind: "table",
      caption: "Risk-limit tiers for BTCUSDT",
      total: 12,
      collapsedCount: 3,
      expandedCount: 8,
      scrolls: true,
      showAll: "Show all 12 tiers",
    });
    if (view.kind !== "table") throw new Error("table");
    expect(view.rows[0]).toEqual({ tier: 1, riskLimitValue: "2,000,000", maxLeverage: "100" });
    const small = buildRules({ ...BTC, risk_limit_tiers: tiers.slice(0, 2) }, NOW).tiers;
    expect(small).toMatchObject({
      collapsedCount: 2,
      expandedCount: 2,
      scrolls: false,
      showAll: null,
    });
  });
});

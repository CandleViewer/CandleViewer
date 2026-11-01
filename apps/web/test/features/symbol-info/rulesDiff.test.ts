/** E08-D06 D-13: what a re-read changes, marked and never swapped; a revision with no shown field changes nothing. */
import type { generated } from "@candleviewer/protocol";
import { describe, expect, it } from "vitest";
import {
  announcementFor,
  changedNote,
  diffRules,
  wasFor,
} from "../../../src/features/symbol-info/rulesDiff";

type Detail = generated.rest.components["schemas"]["InstrumentDetail"];
/** `exactOptionalPropertyTypes`: an absent field is a missing key, not `undefined`. */
const without = (d: Detail, ...keys: (keyof Detail)[]): Detail => {
  const copy = { ...d };
  for (const key of keys) delete copy[key];
  return copy;
};

const SOL: Detail = {
  symbol: "SOLUSDT",
  category: "linear",
  quote_coin: "USDT",
  base_coin: "SOL",
  status: "Trading",
  tick_size: "0.010",
  qty_step: "0.1",
  min_order_qty: "0.1",
  max_order_qty: "1000",
  min_notional_value: "5",
  max_leverage: "50",
  leverage_step: "0.01",
  funding_interval_minutes: 480,
  revision: 7,
};

describe("diffRules", () => {
  it("finds no change when only the representation or the provenance differs", () => {
    const next: Detail = {
      ...SOL,
      tick_size: "0.01",
      max_order_qty: "1000.000",
      revision: 8,
      updated_at: "2026-11-01T06:40:00Z",
      price_scale: 3,
    };
    const diff = diffRules(SOL, next);
    expect(diff.changes).toEqual([]);
    expect(diff).toMatchObject({ revisionFrom: 7, revisionTo: 8 });
    expect(announcementFor(diff)).toBeNull();
    expect(changedNote(diff, Date.parse("2026-11-01T06:40:00Z"))).toBeNull();
  });

  it("marks the tick change with the old value and says so once", () => {
    const diff = diffRules(SOL, { ...SOL, tick_size: "0.005", revision: 8 });
    expect(diff.changes).toEqual([
      {
        field: "tick_size",
        key: "tick_size",
        label: "tick size",
        was: "0.01",
        now: "0.005",
        unit: "USDT",
      },
    ]);
    expect(wasFor(diff, "tick_size")).toBe("Changed · was 0.01");
    expect(wasFor(diff, "qty_step")).toBeNull();
    expect(announcementFor(diff)).toBe(
      "Contract rules changed: tick size is now 0.005 USDT, was 0.01.",
    );
    expect(changedNote(diff, Date.parse("2026-11-01T06:40:30Z"))).toBe(
      "Rules changed at 06:40 UTC (revision 7 → 8).",
    );
  });

  it("lists several changes in the band's order and announces the first", () => {
    const diff = diffRules(SOL, {
      ...SOL,
      max_leverage: "25",
      status: "Closed",
      funding_interval_minutes: 60,
    });
    expect(diff.changes.map((c) => c.field)).toEqual([
      "status",
      "max_leverage",
      "funding_interval_minutes",
    ]);
    expect(announcementFor(diff)).toBe(
      "Contract rules changed: status is now Closed, was Trading.",
    );
    expect(diff.changes[2]).toMatchObject({ was: "8 h", now: "1 h" });
  });

  it("keeps a dash for a value that was absent and drops the adapter's zero minimum", () => {
    const diff = diffRules({ ...SOL, min_notional_value: "0" }, SOL);
    expect(diff.changes[0]).toMatchObject({ field: "min_notional_value", was: "—", now: "5" });
  });

  it("gives no note without both revisions", () => {
    const diff = diffRules(without(SOL, "revision"), { ...SOL, tick_size: "1" });
    expect(changedNote(diff, 0)).toBeNull();
    expect(diff.revisionFrom).toBeNull();
  });
});

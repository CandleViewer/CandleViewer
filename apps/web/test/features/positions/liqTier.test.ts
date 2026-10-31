/**
 * E29-S01 (#911, BQ-11) liquidation tiers: E29-D02 §5.3 as drawn. The §5.2 fixture rows, each
 * threshold's boundary, the 5-point hysteresis, the 1 % floor, and the crossing events (once per
 * crossing up into Near or Critical; a row re-arms when it leaves the tier).
 */
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import {
  CRITICAL_DISTANCE_FLOOR_PCT,
  CROSS_CRITICAL_MM_RATE_PCT,
  HYSTERESIS_POINTS,
  ISOLATED_NEAR_SHARE_PCT,
  LiqTierTracker,
  TIER_TEXT,
  crossingOf,
  readLiq,
  type LiqInputs,
  type LiqTier,
} from "../../../src/features/positions/model/liqTier";
import { add, dec, toPlain } from "../../../src/features/positions/model/decimal";

const iso = (side: "long" | "short", entry: string, mark: string, liq: string): LiqInputs => ({
  side,
  entry,
  mark,
  liqPrice: liq,
  marginMode: "isolated",
  mmRate: null,
});
const cross = (
  mark: string,
  liq: string,
  rate: string | null,
  mode: "cross" | "portfolio" = "cross",
): LiqInputs => ({
  side: "long",
  entry: "100",
  mark,
  liqPrice: liq,
  marginMode: mode,
  mmRate: rate,
});
/** A long at entry 101 and liquidation 1 (a buffer of exactly 100), `pct` % of it left. */
const share = (pct: string): LiqInputs => iso("long", "101", toPlain(add(dec("1"), dec(pct))), "1");

describe("Liquidation proximity is not colour-only: D02 §5.2's rows (glyph, word, distance)", () => {
  it.each([
    [
      "Main BTCUSDT, 101 % of the buffer",
      iso("long", "63980.0", "64012.0", "57901.9"),
      "none",
      "9.5",
      "101",
    ],
    ["Sub-1 BTCUSDT", iso("long", "63985.0", "64012.0", "51507.9"), "none", "19.5", "100"],
    [
      "Sub-1 ETHUSDT short, 27 %: Near",
      iso("short", "2480.00", "2561.00", "2591.60"),
      "near",
      "1.2",
      "27",
    ],
    [
      "Sub-2 SOLUSDT, 14 %: Critical",
      iso("long", "152.40", "147.80", "147.07"),
      "critical",
      "0.5",
      "14",
    ],
    ["Sub-2 BTCUSDT", iso("long", "64050.0", "64012.0", "57965.3"), "none", "9.4", "99"],
    [
      "Main DEMO ETHUSDT, 46 %: Watch",
      iso("long", "2625.00", "2561.00", "2506.88"),
      "watch",
      "2.1",
      "46",
    ],
  ])("%s", (_, inputs, tier, distance, sharePct) => {
    expect(readLiq(inputs)).toEqual({
      tier,
      basis: "buffer",
      distancePct: distance,
      sharePct,
      mmRatePct: null,
    });
  });

  it("the tiers' glyph, word and label are D02 §5.3's and D01 D5's", () => {
    const d02 = readFileSync(
      join(import.meta.dirname, "../../../../../docs/design/E29/E29-D02.md"),
      "utf8",
    );
    const d01 = readFileSync(
      join(import.meta.dirname, "../../../../../docs/design/E29/E29-D01.md"),
      "utf8",
    );
    for (const { glyph, word, label } of Object.values(TIER_TEXT)) {
      expect(d02).toContain(`"${glyph} ${word} `);
      expect(d01).toContain(`"${label}"`);
    }
  });
});

describe("boundaries", () => {
  const tierAt = (inputs: LiqInputs): LiqTier => readLiq(inputs).tier;

  it.each([
    ["50", "watch"],
    ["50.01", "none"],
    ["30", "near"],
    ["30.01", "watch"],
    ["15", "critical"],
    ["15.01", "near"],
  ])("isolated, %s %% of the buffer left: %s", (pct, tier) => {
    expect(tierAt(share(pct))).toBe(tier);
  });

  it.each([
    ["0.4999", "none"],
    ["0.50", "watch"],
    ["0.70", "near"],
    ["0.85", "critical"],
  ])("cross, MM rate %s: %s", (rate, tier) => {
    expect(tierAt(cross("200", "50", rate))).toBe(tier);
    expect(tierAt(cross("200", "50", rate, "portfolio"))).toBe(tier);
  });

  it("the 1 % floor makes any mode Critical, at exactly 1 % too", () => {
    expect(toPlain(CRITICAL_DISTANCE_FLOOR_PCT)).toBe("1");
    expect(tierAt(cross("100", "99", "0.10"))).toBe("critical"); // exactly 1 %
    expect(tierAt(cross("100", "98.99", "0.10"))).toBe("none"); // 1.01 %
    expect(readLiq(iso("long", "100.5", "100", "99.5"))).toMatchObject({
      tier: "critical",
      distancePct: "0.5",
    });
  });

  it("no liquidation price, or Bybit's 0, shows no tier and no distance", () => {
    expect(readLiq(iso("long", "100", "99", "0"))).toMatchObject({
      tier: "none",
      distancePct: null,
    });
    expect(readLiq({ ...iso("long", "100", "99", "1"), liqPrice: null })).toMatchObject({
      tier: "none",
    });
  });

  it("cross without an MM rate, or an unknown mode, has only the floor", () => {
    expect(readLiq(cross("200", "50", null))).toMatchObject({ tier: "none", basis: "floor" });
    expect(readLiq({ ...cross("100", "99.5", null), marginMode: null })).toMatchObject({
      tier: "critical",
      basis: "floor",
    });
    expect(readLiq(cross("200", "50", "0.72"))).toMatchObject({
      tier: "near",
      basis: "mm_rate",
      mmRatePct: "72",
    });
  });
});

describe("hysteresis (D01 D5: left 5 points past, one tier at a time)", () => {
  it("named constants", () => {
    expect([
      toPlain(HYSTERESIS_POINTS),
      toPlain(ISOLATED_NEAR_SHARE_PCT),
      toPlain(CROSS_CRITICAL_MM_RATE_PCT),
    ]).toEqual(["5", "30", "85"]);
  });

  it("Near holds until the share passes 35 %, then steps to Watch", () => {
    expect(readLiq(share("34"), "near").tier).toBe("near");
    expect(readLiq(share("35"), "near").tier).toBe("near");
    expect(readLiq(share("35.5"), "near").tier).toBe("watch");
  });

  it("Critical holds until 20 %; a big recovery steps down through every tier", () => {
    expect(readLiq(share("19"), "critical").tier).toBe("critical");
    expect(readLiq(share("21"), "critical").tier).toBe("near");
    expect(readLiq(share("60"), "critical").tier).toBe("none");
  });

  it("cross: Near holds until the rate drops under 65 %", () => {
    expect(readLiq(cross("200", "50", "0.66"), "near").tier).toBe("near");
    expect(readLiq(cross("200", "50", "0.64"), "near").tier).toBe("watch");
  });

  it("the floor has no band: past 1 % the share decides", () => {
    // 45 % of the buffer left, within 1 % of liquidation: Critical; at 1.01 %: Watch
    expect(readLiq(iso("long", "101.2222", "100", "99"), "none").tier).toBe("critical");
    expect(readLiq(iso("long", "101.2222", "100.0101", "99"), "critical").tier).toBe("watch");
  });

  it("an escalation is never held back", () => {
    expect(readLiq(share("10"), "watch").tier).toBe("critical");
  });
});

describe("crossings: once each, re-armed when the row leaves the tier", () => {
  it("crossingOf: up into Near and Critical only", () => {
    expect(crossingOf("none", "near")).toBe("near");
    expect(crossingOf("watch", "critical")).toBe("critical");
    expect(crossingOf("none", "watch")).toBeNull();
    expect(crossingOf("critical", "near")).toBeNull();
    expect(crossingOf("near", "near")).toBeNull();
  });

  it("a row seen first crossed nothing; later crossings are told once", () => {
    const tracker = new LiqTierTracker();
    expect(tracker.update("k", share("25")).crossing).toBeNull(); // first sight: Near, no event
    expect(tracker.update("k", share("25")).crossing).toBeNull();
    expect(tracker.update("k", share("12"))).toMatchObject({ crossing: "critical" });
    expect(tracker.update("k", share("13")).crossing).toBeNull();
    expect(tracker.update("k", share("40")).crossing).toBeNull(); // down to Watch
    expect(tracker.update("k", share("29"))).toMatchObject({ crossing: "near" }); // re-armed
  });

  it("a row that leaves the view is forgotten, so it re-arms", () => {
    const tracker = new LiqTierTracker();
    tracker.update("k", share("60"));
    tracker.update("k", share("25"));
    tracker.retain(new Set());
    expect(tracker.update("k", share("12")).crossing).toBeNull();
    tracker.clear();
    expect(tracker.update("k", share("60")).crossing).toBeNull();
  });
});

// E24-S01 (#776) slice 1: intervals, the granularity note's condition (US-DERIV-001 sc. 2), alignment, units.
import { describe, expect, it } from "vitest";
import {
  alignToBar,
  baseCoin,
  granularityNote,
  intervalLabel,
  isOiInterval,
  requestInterval,
} from "../../../src/features/derivatives/oi/intervals";

const MIN = 60_000;

describe("OI intervals", () => {
  it("asks for the coarsest REST interval no coarser than the bar, 5 min below it", () => {
    expect(requestInterval(MIN)).toBe("5min");
    expect(requestInterval(5 * MIN)).toBe("5min");
    expect(requestInterval(10 * MIN)).toBe("5min");
    expect(requestInterval(15 * MIN)).toBe("15min");
    expect(requestInterval(60 * MIN)).toBe("1h");
    expect(requestInterval(2 * 60 * MIN)).toBe("1h");
    expect(requestInterval(24 * 60 * MIN)).toBe("1d");
    expect(requestInterval(7 * 24 * 60 * MIN)).toBe("1d");
  });

  it("notes the native granularity only when the bar is finer, from coverage, never hard-coded", () => {
    expect(granularityNote(MIN, "5min")).toBe("Native granularity 5 min");
    expect(granularityNote(5 * MIN, "15min")).toBe("Native granularity 15 min");
    expect(granularityNote(5 * MIN, "5min")).toBeNull();
    expect(granularityNote(60 * MIN, "5min")).toBeNull();
    expect(granularityNote(MIN, null)).toBeNull();
  });

  it("aligns a time to its bar's UTC start", () => {
    const t = Date.parse("2026-09-14T10:27:41.250Z");
    expect(alignToBar(t, MIN)).toBe(Date.parse("2026-09-14T10:27:00Z"));
    expect(alignToBar(t, 5 * MIN)).toBe(Date.parse("2026-09-14T10:25:00Z"));
    expect(alignToBar(Date.parse("2026-09-14T10:25:00Z"), 5 * MIN)).toBe(
      Date.parse("2026-09-14T10:25:00Z"),
    );
    expect(alignToBar(-1, MIN)).toBe(-MIN);
    // days are UTC midnights; a 7-day bar opens on Monday 00:00 UTC (the epoch is a Thursday)
    expect(alignToBar(t, 86_400_000)).toBe(Date.parse("2026-09-14T00:00:00Z"));
    const week = 7 * 86_400_000;
    expect(alignToBar(Date.parse("2026-09-20T23:59:59Z"), week)).toBe(
      Date.parse("2026-09-14T00:00:00Z"),
    );
    expect(alignToBar(Date.parse("2026-09-21T00:00:00Z"), week)).toBe(
      Date.parse("2026-09-21T00:00:00Z"),
    );
    expect(new Date(alignToBar(Date.parse("2026-09-17T10:00:00Z"), week)).getUTCDay()).toBe(1);
  });

  it("reads the base coin off a USDT perpetual and labels spans in words", () => {
    expect(baseCoin("BTCUSDT")).toBe("BTC");
    expect(baseCoin("1000PEPEUSDT")).toBe("1000PEPE");
    expect(baseCoin("USDT")).toBe("USDT");
    expect(intervalLabel("1h")).toBe("1 h");
    expect(isOiInterval("5min")).toBe(true);
    expect(isOiInterval("2min")).toBe(false);
    expect(isOiInterval("toString")).toBe(false);
  });
});

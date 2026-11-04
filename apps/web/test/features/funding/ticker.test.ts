// E24-S03 (#778) slice 2: the funding fields of `23` §14.8 ticker items, read off the recorded stream.
import { describe, expect, it } from "vitest";
import { parseFundingFrames, parseFundingItem } from "../../../src/features/funding/ticker";
import { delta, recordedFundingItems, snap } from "./support/tickerFrames";

const ITEMS = recordedFundingItems();
const FIRST = ITEMS[0];

describe("funding ticker fields", () => {
  it("reads the recorded rate and next settlement as sent", () => {
    expect(FIRST).toBeDefined();
    const tick = parseFundingItem(FIRST, "BTCUSDT");
    expect(tick?.rate).toBe(FIRST?.funding_rate);
    expect(tick?.nextFundingTimeMs).toBe(1792396800000);
    expect(tick?.stale).toBe(false);
  });

  it("reads an absent or malformed field as null, never 0, and skips another symbol", () => {
    const base = { ...FIRST, funding_rate: "1e-4", next_funding_time_ms: undefined };
    expect(parseFundingItem(base, "BTCUSDT")).toMatchObject({
      rate: null,
      nextFundingTimeMs: null,
    });
    expect(parseFundingItem(FIRST, "ETHUSDT")).toBeNull();
    expect(parseFundingItem({ ...FIRST, ts_ms: -1 }, "BTCUSDT")).toBeNull();
  });

  it("keeps arrival order across snapshot, delta and reset frames, and ignores a binary body", () => {
    const out = parseFundingFrames(
      [
        snap(ITEMS.slice(0, 1)),
        { kind: "reset", reason: "reconnect" },
        delta(ITEMS.slice(1, 2)),
        { ...delta([]), body: { e: "b", p: new ArrayBuffer(0) } } as never,
      ],
      "BTCUSDT",
    );
    expect(out).toHaveLength(3);
    expect(out[1]).toBe("reset");
  });
});

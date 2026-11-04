// E24-S05 (#780): `23` §14.9 items and `22` `Liquidation` items into prints; malformed ones are counted, never
// coerced.
import { describe, expect, it } from "vitest";
import {
  parseLiquidationFrames,
  parseRestItem,
  parseWireItem,
} from "../../../../src/features/derivatives/liquidations/prints";
import { delta, DESIGN, EXAMPLE, reset, snap } from "./liqFrames";

describe("parseWireItem", () => {
  it("keeps the decimals as sent and maps the side", () => {
    expect(parseWireItem(DESIGN, "BTCUSDT")).toEqual({
      tsMs: DESIGN.ts_ms,
      side: "long",
      price: "82751.20",
      size: "0.498",
      notionalUsd: "41210.10",
      clusterSize: 8,
    });
  });

  it("defaults the optional fields (notional null, cluster 1)", () => {
    const bare = { symbol: "BTCUSDT", ts_ms: EXAMPLE.ts_ms, side: "buy", price: "1.0", size: "2" };
    expect(parseWireItem(bare, "BTCUSDT")).toMatchObject({
      side: "short",
      notionalUsd: null,
      clusterSize: 1,
    });
  });

  it.each([
    ["another symbol", { symbol: "ETHUSDT" }],
    ["a numeric price", { price: 62880 }],
    ["a negative size", { size: "-1" }],
    ["an unknown side", { side: "long" }],
    ["a zero cluster", { cluster_size: 0 }],
    ["a string time", { ts_ms: "1" }],
  ])("refuses %s", (_name, over) => {
    expect(parseWireItem({ ...EXAMPLE, ...over }, "BTCUSDT")).toBeNull();
  });
});

describe("parseRestItem", () => {
  it("reads the 22 example item, its ts in RFC 3339", () => {
    const { ts_ms, ...rest } = EXAMPLE;
    const item = { ...rest, ts: new Date(ts_ms).toISOString() };
    expect(parseRestItem(item, "BTCUSDT")).toMatchObject({ tsMs: ts_ms, side: "long" });
    expect(parseRestItem({ ...item, ts: "not a time" }, "BTCUSDT")).toBeNull();
  });
});

describe("parseLiquidationFrames", () => {
  it("keeps the order, the kind and the resets, and counts malformed items", () => {
    const out = parseLiquidationFrames(
      [snap([EXAMPLE]), reset(), delta([DESIGN, { ...DESIGN, price: 1 }])],
      "BTCUSDT",
    );
    expect(out.map((b) => (b === "reset" ? b : `${b.kind}:${String(b.prints.length)}`))).toEqual([
      "snap:1",
      "reset",
      "d:1",
    ]);
    const last = out[2];
    expect(last !== "reset" && last?.malformed).toBe(1);
  });

  it("ignores a body that is not structured or carries no array", () => {
    const binary = { ...delta([]), body: { e: "b64" as const, bytes: new ArrayBuffer(0) } };
    const noArray = { ...delta([]), body: { e: "j" as const, p: { liquidations: null } } };
    const out = parseLiquidationFrames([binary, noArray], "BTCUSDT");
    expect(out).toEqual([
      { kind: "d", prints: [], malformed: 0 },
      { kind: "d", prints: [], malformed: 0 },
    ]);
  });
});

// E24-S08 (#783): the basis readout's test inputs, read from the recorded capture (C-13.5), never invented:
// `bybit/2026-10-05/ws/recorded_tickers_BTCUSDT.jsonl`, folded snapshot + deltas into the merged state
// `23` §14.8 serves, mapped to `TickerUpdate` items (`lastPrice`, `markPrice`, `indexPrice`).
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import type { DeltaFrame, ResetFrame, SnapFrame } from "../../../../src/lib/ws/api";

const CAPTURE = resolve(
  import.meta.dirname,
  "../../../../../../packages/fixtures/bybit/2026-10-05",
);

export interface TickerItem {
  symbol: string;
  last_price: string;
  mark_price?: string | undefined;
  index_price?: string | undefined;
  ts_ms: number;
  stale?: boolean;
}

export const recordedTickerItems = (): TickerItem[] => {
  const lines = readFileSync(resolve(CAPTURE, "ws/recorded_tickers_BTCUSDT.jsonl"), "utf8")
    .split("\n")
    .filter((l) => l.trim() !== "");
  const merged: Record<string, string> = {};
  return lines.map((line) => {
    const msg = JSON.parse(line) as { ts: number; data: Record<string, string> };
    Object.assign(merged, msg.data);
    return {
      symbol: merged["symbol"] ?? "",
      last_price: merged["lastPrice"] ?? "",
      mark_price: merged["markPrice"],
      index_price: merged["indexPrice"],
      ts_ms: msg.ts,
    };
  });
};

const stamp = { seq: 1, ts: 0, sp: undefined, decodeMs: 0, size: 1 };

export const tickerSnap = (items: readonly TickerItem[]): SnapFrame => ({
  kind: "snap",
  meta: undefined,
  bodies: [{ e: "j", p: { tickers: items } }],
  ...stamp,
});

export const tickerDelta = (items: readonly TickerItem[]): DeltaFrame => ({
  kind: "d",
  meta: undefined,
  body: { e: "j", p: { tickers: items } },
  ...stamp,
});

export const tickerReset: ResetFrame = { kind: "reset", reason: "reconnect" };

// E24-S03 (#778): the recorded `bybit/2026-10-05/ws/recorded_tickers_BTCUSDT.jsonl` (C-13.5), folded into the
// merged `23` §14.8 items (`fundingRate` → `funding_rate`, `nextFundingTime` → `next_funding_time_ms`).
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import type { DeltaFrame, SnapFrame } from "../../../../src/lib/ws/api";

const FILE = resolve(
  import.meta.dirname,
  "../../../../../../packages/fixtures/bybit/2026-10-05/ws/recorded_tickers_BTCUSDT.jsonl",
);

export interface FundingTickerItem {
  symbol: string;
  last_price: string;
  funding_rate?: string | undefined;
  next_funding_time_ms?: number | undefined;
  ts_ms: number;
  stale?: boolean;
}

export const recordedFundingItems = (): FundingTickerItem[] => {
  const merged: Record<string, string> = {};
  return readFileSync(FILE, "utf8")
    .split("\n")
    .filter((l) => l.trim() !== "")
    .map((line) => {
      const msg = JSON.parse(line) as { ts: number; data: Record<string, string> };
      Object.assign(merged, msg.data);
      const next = merged["nextFundingTime"];
      return {
        symbol: merged["symbol"] ?? "",
        last_price: merged["lastPrice"] ?? "",
        funding_rate: merged["fundingRate"],
        next_funding_time_ms: next === undefined ? undefined : Number(next),
        ts_ms: msg.ts,
      };
    });
};

const stamp = { seq: 1, ts: 0, sp: undefined, decodeMs: 0, size: 1 };

export const snap = (items: readonly FundingTickerItem[]): SnapFrame => ({
  kind: "snap",
  meta: undefined,
  bodies: [{ e: "j", p: { tickers: items } }],
  ...stamp,
});

export const delta = (items: readonly FundingTickerItem[]): DeltaFrame => ({
  kind: "d",
  meta: undefined,
  body: { e: "j", p: { tickers: items } },
  ...stamp,
});

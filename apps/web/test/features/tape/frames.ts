// E22-S01 (#714): `trades.{symbol}` frames as `TopicHandle.read()` hands them over, built to the
// `23` §14.2 `TradesBatch` schema (a server frame shape, not a Bybit payload: C-13.5 fixtures cover
// the exchange side).
import type { DeltaFrame, ResetFrame, ResetReason, SnapFrame } from "../../../src/lib/ws/api";

export interface Item {
  id?: string;
  ts_ms: number;
  price: string;
  size: string;
  side: "buy" | "sell";
  is_big_trade?: boolean;
  is_block_trade?: boolean;
  is_liquidation?: boolean;
  cluster_size?: number;
}

export const item = (n: number, over: Partial<Item> = {}): Item => ({
  id: `t${n}`,
  ts_ms: 1_700_000_000_000 + n,
  price: (65_000 + (n % 10) / 10).toFixed(1),
  size: "0.010",
  side: n % 2 === 0 ? "buy" : "sell",
  ...over,
});

export const items = (from: number, to: number): Item[] =>
  Array.from({ length: to - from + 1 }, (_, k) => item(from + k));

interface BatchExtra {
  symbol?: string;
  dropped?: number;
  coalesced?: boolean;
  coalesced_count?: number;
  big_trade_threshold?: string;
}

const batch = (trades: readonly unknown[], extra: BatchExtra) => ({
  symbol: "BTCUSDT",
  big_trade_threshold: "250000",
  ...extra,
  trades,
});

const stamp = { ts: 0, sp: undefined, decodeMs: 0, size: 0 };

export const snap = (trades: readonly unknown[], extra: BatchExtra = {}, seq = 1): SnapFrame => ({
  kind: "snap",
  seq,
  ...stamp,
  meta: undefined,
  bodies: [{ e: "j", p: batch(trades, extra) }],
});

export const delta = (trades: readonly unknown[], extra: BatchExtra = {}, seq = 2): DeltaFrame => ({
  kind: "d",
  seq,
  ...stamp,
  meta: undefined,
  body: { e: "j", p: batch(trades, extra) },
});

export const reset = (reason: ResetReason = "reconnect"): ResetFrame => ({ kind: "reset", reason });

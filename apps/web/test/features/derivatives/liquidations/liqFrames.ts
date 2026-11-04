// E24-S05 (#780): `liquidations.{symbol}` frames as `TopicHandle.read()` hands them over, built to `23` §14.9
// `LiquidationBatch` (a server frame shape, not a Bybit payload). No recorded liquidation capture is on `main`
// yet (#5273 adds one), so the item values are the declared samples: `22` `getLiquidations` example `liqs`
// (62880.00 × 3.220 = 202473.60, `sell`) and D02 §6's row (82,751.20 × 0.498 = 41,210.10, ×8).
import type { DeltaFrame, ResetFrame, SnapFrame } from "../../../../src/lib/ws/api";

export interface WireItem {
  symbol: string;
  ts_ms: number;
  side: "buy" | "sell";
  price: string;
  size: string;
  notional_usd?: string;
  cluster_size?: number;
}

/** `22` example `liqs`, item 0, on the wire (`ts` 2026-09-14T10:12:44.120Z as epoch ms). */
export const EXAMPLE: WireItem = {
  symbol: "BTCUSDT",
  ts_ms: Date.parse("2026-09-14T10:12:44.120Z"),
  side: "sell",
  price: "62880.00",
  size: "3.220",
  notional_usd: "202473.60",
  cluster_size: 1,
};

/** D02 §6 / D03 S54-41's row, its side `sell` (a long liquidated, BQ 1). */
export const DESIGN: WireItem = {
  symbol: "BTCUSDT",
  ts_ms: Date.parse("2026-10-21T09:14:02Z"),
  side: "sell",
  price: "82751.20",
  size: "0.498",
  notional_usd: "41210.10",
  cluster_size: 8,
};

/** `n` copies of `item`, a millisecond apart: a cascade push. */
export const burst = (n: number, item: WireItem = EXAMPLE, fromMs = item.ts_ms): WireItem[] =>
  Array.from({ length: n }, (_, k) => ({ ...item, ts_ms: fromMs + k }));

const stamp = { ts: 0, sp: undefined, decodeMs: 0, size: 0 };
const NOTE =
  "Bybit batches at most one allLiquidation push per symbol per 500 ms; counts are lower bounds.";

export const snap = (items: readonly unknown[], seq = 1): SnapFrame => ({
  kind: "snap",
  seq,
  ...stamp,
  meta: undefined,
  bodies: [{ e: "j", p: { liquidations: items, note: NOTE } }],
});

export const delta = (items: readonly unknown[], seq = 2): DeltaFrame => ({
  kind: "d",
  seq,
  ...stamp,
  meta: undefined,
  body: { e: "j", p: { liquidations: items } },
});

export const reset = (): ResetFrame => ({ kind: "reset", reason: "reconnect" });

/** A `22` `Liquidation` item: the wire item with `ts` as RFC 3339. */
export const restItem = (w: WireItem) => {
  const { ts_ms, ...rest } = w;
  return { ...rest, ts: new Date(ts_ms).toISOString() };
};

/** `22` example `liqs`, `meta.coverage`, as served. */
export const EXAMPLE_COVERAGE_WIRE = {
  first_available_ts: "2026-09-01T00:00:00.250Z",
  covered_from: "2026-09-14T10:00:00Z",
  covered_to: "2026-09-14T11:00:00Z",
  no_coverage: false,
};

/** A `22` liquidations page (`Page` + `LiquidationsPageMeta`). */
export const restPage = (
  items: readonly unknown[],
  meta: { has_more?: boolean; next_cursor?: string | null; coverage?: unknown } = {},
) => ({
  items,
  meta: {
    count: items.length,
    has_more: meta.has_more ?? false,
    next_cursor: meta.next_cursor ?? null,
    coverage: meta.coverage ?? EXAMPLE_COVERAGE_WIRE,
  },
});

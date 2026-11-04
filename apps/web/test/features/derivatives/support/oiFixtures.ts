// E24-S01 (#776): the OI pane's test inputs, read from the recorded fixtures (C-13.5), never invented.
// - REST: `bybit/2026-10-05/rest/open_interest_BTCUSDT_5min_page{0,1}.json` (documented-shape, exception
//   #1778 A), mapped row by row to `22` `OpenInterestPoint` the way `22` describes the store's REST series:
//   `open_interest` = `openInterest` (base coin, both sides), `t` = `timestamp`, `open_interest_value` null,
//   `interval` "5min", `source` "rest". Derived in the test, not a new fixture file.
// - WS: `bybit/2026-10-05/ws/recorded_tickers_BTCUSDT.jsonl` (recorded), folded snapshot + deltas into the
//   merged state `23` §14.8 serves, mapped to `TickerUpdate` items.
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import type { DeltaFrame, ResetFrame, SnapFrame } from "../../../../src/lib/ws/api";

const CAPTURE = resolve(
  import.meta.dirname,
  "../../../../../../packages/fixtures/bybit/2026-10-05",
);

interface BybitOiRow {
  readonly openInterest: string;
  readonly timestamp: string;
}

const bybitPage = (n: 0 | 1): readonly BybitOiRow[] => {
  const raw: unknown = JSON.parse(
    readFileSync(resolve(CAPTURE, `rest/open_interest_BTCUSDT_5min_page${n}.json`), "utf8"),
  );
  return (raw as { result: { list: BybitOiRow[] } }).result.list;
};

export interface ApiPoint {
  t: string;
  open_interest: string;
  open_interest_value: string | null;
  interval: string;
  source: string;
}

/** Every recorded REST row as a `22` point, ascending (the venue answers newest first). */
export const recordedRestPoints = (): ApiPoint[] =>
  [...bybitPage(0), ...bybitPage(1)]
    .map((r) => ({
      t: new Date(Number(r.timestamp)).toISOString(),
      open_interest: r.openInterest,
      open_interest_value: null,
      interval: "5min",
      source: "rest",
    }))
    .sort((a, b) => Date.parse(a.t) - Date.parse(b.t));

export const coverageOf = (points: readonly ApiPoint[], over: Record<string, unknown> = {}) => ({
  from: points[0]?.t ?? null,
  to: points[points.length - 1]?.t ?? null,
  native_interval: "5min",
  source: "rest",
  gaps: [],
  ...over,
});

/** A `22` page body. */
export const page = (
  items: readonly ApiPoint[],
  meta: { next_cursor?: string | null; has_more?: boolean; coverage?: unknown } = {},
) => ({
  symbol: "BTCUSDT",
  items,
  meta: {
    count: items.length,
    has_more: meta.has_more ?? false,
    next_cursor: meta.next_cursor ?? null,
    coverage: meta.coverage ?? coverageOf(items),
  },
});

export interface TickerItem {
  symbol: string;
  last_price: string;
  open_interest?: string | undefined;
  open_interest_value?: string | undefined;
  ts_ms: number;
  stale?: boolean;
}

/** The recorded ticker stream, folded into merged state: one item per message, OI fields included. */
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
      open_interest: merged["openInterest"],
      open_interest_value: merged["openInterestValue"],
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

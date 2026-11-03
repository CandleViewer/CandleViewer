// E24-S01 (#776) slice 1: the OI fields of `ticker.{symbol}` frames (`23` §14.8 `TickerUpdate`), as
// `TopicHandle.read()` hands them over. Whole items, last write wins (`23` §8.2); only this symbol's
// items with a decimal `open_interest` are kept, the rest are skipped, never coerced. A reset is
// passed through so the series can draw the seam.
import type { generated } from "@candleviewer/protocol";
import type { TopicFrame } from "../../../lib/ws/api";
import type { DataBody } from "../../../lib/ws/protocol/codec";
import { isDecimal } from "./decimal";
import type { LiveTick } from "./series";

type TickerItem = generated.ws.TickerSymbolTicker["tickers"][number];

export interface ParsedTick extends LiveTick {
  /** `23` §14.8 per-item `stale`; absent reads `false`. */
  readonly stale: boolean;
}

const get = (v: unknown, key: string): unknown =>
  typeof v === "object" && v !== null ? Reflect.get(v, key) : undefined;

const isEpochMs = (v: unknown): v is number =>
  typeof v === "number" && Number.isSafeInteger(v) && v > 0;

export function parseTickerItem(item: unknown, symbol: string): ParsedTick | null {
  const sym: unknown = get(item, "symbol" satisfies keyof TickerItem);
  const base: unknown = get(item, "open_interest" satisfies keyof TickerItem);
  const value: unknown = get(item, "open_interest_value" satisfies keyof TickerItem);
  const ts: unknown = get(item, "ts_ms" satisfies keyof TickerItem);
  if (sym !== symbol || !isDecimal(base) || !isEpochMs(ts)) return null;
  return {
    tsMs: ts,
    base,
    valueUsdt: isDecimal(value) ? value : null,
    stale: get(item, "stale" satisfies keyof TickerItem) === true,
  };
}

function itemsOf(body: DataBody): readonly unknown[] {
  if (body.e !== "j") return []; // `ticker` is structured; a binary body carries no ticker (`23` §6.1)
  const tickers = get(body.p, "tickers");
  return Array.isArray(tickers) ? tickers : [];
}

/** The frames' ticks in arrival order, with `"reset"` where the stream reset. */
export function parseTickerFrames(
  frames: readonly TopicFrame[],
  symbol: string,
): readonly (ParsedTick | "reset")[] {
  const out: (ParsedTick | "reset")[] = [];
  for (const frame of frames) {
    if (frame.kind === "reset") {
      out.push("reset");
      continue;
    }
    const bodies = frame.kind === "snap" ? frame.bodies : [frame.body];
    for (const body of bodies) {
      for (const item of itemsOf(body)) {
        const tick = parseTickerItem(item, symbol);
        if (tick !== null) out.push(tick);
      }
    }
  }
  return out;
}

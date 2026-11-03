// E24-S08 (#783) slice 1: the price fields of `ticker.{symbol}` frames (`23` §14.8 `TickerUpdate`) as
// `TopicHandle.read()` hands them over. Whole items, last write wins (`23` §8.2); only this symbol's items
// with a decimal `last_price` and a `ts_ms` are kept, the rest are skipped, never coerced. `mark_price` /
// `index_price` are optional in the schema: absent or malformed reads `null`, never 0.
import type { generated } from "@candleviewer/protocol";
import type { TopicFrame } from "../../lib/ws/api";
import { isDecimalString } from "./decimal";
import type { DataBody } from "../../lib/ws/protocol/codec";

type TickerItem = generated.ws.TickerSymbolTicker["tickers"][number];

export interface BasisTick {
  readonly tsMs: number;
  readonly last: string;
  readonly mark: string | null;
  readonly index: string | null;
  /** `23` §14.8 per-item `stale`; absent reads `false`. */
  readonly stale: boolean;
}

const get = (v: unknown, key: string): unknown =>
  typeof v === "object" && v !== null ? Reflect.get(v, key) : undefined;

const isEpochMs = (v: unknown): v is number =>
  typeof v === "number" && Number.isSafeInteger(v) && v > 0;

export function parseBasisItem(item: unknown, symbol: string): BasisTick | null {
  const sym: unknown = get(item, "symbol" satisfies keyof TickerItem);
  const last: unknown = get(item, "last_price" satisfies keyof TickerItem);
  const mark: unknown = get(item, "mark_price" satisfies keyof TickerItem);
  const index: unknown = get(item, "index_price" satisfies keyof TickerItem);
  const ts: unknown = get(item, "ts_ms" satisfies keyof TickerItem);
  if (sym !== symbol || !isDecimalString(last) || !isEpochMs(ts)) return null;
  return {
    tsMs: ts,
    last,
    mark: isDecimalString(mark) ? mark : null,
    index: isDecimalString(index) ? index : null,
    stale: get(item, "stale" satisfies keyof TickerItem) === true,
  };
}

function itemsOf(body: DataBody): readonly unknown[] {
  if (body.e !== "j") return []; // `ticker` is structured; a binary body carries no ticker (`23` §6.1)
  const tickers = get(body.p, "tickers");
  return Array.isArray(tickers) ? tickers : [];
}

/** The frames' ticks in arrival order, with `"reset"` where the stream reset. */
export function parseBasisFrames(
  frames: readonly TopicFrame[],
  symbol: string,
): readonly (BasisTick | "reset")[] {
  const out: (BasisTick | "reset")[] = [];
  for (const frame of frames) {
    if (frame.kind === "reset") {
      out.push("reset");
      continue;
    }
    const bodies = frame.kind === "snap" ? frame.bodies : [frame.body];
    for (const body of bodies) {
      for (const item of itemsOf(body)) {
        const tick = parseBasisItem(item, symbol);
        if (tick !== null) out.push(tick);
      }
    }
  }
  return out;
}

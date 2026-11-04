// E24-S03 (#778) slice 2: the funding fields of `ticker.{symbol}` items (`23` §14.8), last write wins. An
// absent or malformed field reads `null`, never 0 and never a time computed from the interval (BQ 1).
import type { generated } from "@candleviewer/protocol";
import type { TopicFrame } from "../../lib/ws/api";
import type { DataBody } from "../../lib/ws/protocol/codec";
import { isDecimal } from "./history";

type TickerItem = generated.ws.TickerSymbolTicker["tickers"][number];

export interface FundingTick {
  readonly tsMs: number;
  /** The accruing rate per interval, as sent. */
  readonly rate: string | null;
  readonly nextFundingTimeMs: number | null;
  readonly stale: boolean;
}

const get = (v: unknown, key: string): unknown =>
  typeof v === "object" && v !== null ? Reflect.get(v, key) : undefined;

const isEpochMs = (v: unknown): v is number =>
  typeof v === "number" && Number.isSafeInteger(v) && v > 0;

export function parseFundingItem(item: unknown, symbol: string): FundingTick | null {
  const ts = get(item, "ts_ms" satisfies keyof TickerItem);
  if (get(item, "symbol" satisfies keyof TickerItem) !== symbol || !isEpochMs(ts)) return null;
  const rate = get(item, "funding_rate" satisfies keyof TickerItem);
  const next = get(item, "next_funding_time_ms" satisfies keyof TickerItem);
  return {
    tsMs: ts,
    rate: isDecimal(rate) ? rate : null,
    nextFundingTimeMs: isEpochMs(next) ? next : null,
    stale: get(item, "stale" satisfies keyof TickerItem) === true,
  };
}

function itemsOf(body: DataBody): readonly unknown[] {
  if (body.e !== "j") return []; // `ticker` is structured; a binary body carries no ticker (`23` §6.1)
  const tickers = get(body.p, "tickers");
  return Array.isArray(tickers) ? tickers : [];
}

/** The frames' ticks in arrival order, with `"reset"` where the stream reset. */
export function parseFundingFrames(
  frames: readonly TopicFrame[],
  symbol: string,
): readonly (FundingTick | "reset")[] {
  const out: (FundingTick | "reset")[] = [];
  for (const frame of frames) {
    if (frame.kind === "reset") {
      out.push("reset");
      continue;
    }
    const bodies = frame.kind === "snap" ? frame.bodies : [frame.body];
    for (const body of bodies) {
      for (const item of itemsOf(body)) {
        const tick = parseFundingItem(item, symbol);
        if (tick !== null) out.push(tick);
      }
    }
  }
  return out;
}

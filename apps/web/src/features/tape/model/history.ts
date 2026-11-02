// E22-S01 (#714) PR-B: prints from REST `GET /market/trades` (`22` getTrades, `marketdata:read`):
// the missed prints of a reconnect gap (S15 / S16, "Load missed prints") and the history below the
// oldest held print (S14, BQ-214). The source is the server's hot tape, the last 1 000 prints per
// symbol (G-59); recorded history is E16's. They are display rows only and never enter the ring.
import { apiFetch } from "../../../lib/http/csrfFetch";
import { FLAG_BIG, FLAG_BLOCK, FLAG_LIQUIDATION, SIDE_BUY, SIDE_SELL, type TapeSide } from "./ring";

export interface ExtraPrint {
  readonly id: string;
  readonly tsMs: number;
  readonly price: string;
  readonly size: string;
  readonly side: TapeSide;
  readonly flags: number;
  readonly clusterSize: number;
}

export interface TradesQuery {
  readonly symbol: string;
  /** Inclusive, epoch ms. */
  readonly fromMs: number;
  /** Exclusive, epoch ms. */
  readonly toMs: number;
}

/** Resolves the page's items as sent, newest first; the tape checks each one. */
export type FetchTrades = (query: TradesQuery) => Promise<readonly unknown[]>;

/** `22` getTrades: `limit` at most 500 (SR-E22-02), `to - from` at most 6 h (SR-E22-01). */
export const TRADES_PAGE_LIMIT = 500;
export const TRADES_MAX_WINDOW_MS = 6 * 60 * 60 * 1000;

const isDecimal = (v: unknown): v is string =>
  typeof v === "string" && v.length > 0 && v.length <= 40 && Number.isFinite(Number(v));

/** A `22` `PublicTrade`, or `null` when it fails the shape (it is then not shown). */
export function parsePublicTrade(v: unknown): ExtraPrint | null {
  if (typeof v !== "object" || v === null || Array.isArray(v)) return null;
  const t = v as Readonly<Record<string, unknown>>;
  const tsMs = typeof t["ts"] === "string" ? Date.parse(t["ts"]) : Number.NaN;
  const id = t["id"];
  const side = t["side"];
  if (
    typeof id !== "string" ||
    id.length === 0 ||
    !Number.isFinite(tsMs) ||
    !isDecimal(t["price"]) ||
    !isDecimal(t["size"]) ||
    (side !== "buy" && side !== "sell")
  ) {
    return null;
  }
  const cluster = t["cluster_size"];
  return {
    id,
    tsMs,
    price: t["price"],
    size: t["size"],
    side: side === "buy" ? SIDE_BUY : SIDE_SELL,
    flags:
      (t["is_block_trade"] === true ? FLAG_BLOCK : 0) |
      (t["is_liquidation"] === true ? FLAG_LIQUIDATION : 0) |
      (t["is_big_trade"] === true ? FLAG_BIG : 0),
    clusterSize:
      typeof cluster === "number" && Number.isInteger(cluster) && cluster > 1 ? cluster : 1,
  };
}

/** The app's fetch: one page of the hot tape, same origin, through the CSRF-aware client. */
export const fetchTradesPage: FetchTrades = async ({ symbol, fromMs, toMs }) => {
  const params = new URLSearchParams({
    symbol,
    from: new Date(fromMs).toISOString(),
    to: new Date(toMs).toISOString(),
    limit: String(TRADES_PAGE_LIMIT),
  });
  const res = await apiFetch(`/api/v1/market/trades?${params.toString()}`, { method: "GET" });
  if (!res.ok) throw new Error(`trades page refused (${res.status})`);
  const body: unknown = await res.json();
  const items =
    typeof body === "object" && body !== null ? (body as { items?: unknown }).items : undefined;
  return Array.isArray(items) ? (items as readonly unknown[]) : [];
};

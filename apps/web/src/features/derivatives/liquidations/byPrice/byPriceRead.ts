// E24-S07 (#782) slice 2: the recorded liquidations by price read, `GET /api/v1/market/liquidations/by-price` (`22`
// `getLiquidationsByPrice`, slice 0). The server computes the buckets; the client never re-buckets prints (the ruling
// on #781, 6618707867). Every member is checked against the generated `LiquidationsByPrice` at the boundary and the
// Decimal strings stay strings. BQ 7 (ruled 6624627875): an answer without its required `estimated` flag is refused,
// as is any other shape or an answer for another symbol, and a refused answer draws nothing.
import type { generated } from "@candleviewer/protocol";
import { apiFetch } from "../../../../lib/http/csrfFetch";

type Schemas = generated.rest.components["schemas"];
export type ByPriceAnswer = Schemas["LiquidationsByPrice"];
export type ByPriceBucket = Schemas["LiquidationPriceBucket"];

export const BY_PRICE_PATH = "/api/v1/market/liquidations/by-price";
export const DEADLINE_MS = 10_000;

/** Why an answer was refused: analytics tokens. */
export type RefusalCode = "estimated_missing" | "symbol_mismatch" | "malformed";

export type ByPriceRead =
  | { readonly kind: "ok"; readonly answer: ByPriceAnswer }
  | { readonly kind: "refused"; readonly code: RefusalCode }
  /** `status` `null`: no answer (network, deadline, unreadable body). */
  | { readonly kind: "failed"; readonly status: number | null; readonly code: string | null };

export interface ByPriceRequest {
  readonly symbol: string;
  readonly signal: AbortSignal;
}

const get = (v: unknown, key: string): unknown =>
  typeof v === "object" && v !== null ? Reflect.get(v, key) : undefined;
const decimal = (v: unknown): v is string => typeof v === "string" && /^\d+(?:\.\d+)?$/.test(v);
const time = (v: unknown): v is string => typeof v === "string" && Number.isFinite(Date.parse(v));
const timeOrNull = (v: unknown): v is string | null => v === null || time(v);
const count = (v: unknown, min: number, max: number): v is number =>
  Number.isInteger(v) && (v as number) >= min && (v as number) <= max;

const BUCKET_KEYS = ["price_lo", "price_hi", "long_notional_usd", "short_notional_usd"] as const;
const isBucket = (v: unknown): v is ByPriceBucket =>
  BUCKET_KEYS.every((k) => decimal(get(v, k))) &&
  count(get(v, "prints"), 1, Number.MAX_SAFE_INTEGER);

/** The answer, typed, or why it is refused. */
export function parseByPrice(
  body: unknown,
  symbol: string,
): Exclude<ByPriceRead, { kind: "failed" }> {
  const estimated = get(body, "estimated");
  // checked first: a stripped flag is the X02 negative and is named as such
  if (typeof estimated !== "boolean") return { kind: "refused", code: "estimated_missing" };
  const echoed = get(body, "symbol");
  if (typeof echoed === "string" && echoed !== symbol)
    return { kind: "refused", code: "symbol_mismatch" };
  const [from, to, ticks, tick, items] = ["from", "to", "bucket_ticks", "tick_size", "items"].map(
    (k) => get(body, k),
  );
  const c = get(get(body, "meta"), "coverage");
  const [first, coveredFrom, coveredTo, none] = [
    "first_available_ts",
    "covered_from",
    "covered_to",
    "no_coverage",
  ].map((k) => get(c, k));
  const ok =
    echoed === symbol &&
    time(from) &&
    time(to) &&
    decimal(tick) &&
    count(ticks, 1, 1000) &&
    Array.isArray(items) &&
    items.length <= 20 &&
    items.every(isBucket) &&
    timeOrNull(first) &&
    timeOrNull(coveredFrom) &&
    timeOrNull(coveredTo) &&
    typeof none === "boolean";
  if (!ok) return { kind: "refused", code: "malformed" };
  return {
    kind: "ok",
    answer: {
      symbol,
      from,
      to,
      bucket_ticks: ticks,
      tick_size: tick,
      estimated,
      items: items.map((b: ByPriceBucket) => ({
        price_lo: b.price_lo,
        price_hi: b.price_hi,
        long_notional_usd: b.long_notional_usd,
        short_notional_usd: b.short_notional_usd,
        prints: b.prints,
      })),
      meta: {
        coverage: {
          first_available_ts: first,
          covered_from: coveredFrom,
          covered_to: coveredTo,
          no_coverage: none,
        },
      },
    },
  };
}

/** K01 §1 item 3's defaults, sent so the request names them; `from` is left to the server's UTC day (BQ 5). */
export const byPricePath = (symbol: string): string =>
  `${BY_PRICE_PATH}?${new URLSearchParams({ symbol, bucket_ticks: "20", top: "5" }).toString()}`;

export async function fetchLiquidationsByPrice(req: ByPriceRequest): Promise<ByPriceRead> {
  const call = new AbortController();
  const end = (): void => call.abort();
  const deadline = setTimeout(end, DEADLINE_MS);
  req.signal.addEventListener("abort", end);
  try {
    if (req.signal.aborted) return { kind: "failed", status: null, code: null };
    const res = await apiFetch(byPricePath(req.symbol), { method: "GET", signal: call.signal });
    const body: unknown = await res.json().catch(() => null);
    if (res.status === 200) return parseByPrice(body, req.symbol);
    const code = get(body, "code");
    return { kind: "failed", status: res.status, code: typeof code === "string" ? code : null };
  } catch {
    return { kind: "failed", status: null, code: null };
  } finally {
    clearTimeout(deadline);
    req.signal.removeEventListener("abort", end);
  }
}

// E24-S05 (#780) slice 1: the prints of `liquidations.{symbol}` frames (`23` §14.9 `LiquidationBatch`) as
// `TopicHandle.read()` hands them over, and of `/market/liquidations` items (`22` `Liquidation`). Only this
// symbol's well-formed items are kept; the rest are counted and skipped, never coerced. Decimals stay the
// strings the server sent: the client formats, it never computes (`22`: notional is computed once at ingest).
import type { generated } from "@candleviewer/protocol";
import type { TopicFrame } from "../../../lib/ws/api";
import type { DataBody } from "../../../lib/ws/protocol/codec";
import { liquidatedSide, type LiquidatedSide, type WireSide } from "./side";

/**
 * BQ 2 (ruled 6612481277, #780): no server clustering, so every item is one print and the rate counts prints.
 * The `cluster_size` a print still carries is Bybit's own, shown as ×N.
 */
export const CLUSTER_WINDOW_MS = 0;

type WireItem = generated.ws.LiquidationsSymbolLiquidations["liquidations"][number];
type RestItem = generated.rest.components["schemas"]["Liquidation"];

/** One print as the feed holds it. */
export interface LiquidationPrint {
  readonly tsMs: number;
  readonly side: LiquidatedSide;
  readonly price: string;
  /** Base units. */
  readonly size: string;
  /** USD, as served; `null` when the item carries none (it is optional on the wire). */
  readonly notionalUsd: string | null;
  /** `cluster_size`, 1 when absent (`cluster_window_ms = 0`, BQ 2). */
  readonly clusterSize: number;
}

/** A snapshot's prints (a subscribe or a resync's "last 100") or a delta's appended ones. */
export interface ParsedBatch {
  readonly kind: "snap" | "d";
  readonly prints: readonly LiquidationPrint[];
  readonly malformed: number;
}

const get = (v: unknown, key: string): unknown =>
  typeof v === "object" && v !== null ? Reflect.get(v, key) : undefined;

const isDecimal = (v: unknown): v is string =>
  typeof v === "string" && /^\d{1,30}(\.\d{1,18})?$/.test(v);

const isEpochMs = (v: unknown): v is number =>
  typeof v === "number" && Number.isSafeInteger(v) && v > 0;

const isSide = (v: unknown): v is WireSide => v === "buy" || v === "sell";

const clusterOf = (v: unknown): number | null =>
  v === undefined ? 1 : typeof v === "number" && Number.isSafeInteger(v) && v >= 1 ? v : null;

function build(
  tsMs: number | null,
  side: unknown,
  price: unknown,
  size: unknown,
  notional: unknown,
  cluster: unknown,
): LiquidationPrint | null {
  const clusterSize = clusterOf(cluster);
  if (tsMs === null || !isSide(side) || !isDecimal(price) || !isDecimal(size)) return null;
  if (clusterSize === null || (notional !== undefined && !isDecimal(notional))) return null;
  return {
    tsMs,
    side: liquidatedSide(side),
    price,
    size,
    notionalUsd: notional ?? null,
    clusterSize,
  };
}

/** A `23` §14.9 item for `symbol`, or `null`. */
export function parseWireItem(item: unknown, symbol: string): LiquidationPrint | null {
  if (get(item, "symbol" satisfies keyof WireItem) !== symbol) return null;
  const ts = get(item, "ts_ms" satisfies keyof WireItem);
  return build(
    isEpochMs(ts) ? ts : null,
    get(item, "side" satisfies keyof WireItem),
    get(item, "price" satisfies keyof WireItem),
    get(item, "size" satisfies keyof WireItem),
    get(item, "notional_usd" satisfies keyof WireItem),
    get(item, "cluster_size" satisfies keyof WireItem),
  );
}

/** A `22` `Liquidation` item for `symbol` (`ts` as RFC 3339), or `null`. */
export function parseRestItem(item: unknown, symbol: string): LiquidationPrint | null {
  if (get(item, "symbol" satisfies keyof RestItem) !== symbol) return null;
  const ts = get(item, "ts" satisfies keyof RestItem);
  const ms = typeof ts === "string" ? Date.parse(ts) : NaN;
  return build(
    Number.isFinite(ms) && ms > 0 ? ms : null,
    get(item, "side" satisfies keyof RestItem),
    get(item, "price" satisfies keyof RestItem),
    get(item, "size" satisfies keyof RestItem),
    get(item, "notional_usd" satisfies keyof RestItem),
    get(item, "cluster_size" satisfies keyof RestItem),
  );
}

function parseBodies(kind: ParsedBatch["kind"], bodies: readonly DataBody[], symbol: string) {
  const prints: LiquidationPrint[] = [];
  let malformed = 0;
  for (const body of bodies) {
    if (body.e !== "j") continue; // `liquidations` is structured only (`23` §6.1)
    const items = get(body.p, "liquidations");
    if (!Array.isArray(items)) continue;
    for (const item of items) {
      const print = parseWireItem(item, symbol);
      if (print === null) malformed += 1;
      else prints.push(print);
    }
  }
  return { kind, prints, malformed };
}

/** The frames' batches in arrival order, with `"reset"` where the stream reset. */
export function parseLiquidationFrames(
  frames: readonly TopicFrame[],
  symbol: string,
): readonly (ParsedBatch | "reset")[] {
  const out: (ParsedBatch | "reset")[] = [];
  for (const frame of frames) {
    if (frame.kind === "reset") out.push("reset");
    else if (frame.kind === "snap") out.push(parseBodies("snap", frame.bodies, symbol));
    else out.push(parseBodies("d", [frame.body], symbol));
  }
  return out;
}

// E24-S05 (#780) PR 4: the feed's rows are D02 §6's 250 ms buckets per side (BQ 5, ruled 6612481277). A bucket of
// one print shows the print; a bucket of many shows its print count, total size, average bankruptcy price
// (served notional ÷ size) and total notional, never one row per print in a cascade. Buckets are cut on the
// prints' own `ts_ms`: `[k·250, (k+1)·250)` per side. All sums are exact (`decimal.ts`).
import { addDec, divDec, formatDec, parseDec } from "./decimal";
import type { HeldPrint } from "./ring";

export const ROW_BUCKET_MS = 250;

/** One feed row: a print, or a bucket of prints (`prints > 1`, `price` the average, `tsMs` the bucket start). */
export interface FeedRow extends HeldPrint {
  readonly prints: number;
}

const bucketOf = (p: HeldPrint): number => Math.floor(p.tsMs / ROW_BUCKET_MS);

function merge(group: readonly HeldPrint[]): FeedRow {
  const [newest] = group;
  if (newest === undefined) throw new RangeError("an empty bucket");
  if (group.length === 1) return { ...newest, prints: 1 };
  let size = parseDec("0");
  let notional = parseDec("0");
  let served = true;
  let cluster = 0;
  for (const p of group) {
    size = addDec(size, parseDec(p.size));
    if (p.notionalUsd === null) served = false;
    else notional = addDec(notional, parseDec(p.notionalUsd));
    cluster += p.clusterSize;
  }
  const priceScale = parseDec(newest.price).scale;
  const avg = served ? divDec(notional, size, priceScale) : null;
  return {
    ...newest, // the newest print's seq keys the row
    tsMs: bucketOf(newest) * ROW_BUCKET_MS,
    price: avg === null ? newest.price : formatDec(avg),
    size: formatDec(size),
    notionalUsd: served ? formatDec(notional) : null,
    clusterSize: cluster,
    prints: group.length,
  };
}

/** Newest-first prints into at most `max` newest-first rows, one per bucket and side. */
export function feedRows(newestFirst: readonly HeldPrint[], max: number): FeedRow[] {
  const groups = new Map<string, HeldPrint[]>();
  const order: string[] = [];
  for (const p of newestFirst) {
    const key = `${String(bucketOf(p))}|${p.side}`;
    let group = groups.get(key);
    if (group === undefined) {
      if (order.length === max) break; // older prints only fill older rows
      group = [];
      groups.set(key, group);
      order.push(key);
    }
    group.push(p);
  }
  return order.map((key) => merge(groups.get(key) ?? []));
}

// The worker's eviction seam (26 §7, BQ-S15-04): layers that hold droppable ranges register an
// `evict(fromTime, toTime, tier)` callback, and an `EvictionLedger` remembers what was dropped so
// the planner never plans a range twice and the paging trigger can ask for exactly an evicted
// range again. Internal, not package API; the runtime owns one of each per chart (PR-2b).
import type { EvictionPlan, EvictionTier, TimeRange } from "./EvictionPlanner.js";

/** A layer's drop callback: release `[fromTime, toTime]` (whole bars, inclusive) at `tier`. */
export type EvictFn = (fromTime: number, toTime: number, tier: EvictionTier) => void;

export class EvictableRegistry {
  private readonly layers: { readonly layer: string; readonly evict: EvictFn }[] = [];

  /** Adds `layer`, replacing one with the same name; returns the function that removes it. */
  registerEvictable(layer: string, evict: EvictFn): () => void {
    const i = this.layers.findIndex((l) => l.layer === layer);
    if (i >= 0) this.layers.splice(i, 1);
    const entry = { layer, evict };
    this.layers.push(entry);
    return () => {
      const j = this.layers.indexOf(entry);
      if (j >= 0) this.layers.splice(j, 1);
    };
  }

  /** The layer names, in registration order (tests and diagnostics). Allocates: never per frame. */
  get names(): readonly string[] {
    return this.layers.map((l) => l.layer);
  }

  /**
   * Hands every range of `plan` to every layer, GPU drops first, and records in `ledger` each range
   * every layer dropped. A throwing layer does not stop the others, and its range is not recorded:
   * the layer still holds it, so the planner plans it again and paging does not re-ask for it.
   * Returns the count of failed calls; the runtime surfaces it as a metric (PR-2b).
   */
  apply(plan: EvictionPlan, ledger: EvictionLedger): number {
    let failed = 0;
    const each = (ranges: readonly TimeRange[], tier: EvictionTier): void => {
      for (const r of ranges) {
        let ok = true;
        for (const l of this.layers) {
          try {
            l.evict(r.fromTime, r.toTime, tier);
          } catch {
            failed += 1;
            ok = false;
          }
        }
        if (ok) ledger.record(r, tier);
      }
    };
    each(plan.gpu, "gpu");
    each(plan.cpu, "cpu");
    return failed;
  }
}

/** The ranges dropped per tier, until re-uploaded / re-fetched or cleared. */
export class EvictionLedger {
  private readonly ranges: Record<EvictionTier, TimeRange[]> = { gpu: [], cpu: [] };

  /** The ranges evicted at `tier`, ascending by `fromTime`. */
  evicted(tier: EvictionTier): readonly TimeRange[] {
    return this.ranges[tier];
  }

  record(range: TimeRange, tier: EvictionTier): void {
    const list = this.ranges[tier];
    let i = 0;
    while (i < list.length && (list[i] as TimeRange).fromTime < range.fromTime) i += 1;
    list.splice(i, 0, { fromTime: range.fromTime, toTime: range.toTime });
    // A CPU drop takes the GPU copy with it: remember it at both tiers.
    if (tier === "cpu" && !this.ranges.gpu.some((r) => covers(r, range))) this.record(range, "gpu");
  }

  /**
   * `[fromTime, toTime]` is held again (a re-upload at `gpu`, a landed `prependHistory` at `cpu`,
   * which also restores the GPU copy): forget it at that tier. A range it covers only in part keeps
   * its uncovered remainder, so paging asks for just what is still missing.
   */
  restored(fromTime: number, toTime: number, tier: EvictionTier): void {
    const tiers: readonly EvictionTier[] = tier === "cpu" ? ["cpu", "gpu"] : ["gpu"];
    for (const t of tiers) subtractRange(this.ranges[t], fromTime, toTime);
  }

  /** Forgets everything: a snapshot `setData`, a symbol or timeframe change, a context rebuild. */
  clear(): void {
    this.ranges.gpu = [];
    this.ranges.cpu = [];
  }
}

/** True when `outer` contains `inner`. */
function covers(outer: TimeRange, inner: TimeRange): boolean {
  return outer.fromTime <= inner.fromTime && inner.toTime <= outer.toTime;
}

/**
 * Removes `[fromTime, toTime]` from every range of `list` in place, keeping the uncovered parts:
 * a range covered in full goes, one covered at an end is trimmed to the rest, one covering the span
 * strictly inside is split in two. Ranges are inclusive on both ends, so a trimmed bound keeps the
 * nearest bound outside the span exactly as the caller reported it (`fromTime` / `toTime` of a
 * landed batch are bar open times: the remainder ends at the span's edge, which may re-fetch that one
 * bar, never miss one). Order by `fromTime` is kept. Allocates only on a split (per landing, never
 * per frame).
 */
export function subtractRange(list: TimeRange[], fromTime: number, toTime: number): boolean {
  let changed = false;
  for (let i = list.length - 1; i >= 0; i -= 1) {
    const r = list[i] as TimeRange;
    if (r.toTime < fromTime || r.fromTime > toTime) continue;
    changed = true;
    const left = r.fromTime < fromTime;
    const right = r.toTime > toTime;
    if (left && right) {
      list.splice(
        i,
        1,
        { fromTime: r.fromTime, toTime: fromTime },
        { fromTime: toTime, toTime: r.toTime },
      );
    } else if (left) {
      list[i] = { fromTime: r.fromTime, toTime: fromTime };
    } else if (right) {
      list[i] = { fromTime: toTime, toTime: r.toTime };
    } else {
      list.splice(i, 1);
    }
  }
  return changed;
}

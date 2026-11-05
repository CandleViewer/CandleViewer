// The paging trigger (26 §9 "paging trigger", §7 internal constants; E11-S15 AC4, BQ-S15-07).
// Pure: the caller passes the clock (`now`, ms) and the governor's state; it decides when the
// worker should emit `visibleRangeNeedsData` and keeps the `loadingRanges` bookkeeping (§6). No
// timers, no messages: the runtime feeds it viewports and polls it on its tick (PR-2b).
//
// - A need arises when the visible range comes within PAGING_DISTANCE_SPANS visible spans of the
//   loaded history edge, or when a remembered evicted range (§7) lies within that distance; an
//   evicted range is asked for with exactly its own bounds, nearest to the visible range first.
// - An edge page is `[max(recordedFrom, visibleFrom - distance), loadedFrom]`: `toTime` is the
//   loaded edge itself (inclusive, like every engine range), so its bar may come back once.
// - Trailing debounce of PAGING_DEBOUNCE_MS on the viewport stream: each viewport with a need
//   restarts it; a viewport with none (the range is covered again) cancels it.
// - A range in flight (in `loadingRanges`) is not asked for again until `landed` answers it or a
//   different range is needed; when the nearest evicted range is in flight, the loaded edge is
//   still considered. Nothing before recorded history, nothing while `over`.
// - The `landed` contract (for the runtime, PR-2b): report the open times of the oldest and newest
//   bar the `prependHistory` batch carried. Any in-flight request the span overlaps is answered
//   (an edge page's prepend ends just before `loadedFrom`, so it overlaps but need not cover); an
//   evicted range keeps only what the span did not cover, and the next viewport asks for that.
// - Single source for evicted ranges: the runtime feeds `evictedRange` from the EvictionLedger's
//   CPU list as it records a plan (PR-2b), and `landed` mirrors `EvictionLedger.restored`; nothing
//   else writes either list, so the two cannot diverge.
// A viewport update reads and writes numbers only: it allocates nothing.
import { subtractRange } from "./Evictables.js";
import type { TimeRange } from "./EvictionPlanner.js";
import type { MemoryState } from "./Governor.js";

/** Paging distance: visible spans between the visible range and the loaded edge (26 §7 table). */
export const PAGING_DISTANCE_SPANS = 1;
/** Paging debounce on the viewport stream, ms (26 §7 table). */
export const PAGING_DEBOUNCE_MS = 250;

/** One viewport sample, the paging trigger's input. */
export interface PagingView {
  readonly visibleFrom: number;
  readonly visibleTo: number;
  /** Open time of the oldest loaded bar; `Infinity` when nothing is loaded. */
  readonly loadedFrom: number;
  readonly state: MemoryState;
}

export class PagingTrigger {
  /** The ranges asked for and not yet answered, oldest request first (`viewport.loadingRanges`). */
  readonly loadingRanges: TimeRange[] = [];
  /** Requests emitted so far (the ticket's engine.paging.requests). */
  requests = 0;
  private recordedFrom = Number.NEGATIVE_INFINITY;
  private readonly evicted: TimeRange[] = [];
  private pendingFrom = 0;
  private pendingTo = 0;
  private deadline = Number.POSITIVE_INFINITY;
  private loadingDirty = false;

  /** Open time of the oldest recorded bar (E11-D01 D2); nothing is asked for before it. */
  setRecordedFrom(time: number): void {
    this.recordedFrom = Number.isFinite(time) ? time : Number.NEGATIVE_INFINITY;
  }

  /** A CPU drop (§7): remembered, so panning back asks for exactly this range. */
  evictedRange(range: TimeRange): void {
    this.evicted.push({ fromTime: range.fromTime, toTime: range.toTime });
  }

  /** The remembered evicted ranges (tests and diagnostics). */
  get evictedRanges(): readonly TimeRange[] {
    return this.evicted;
  }

  /** True when a request is waiting for its debounce. */
  get pending(): boolean {
    return this.deadline !== Number.POSITIVE_INFINITY;
  }

  /** A viewport on the stream: (re)starts or cancels the debounce. */
  viewport(now: number, v: PagingView): void {
    if (!this.need(v)) {
      this.deadline = Number.POSITIVE_INFINITY;
      return;
    }
    this.deadline = now + PAGING_DEBOUNCE_MS;
  }

  /**
   * The tick: once the debounce has elapsed, returns the range to emit as `visibleRangeNeedsData`
   * (and lists it in `loadingRanges`); otherwise null. `state` is re-read: `over` cancels.
   */
  poll(now: number, state: MemoryState): TimeRange | null {
    if (state === "over") {
      this.deadline = Number.POSITIVE_INFINITY;
      return null;
    }
    if (now < this.deadline) return null;
    this.deadline = Number.POSITIVE_INFINITY;
    const range = { fromTime: this.pendingFrom, toTime: this.pendingTo };
    this.loadingRanges.push(range);
    this.loadingDirty = true;
    this.requests += 1;
    return range;
  }

  /**
   * A `prependHistory` landed with bars from `fromTime` to `toTime` (see the contract above): drops
   * every in-flight request the span overlaps, and trims the span out of the evicted ranges.
   */
  landed(fromTime: number, toTime: number): void {
    const loading = this.loadingRanges;
    for (let i = loading.length - 1; i >= 0; i -= 1) {
      const r = loading[i] as TimeRange;
      if (r.toTime >= fromTime && r.fromTime <= toTime) {
        loading.splice(i, 1);
        this.loadingDirty = true;
      }
    }
    // A request still waiting for its debounce would ask for what just landed: cancel it.
    if (this.pending && this.pendingTo >= fromTime && this.pendingFrom <= toTime) {
      this.deadline = Number.POSITIVE_INFINITY;
    }
    subtractRange(this.evicted, fromTime, toTime);
  }

  /** True once after `loadingRanges` changed: send it in the next `viewport` message (§6). */
  takeLoadingChanged(): boolean {
    const dirty = this.loadingDirty;
    this.loadingDirty = false;
    return dirty;
  }

  /** Forgets everything: a snapshot `setData`, a symbol or timeframe change, `dispose`. */
  reset(): void {
    if (this.loadingRanges.length > 0) this.loadingDirty = true;
    this.loadingRanges.length = 0;
    this.evicted.length = 0;
    this.recordedFrom = Number.NEGATIVE_INFINITY;
    this.deadline = Number.POSITIVE_INFINITY;
  }

  /** Computes the range `v` needs into pendingFrom / pendingTo; false when none is needed. */
  private need(v: PagingView): boolean {
    const { visibleFrom, visibleTo, loadedFrom, state } = v;
    if (state === "over" || !Number.isFinite(visibleFrom) || !Number.isFinite(visibleTo)) {
      return false;
    }
    const span = visibleTo - visibleFrom;
    if (!(span > 0)) return false;
    const reach = span * PAGING_DISTANCE_SPANS;
    const lo = visibleFrom - reach;
    const hi = visibleTo + reach;
    // A remembered evicted range within reach: exactly its bounds, nearest first.
    let best = -1;
    let bestGap = Number.POSITIVE_INFINITY;
    for (let i = 0; i < this.evicted.length; i += 1) {
      const r = this.evicted[i] as TimeRange;
      if (r.toTime < lo || r.fromTime > hi) continue;
      const gap =
        r.toTime < visibleFrom ? visibleFrom - r.toTime : Math.max(0, r.fromTime - visibleTo);
      if (gap < bestGap) {
        best = i;
        bestGap = gap;
      }
    }
    if (best >= 0) {
      const r = this.evicted[best] as TimeRange;
      if (this.propose(r.fromTime, r.toTime)) return true;
      // That range is in flight: the loaded edge is a different range, so it may still page.
    }
    // The loaded history edge within reach, and history recorded before it.
    if (!Number.isFinite(loadedFrom) || lo >= loadedFrom || loadedFrom <= this.recordedFrom) {
      return false;
    }
    return this.propose(Math.max(this.recordedFrom, lo), loadedFrom);
  }

  /** Records the proposal unless an in-flight request already covers it. */
  private propose(fromTime: number, toTime: number): boolean {
    for (let i = 0; i < this.loadingRanges.length; i += 1) {
      const r = this.loadingRanges[i] as TimeRange;
      if (r.fromTime <= fromTime && toTime <= r.toTime) return false;
    }
    this.pendingFrom = fromTime;
    this.pendingTo = toTime;
    return true;
  }
}

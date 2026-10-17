// E17-T04 S3b (23 6.1.1 "Re-derivation"): a resize drag fires dozens of events a second, and the server
// answers a changed `time_bucket_ms` with a full re-snapshot. So the bucket is re-derived on every
// event, but a `ctl` leaves only once it has stopped changing for 400 ms, and only if it differs
// from the bucket the server holds. Only a key the server has confirmed (`activate`, at `sub_ok`) can
// send one: a late resize for a topic that was released, or never confirmed, sends nothing.
import {
  selectHeatmapBucket,
  type HeatmapBucketInput,
  type HeatmapBucketMs,
} from "../protocol/heatmapBucket";
import { platformTimers, type Timers } from "./timers";

export const CTL_DEBOUNCE_MS = 400;

export interface CtlDebouncerOptions {
  /**
   * One call per settled change; the caller sends it as `ctl { time_bucket_ms }`. A throw leaves the
   * baseline as it was, so the next `resize` derives the change again and sends it; the error is rethrown.
   */
  readonly emit: (key: string, timeBucketMs: HeatmapBucketMs) => void;
  /** The timers it runs on; defaults to the platform's. */
  readonly timers?: Partial<Timers> | undefined;
}

/**
 * Keyed by `ch` alone, as `ctl` is on the wire: 23 11 lets a live and a replay subscription share a `ch`
 * (told apart by `sub_id`, and replay frames carry `rs`) while `ctl` carries no `sub_id`, so S4 decides
 * how a replay one is keyed (a #572 candidate). The geometry is ONE per key: with two panes or tabs on
 * one heatmap `ch`, each one's resize would flip the bucket back and forth, a re-snapshot every time,
 * so S4 aggregates them (the widest pane decides) before it calls `resize`.
 */
export interface CtlDebouncer {
  /** The bucket the server holds for `key` (`sub_ok` or `ctl_ok` `effective`, C4); the key can send changes from now on. Emits nothing. */
  activate(key: string, timeBucketMs: HeatmapBucketMs): void;
  /**
   * The pane's size, DPR or `window_seconds` changed. Ignored for a key that is not active, and for
   * a geometry that is not a size (a `display: none` pane is 0 x 0: deriving from it would flip the
   * bucket on every hide and show). A user-set bucket needs no geometry.
   */
  resize(key: string, input: HeatmapBucketInput): void;
  /** The topic was released or the pane closed: its pending change and its baseline go, and a late resize sends nothing until `activate`. */
  forget(key: string): void;
  /** The client stopped: every pending change and baseline goes, and nothing can be activated again. */
  dispose(): void;
}

interface Slot {
  active: HeatmapBucketMs;
  timer: unknown;
}

const positive = (n: number): boolean => Number.isFinite(n) && n > 0;
const hasSize = ({ windowSeconds, cssWidth, dpr }: HeatmapBucketInput): boolean =>
  positive(windowSeconds) && positive(cssWidth) && positive(dpr);

export function createCtlDebouncer(options: CtlDebouncerOptions): CtlDebouncer {
  const timers = { ...platformTimers, ...options.timers };
  const slots = new Map<string, Slot>(); // only keys the server has confirmed
  let disposed = false;

  /** Stops a pending change. Never clears a handle that was not set: a strict worker `clearTimeout` throws on one. */
  const cancel = (slot: Slot | undefined): void => {
    if (slot === undefined) return;
    if (slot.timer !== undefined) timers.clearTimeout(slot.timer);
    slot.timer = undefined;
  };

  return {
    activate: (key, timeBucketMs) => {
      if (disposed) return;
      const slot = slots.get(key);
      if (slot === undefined) slots.set(key, { active: timeBucketMs, timer: undefined });
      else slot.active = timeBucketMs;
    },
    resize: (key, input) => {
      const slot = slots.get(key);
      if (slot === undefined || (input.userBucketMs === undefined && !hasSize(input))) return;
      const wanted = selectHeatmapBucket(input);
      cancel(slot);
      if (wanted === slot.active) return; // back on what the server holds: nothing to send
      slot.timer = timers.setTimeout(() => {
        slot.timer = undefined;
        if (wanted === slot.active) return; // the server came to hold it meanwhile (`activate`)
        const held = slot.active;
        slot.active = wanted; // optimistic, so a settle on the same value does not send twice
        try {
          options.emit(key, wanted);
        } catch (error) {
          slot.active = held; // not sent: the next resize derives it again
          throw error;
        }
      }, CTL_DEBOUNCE_MS);
    },
    forget: (key) => {
      cancel(slots.get(key));
      slots.delete(key);
    },
    dispose: () => {
      disposed = true;
      for (const slot of slots.values()) cancel(slot);
      slots.clear();
    },
  };
}

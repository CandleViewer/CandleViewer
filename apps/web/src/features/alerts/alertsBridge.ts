/**
 * WS -> store bridge for the `alerts` topic (E40-S01). Transport -> coalesce -> store, never a
 * store write per message: frames only fold into a pending per-alert fact, and the frame
 * scheduler (the shell WS client's rAF scheduler) applies everything that arrived since the last
 * frame in one `recordFires` call. `stop()` unsubscribes from the source, cancels the pending
 * frame and drops the pending facts; frames after that are ignored.
 */
import {
  createFrameScheduler,
  type FrameSchedulerOptions,
} from "../../lib/ws/client/frameScheduler.js";
import type { AlertsStore, FireFact } from "./alertsStore.js";
import type { AlertsFrame } from "./types.js";

/** Whatever delivers `alerts` frames; returns the teardown. */
export interface AlertsFrameSource {
  readonly subscribe: (onFrame: (frame: AlertsFrame) => void) => () => void;
}

export type AlertsBridgeOptions = Pick<FrameSchedulerOptions<FireFact>, "raf" | "caf" | "now">;

export function startAlertsBridge(
  source: AlertsFrameSource,
  store: AlertsStore,
  options: AlertsBridgeOptions = {},
): () => void {
  const pending = new Map<string, FireFact>();
  let unacked: number | undefined;
  const scheduler = createFrameScheduler<FireFact>({
    ...options,
    render: (batch) => {
      pending.clear();
      store.recordFires([...batch.values()].filter((fact) => fact.count > 0));
      if (unacked !== undefined) {
        store.setUnackedCount(unacked);
        unacked = undefined;
      }
    },
  });
  const unsubscribe = source.subscribe((frame) => {
    for (const delivery of frame.deliveries) {
      const before = pending.get(delivery.alert_id);
      const fact: FireFact = {
        alertId: delivery.alert_id,
        firedAtMs: Math.max(before?.firedAtMs ?? Number.NEGATIVE_INFINITY, delivery.fired_at_ms),
        count: (before?.count ?? 0) + 1,
      };
      pending.set(delivery.alert_id, fact);
      scheduler.post(delivery.alert_id, fact);
    }
    if (frame.unacked_count !== undefined) {
      unacked = frame.unacked_count;
      // A frame carrying only a count still needs a frame to land on.
      if (frame.deliveries.length === 0)
        scheduler.post("\u0000unacked", { alertId: "", firedAtMs: 0, count: 0 });
    }
  });
  return () => {
    unsubscribe();
    scheduler.stop();
    pending.clear();
    unacked = undefined;
  };
}

/**
 * The real `alerts` topic as an `AlertsFrameSource` (E40-S01). One consumer on the active WS client
 * (private bucket), drained at most once a second (the screen's <=1 Hz repaint, SCR-090 §2.8) and
 * released on teardown. A snapshot holds the already-existing unacknowledged rows, not new firings,
 * so it carries only the unacked count; deltas carry fires. A reset (gap, reconnect) asks for a refetch.
 */
import type { TopicFrame } from "../../lib/ws/api";
import type { WsClientHandle } from "../../lib/ws/client/createWsClient";
import type { AlertsFrameSource } from "./alertsBridge.js";
import type { AlertsFrame } from "./types.js";

export const ALERTS_TOPIC = "alerts";
export const DRAIN_MS = 1_000;

function payloadOf(body: { readonly e: string; readonly p?: unknown }): AlertsFrame | null {
  if (body.e !== "j" || typeof body.p !== "object" || body.p === null) return null;
  const p = body.p as Partial<AlertsFrame>;
  return Array.isArray(p.deliveries) ? ({ deliveries: p.deliveries, ...p } as AlertsFrame) : null;
}

export function frameFor(frame: TopicFrame): AlertsFrame | null {
  if (frame.kind === "reset") return null;
  if (frame.kind === "d") return payloadOf(frame.body);
  const snap = frame.bodies.map(payloadOf).at(-1);
  if (snap === null || snap === undefined) return null;
  return snap.unacked_count === undefined
    ? { deliveries: [] }
    : { deliveries: [], unacked_count: snap.unacked_count };
}

export function createWsAlertsSource(
  client: () => WsClientHandle | null,
  onResync: () => void = () => undefined,
  schedule: { readonly every: (fn: () => void, ms: number) => () => void } = {
    every: (fn, ms) => {
      const id = setInterval(fn, ms);
      return () => clearInterval(id);
    },
  },
): AlertsFrameSource {
  return {
    subscribe: (onFrame) => {
      const handle = client()?.consume({
        ch: ALERTS_TOPIC,
        paneId: "alerts-centre",
        priority: "private",
      });
      if (handle === undefined) return () => undefined;
      const stop = schedule.every(() => {
        for (const frame of handle.read()) {
          if (frame.kind === "reset") onResync();
          const mapped = frameFor(frame);
          if (mapped !== null) onFrame(mapped);
        }
      }, DRAIN_MS);
      return () => {
        stop();
        handle.release();
      };
    },
  };
}

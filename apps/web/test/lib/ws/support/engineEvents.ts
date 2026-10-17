// Builders for the `EngineEvent`s the reducer consumes (S4's engine emits them), and the check of
// the ordering promises S4 keeps. Shared by the reducer scenarios and the exhaustive sweep.
import type { KillSwitchPayload, SystemUpdate } from "../../../../src/lib/ws/protocol/frames";
import type { EngineEvent, TopicStatus } from "../../../../src/lib/ws/state/types";

export const OFF: KillSwitchPayload = { engaged: false, scope: "global" };
export const ON: KillSwitchPayload = { engaged: true, scope: "global" };

/** An untrusted wire value that the generated types forbid; the cast is the point of the test. */
export const wire = <T>(value: unknown): T => value as T;

export const connecting: EngineEvent = { type: "connecting" };
export const offline: EngineEvent = { type: "offline", cause: "tailnet_unreachable" };
export const authOk = (killSwitch?: KillSwitchPayload): EngineEvent => ({
  type: "auth_ok",
  killSwitch,
});
export const retry = (attempt: number): EngineEvent => ({
  type: "reconnecting",
  attempt,
  nextAttemptAtMs: 1,
});
export const stream = (status: TopicStatus): EngineEvent => ({ type: "system_stream", status });

export const system = (update: SystemUpdate): EngineEvent => ({ type: "system", update });
export const quality = (wireClass: unknown): EngineEvent =>
  system({ kind: "connection_quality", class: wire<"healthy">(wireClass) });
export const killSwitch = (payload: unknown): EngineEvent =>
  system({ kind: "kill_switch", kill_switch: wire<KillSwitchPayload>(payload) });
/** A `shutdown_notice` as the gateway sends it, prose included so that a leak into the state shows. */
export const notice = (countdown: Record<string, unknown>): EngineEvent =>
  system({
    kind: "shutdown_notice",
    reason: "PROSE_DEPLOY",
    message: "PROSE_MESSAGE",
    ...wire<Partial<SystemUpdate>>(countdown),
  });
export const shutdown = notice({ closing_in_ms: 5000, expected_downtime_ms: 2e4 });

/**
 * The first break of the two promises on `EngineEvent`, or `undefined`. A new socket is announced
 * by `connecting`, so an `auth_ok` never follows `reconnecting` or `offline`; and a resynced
 * `system` stream reports `live` before the update of the snapshot that ended the resync.
 */
export function orderViolation(events: readonly EngineEvent[]): string | undefined {
  let link = "connecting"; // the reducer's initial state
  let status: TopicStatus = "pending";
  for (const [i, e] of events.entries()) {
    if (e.type === "auth_ok" && (link === "reconnecting" || link === "offline")) {
      return `#${i} auth_ok after ${link}: the new socket was not announced by connecting`;
    }
    if (e.type === "system" && status !== "pending" && status !== "live") {
      return `#${i} system update while the stream is ${status}: report live first`;
    }
    if (e.type === "system_stream") status = e.status;
    if (e.type === "auth_ok" && link === "connecting") status = "pending";
    if (e.type === "auth_ok") link = "up";
    if (e.type === "connecting" || e.type === "reconnecting" || e.type === "offline") {
      link = e.type;
      status = "pending";
    }
  }
  return undefined;
}

/** What S4's tests run on the events its engine emitted. */
export function assertEngineOrder(events: readonly EngineEvent[]): void {
  const violation = orderViolation(events);
  if (violation !== undefined) throw new Error(`engine order broken: ${violation}`);
}

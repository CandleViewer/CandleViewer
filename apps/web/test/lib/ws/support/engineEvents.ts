// Builders for the `EngineEvent`s the reducer consumes (S4's engine emits them). Shared by the
// reducer scenarios and the exhaustive sweep.
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
export const shutdown = system({
  kind: "shutdown_notice",
  closing_in_ms: 5000,
  expected_downtime_ms: 2e4,
});

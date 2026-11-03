// The `window.__engineEvents` contract between the harness page (main.tsx fills it) and the specs
// (support/engine/harness.ts reads it). Public engine events only (BQ-03).
/** The public engine events the harness records (no `pick`: `crosshair` is its public form, #388). */
export const RECORDED = [
  "viewportChanged",
  "frameStats",
  "crosshair",
  "click",
  "dataState",
  "error",
] as const;

export interface HarnessEvent {
  readonly seq: number;
  readonly type: (typeof RECORDED)[number] | "fixtureLoaded";
  readonly payload: unknown;
}

export interface EngineEventLog {
  readonly log: HarnessEvent[];
  seq: number;
}

declare global {
  interface Window {
    __engineEvents?: EngineEventLog;
  }
}

const CAP = 4000;

export function record(events: EngineEventLog, type: HarnessEvent["type"], payload: unknown): void {
  events.seq += 1;
  events.log.push({ seq: events.seq, type, payload });
  if (events.log.length > CAP) events.log.splice(0, events.log.length - CAP);
}

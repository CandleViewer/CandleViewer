/** Headless fakes for the SyncBus tests: members with no engine and a hand-cranked frame. */
import {
  createSyncBus,
  type SyncBus,
  type SyncBusOptions,
} from "../../../../src/features/workspace/sync/syncBus";
import type {
  ApplyResult,
  SyncAxes,
  SyncGroupId,
  SyncMember,
  SyncPayload,
} from "../../../../src/features/workspace/sync/types";

export interface FakeMember extends SyncMember {
  symbol: string | null;
  interval: string | null;
  /** An order-capable chart (CMP-221) holds a symbol while armed. */
  armed: boolean;
  readonly received: SyncPayload[];
  /** Runs inside `apply`, after the value is taken (a chart re-emitting what it was given). */
  onApply?: (payload: SyncPayload) => void;
}

export function fakeMember(
  paneId: string,
  init: { kind?: string; symbol?: string | null; interval?: string | null; armed?: boolean } = {},
): FakeMember {
  const m: FakeMember = {
    paneId,
    kind: init.kind ?? "chart",
    symbol: init.symbol === undefined ? "BTCUSDT" : init.symbol,
    interval: init.interval === undefined ? "time:1" : init.interval,
    armed: init.armed ?? false,
    received: [],
    current: () => ({ symbol: m.symbol, interval: m.interval }),
    apply(payload): ApplyResult {
      if (payload.axis === "symbol" && m.armed) return "held";
      m.received.push(payload);
      if (payload.axis === "symbol") m.symbol = payload.symbol;
      if (payload.axis === "interval") m.interval = payload.interval;
      m.onApply?.(payload);
      return "applied";
    },
  };
  return m;
}

export interface Frames {
  readonly requestFrame: (flush: () => void) => void;
  /** Runs the frames queued so far; returns how many ran. */
  run(): number;
  readonly pending: number;
}

export function manualFrames(): Frames {
  const queue: (() => void)[] = [];
  return {
    requestFrame: (flush) => void queue.push(flush),
    run() {
      const due = queue.splice(0);
      for (const flush of due) flush();
      return due.length;
    },
    get pending() {
      return queue.length;
    },
  };
}

export const ALL_ON: SyncAxes = {
  symbol: true,
  interval: true,
  crosshair: true,
  timeRange: true,
  drawings: true,
};

/** A bus on manual frames with every group's axes all on. */
export function busWithFrames(options: SyncBusOptions = {}): { bus: SyncBus; frames: Frames } {
  const frames = manualFrames();
  const bus = createSyncBus({ dev: true, requestFrame: frames.requestFrame, ...options });
  for (const g of ["A", "B", "C"] as SyncGroupId[]) bus.setAxes(g, ALL_ON);
  frames.run();
  return { bus, frames };
}

/** `n` chart members `p1..pn` joined to `group`. */
export function joinAll(bus: SyncBus, n: number, group: SyncGroupId = "A"): FakeMember[] {
  return Array.from({ length: n }, (_, i) => {
    const m = fakeMember(`p${i + 1}`);
    bus.join(m, group);
    return m;
  });
}

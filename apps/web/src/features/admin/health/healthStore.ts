/**
 * SCR-143's store (E42-D05 D5–D9; the build plan's §1.2), one module-level store as S01's is. The
 * page's mount holds it. D5's reads (the report, page 1 of the open and of the acknowledged
 * incidents, the protection counters) run on the hold and on Re-read only, never on a timer (D6,
 * ruling Q10); a Retry re-reads the report. One read per id at a time; a good answer is kept through
 * a failed re-read, stale from that failure (D6). While held it folds the shell's `system` frames and
 * notes when the transport dropped (HL-14). The last release aborts every read and drops everything
 * [BQ-20]; a `403` on any read stops everything and calls the area's `deny` once (BQ-10).
 */
import { useEffect, useRef, useSyncExternalStore } from "react";
import type { ErrorCode } from "@candleviewer/protocol";
import {
  getShellState,
  subscribeShellState,
  type ShellState,
} from "../../../shell/bootstrap/store";
import { denyArea, type DenyHook } from "../ops/deny";
import {
  HEALTH_TIMEOUT_MS,
  LIST_TIMEOUT_MS,
  OPS_PATHS,
  readOps,
  vetHealthReport,
  vetIncidentPage,
  vetProtection,
  type ComponentState,
  type HealthReport,
  type IncidentPageBody,
  type OpsAnswer,
  type OpsFailReason,
  type ProtectionBody,
  type ReadOptions,
} from "../ops/opsReads";
import type { ReadTimers } from "../overview/adminReads";
import { sameJson } from "../overview/readStore";
import {
  foldClock,
  foldHealthFrame,
  frameOverall,
  NO_WORDS,
  type ClockSeen,
  type SystemUpdate,
  type Words,
} from "./frames";

export interface Bodies {
  readonly health: HealthReport;
  readonly open: IncidentPageBody;
  readonly acknowledged: IncidentPageBody;
  readonly protection: ProtectionBody;
}
export type ReadId = keyof Bodies;
export const READ_IDS: readonly ReadId[] = ["health", "open", "acknowledged", "protection"];

/** Why the last answer failed: no usable answer, or a refusal's status and registered code. */
export type Failure =
  { readonly reason: OpsFailReason } | { readonly status: number; readonly code: ErrorCode | null };

export interface Slot<T> {
  /** The last answer's kind; `idle` until the first one this visit. */
  readonly phase: "idle" | "ok" | "failed" | "not_built";
  readonly inFlight: boolean;
  /** The last good body, kept through a failure: shown as old, never as fresh. */
  readonly data?: T | undefined;
  /** The client's clock at the last good answer. */
  readonly okAt?: number | undefined;
  /** The first failure since the last good answer: "stale since" (D6). */
  readonly failedAt?: number | undefined;
  readonly failure?: Failure | undefined;
  /** What pressed the Retry whose read is in flight: only that control shows busy. */
  readonly retriedBy?: string | undefined;
  /** How many answers this visit: a failed read says its line once per read. */
  readonly answers?: number | undefined;
}

export interface HealthState {
  readonly reads: { readonly [K in ReadId]: Slot<Bodies[K]> };
  /** The components' words from the frames seen while held. */
  readonly words: Words;
  /** When the newest frame listing components arrived; none: the frame held at mount. */
  readonly framesSeenAt?: number | undefined;
  readonly clock: ClockSeen;
  /** The newest frame's overall word, and when it arrived (none: the frame held at mount). */
  readonly overall?:
    { readonly word: ComponentState; readonly at?: number | undefined } | undefined;
  /** When the page saw the transport drop; undefined while it is live (HL-14). */
  readonly droppedAt?: number | undefined;
  /** A `403` withdrew the area: its problem's Ref. */
  readonly denied: { readonly refId: string | undefined } | null;
}

export interface HealthDeps {
  readonly now: () => number;
  readonly read: <K extends ReadId>(id: K, signal: AbortSignal) => Promise<OpsAnswer<Bodies[K]>>;
  /** The shell store: its `system` frames and its transport. */
  readonly shell: {
    readonly get: () => ShellState;
    readonly subscribe: (listener: () => void) => () => void;
  };
  readonly deny: DenyHook;
}

const IDLE: Slot<never> = Object.freeze({ phase: "idle", inFlight: false });
const INITIAL: HealthState = Object.freeze({
  reads: Object.freeze({ health: IDLE, open: IDLE, acknowledged: IDLE, protection: IDLE }),
  words: NO_WORDS,
  clock: Object.freeze({}),
  denied: null,
});

/** A transport the session had, and has lost: a later `connecting` is a loss, not the boot. */
const lost = (s: ShellState): boolean => s.everLive && s.connection.kind !== "live";

export type HealthStore = ReturnType<typeof createHealthStore>;

export function createHealthStore(deps: HealthDeps) {
  let state = INITIAL;
  const listeners = new Set<() => void>();
  const controllers = new Map<ReadId, AbortController>();
  let holds = 0;
  let unwatch: (() => void) | null = null;
  let seenHealth: SystemUpdate | undefined;
  let seenDrift: SystemUpdate | undefined;

  function set(next: HealthState): void {
    if (next === state) return;
    state = next;
    for (const listener of [...listeners]) listener();
  }
  const setSlot = <K extends ReadId>(id: K, slot: Slot<Bodies[K]>): void =>
    set({ ...state, reads: { ...state.reads, [id]: slot } });

  function abortAll(): void {
    for (const controller of controllers.values()) controller.abort();
    controllers.clear();
  }

  function unwatchShell(): void {
    unwatch?.();
    unwatch = null;
    seenHealth = undefined;
    seenDrift = undefined;
  }

  function withdraw(refId: string | undefined): void {
    abortAll();
    unwatchShell();
    set({ ...INITIAL, denied: { refId } });
    deps.deny(refId);
  }

  function settle<K extends ReadId>(id: K, answer: OpsAnswer<Bodies[K]>): void {
    const prev = state.reads[id];
    const answers = (prev.answers ?? 0) + 1;
    if (answer.kind === "ok") {
      const data = sameJson(prev.data, answer.body) ? prev.data : answer.body;
      setSlot(id, { phase: "ok", inFlight: false, data, okAt: answer.at, answers });
    } else if (answer.kind === "not_built") {
      setSlot(id, { phase: "not_built", inFlight: false, answers });
    } else if (answer.kind === "refused" && answer.denied) {
      withdraw(answer.refId);
    } else {
      const failure: Failure =
        answer.kind === "failed"
          ? { reason: answer.reason }
          : { status: answer.status, code: answer.code };
      const failedAt = prev.phase === "failed" ? prev.failedAt : deps.now();
      const { data, okAt } = prev;
      setSlot(id, { phase: "failed", inFlight: false, data, okAt, failedAt, failure, answers });
    }
  }

  function start(id: ReadId, retriedBy?: string): void {
    if (state.denied !== null || holds === 0) return;
    const slot = state.reads[id];
    if (controllers.has(id)) {
      if (retriedBy !== undefined) setSlot(id, { ...slot, retriedBy });
      return;
    }
    const controller = new AbortController();
    controllers.set(id, controller);
    setSlot(id, { ...slot, inFlight: true, retriedBy });
    void deps.read(id, controller.signal).then((answer) => {
      if (controllers.get(id) !== controller) return; // stopped meanwhile: the answer is dropped
      controllers.delete(id);
      settle(id, answer);
    });
  }

  /** A new frame object is a new frame: its words and clock take the client's time now. */
  function onShell(): void {
    const s = deps.shell.get();
    const at = deps.now();
    let next = state;
    const health = s.systemByKind.health;
    if (health !== undefined && health !== seenHealth) {
      seenHealth = health;
      const word = frameOverall(health);
      next = {
        ...next,
        words: foldHealthFrame(next.words, health),
        framesSeenAt: Array.isArray(health.components) ? at : next.framesSeenAt,
        clock: foldClock(next.clock, health, at),
        overall: word === undefined ? next.overall : { word, at },
      };
    }
    const drift = s.systemByKind.clock_drift;
    if (drift !== undefined && drift !== seenDrift) {
      seenDrift = drift;
      next = { ...next, clock: foldClock(next.clock, drift, at) };
    }
    const droppedAt = lost(s) ? (next.droppedAt ?? at) : undefined;
    set(droppedAt === next.droppedAt ? next : { ...next, droppedAt });
  }

  /**
   * The frames the shell already holds read "as of —" until the next one: the shell keeps no frame
   * time [BQ-8]. A drift notice held at mount may be long over, so only a new one counts. A transport
   * already lost counts as dropped when the page saw it.
   */
  function watchShell(): void {
    if (unwatch !== null) return;
    const s = deps.shell.get();
    seenHealth = s.systemByKind.health;
    seenDrift = s.systemByKind.clock_drift;
    const frame = seenHealth;
    const word = frame === undefined ? undefined : frameOverall(frame);
    set({
      ...state,
      words: frame === undefined ? NO_WORDS : foldHealthFrame(NO_WORDS, frame),
      framesSeenAt: undefined,
      clock: frame === undefined ? {} : foldClock({}, frame, undefined),
      overall: word === undefined ? undefined : { word },
      droppedAt: lost(s) ? deps.now() : undefined,
    });
    unwatch = deps.shell.subscribe(onShell);
  }

  function stopAll(): void {
    abortAll();
    unwatchShell();
    // Leaving the page keeps nothing it read: the next visit starts cold [BQ-20].
    set(state.denied === null ? INITIAL : { ...INITIAL, denied: state.denied });
  }

  return {
    getState: (): HealthState => state,
    subscribe: (listener: () => void): (() => void) => {
      listeners.add(listener);
      return () => {
        listeners.delete(listener);
      };
    },
    /** Holds the page's reads and frames while the page is mounted; returns the release. */
    hold: (): (() => void) => {
      holds += 1;
      if (state.denied === null) {
        watchShell();
        // A visit's first hold reads; StrictMode's second finds the reads in flight.
        for (const id of READ_IDS) if (state.reads[id].phase === "idle") start(id);
      }
      let released = false;
      return () => {
        if (released) return;
        released = true;
        holds = Math.max(0, holds - 1); // a release after `reset` finds nothing held
        // A remount releases and holds again in one commit: stop only if nothing came back.
        queueMicrotask(() => {
          if (holds === 0) stopAll();
        });
      };
    },
    /** Re-read: D5's reads again, each one not already in flight. */
    reread: (): void => {
      for (const id of READ_IDS) start(id);
    },
    /** A Retry: the report again; `origin` names the control shown busy. */
    retry: (origin: string): void => start("health", origin),
    /** Tests only: back to the first state, every read and subscription stopped. */
    reset: (): void => {
      holds = 0;
      abortAll();
      unwatchShell();
      state = INITIAL;
      for (const listener of [...listeners]) listener();
    },
  };
}

const TIMERS: ReadTimers = {
  setTimeout: (run, ms) => globalThis.setTimeout(run, ms),
  clearTimeout: (handle) => globalThis.clearTimeout(handle as ReturnType<typeof setTimeout>),
};

const READERS: { readonly [K in ReadId]: (o: ReadOptions) => Promise<OpsAnswer<Bodies[K]>> } = {
  health: (o) => readOps(OPS_PATHS.health, vetHealthReport, HEALTH_TIMEOUT_MS, o),
  open: (o) => readOps(OPS_PATHS.incidents("open"), vetIncidentPage, LIST_TIMEOUT_MS, o),
  acknowledged: (o) =>
    readOps(OPS_PATHS.incidents("acknowledged"), vetIncidentPage, LIST_TIMEOUT_MS, o),
  protection: (o) => readOps(OPS_PATHS.protection, vetProtection, LIST_TIMEOUT_MS, o),
};

const now = (): number => Date.now();

/** SCR-143's one store. */
export const healthStore: HealthStore = createHealthStore({
  now,
  read: (id, signal) => READERS[id]({ signal, timers: TIMERS, now }),
  shell: { get: getShellState, subscribe: subscribeShellState },
  deny: denyArea,
});

/** Holds the page's reads and frames while the calling page is mounted. */
export function useHealthHold(store: HealthStore = healthStore): void {
  useEffect(() => store.hold(), [store]);
}

/**
 * A selection from the store, kept while its JSON is unchanged: a view re-renders only when what it
 * shows changed, so a frame that changes one component renders one tile.
 */
export function useHealthSelector<T>(
  selector: (state: HealthState) => T,
  store: HealthStore = healthStore,
): T {
  const memo = useRef<{ state: HealthState; selector: typeof selector; value: T } | null>(null);
  const getSnapshot = (): T => {
    const current = store.getState();
    const last = memo.current;
    if (last !== null && last.state === current && last.selector === selector) return last.value;
    const next = selector(current);
    const value = last !== null && sameJson(last.value, next) ? last.value : next;
    memo.current = { state: current, selector, value };
    return value;
  };
  return useSyncExternalStore(store.subscribe, getSnapshot, getSnapshot);
}

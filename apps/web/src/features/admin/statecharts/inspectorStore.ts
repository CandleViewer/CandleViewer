/**
 * The statechart inspector's store (E42-S08 §3.3): one module-level store, read through
 * `useSyncExternalStore` as the overview's is (`overview/readStore.ts`). The page's mount holds it
 * and an open machine view holds its machine. Reads run on a hold (once per visit), on [Re-read],
 * on a Retry and on opening a machine, never on a timer: no interval and no re-read cycle (BQ-7).
 * At most one read is in flight per resource, and a new filter or machine aborts the older read.
 * A chart is read once per `kind@hash` per visit: an export is a kind's structure, the same for
 * every machine of that kind and hash. A re-read keeps every field that reads the same (a page's
 * rows, its kinds; a machine, its configuration, its events), so a view memoised on one draws
 * nothing again when only `generated_at` moved. "Latched only" reads the rows again and keeps the
 * kinds and slices meanwhile, the same on every filter (`22`). The last release aborts every read
 * in flight and drops every answer and chart, so the next visit starts cold. A `403` on any read
 * stops everything, drops every answer and calls the area's `deny` hook once (BQ-8); nothing more
 * is asked after it. The store never derives a state, a transition or the latch: it holds what was
 * served (C-2.21).
 */
import { useEffect, useRef, useSyncExternalStore } from "react";
import type { FailReason, ReadTimers } from "../overview/adminReads";
import { sameJson } from "../overview/readStore";
import {
  readDetail,
  readExport,
  readList,
  type ChartExport,
  type InspectorOutcome,
  type ListRequest,
  type MachineDetail,
  type MachineList,
  type MachineRef,
} from "./inspectorReads";

export interface ListState {
  /** The last answer's kind; `idle` until the first one of this visit and filter. */
  readonly phase: "idle" | "ok" | "failed" | "not_built";
  readonly inFlight: boolean;
  /** "Latched only": the list reads `degraded=true`. */
  readonly latchedOnly: boolean;
  /** The last good page for this filter, kept through a failed re-read (its rows stay). */
  readonly data?: MachineList | undefined;
  /**
   * `data` is the other filter's page: this filter's first page has not answered (it is in flight,
   * or it failed). Its rows are not this filter's, so none is shown; its kinds, slices and "as of",
   * the same on every filter (`22`), are.
   */
  readonly otherFilter?: boolean | undefined;
  /** The client's clock at the last answer. */
  readonly answeredAt?: number | undefined;
  readonly reason?: FailReason | undefined;
  readonly status?: number | undefined;
}

/** The open machine's chart: read by its detail's kind and hash. */
export interface ChartRead {
  readonly kind: string;
  readonly hash: string;
  readonly phase: "idle" | "ok" | "unusable";
  readonly inFlight: boolean;
  readonly chart?: ChartExport | undefined;
  /** Why it is unusable: no chart for the kind (`not_found`), not served, or a failed read. */
  readonly reason?: "not_found" | "not_built" | FailReason | undefined;
}

export interface MachineState {
  readonly ref: MachineRef | null;
  readonly phase: "idle" | "ok" | "failed" | "not_found" | "not_built";
  readonly inFlight: boolean;
  /** The last good detail of this machine, kept through a failed re-read. */
  readonly detail?: MachineDetail | undefined;
  readonly answeredAt?: number | undefined;
  readonly reason?: FailReason | undefined;
  readonly status?: number | undefined;
  /** Once a detail served the machine: its chart. */
  readonly chart: ChartRead | null;
}

export interface InspectorState {
  readonly list: ListState;
  readonly machine: MachineState;
  /** A `403` withdrew the area: nothing more is asked until the page reloads (BQ-8). */
  readonly denied: { readonly refId: string | undefined } | null;
}

/** The area's withdrawal on a `403`: the shape of #1023's `deny()` (`overview/readStore.ts`). */
export type DenyHook = (refId: string | undefined) => void;

export interface InspectorDeps {
  readonly now: () => number;
  readonly readList: (
    request: ListRequest,
    signal: AbortSignal,
  ) => Promise<InspectorOutcome<MachineList>>;
  readonly readDetail: (
    ref: MachineRef,
    signal: AbortSignal,
  ) => Promise<InspectorOutcome<MachineDetail>>;
  readonly readExport: (
    kind: string,
    signal: AbortSignal,
  ) => Promise<InspectorOutcome<ChartExport>>;
  readonly deny: DenyHook;
}

export interface InspectorStore {
  readonly getState: () => InspectorState;
  readonly subscribe: (listener: () => void) => () => void;
  /** The page's mount: reads the list once per visit; returns the release. */
  readonly hold: () => () => void;
  /** "Latched only": the first page under the new filter; the older read is aborted. */
  readonly setLatchedOnly: (on: boolean) => void;
  /**
   * [Re-read]: the held list's page and the open machine's detail; a read in flight is not
   * repeated, and focus stays where it is (D05 §13).
   */
  readonly reread: () => void;
  /** A Retry: the list's, the open machine's or its chart's read again. */
  readonly retry: (what: "list" | "machine" | "chart") => void;
  /** Opens a machine: its detail, then its chart unless read this visit; returns the close. */
  readonly open: (ref: MachineRef) => () => void;
  /** Tests only: back to the first state, every read stopped. */
  readonly reset: () => void;
}

const IDLE_LIST: ListState = Object.freeze({ phase: "idle", inFlight: false, latchedOnly: false });
const IDLE_MACHINE: MachineState = Object.freeze({
  ref: null,
  phase: "idle",
  inFlight: false,
  chart: null,
});
const INITIAL: InspectorState = Object.freeze({
  list: IDLE_LIST,
  machine: IDLE_MACHINE,
  denied: null,
});

/** The visit's chart cache key: an export is the same for every machine of a kind and hash. */
export const chartKey = (kind: string, hash: string): string => `${kind}@${hash}`;

const sameRef = (a: MachineRef | null, b: MachineRef): boolean =>
  a !== null && a.key === b.key && a.env === b.env;

/** `next`, or `prev` when it reads the same: a view memoised on it draws nothing again. */
const kept = <T>(prev: T | undefined, next: T): T =>
  prev !== undefined && sameJson(prev, next) ? prev : next;

/**
 * A page that keeps each field of `prev` that reads the same: every slice carries its own read
 * time (`generated_at`, under 5 s old), so a re-read rarely reads the same as a whole, while its
 * rows and kinds often do.
 */
function shareList(prev: MachineList | undefined, next: MachineList): MachineList {
  if (prev === undefined || sameJson(prev, next)) return prev ?? next;
  return {
    items: kept(prev.items, next.items),
    kinds: kept(prev.kinds, next.kinds),
    snapshots: kept(prev.snapshots, next.snapshots),
    metrics: kept(prev.metrics, next.metrics),
    meta: kept(prev.meta, next.meta),
  };
}

/** A machine's detail that keeps each field of `prev` that reads the same, as `shareList`. */
function shareDetail(prev: MachineDetail | undefined, next: MachineDetail): MachineDetail {
  if (prev === undefined || sameJson(prev, next)) return prev ?? next;
  const { events, machine, configuration, recent_events: recent } = next;
  return {
    ...next,
    snapshots: kept(prev.snapshots, next.snapshots),
    ...(events === undefined ? {} : { events: kept(prev.events, events) }),
    ...(machine === undefined ? {} : { machine: kept(prev.machine, machine) }),
    ...(configuration === undefined
      ? {}
      : { configuration: kept(prev.configuration, configuration) }),
    ...(recent === undefined ? {} : { recent_events: kept(prev.recent_events, recent) }),
  };
}

/** A read the store did not expect (`invalid_cursor` before any cursor is sent) is a failure. */
const failure = (
  outcome: InspectorOutcome<unknown>,
): { readonly reason: FailReason; readonly status: number | undefined } =>
  outcome.kind === "failed"
    ? { reason: outcome.reason, status: outcome.status }
    : { reason: "status", status: 400 };

export function createInspectorStore(deps: InspectorDeps): InspectorStore {
  let state: InspectorState = INITIAL;
  const listeners = new Set<() => void>();
  /** The visit's charts by `kind@hash`: only answers that read, never a failure. */
  const charts = new Map<string, ChartExport>();
  let holds = 0;
  /** The current open's token; `0` while no machine view holds one. */
  let openToken = 0;
  let listRead: AbortController | null = null;
  let detailRead: AbortController | null = null;
  let chartRead: AbortController | null = null;

  function notify(): void {
    for (const listener of [...listeners]) listener();
  }
  function setList(list: ListState): void {
    state = { ...state, list };
    notify();
  }
  function setMachine(machine: MachineState): void {
    state = { ...state, machine };
    notify();
  }
  function stopChart(): void {
    chartRead?.abort();
    chartRead = null;
  }
  function stopMachine(): void {
    detailRead?.abort();
    detailRead = null;
    stopChart();
  }
  /** Aborts every read in flight: an answer that comes later is dropped. */
  function abortAll(): void {
    listRead?.abort();
    listRead = null;
    stopMachine();
  }

  /** A `403`: every read stops, every answer goes, and the area's withdrawal is asked for once. */
  function deny(refId: string | undefined): void {
    abortAll();
    charts.clear();
    state = { list: IDLE_LIST, machine: IDLE_MACHINE, denied: { refId } };
    notify();
    deps.deny(refId);
  }

  function startList(): void {
    if (state.denied !== null || listRead !== null) return;
    const controller = new AbortController();
    listRead = controller;
    setList({ ...state.list, inFlight: true });
    void deps
      .readList({ latchedOnly: state.list.latchedOnly }, controller.signal)
      .then((outcome) => {
        if (listRead !== controller) return; // stopped or replaced: its answer is dropped
        listRead = null;
        settleList(outcome);
      });
  }

  function settleList(outcome: InspectorOutcome<MachineList>): void {
    const prev = state.list;
    const base = { inFlight: false, latchedOnly: prev.latchedOnly, answeredAt: deps.now() };
    switch (outcome.kind) {
      case "ok":
        setList({ ...base, phase: "ok", data: shareList(prev.data, outcome.body) });
        return;
      case "denied":
        deny(outcome.refId);
        return;
      case "not_built":
      case "not_found":
        setList({ ...base, phase: "not_built" });
        return;
      case "failed":
      case "invalid_cursor": {
        const other = prev.otherFilter === true ? { otherFilter: true } : {};
        setList({ ...base, ...other, phase: "failed", data: prev.data, ...failure(outcome) });
      }
    }
  }

  function startChart(kind: string, hash: string): void {
    if (state.denied !== null) return;
    stopChart();
    const controller = new AbortController();
    chartRead = controller;
    setMachine({ ...state.machine, chart: { kind, hash, phase: "idle", inFlight: true } });
    void deps.readExport(kind, controller.signal).then((outcome) => {
      if (chartRead !== controller) return;
      chartRead = null;
      if (outcome.kind === "denied") {
        deny(outcome.refId);
      } else if (outcome.kind === "ok") {
        charts.set(chartKey(kind, hash), outcome.body);
        const chart: ChartRead = { kind, hash, phase: "ok", inFlight: false, chart: outcome.body };
        setMachine({ ...state.machine, chart });
      } else {
        const reason =
          outcome.kind === "not_found" || outcome.kind === "not_built"
            ? outcome.kind
            : failure(outcome).reason;
        const chart: ChartRead = { kind, hash, phase: "unusable", inFlight: false, reason };
        setMachine({ ...state.machine, chart });
      }
    });
  }

  /** The served machine's chart: from this visit's cache, else read once by its bare kind. */
  function showChart(kind: string, hash: string): void {
    const current = state.machine.chart;
    if (current?.kind === kind && current.hash === hash && current.phase !== "unusable") return;
    const cached = charts.get(chartKey(kind, hash));
    if (cached === undefined) {
      startChart(kind, hash);
      return;
    }
    stopChart();
    setMachine({
      ...state.machine,
      chart: { kind, hash, phase: "ok", inFlight: false, chart: cached },
    });
  }

  function startDetail(): void {
    const ref = state.machine.ref;
    if (state.denied !== null || ref === null || detailRead !== null) return;
    const controller = new AbortController();
    detailRead = controller;
    setMachine({ ...state.machine, inFlight: true });
    void deps.readDetail(ref, controller.signal).then((outcome) => {
      if (detailRead !== controller) return;
      detailRead = null;
      settleDetail(outcome);
    });
  }

  function settleDetail(outcome: InspectorOutcome<MachineDetail>): void {
    const prev = state.machine;
    const base = { ref: prev.ref, inFlight: false, answeredAt: deps.now() };
    switch (outcome.kind) {
      case "ok": {
        const detail = shareDetail(prev.detail, outcome.body);
        const machine = outcome.body.snapshots.status === "ok" ? outcome.body.machine : undefined;
        if (machine === undefined) stopChart();
        setMachine({
          ...base,
          phase: "ok",
          detail,
          chart: machine === undefined ? null : prev.chart,
        });
        if (machine !== undefined) showChart(machine.machine_kind, machine.machine_hash);
        return;
      }
      case "denied":
        deny(outcome.refId);
        return;
      case "not_found":
      case "not_built":
        stopChart();
        setMachine({ ...base, phase: outcome.kind, chart: null });
        return;
      case "failed":
      case "invalid_cursor":
        setMachine({ ...prev, ...base, phase: "failed", ...failure(outcome) });
    }
  }

  /** The visit is over: every read stops, and nothing it read stays (the denial does). */
  function stopAll(): void {
    abortAll();
    charts.clear();
    if (state.list === IDLE_LIST && state.machine === IDLE_MACHINE) return;
    state = { ...state, list: IDLE_LIST, machine: IDLE_MACHINE };
    notify();
  }

  /** After a release or a close: stop only if nothing came back in the same commit. */
  function settleRelease(): void {
    queueMicrotask(() => {
      if (holds === 0 && openToken === 0) stopAll();
    });
  }

  return {
    getState: () => state,
    subscribe: (listener) => {
      listeners.add(listener);
      return () => {
        listeners.delete(listener);
      };
    },
    hold: () => {
      holds += 1;
      if (state.list.phase === "idle") startList();
      let released = false;
      return () => {
        if (released) return;
        released = true;
        holds -= 1;
        settleRelease();
      };
    },
    setLatchedOnly: (on) => {
      if (state.denied !== null || on === state.list.latchedOnly) return;
      listRead?.abort();
      listRead = null;
      // A new filter is a new list: no row of the other filter shows meanwhile, but its kinds,
      // slices and "as of" are this filter's too, so they stay while the rows are read.
      const { data } = state.list;
      const list: ListState = { phase: "idle", inFlight: false, latchedOnly: on };
      state = { ...state, list: data === undefined ? list : { ...list, data, otherFilter: true } };
      startList();
    },
    reread: () => {
      if (holds > 0) startList();
      startDetail();
    },
    retry: (what) => {
      const chart = state.machine.chart;
      if (what === "list" && holds > 0) startList();
      else if (what === "machine") startDetail();
      else if (what === "chart" && chart?.phase === "unusable") startChart(chart.kind, chart.hash);
    },
    open: (ref) => {
      openToken += 1;
      const token = openToken;
      if (state.denied === null && !sameRef(state.machine.ref, ref)) {
        stopMachine();
        state = { ...state, machine: { ...IDLE_MACHINE, ref: { key: ref.key, env: ref.env } } };
        startDetail();
      }
      let closed = false;
      return () => {
        if (closed) return;
        closed = true;
        // A view that closes and opens again in one commit (a re-render) keeps its reads.
        queueMicrotask(() => {
          if (openToken !== token) return;
          openToken = 0;
          stopMachine();
          if (state.machine !== IDLE_MACHINE) setMachine(IDLE_MACHINE);
          settleRelease();
        });
      };
    },
    reset: () => {
      abortAll();
      charts.clear();
      holds = 0;
      openToken = 0;
      state = INITIAL;
      notify();
    },
  };
}

const TIMERS: ReadTimers = {
  setTimeout: (run, ms) => globalThis.setTimeout(run, ms),
  // `ReadTimers` types the handle as opaque; it is always the one `setTimeout` above returned.
  clearTimeout: (handle) => globalThis.clearTimeout(handle as ReturnType<typeof setTimeout>),
};

const browserDeps: InspectorDeps = {
  now: () => Date.now(),
  readList: (request, signal) => readList(request, signal, TIMERS),
  readDetail: (ref, signal) => readDetail(ref, signal, TIMERS),
  readExport: (kind, signal) => readExport(kind, signal, TIMERS),
  // The hook point for the area's `deny()`, which E42-S02 owns by the orchestrator's ruling on the
  // shared kit (BQ-8): it plugs in here when it lands. Until then a `403` withdraws this store
  // alone (`denied`), and `InspectorPage` renders `AdminDenied` itself; the area's band and strip
  // stay until one of their own reads is refused (SCR-154 N-2).
  deny: () => undefined,
};

/** The inspector's one store. */
export const inspector: InspectorStore = createInspectorStore(browserDeps);

/** Holds the inspector while the calling page is mounted: its list is read once per visit. */
export function useInspectorHold(store: InspectorStore = inspector): void {
  useEffect(() => store.hold(), [store]);
}

/** Opens `ref`'s machine while the calling view is mounted: its detail, then its chart. */
export function useOpenMachine(ref: MachineRef, store: InspectorStore = inspector): void {
  const { key, env } = ref;
  useEffect(() => store.open({ key, env }), [store, key, env]);
}

/**
 * A selection from the store, kept while its JSON is unchanged: a view re-renders only when what
 * it shows changed (a re-read that changed nothing renders nothing).
 */
export function useInspectorSelector<T>(
  selector: (state: InspectorState) => T,
  store: InspectorStore = inspector,
): T {
  const memo = useRef<{ state: InspectorState; selector: typeof selector; value: T } | null>(null);
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

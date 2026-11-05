// E13-S01 (#423) S2: the chart's indicator instances as client state (BQ-3; D06 §3.2 "SCR-036 tree
// ← client state"), per chart, with its undo/redo history (BQ-4). A plain external store read
// through `useSyncExternalStore` with selectors, as `features/drawings/store/drawingStore.ts`
// (no new state dependency: the coordinator's E14-T02 BQ-01 ruling; Zustand is not in the repo).
// BQ-05 ruled a Zustand slice, but zustand is not a dependency and the same ruling allows no new one
// for tests, so this keeps the drawings precedent; the conflict is raised on #423.
// It holds instance CONFIG only (id, indicator, params, placement, slot, flags): series, values and
// recompute results never pass through it or React state (BQ-7). Every operation goes through the
// chart's bound `IndicatorEnginePort`, and the port is called before state commits, so an engine
// throw or a server refusal leaves the store unchanged. The port's opaque keys (BQ-03) are the
// binding's, kept beside the documents and never derived here. Caps, schema and params are
// re-checked here (BQ-11, BQ-15); the server stays the authority for its own (C-12.4, `23:779`).
import { reportIndicator, type AddEntry, type IndicatorReporter } from "../analytics";
import type { EngineAddSpec, EngineKey, IndicatorEnginePort, ServerRefusal } from "../engine/port";
import type { UnavailableReason } from "../model/availability";
import type { CatalogueEntry } from "../model/catalogue";
import {
  CAP_INSTANCES,
  createInstance,
  paneKey,
  type Instance,
  type InstanceId,
} from "../model/instances";
import { validateParams, type ParamError } from "../model/params";
import type { Params, PaneTarget } from "../model/types";
import {
  EMPTY_DOC,
  paneIds,
  reduce,
  withinCaps,
  type ChartDoc,
  type DocAction,
  type Effect,
} from "./history";

export type Refusal =
  | UnavailableReason
  /** The server's refusal, as it sent it (never pre-empted or clamped; `23:779`). */
  | ServerRefusal
  /**
   * A locked item's Move and Remove are T2 "Unlock to move or remove" (D06 §7). The key is PROPOSED
   * (BQ-08 rider; `copy.ts` `PROPOSED_KEYS`), never an `rbac.*` key.
   */
  | "indicator.locked"
  | "invalid_params"
  /** No engine is bound to the chart (not mounted). */
  | "unbound"
  | "unknown_instance"
  /** Nothing would change: nothing is recorded or sent. */
  | "unchanged";

export type OpResult =
  | { readonly ok: true; readonly id: InstanceId }
  | { readonly ok: false; readonly reason: Refusal; readonly errors?: readonly ParamError[] };

/**
 * `empty`: nothing to undo/redo; `unavailable`: the entry no longer applies and was dropped;
 * `refused`: the server refused it (the entry stays, nothing changed).
 */
export type HistoryResult = "done" | "empty" | "unavailable" | "refused" | "unbound";

export interface AddInput {
  readonly entry: CatalogueEntry;
  /** Raw values from the form, a preset or a bundle: validated here before the port sees them. */
  readonly params: unknown;
  readonly target: PaneTarget;
  readonly source: AddEntry;
}

export interface HistoryState {
  readonly canUndo: boolean;
  readonly canRedo: boolean;
}

export interface IndicatorStore {
  readonly subscribe: (listener: () => void) => () => void;
  readonly getChart: (chart: string) => ChartDoc;
  /** The chart's instances in list order. Stable until the chart's list changes. */
  readonly selectInstances: (chart: string) => readonly Instance[];
  /** One pane's instances in render order (`paneKey`). Stable until that list changes. */
  readonly selectPane: (chart: string, pane: string) => readonly Instance[];
  readonly selectHistory: (chart: string) => HistoryState;
  /**
   * Binds the chart's engine: the existing instances are re-added in order (a remount). Returns
   * the unbind; after it the store never calls that port again. A second bind replaces the first.
   */
  readonly bind: (chart: string, port: IndicatorEnginePort) => () => void;
  readonly add: (chart: string, input: AddInput) => OpResult;
  readonly configure: (
    chart: string,
    id: InstanceId,
    entry: CatalogueEntry,
    params: unknown,
  ) => OpResult;
  readonly remove: (chart: string, id: InstanceId) => OpResult;
  /** Moves an instance to `to` within its pane (D06 §7; never across panes here). */
  readonly reorder: (chart: string, id: InstanceId, to: number) => OpResult;
  readonly undo: (chart: string) => HistoryResult;
  readonly redo: (chart: string) => HistoryResult;
  /** The port's opaque key for a bound instance (BQ-03), or `null` (unbound or refused). */
  readonly keyOf: (chart: string, id: InstanceId) => EngineKey | null;
  /** Session-only lock (D03 G-11): no engine call, not an undoable edit (the drawer is S5b). */
  readonly setLocked: (chart: string, id: InstanceId, locked: boolean) => void;
  /** Drops the chart's state and binding (the chart is closed). */
  readonly dispose: (chart: string) => void;
}

export interface IndicatorStoreDeps {
  readonly mint?: () => string;
  readonly report?: IndicatorReporter;
}

const NO_INSTANCES: readonly Instance[] = Object.freeze([]);
const NO_HISTORY: HistoryState = Object.freeze({ canUndo: false, canRedo: false });

const capReason = (instances: readonly Instance[]): UnavailableReason =>
  instances.length >= CAP_INSTANCES ? "indicator.cap_instances" : "indicator.cap_subpanes";

const specOf = (instance: Instance): EngineAddSpec => ({
  indicator: instance.indicator,
  compute: instance.compute,
  pane: paneKey(instance.placement),
  params: instance.params,
});

type Ran =
  | { readonly kind: "ran"; readonly instance: Instance | undefined; readonly add: boolean }
  | { readonly kind: "refused"; readonly refusal: ServerRefusal }
  | { readonly kind: "unavailable" | "unbound" };

export function createIndicatorStore(deps: IndicatorStoreDeps = {}): IndicatorStore {
  const mint = deps.mint ?? (() => globalThis.crypto.randomUUID());
  const report = deps.report ?? reportIndicator;
  let charts: ReadonlyMap<string, ChartDoc> = new Map();
  const ports = new Map<string, IndicatorEnginePort>();
  const keys = new Map<string, Map<InstanceId, EngineKey>>();
  const listeners = new Set<() => void>();
  const paneCache = new Map<string, { from: readonly Instance[]; out: readonly Instance[] }>();
  const historyCache = new Map<string, { from: ChartDoc; out: HistoryState }>();

  const getChart = (chart: string): ChartDoc => charts.get(chart) ?? EMPTY_DOC;
  const commit = (chart: string, doc: ChartDoc | null): void => {
    const next = new Map(charts);
    if (doc === null) next.delete(chart);
    else next.set(chart, doc);
    charts = next;
    for (const listener of [...listeners]) listener();
  };
  /** Runs one effect through the port; `refusal` when the server refused it (nothing changed). */
  function effect(
    port: IndicatorEnginePort,
    bound: Map<InstanceId, EngineKey>,
    e: Effect,
    after: readonly Instance[],
  ): ServerRefusal | null {
    switch (e.op) {
      case "add": {
        const instance = after.find((i) => i.id === e.id) as Instance;
        const outcome = port.add(specOf(instance));
        if (!outcome.ok) return outcome.refusal;
        bound.set(e.id, outcome.key);
        return null;
      }
      case "setParams": {
        const key = bound.get(e.id);
        if (key === undefined) return null;
        const outcome = port.setParams(key, e.params);
        if (!outcome.ok) return outcome.refusal;
        bound.set(e.id, outcome.key);
        return null;
      }
      case "remove": {
        const key = bound.get(e.id);
        if (key !== undefined) port.remove(key);
        bound.delete(e.id);
        return null;
      }
      case "setOrder": {
        const order = e.ids.flatMap((id) => bound.get(id) ?? []);
        port.setOrder(e.pane, order);
        return null;
      }
    }
  }

  /** Runs one action: port first, then state; a refusal or a throw changes nothing. */
  function run(chart: string, action: DocAction): Ran {
    const port = ports.get(chart);
    if (port === undefined) return { kind: "unbound" };
    const doc = getChart(chart);
    const step = reduce(doc, action);
    if (step.unavailable) {
      // An undo/redo entry that no longer applies is dropped from its stack, as drawings do.
      if (action.type !== "do") commit(chart, step.doc);
      return { kind: "unavailable" };
    }
    if (step.ran === null) return { kind: "unavailable" };
    const bound = new Map(keys.get(chart));
    for (const e of step.effects) {
      const refusal = effect(port, bound, e, step.doc.instances);
      if (refusal !== null) return { kind: "refused", refusal };
    }
    keys.set(chart, bound);
    commit(chart, step.doc);
    const ran = step.ran;
    const id = ran.kind === "add" || ran.kind === "remove" ? ran.instance.id : ran.id;
    const instance = step.doc.instances.find((i) => i.id === id);
    return { kind: "ran", instance, add: ran.kind === "add" };
  }

  /** A non-history field edit; an unchanged instance commits nothing. */
  function patch(chart: string, id: InstanceId, edit: (i: Instance) => Instance): void {
    const doc = getChart(chart);
    const found = doc.instances.find((i) => i.id === id);
    if (found === undefined) return;
    const next = edit(found);
    if (next === found) return;
    commit(chart, { ...doc, instances: doc.instances.map((i) => (i.id === id ? next : i)) });
  }

  const find = (chart: string, id: InstanceId): Instance | undefined =>
    getChart(chart).instances.find((i) => i.id === id);

  function history(chart: string, type: "undo" | "redo"): HistoryResult {
    if (!ports.has(chart)) return "unbound";
    const doc = getChart(chart);
    if ((type === "undo" ? doc.undo : doc.redo).length === 0) return "empty";
    const ran = run(chart, { type });
    if (ran.kind === "refused") return "refused";
    if (ran.kind !== "ran") return "unavailable";
    // D02 §8: an undo of a removal is an add with `entry: "undo"`; redo and other undos emit none.
    if (type === "undo" && ran.add && ran.instance !== undefined) {
      report({
        name: "indicator.added",
        type: ran.instance.indicator,
        pane_target: ran.instance.placement.kind === "price" ? "overlay" : "subpane",
        entry: "undo",
        compute: ran.instance.compute,
      });
    }
    return "done";
  }

  return {
    subscribe(listener) {
      listeners.add(listener);
      return () => {
        listeners.delete(listener);
      };
    },
    getChart,
    selectInstances: (chart) => charts.get(chart)?.instances ?? NO_INSTANCES,
    selectPane(chart, pane) {
      const from = getChart(chart).instances;
      const cacheKey = `${chart}\u0000${pane}`;
      const hit = paneCache.get(cacheKey);
      if (hit !== undefined && hit.from === from) return hit.out;
      const out = from.filter((i) => paneKey(i.placement) === pane);
      // Same members in the same order keep the previous array (a sibling pane's edit).
      const same =
        hit !== undefined && hit.out.length === out.length && hit.out.every((i, k) => i === out[k]);
      const kept = same ? hit.out : out.length === 0 ? NO_INSTANCES : out;
      paneCache.set(cacheKey, { from, out: kept });
      return kept;
    },
    selectHistory(chart) {
      const doc = charts.get(chart);
      if (doc === undefined) return NO_HISTORY;
      const hit = historyCache.get(chart);
      if (hit !== undefined && hit.from === doc) return hit.out;
      const canUndo = doc.undo.length > 0;
      const canRedo = doc.redo.length > 0;
      const out =
        hit !== undefined && hit.out.canUndo === canUndo && hit.out.canRedo === canRedo
          ? hit.out
          : { canUndo, canRedo };
      historyCache.set(chart, { from: doc, out });
      return out;
    },
    bind(chart, port) {
      ports.set(chart, port);
      // A re-mount re-adds in order; an instance the server now refuses stays keyless (S5 shows it).
      const bound = new Map<InstanceId, EngineKey>();
      for (const instance of getChart(chart).instances) {
        const outcome = port.add(specOf(instance));
        if (outcome.ok) bound.set(instance.id, outcome.key);
      }
      keys.set(chart, bound);
      return () => {
        if (ports.get(chart) !== port) return;
        ports.delete(chart);
        keys.delete(chart);
      };
    },
    add(chart, input) {
      if (!ports.has(chart)) return { ok: false, reason: "unbound" };
      if (!input.entry.schema.ok) return { ok: false, reason: "no_path" };
      const checked = validateParams(input.entry.schema.fields, input.params);
      if (!checked.ok) return { ok: false, reason: "invalid_params", errors: checked.errors };
      const { instances } = getChart(chart);
      const request = { entry: input.entry, params: checked.params, target: input.target };
      const instance = createInstance(instances, request, mint);
      if (!withinCaps(instances, instance)) return { ok: false, reason: capReason(instances) };
      const ran = run(chart, { type: "do", command: { kind: "add", instance } });
      if (ran.kind === "refused") return { ok: false, reason: ran.refusal };
      if (ran.kind !== "ran") return { ok: false, reason: capReason(instances) };
      report({
        name: "indicator.added",
        type: instance.indicator,
        pane_target: input.target,
        entry: input.source,
        compute: instance.compute,
      });
      return { ok: true, id: instance.id };
    },
    configure(chart, id, entry, params) {
      if (!ports.has(chart)) return { ok: false, reason: "unbound" };
      const found = find(chart, id);
      if (found === undefined || found.indicator !== entry.id) {
        return { ok: false, reason: "unknown_instance" };
      }
      if (!entry.schema.ok) return { ok: false, reason: "no_path" };
      const checked = validateParams(entry.schema.fields, params);
      if (!checked.ok) return { ok: false, reason: "invalid_params", errors: checked.errors };
      const after: Params = checked.params;
      const changed = Object.keys(after).filter((k) => after[k] !== found.params[k]);
      if (changed.length === 0) return { ok: false, reason: "unchanged" };
      const ran = run(chart, {
        type: "do",
        command: { kind: "configure", id, before: found.params, after },
      });
      if (ran.kind === "refused") return { ok: false, reason: ran.refusal };
      for (const key of changed) {
        report({
          name: "indicator.settings_changed",
          type: found.indicator,
          key,
          tab: "inputs",
          outcome: "applied",
        });
      }
      return { ok: true, id };
    },
    remove(chart, id) {
      if (!ports.has(chart)) return { ok: false, reason: "unbound" };
      const found = find(chart, id);
      if (found === undefined) return { ok: false, reason: "unknown_instance" };
      if (found.locked) return { ok: false, reason: "indicator.locked" };
      run(chart, { type: "do", command: { kind: "remove", instance: found } });
      return { ok: true, id };
    },
    reorder(chart, id, to) {
      if (!ports.has(chart)) return { ok: false, reason: "unbound" };
      const found = find(chart, id);
      if (found === undefined) return { ok: false, reason: "unknown_instance" };
      if (found.locked) return { ok: false, reason: "indicator.locked" };
      const ids = paneIds(getChart(chart).instances, paneKey(found.placement));
      const from = ids.indexOf(id);
      if (to === from || to < 0 || to >= ids.length) return { ok: false, reason: "unchanged" };
      run(chart, { type: "do", command: { kind: "reorder", id, from, to } });
      report({
        name: "indicator.reordered",
        type: found.indicator,
        group: found.placement.kind === "price" ? "overlays" : "subpanes",
        from,
        to,
      });
      return { ok: true, id };
    },
    undo: (chart) => history(chart, "undo"),
    redo: (chart) => history(chart, "redo"),
    keyOf: (chart, id) => keys.get(chart)?.get(id) ?? null,
    setLocked(chart, id, locked) {
      patch(chart, id, (i) => (i.locked === locked ? i : { ...i, locked }));
    },
    dispose(chart) {
      ports.delete(chart);
      keys.delete(chart);
      paneCache.forEach((_, k) => {
        if (k.startsWith(`${chart}\u0000`)) paneCache.delete(k);
      });
      historyCache.delete(chart);
      if (charts.has(chart)) commit(chart, null);
    },
  };
}

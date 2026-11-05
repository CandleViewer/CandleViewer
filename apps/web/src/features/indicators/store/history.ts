// E13-S01 (#423) S1b: the pure command reducer with a bounded per-chart undo/redo history (BQ-4),
// shaped on `features/drawings/store/history.ts` (E14-T02): 100 entries, in memory only, a new
// command clears redo, a command whose target is gone is dropped and reported, never forced. It is
// not shared with the drawings stack (that one is per symbol; E15 may unify them). A step returns
// the engine effects it implies, by instance id; the store (S2) runs them through the port.
// Undoing a removal re-adds the same params on the next free (slot, tier) pair at the end of its
// pane, never the old pair or position (BQ-04 rider, ruling 6652282467); the client caps are
// re-checked, and a `server` instance past the 8-instance cap is refused by the server, never
// resurrected (`23:779`).
import {
  CAP_INSTANCES,
  CAP_SUBPANES,
  paneKey,
  readdInstance,
  subpaneCount,
  type Instance,
  type InstanceId,
} from "../model/instances";
import type { Params } from "../model/types";

export const HISTORY_LIMIT = 100;

export type Command =
  | { readonly kind: "add"; readonly instance: Instance }
  | { readonly kind: "remove"; readonly instance: Instance }
  | {
      readonly kind: "configure";
      readonly id: InstanceId;
      readonly before: Params;
      readonly after: Params;
    }
  /** `from` and `to` are positions in the instance's pane. */
  | {
      readonly kind: "reorder";
      readonly id: InstanceId;
      readonly from: number;
      readonly to: number;
    };

/** One engine effect of a step, by instance id; the store maps ids to the port's keys. */
export type Effect =
  | { readonly op: "add"; readonly id: InstanceId }
  | { readonly op: "remove"; readonly id: InstanceId }
  | { readonly op: "setParams"; readonly id: InstanceId; readonly params: Params }
  | { readonly op: "setOrder"; readonly pane: string; readonly ids: readonly InstanceId[] };

export interface ChartDoc {
  /** Every instance on the chart; a pane's render order is its members' order here. */
  readonly instances: readonly Instance[];
  readonly undo: readonly Command[];
  readonly redo: readonly Command[];
}

export const EMPTY_DOC: ChartDoc = Object.freeze({ instances: [], undo: [], redo: [] });

export type DocAction =
  | { readonly type: "do"; readonly command: Command }
  | { readonly type: "undo" }
  | { readonly type: "redo" };

export interface Step {
  readonly doc: ChartDoc;
  /** Exactly one effect per command that ran. */
  readonly effects: readonly Effect[];
  /** The command as run (an undo runs the inverse); `null` when nothing ran. */
  readonly ran: Command | null;
  /** The command could not apply: its target is gone, its id is taken, or a cap is reached. */
  readonly unavailable: boolean;
}

export function invert(command: Command): Command {
  switch (command.kind) {
    case "add":
      return { kind: "remove", instance: command.instance };
    case "remove":
      return { kind: "add", instance: command.instance };
    case "configure":
      return { kind: "configure", id: command.id, before: command.after, after: command.before };
    case "reorder":
      return { kind: "reorder", id: command.id, from: command.to, to: command.from };
  }
}

export const paneIds = (instances: readonly Instance[], pane: string): InstanceId[] =>
  instances.filter((i) => paneKey(i.placement) === pane).map((i) => i.id);

/** Whether one more instance at `instance`'s placement stays within the client caps. */
export function withinCaps(instances: readonly Instance[], instance: Instance): boolean {
  if (instances.length >= CAP_INSTANCES) return false;
  if (instance.placement.kind === "price") return true;
  const pane = paneKey(instance.placement);
  const opened = instances.some((i) => paneKey(i.placement) === pane);
  return opened || subpaneCount(instances) < CAP_SUBPANES;
}

type Applied = { readonly instances: readonly Instance[]; readonly effects: readonly Effect[] };

function apply(command: Command, instances: readonly Instance[]): Applied | null {
  switch (command.kind) {
    case "add": {
      if (instances.some((i) => i.id === command.instance.id)) return null;
      if (!withinCaps(instances, command.instance)) return null;
      // The engine appends: an add, a redo or an undo's re-add joins the end of its pane.
      const instance = readdInstance(instances, command.instance);
      return { instances: [...instances, instance], effects: [{ op: "add", id: instance.id }] };
    }
    case "remove": {
      if (!instances.some((i) => i.id === command.instance.id)) return null;
      return {
        instances: instances.filter((i) => i.id !== command.instance.id),
        effects: [{ op: "remove", id: command.instance.id }],
      };
    }
    case "configure": {
      const found = instances.find((i) => i.id === command.id);
      if (found === undefined) return null;
      const next: Instance = { ...found, params: command.after };
      return {
        instances: instances.map((i) => (i.id === command.id ? next : i)),
        effects: [{ op: "setParams", id: command.id, params: command.after }],
      };
    }
    case "reorder": {
      const found = instances.find((i) => i.id === command.id);
      if (found === undefined) return null;
      const pane = paneKey(found.placement);
      const ids = paneIds(instances, pane);
      if (ids[command.from] !== command.id || command.to < 0 || command.to >= ids.length) {
        return null;
      }
      ids.splice(command.from, 1);
      ids.splice(command.to, 0, command.id);
      const byId = new Map(instances.map((i) => [i.id, i] as const));
      let k = 0;
      const next = instances.map((i) =>
        paneKey(i.placement) === pane ? (byId.get(ids[k++] as InstanceId) as Instance) : i,
      );
      return { instances: next, effects: [{ op: "setOrder", pane, ids }] };
    }
  }
}

const bounded = (stack: readonly Command[], next: Command): readonly Command[] =>
  stack.length >= HISTORY_LIMIT
    ? [...stack.slice(stack.length - HISTORY_LIMIT + 1), next]
    : [...stack, next];

export function reduce(doc: ChartDoc, action: DocAction): Step {
  if (action.type === "do") {
    const done = apply(action.command, doc.instances);
    if (done === null) return { doc, effects: [], ran: null, unavailable: true };
    return {
      doc: { instances: done.instances, undo: bounded(doc.undo, action.command), redo: [] },
      effects: done.effects,
      ran: action.command,
      unavailable: false,
    };
  }
  const from = action.type === "undo" ? doc.undo : doc.redo;
  const entry = from.at(-1);
  if (entry === undefined) return { doc, effects: [], ran: null, unavailable: false };
  const rest = from.slice(0, -1);
  const command = action.type === "undo" ? invert(entry) : entry;
  const done = apply(command, doc.instances);
  if (done === null) {
    const dropped = action.type === "undo" ? { ...doc, undo: rest } : { ...doc, redo: rest };
    return { doc: dropped, effects: [], ran: null, unavailable: true };
  }
  const next: ChartDoc =
    action.type === "undo"
      ? { instances: done.instances, undo: rest, redo: [...doc.redo, entry] }
      : { instances: done.instances, undo: bounded(doc.undo, entry), redo: rest };
  return { doc: next, effects: done.effects, ran: command, unavailable: false };
}

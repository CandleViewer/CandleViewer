/**
 * The editor's one undo stack (E37-S01; E37-D02 §8 O13, E37-D04 K-18): pointer and keyboard edits
 * share it, and E37-S05's commands call it verbatim. An entry is an edit's reversible ops, so undo
 * applies their inverses in reverse order and redo applies them again: nothing is planned or
 * checked twice, and the history is the only writer of the graph. One command is one entry (an
 * insert that also connects is one), one drag is one entry (its moves share a gesture key), a new
 * edit clears the redo stack, and the stack keeps the latest `HISTORY_DEPTH` entries. A selection
 * change is not an edit: it leaves both stacks as they are. Undo restores the selection the edit
 * started from, redo the one it ended with. Pure.
 */
import type { PortOracle } from "../a11y/graph.js";
import type { Point } from "../a11y/nudge.js";
import {
  applyOps,
  reduce,
  samePoint,
  withSelection,
  type CommandEffect,
  type Edit,
  type EditorState,
  type GraphCommand,
  type Op,
  type Selection,
} from "./commands.js";
import { portOracle } from "./portOracle.js";

/** The entries kept; the oldest drops off past it. */
export const HISTORY_DEPTH = 100;

export interface HistoryEntry extends Edit {
  /** The selection before the edit (restored on undo) and after it (restored on redo). */
  readonly before: Selection;
  readonly after: Selection;
}

export interface History {
  readonly state: EditorState;
  /** Applied entries, the latest last. */
  readonly past: readonly HistoryEntry[];
  /** Undone entries, the next to redo last. */
  readonly future: readonly HistoryEntry[];
}

export const historyOf = (state: EditorState): History => ({ state, past: [], future: [] });

export const canUndo = (history: History): boolean => history.past.length > 0;
export const canRedo = (history: History): boolean => history.future.length > 0;

/** The ops that undo `ops`: each one's inverse, last first. */
export function invert(ops: readonly Op[]): Op[] {
  return [...ops].reverse().map((op): Op => {
    switch (op.op) {
      case "addNode":
        return { ...op, op: "removeNode" };
      case "removeNode":
        return { ...op, op: "addNode" };
      case "addEdge":
        return { ...op, op: "removeEdge" };
      case "removeEdge":
        return { ...op, op: "addEdge" };
      case "position":
        return { op: "position", id: op.id, from: op.to, to: op.from };
    }
  });
}

/** `next` folded into `top`, two moves of one drag; none when the drag ends where it began. */
function joinDrag(top: HistoryEntry, next: HistoryEntry): HistoryEntry[] {
  const span = new Map<string, { from: Point | undefined; to: Point | undefined }>();
  for (const op of [...top.ops, ...next.ops]) {
    if (op.op !== "position") continue;
    const seen = span.get(op.id); // the first move's start, even an unplaced one
    span.set(op.id, { from: seen === undefined ? op.from : seen.from, to: op.to });
  }
  const ops = [...span]
    .filter(([, { from, to }]) => !samePoint(from, to))
    .map(([id, { from, to }]): Op => ({ op: "position", id, from, to }));
  return ops.length === 0 ? [] : [{ ...next, ops, before: top.before }];
}

const sameDrag = (top: HistoryEntry | undefined, next: HistoryEntry): top is HistoryEntry =>
  top !== undefined &&
  top.kind === "move" &&
  next.kind === "move" &&
  top.gesture !== undefined &&
  top.gesture === next.gesture;

export interface Dispatched {
  readonly history: History;
  readonly effect: CommandEffect;
}

/** One command through the reducer; an edit becomes an entry and clears the redo stack. */
export function dispatch(
  history: History,
  command: GraphCommand,
  oracle: PortOracle = portOracle,
): Dispatched {
  const { state, effect, edit } = reduce(history.state, command, oracle);
  if (edit === undefined) {
    return { history: state === history.state ? history : { ...history, state }, effect };
  }
  const entry: HistoryEntry = { ...edit, before: history.state.selection, after: state.selection };
  const top = history.past[history.past.length - 1];
  const past = sameDrag(top, entry)
    ? [...history.past.slice(0, -1), ...joinDrag(top, entry)]
    : [...history.past, entry];
  return { history: { state, past: past.slice(-HISTORY_DEPTH), future: [] }, effect };
}

export interface Stepped {
  readonly history: History;
  /** The entry undone or redone (its `kind` names the operation); none at an end of the stack. */
  readonly entry: HistoryEntry | undefined;
}

export function undo(history: History): Stepped {
  const entry = history.past[history.past.length - 1];
  if (entry === undefined) return { history, entry };
  const state = withSelection(applyOps(history.state, invert(entry.ops)), entry.before);
  return {
    history: { state, past: history.past.slice(0, -1), future: [...history.future, entry] },
    entry,
  };
}

export function redo(history: History): Stepped {
  const entry = history.future[history.future.length - 1];
  if (entry === undefined) return { history, entry };
  const state = withSelection(applyOps(history.state, entry.ops), entry.after);
  return {
    history: { state, past: [...history.past, entry], future: history.future.slice(0, -1) },
    entry,
  };
}

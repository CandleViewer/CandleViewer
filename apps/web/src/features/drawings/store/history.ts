// E14-T02 (#400, BQ-07): the pure command reducer with a bounded per-symbol undo/redo history.
// One history per symbol, shared by every pane on it (D02 AD-8/AD-10), session-scoped, 100 entries
// (`26` §3.10). A new command clears redo. Undoing a delete re-creates under a NEW id from `mintId`
// with identical content (an id is unavailable for 90 days, `22`; D07 §8.2); the handle stays.
// An entry whose target is gone (removed elsewhere) is dropped and reported, never resurrected.
import type { Command, Handle, LocalDrawing, Mutation } from "./types";

export const HISTORY_LIMIT = 100;

export interface SymbolDoc {
  readonly drawings: ReadonlyMap<Handle, LocalDrawing>;
  readonly undo: readonly Command[];
  readonly redo: readonly Command[];
}

export const EMPTY_DOC: SymbolDoc = { drawings: new Map(), undo: [], redo: [] };

export type DocAction =
  | { readonly type: "do"; readonly command: Command }
  | { readonly type: "undo" }
  | { readonly type: "redo" };

export interface Step {
  readonly doc: SymbolDoc;
  readonly mutations: readonly Mutation[];
  /** The command could not apply because a target is gone (or a create's handle is taken). */
  readonly unavailable: boolean;
}

export function invert(command: Command): Command {
  switch (command.kind) {
    case "create":
      return { kind: "delete", handle: command.handle, input: command.input };
    case "delete":
      return { kind: "create", handle: command.handle, input: command.input };
    case "update":
      return {
        kind: "update",
        handle: command.handle,
        before: command.after,
        after: command.before,
      };
    case "batch":
      return { kind: "batch", commands: [...command.commands].reverse().map(invert) };
  }
}

/** Applies onto `work` (a private copy); false when any part is unavailable. */
function apply(
  command: Command,
  work: Map<Handle, LocalDrawing>,
  mintId: () => string,
  out: Mutation[],
): boolean {
  switch (command.kind) {
    case "create": {
      if (work.has(command.handle)) return false;
      const id = mintId();
      work.set(command.handle, {
        handle: command.handle,
        id,
        token: null,
        input: command.input,
        base: null,
        tag: null,
      });
      out.push({ op: "create", id, input: command.input });
      return true;
    }
    case "update": {
      const rec = work.get(command.handle);
      if (rec === undefined) return false;
      work.set(command.handle, { ...rec, input: command.after, tag: null });
      out.push({ op: "update", id: rec.id, input: command.after });
      return true;
    }
    case "delete": {
      const rec = work.get(command.handle);
      if (rec === undefined) return false;
      work.delete(command.handle);
      out.push({ op: "delete", id: rec.id });
      return true;
    }
    case "batch":
      return command.commands.every((c) => apply(c, work, mintId, out));
  }
}

const bounded = (stack: readonly Command[], next: Command): readonly Command[] =>
  stack.length >= HISTORY_LIMIT
    ? [...stack.slice(stack.length - HISTORY_LIMIT + 1), next]
    : [...stack, next];

function run(
  doc: SymbolDoc,
  command: Command,
  mintId: () => string,
): { drawings: ReadonlyMap<Handle, LocalDrawing>; mutations: Mutation[] } | null {
  const work = new Map(doc.drawings);
  const mutations: Mutation[] = [];
  return apply(command, work, mintId, mutations) ? { drawings: work, mutations } : null;
}

export function reduce(doc: SymbolDoc, action: DocAction, mintId: () => string): Step {
  if (action.type === "do") {
    const done = run(doc, action.command, mintId);
    if (done === null) return { doc, mutations: [], unavailable: true };
    return {
      doc: { drawings: done.drawings, undo: bounded(doc.undo, action.command), redo: [] },
      mutations: done.mutations,
      unavailable: false,
    };
  }
  const from = action.type === "undo" ? doc.undo : doc.redo;
  const entry = from.at(-1);
  if (entry === undefined) return { doc, mutations: [], unavailable: false };
  const rest = from.slice(0, -1);
  const done = run(doc, action.type === "undo" ? invert(entry) : entry, mintId);
  if (done === null) {
    const dropped = action.type === "undo" ? { ...doc, undo: rest } : { ...doc, redo: rest };
    return { doc: dropped, mutations: [], unavailable: true };
  }
  const next: SymbolDoc =
    action.type === "undo"
      ? { drawings: done.drawings, undo: rest, redo: [...doc.redo, entry] }
      : { drawings: done.drawings, undo: bounded(doc.undo, entry), redo: rest };
  return { doc: next, mutations: done.mutations, unavailable: false };
}

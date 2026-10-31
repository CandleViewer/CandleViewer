/**
 * The local-first edits of one list, SCR-100's and SCR-101's (E08-D07 D15, §4.3, §6.2, §6.4): each change shows at
 * once, then `PUT /watchlists/{watchlistId}` replaces the whole list against the version last read (E08-T07's
 * `If-Match`). One save is in flight at a time; the edits made meanwhile go next, as one save of the latest list. A
 * failed save rolls back to the list as last saved, with the error, and Retry sends the change again (none after a
 * refusal, a 403). `Del`'s Undo stays until a change other than a removal and restores every removal since, each in
 * its place. Each list saved goes back to the host (`onSaved`), whose next read of it carries the version the server
 * holds (C-2.12); after a conflict, Reload's list read again is adopted whole, or the change undone is saved over it
 * (SCR-101's "Overwrite with my version"). SCR-101 also renames the list: the name is one more part of the change.
 */
import type { generated } from "@candleviewer/protocol";
import { LIST_CAP } from "./copy";

export type Watchlist = generated.rest.components["schemas"]["Watchlist"];

/** A save's answer: the stored list, a version conflict (412), a taken name (409), a refusal (403), or a failure. */
export type SaveOutcome =
  | { readonly kind: "saved"; readonly list: Watchlist }
  | { readonly kind: "conflict" }
  | { readonly kind: "name_taken" }
  | { readonly kind: "refused" }
  | { readonly kind: "failed" };

/** Why a change was rolled back. */
export type SaveError = Exclude<SaveOutcome["kind"], "saved">;

/** What a save sends: the whole list; without `name` the name stays. */
export interface ListContent {
  readonly name?: string;
  readonly symbols: readonly string[];
  readonly columns: readonly string[];
}

export interface WatchlistSaver {
  /** Replaces `list` (its id and version) with `next`. */
  replace(list: Watchlist, next: ListContent): Promise<SaveOutcome>;
}

export interface Removal {
  readonly symbol: string;
  /** Its place when it was removed. */
  readonly index: number;
}

export interface EditsState {
  /** The list as last saved (or read). */
  readonly list: Watchlist;
  /** What shows: the local edits over it. */
  readonly name: string;
  readonly symbols: readonly string[];
  readonly columns: readonly string[];
  /** The removals Undo restores, oldest first. */
  readonly removed: readonly Removal[];
  readonly saving: boolean;
  /** Why the last change was rolled back; a taken name (409) names the name that was sent. */
  readonly error: null | { readonly kind: SaveError; readonly name?: string };
}

export type AddOutcome = "added" | "on-list" | "full";

export interface ListEdits {
  getState(): EditsState;
  subscribe(listener: () => void): () => void;
  remove(symbol: string): void;
  /** Restores every removal since the last other change; returns the symbols restored, in removal order. */
  undo(): readonly string[];
  /** Moves `symbol` to index `to` of the shown list. */
  move(symbol: string, to: number): void;
  add(symbol: string): AddOutcome;
  /** Appends the symbols not on the list yet, as one change, up to the cap; returns those added. */
  addAll(symbols: readonly string[]): readonly string[];
  setColumns(columns: readonly string[]): void;
  /** Names the list (SCR-101): one more change, saved with the rest. */
  rename(name: string): void;
  /** Sends the change a failed save undid, again. */
  retry(): void;
  /** The list as read again (Reload after a conflict): shown and saved against from now on; no error, no Undo. */
  adopt(list: Watchlist): void;
  /** After a conflict: the change undone, saved over `fresh`, the list as stored now ("Overwrite with my version"). */
  overwrite(fresh: Watchlist): void;
}

type Shown = Pick<EditsState, "name" | "symbols" | "columns">;

export function createListEdits(
  initial: Watchlist,
  saver: WatchlistSaver,
  onSaved: (list: Watchlist) => void = () => undefined,
): ListEdits {
  const listeners = new Set<() => void>();
  let state: EditsState = {
    list: initial,
    name: initial.name,
    symbols: initial.symbols,
    columns: initial.columns,
    removed: [],
    saving: false,
    error: null,
  };
  /** The shown state a failed save undid: Retry (or Overwrite) applies it again. */
  let undone: Shown | null = null;
  let dirty = false;

  const set = (patch: Partial<EditsState>): void => {
    state = { ...state, ...patch };
    for (const listener of [...listeners]) listener();
  };

  function save(): void {
    if (state.saving) {
      dirty = true;
      return;
    }
    dirty = false;
    const sent: ListContent = { name: state.name, symbols: state.symbols, columns: state.columns };
    set({ saving: true });
    void saver
      .replace(state.list, sent)
      .catch((): SaveOutcome => ({ kind: "failed" }))
      .then((outcome) => {
        if (outcome.kind === "saved") {
          set({ list: outcome.list, saving: false });
          onSaved(outcome.list);
          if (dirty) save();
          return;
        }
        // Rolled back to the list as last saved: the edits since are undone, the Undo run with them.
        undone = { name: state.name, symbols: state.symbols, columns: state.columns };
        dirty = false;
        set({
          name: state.list.name,
          symbols: state.list.symbols,
          columns: state.list.columns,
          removed: [],
          saving: false,
          error:
            outcome.kind === "name_taken"
              ? { kind: outcome.kind, name: sent.name ?? state.list.name }
              : { kind: outcome.kind },
        });
      });
  }

  /** A change that is not a removal ends the Undo run. */
  const change = (next: Partial<Shown>): void => {
    undone = null;
    set({ ...next, removed: [], error: null });
    save();
  };

  const adopt = (list: Watchlist): void => {
    undone = null;
    dirty = false;
    set({
      list,
      name: list.name,
      symbols: list.symbols,
      columns: list.columns,
      removed: [],
      error: null,
    });
  };

  return {
    getState: () => state,
    subscribe(listener) {
      listeners.add(listener);
      return () => void listeners.delete(listener);
    },
    remove(symbol) {
      const index = state.symbols.indexOf(symbol);
      if (index < 0) return;
      undone = null;
      set({
        symbols: state.symbols.filter((s) => s !== symbol),
        removed: [...state.removed, { symbol, index }],
        error: null,
      });
      save();
    },
    undo() {
      const removed = state.removed;
      if (removed.length === 0) return [];
      const symbols = [...state.symbols];
      for (const { symbol, index } of [...removed].reverse())
        if (!symbols.includes(symbol)) symbols.splice(Math.min(index, symbols.length), 0, symbol);
      change({ symbols });
      return removed.map((r) => r.symbol);
    },
    move(symbol, to) {
      const from = state.symbols.indexOf(symbol);
      const target = Math.min(Math.max(0, to), state.symbols.length - 1);
      if (from < 0 || from === target) return;
      const symbols = [...state.symbols];
      symbols.splice(from, 1);
      symbols.splice(target, 0, symbol);
      change({ symbols });
    },
    add(symbol) {
      if (state.symbols.includes(symbol)) return "on-list";
      if (state.symbols.length >= LIST_CAP) return "full";
      change({ symbols: [...state.symbols, symbol] });
      return "added";
    },
    addAll(symbols) {
      const held = new Set(state.symbols);
      const fresh = [...new Set(symbols)].filter((s) => !held.has(s));
      const added = fresh.slice(0, Math.max(0, LIST_CAP - state.symbols.length));
      if (added.length > 0) change({ symbols: [...state.symbols, ...added] });
      return added;
    },
    setColumns(columns) {
      change({ columns });
    },
    rename(name) {
      if (name === state.name) return;
      change({ name });
    },
    retry() {
      const again = undone;
      if (again === null || state.error?.kind === "refused") return;
      change(again);
    },
    adopt,
    overwrite(fresh) {
      const mine = undone;
      adopt(fresh);
      if (mine !== null) change(mine);
    },
  };
}

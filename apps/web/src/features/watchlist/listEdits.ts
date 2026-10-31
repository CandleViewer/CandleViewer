/**
 * SCR-100's local-first edits of one list (E08-D07 D15, §6.2, §6.4): each change shows at once, then
 * `PUT /watchlists/{watchlistId}` replaces the whole list against the version last read (E08-T07's `If-Match`). One
 * save is in flight at a time; the edits made meanwhile go next, as one save of the latest list. A failed save rolls
 * back to the list as last saved, with the error, and Retry sends the change again (none after a refusal, a 403).
 * `Del`'s Undo stays until a change other than a removal and restores every removal since, each in its place.
 */
import type { generated } from "@candleviewer/protocol";
import { LIST_CAP } from "./copy";

export type Watchlist = generated.rest.components["schemas"]["Watchlist"];

/** A save's answer: the stored list, a version conflict (412), a refusal (403), or any other failure. */
export type SaveOutcome =
  | { readonly kind: "saved"; readonly list: Watchlist }
  | { readonly kind: "conflict" }
  | { readonly kind: "refused" }
  | { readonly kind: "failed" };

export interface WatchlistSaver {
  /** Replaces `list` (its id and version) with `next`; the name stays. */
  replace(
    list: Watchlist,
    next: { readonly symbols: readonly string[]; readonly columns: readonly string[] },
  ): Promise<SaveOutcome>;
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
  readonly symbols: readonly string[];
  readonly columns: readonly string[];
  /** The removals Undo restores, oldest first. */
  readonly removed: readonly Removal[];
  readonly saving: boolean;
  readonly error: null | { readonly kind: "failed" | "conflict" | "refused" };
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
  setColumns(columns: readonly string[]): void;
  /** Sends the change a failed save undid, again. */
  retry(): void;
}

export function createListEdits(initial: Watchlist, saver: WatchlistSaver): ListEdits {
  const listeners = new Set<() => void>();
  let state: EditsState = {
    list: initial,
    symbols: initial.symbols,
    columns: initial.columns,
    removed: [],
    saving: false,
    error: null,
  };
  /** The shown state a failed save undid: Retry applies it again. */
  let undone: { readonly symbols: readonly string[]; readonly columns: readonly string[] } | null =
    null;
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
    const sent = { symbols: state.symbols, columns: state.columns };
    set({ saving: true });
    void saver
      .replace(state.list, sent)
      .catch((): SaveOutcome => ({ kind: "failed" }))
      .then((outcome) => {
        if (outcome.kind === "saved") {
          set({ list: outcome.list, saving: false });
          if (dirty) save();
          return;
        }
        // Rolled back to the list as last saved: the edits since are undone, the Undo run with them.
        undone = { symbols: state.symbols, columns: state.columns };
        dirty = false;
        set({
          symbols: state.list.symbols,
          columns: state.list.columns,
          removed: [],
          saving: false,
          error: { kind: outcome.kind },
        });
      });
  }

  /** A change that is not a removal ends the Undo run. */
  const change = (symbols: readonly string[], columns: readonly string[] = state.columns): void => {
    undone = null;
    set({ symbols, columns, removed: [], error: null });
    save();
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
      change(symbols);
      return removed.map((r) => r.symbol);
    },
    move(symbol, to) {
      const from = state.symbols.indexOf(symbol);
      const target = Math.min(Math.max(0, to), state.symbols.length - 1);
      if (from < 0 || from === target) return;
      const symbols = [...state.symbols];
      symbols.splice(from, 1);
      symbols.splice(target, 0, symbol);
      change(symbols);
    },
    add(symbol) {
      if (state.symbols.includes(symbol)) return "on-list";
      if (state.symbols.length >= LIST_CAP) return "full";
      change([...state.symbols, symbol]);
      return "added";
    },
    setColumns(columns) {
      change(state.symbols, columns);
    },
    retry() {
      const again = undone;
      if (again === null || state.error?.kind === "refused") return;
      change(again.symbols, again.columns);
    },
  };
}

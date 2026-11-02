// E14-T02 (#400): the client DrawingStore, per symbol. A plain external store read through
// `useSyncExternalStore` (no new state dependency: coordinator ruling on BQ-01, as tapeStore.ts and
// alertsStore.ts). State is replaced, never mutated: an untouched record keeps its reference
// (structural sharing), and a pane's selection is the same array until its symbol's map changes.
// Local edits apply at once (optimistic); the persistence layer (`drawingSync.ts`) subscribes to the
// mutations and writes them back through the server-side methods below. Nothing mounts this store
// yet: the engine binding is PR-B (E14-T03, #358).
import { useSyncExternalStore } from "react";
import { EMPTY_DOC, reduce, type DocAction, type SymbolDoc } from "./history";
import {
  asHandle,
  inputOf,
  type Command,
  type Drawing,
  type DrawingInput,
  type Handle,
  type LocalDrawing,
  type Mutation,
  type Notice,
  type SaveStatus,
  sameInput,
} from "./types";
import { uuidv7 } from "./uuidv7";

export interface SymbolState {
  readonly doc: SymbolDoc;
  readonly status: SaveStatus;
}

const SAVED: SaveStatus = { kind: "saved" };
const EMPTY_STATE: SymbolState = { doc: EMPTY_DOC, status: SAVED };
const NO_DRAWINGS: readonly LocalDrawing[] = [];

export type MutationListener = (symbol: string, mutations: readonly Mutation[]) => void;
export type NoticeListener = (notice: Notice) => void;

export interface DrawingStore {
  readonly subscribe: (listener: () => void) => () => void;
  readonly getSymbol: (symbol: string) => SymbolState;
  /** The drawings a pane shows: its layout's plus the symbol-wide ones, by `z_index`. Stable. */
  readonly selectPane: (symbol: string, layoutId: string | null) => readonly LocalDrawing[];
  readonly create: (input: DrawingInput) => Handle;
  /** One undoable update; a no-op patch records nothing. */
  readonly update: (symbol: string, handle: Handle, patch: Partial<DrawingInput>) => void;
  /** Applies one patch per handle as ONE history entry (a group move). */
  readonly updateMany: (
    symbol: string,
    patches: ReadonlyMap<Handle, Partial<DrawingInput>>,
  ) => void;
  /** Deletes the handles as ONE history entry (a delete-all is one undo, D07:303). */
  readonly remove: (symbol: string, handles: readonly Handle[]) => void;
  readonly undo: (symbol: string) => void;
  readonly redo: (symbol: string) => void;
  readonly onMutations: (listener: MutationListener) => () => void;
  readonly onNotice: (listener: NoticeListener) => () => void;
  readonly notify: (notice: Notice) => void;
  // Server-side writes (the persistence layer only).
  readonly tokenOf: (id: string) => string | null;
  /** A confirmed write: the token advances; `adopt` also takes the server's content. */
  readonly confirm: (drawing: Drawing, adopt: boolean) => void;
  readonly confirmDeleted: (id: string) => void;
  /** Server wins: the server's version replaces the local one, tagged "changed elsewhere". */
  readonly adopt: (drawing: Drawing) => void;
  readonly removeId: (symbol: string, id: string) => void;
  readonly remint: (symbol: string, oldId: string, newId: string) => void;
  /** Merges a fresh server list. Ids for which `busy` holds keep their local version and token. */
  readonly hydrate: (
    symbol: string,
    drawings: readonly Drawing[],
    busy: (id: string) => boolean,
  ) => void;
  readonly setStatus: (symbol: string, status: SaveStatus) => void;
}

export interface DrawingStoreDeps {
  readonly mintId?: () => string;
}

export function createDrawingStore(deps: DrawingStoreDeps = {}): DrawingStore {
  const mintId = deps.mintId ?? (() => uuidv7());
  let symbols: ReadonlyMap<string, SymbolState> = new Map();
  const versions = new Map<string, string>();
  /** Handles of locally deleted records whose delete is not yet confirmed (id -> handle), so a
   * server version adopted over a refused delete keeps the handle history knows (no duplicate). */
  const deletedHandles = new Map<string, Handle>();
  const listeners = new Set<() => void>();
  const mutationListeners = new Set<MutationListener>();
  const noticeListeners = new Set<NoticeListener>();
  const paneCache = new Map<
    string,
    { from: ReadonlyMap<Handle, LocalDrawing>; list: readonly LocalDrawing[] }
  >();

  const get = (symbol: string): SymbolState => symbols.get(symbol) ?? EMPTY_STATE;
  const commit = (symbol: string, next: SymbolState): void => {
    const copy = new Map(symbols);
    copy.set(symbol, next);
    symbols = copy;
    for (const listener of [...listeners]) listener();
  };
  const setDrawings = (symbol: string, drawings: ReadonlyMap<Handle, LocalDrawing>): void => {
    const state = get(symbol);
    commit(symbol, { ...state, doc: { ...state.doc, drawings } });
  };
  const findById = (symbol: string, id: string): LocalDrawing | undefined => {
    for (const rec of get(symbol).doc.drawings.values()) if (rec.id === id) return rec;
    return undefined;
  };
  const replaceRecord = (symbol: string, rec: LocalDrawing): void => {
    const drawings = new Map(get(symbol).doc.drawings);
    drawings.set(rec.handle, rec);
    setDrawings(symbol, drawings);
  };
  const notify = (notice: Notice): void => {
    for (const listener of [...noticeListeners]) listener(notice);
  };

  const step = (symbol: string, action: DocAction): void => {
    const state = get(symbol);
    const result = reduce(state.doc, action, mintId);
    for (const m of result.mutations) {
      if (m.op !== "delete") continue;
      for (const rec of state.doc.drawings.values()) {
        if (rec.id === m.id) deletedHandles.set(m.id, rec.handle);
      }
    }
    if (result.doc !== state.doc) commit(symbol, { ...state, doc: result.doc });
    if (result.unavailable) notify({ kind: "undo_unavailable", symbol });
    if (result.mutations.length > 0) {
      for (const listener of [...mutationListeners]) listener(symbol, result.mutations);
    }
  };
  const updateCommand = (
    symbol: string,
    handle: Handle,
    patch: Partial<DrawingInput>,
  ): Command | null => {
    const rec = get(symbol).doc.drawings.get(handle);
    if (rec === undefined) return null;
    const after: DrawingInput = { ...rec.input, ...patch };
    if (sameInput(after, rec.input)) return null;
    return { kind: "update", handle, before: rec.input, after };
  };

  return {
    subscribe: (listener) => {
      listeners.add(listener);
      return () => {
        listeners.delete(listener);
      };
    },
    getSymbol: get,
    selectPane: (symbol, layoutId) => {
      const drawings = get(symbol).doc.drawings;
      if (drawings.size === 0) return NO_DRAWINGS;
      const key = `${symbol}\u0000${layoutId ?? ""}`;
      const hit = paneCache.get(key);
      if (hit !== undefined && hit.from === drawings) return hit.list;
      const list = [...drawings.values()]
        .filter((d) => d.input.layout_id === null || d.input.layout_id === layoutId)
        .sort((a, b) => a.input.z_index - b.input.z_index);
      paneCache.set(key, { from: drawings, list });
      return list;
    },
    create: (input) => {
      const handle = asHandle(mintId());
      step(input.symbol, { type: "do", command: { kind: "create", handle, input } });
      return handle;
    },
    update: (symbol, handle, patch) => {
      const command = updateCommand(symbol, handle, patch);
      if (command !== null) step(symbol, { type: "do", command });
    },
    updateMany: (symbol, patches) => {
      const commands: Command[] = [];
      for (const [handle, patch] of patches) {
        const command = updateCommand(symbol, handle, patch);
        if (command !== null) commands.push(command);
      }
      if (commands.length > 0) step(symbol, { type: "do", command: { kind: "batch", commands } });
    },
    remove: (symbol, handles) => {
      const drawings = get(symbol).doc.drawings;
      const commands: Command[] = [];
      for (const handle of handles) {
        const rec = drawings.get(handle);
        if (rec !== undefined) commands.push({ kind: "delete", handle, input: rec.input });
      }
      if (commands.length === 0) return;
      const command: Command =
        commands.length === 1 && commands[0] !== undefined
          ? commands[0]
          : { kind: "batch", commands };
      step(symbol, { type: "do", command });
    },
    undo: (symbol) => step(symbol, { type: "undo" }),
    redo: (symbol) => step(symbol, { type: "redo" }),
    onMutations: (listener) => {
      mutationListeners.add(listener);
      return () => {
        mutationListeners.delete(listener);
      };
    },
    onNotice: (listener) => {
      noticeListeners.add(listener);
      return () => {
        noticeListeners.delete(listener);
      };
    },
    notify,
    tokenOf: (id) => versions.get(id) ?? null,
    confirm: (drawing, adopt) => {
      versions.set(drawing.id, drawing.updated_at);
      const rec = findById(drawing.symbol, drawing.id);
      if (rec === undefined) return;
      const base = inputOf(drawing);
      replaceRecord(drawing.symbol, {
        ...rec,
        token: drawing.updated_at,
        base,
        input: adopt ? base : rec.input,
      });
    },
    confirmDeleted: (id) => {
      versions.delete(id);
      deletedHandles.delete(id);
    },
    adopt: (drawing) => {
      versions.set(drawing.id, drawing.updated_at);
      const base = inputOf(drawing);
      const rec = findById(drawing.symbol, drawing.id);
      const gone = deletedHandles.get(drawing.id);
      // An undo may already have re-created that handle under a new id; then both objects stay.
      const free = gone !== undefined && !get(drawing.symbol).doc.drawings.has(gone);
      const handle = rec?.handle ?? (free ? gone : asHandle(drawing.id));
      deletedHandles.delete(drawing.id);
      replaceRecord(drawing.symbol, {
        handle,
        id: drawing.id,
        token: drawing.updated_at,
        input: base,
        base,
        tag: "conflict",
      });
    },
    removeId: (symbol, id) => {
      versions.delete(id);
      deletedHandles.delete(id);
      const rec = findById(symbol, id);
      if (rec === undefined) return;
      const drawings = new Map(get(symbol).doc.drawings);
      drawings.delete(rec.handle);
      setDrawings(symbol, drawings);
    },
    remint: (symbol, oldId, newId) => {
      const rec = findById(symbol, oldId);
      if (rec !== undefined) replaceRecord(symbol, { ...rec, id: newId, token: null, base: null });
    },
    hydrate: (symbol, list, busy) => {
      const current = get(symbol).doc.drawings;
      const byId = new Map<string, LocalDrawing>();
      for (const rec of current.values()) byId.set(rec.id, rec);
      const next = new Map<Handle, LocalDrawing>();
      const seen = new Set<string>();
      for (const d of list) {
        seen.add(d.id);
        const rec = byId.get(d.id);
        if (rec !== undefined && busy(d.id)) {
          next.set(rec.handle, rec);
          continue;
        }
        // Busy with no local record is a local delete still pending or in flight: never re-add it.
        if (rec === undefined && busy(d.id)) continue;
        // A list answered before a later commit is older than what we hold: never revert to it.
        // Tokens are fixed-width UTC strings that strictly increase, so string order is time order.
        const held = rec?.token ?? null;
        if (rec !== undefined && held !== null && d.updated_at < held) {
          next.set(rec.handle, rec);
          continue;
        }
        versions.set(d.id, d.updated_at);
        const base = inputOf(d);
        const same = rec !== undefined && rec.token === d.updated_at && rec.tag === null;
        next.set(
          rec?.handle ?? asHandle(d.id),
          same
            ? rec
            : {
                handle: rec?.handle ?? asHandle(d.id),
                id: d.id,
                token: d.updated_at,
                input: base,
                base,
                tag: null,
              },
        );
      }
      // Local rows the server does not list survive only while unconfirmed or busy.
      for (const rec of current.values()) {
        if (!seen.has(rec.id) && (rec.token === null || busy(rec.id))) next.set(rec.handle, rec);
        else if (!seen.has(rec.id)) versions.delete(rec.id);
      }
      setDrawings(symbol, next);
    },
    setStatus: (symbol, status) => {
      const state = get(symbol);
      const prev = state.status;
      if (prev.kind === status.kind && JSON.stringify(prev) === JSON.stringify(status)) return;
      commit(symbol, { ...state, status });
    },
  };
}

export function usePaneDrawings(
  store: DrawingStore,
  symbol: string,
  layoutId: string | null,
): readonly LocalDrawing[] {
  const read = (): readonly LocalDrawing[] => store.selectPane(symbol, layoutId);
  return useSyncExternalStore(store.subscribe, read, read);
}

export function useSaveStatus(store: DrawingStore, symbol: string): SaveStatus {
  const read = (): SaveStatus => store.getSymbol(symbol).status;
  return useSyncExternalStore(store.subscribe, read, read);
}

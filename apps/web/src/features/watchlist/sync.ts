/**
 * What SCR-101 tells SCR-100 (E08-S08): each list it stores, created or saved (`stored`, with the server's version),
 * and its closing (`reread`), after which the panel reads the lists again (a deleted list goes then). The panel keeps
 * each view on the version the server holds, so it never shows a stale list or saves against a stale version
 * (C-2.12; #4702 PR (b)'s CR-4702B-01 path, reused). A plain channel: no React state, no persistence.
 */
import type { Watchlist } from "./listEdits";

export type ListChange =
  { readonly kind: "stored"; readonly list: Watchlist } | { readonly kind: "reread" };

export interface WatchlistSync {
  publish(change: ListChange): void;
  subscribe(listener: (change: ListChange) => void): () => void;
}

export function createWatchlistSync(): WatchlistSync {
  const listeners = new Set<(change: ListChange) => void>();
  return {
    publish(change) {
      for (const listener of [...listeners]) listener(change);
    },
    subscribe(listener) {
      listeners.add(listener);
      return () => void listeners.delete(listener);
    },
  };
}

/**
 * `lists` with `list` in: in its place when it is a newer version (the server's version only goes up), at the end
 * when it is new; `lists` itself when nothing changes.
 */
export function upsertList(lists: readonly Watchlist[], list: Watchlist): readonly Watchlist[] {
  const at = lists.findIndex((l) => l.id === list.id);
  if (at < 0) return [...lists, list];
  const held = lists[at];
  if (held === undefined || list.version <= held.version) return lists;
  return lists.map((l, i) => (i === at ? list : l));
}

/**
 * The dock's working tree (E15-T02 BQ-12): a `useSyncExternalStore` store, the shell's pattern (the
 * app has no Zustand). Every change goes through `apply`, which runs one `@candleviewer/dock`
 * operation, times it, publishes once, emits `layoutChanged` and says one polite summary: one per
 * commit, never per pointer move. A refused operation (`DockError`) changes nothing. Nothing is
 * persisted here (E15-S03 owns writes).
 */
import { useSyncExternalStore } from "react";
import {
  counterMinter,
  isDockError,
  layoutChanged,
  type DockTree,
  type IdMinter,
  type LayoutChanged,
  type LayoutOp,
  type OpContext,
  type Size,
} from "@candleviewer/dock";

export interface DockStoreOptions {
  readonly tree: DockTree;
  readonly mint?: IdMinter;
  readonly viewport?: Size;
  /** The app's one polite region (CMP-081: one summary per mutation). */
  readonly announce?: (text: string) => void;
  /** Forwarded to analytics as `layout.panel_moved`, `layout.preset_applied`, ... */
  readonly onLayoutChanged?: (event: LayoutChanged) => void;
  readonly now?: () => number;
}

export interface DockStore {
  getTree(): DockTree;
  subscribe(listener: () => void): () => void;
  /**
   * Runs `op` on the current tree; `summary` is the polite announcement (E15-D15 SR-01..SR-10).
   * Returns false, and changes nothing, when the operation is refused.
   */
  apply(op: LayoutOp, run: (tree: DockTree, ctx: OpContext) => DockTree, summary?: string): boolean;
  /** The dock's px size, so operations keep panels at their minimums. */
  setViewport(size: Size): void;
  /** The node and pane id minter, shared with `fromLayout` and new panes. */
  readonly mint: IdMinter;
}

export function createDockStore(options: DockStoreOptions): DockStore {
  let tree = options.tree;
  let viewport = options.viewport;
  const mint = options.mint ?? counterMinter("dock-");
  const now = options.now ?? (() => performance.now());
  const listeners = new Set<() => void>();
  return {
    mint,
    getTree: () => tree,
    subscribe(listener) {
      listeners.add(listener);
      return () => listeners.delete(listener);
    },
    apply(op, run, summary) {
      const started = now();
      let next: DockTree;
      try {
        next = run(tree, viewport === undefined ? { mint } : { mint, viewport });
      } catch (error) {
        if (isDockError(error)) return false;
        throw error;
      }
      if (next === tree) return true;
      tree = next;
      for (const listener of [...listeners]) listener();
      options.onLayoutChanged?.(layoutChanged(op, tree, now() - started));
      if (summary !== undefined) options.announce?.(summary);
      return true;
    },
    setViewport(size) {
      viewport = size;
    },
  };
}

export function useDockTree(store: DockStore): DockTree {
  return useSyncExternalStore(store.subscribe, store.getTree);
}

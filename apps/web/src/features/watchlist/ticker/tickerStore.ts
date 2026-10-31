/**
 * The ticker client's per-symbol stores, its "atoms" (`.claude/rules/30-frontend-react.md`: transport → stream →
 * coalesced → atom): one entry per symbol, written once per coalesced flush (4 Hz) and read by the one row that draws
 * the symbol, so a frame never becomes React state and a row re-renders only when its own symbol changed. A plain
 * external store (`subscribe` / `get`), as the app's other stores are; no dependency.
 */
import { tickerValues, type TickerItem, type TickerValues } from "./tickerValues";

/** §14.8: a server-stale item's state is older than this, so one seen first is at least this old already. */
export const SERVER_STALE_AFTER_MS = 5_000;

export interface TickerEntry {
  readonly values: TickerValues;
  /** When the client read the symbol's last item (its clock). */
  readonly receivedAtMs: number;
  /**
   * When the client read the symbol's last fresh item: a server-stale item (§14.8 `stale`) carries the last values but
   * no new freshness, so the row's age keeps counting from here (E08-D07 D1).
   */
  readonly freshAtMs: number;
}

export interface TickerStore {
  get(symbol: string): TickerEntry | undefined;
  /** The listener hears each flush that changed `symbol`, once. */
  subscribe(symbol: string, listener: () => void): () => void;
  /** The listener hears each flush that changed any symbol, once, with the symbols it changed. */
  subscribeAll(listener: (changed: ReadonlySet<string>) => void): () => void;
  /** One flush: the items of every frame drained since the last, in order (the latest of a symbol wins). */
  apply(items: readonly TickerItem[], nowMs: number): void;
  /** Symbols that left the live set: their values are forgotten, so a row entering again initialises (D7). */
  drop(symbols: Iterable<string>): void;
}

export function createTickerStore(): TickerStore {
  const entries = new Map<string, TickerEntry>();
  const listeners = new Map<string, Set<() => void>>();
  const all = new Set<(changed: ReadonlySet<string>) => void>();

  const tell = (changed: ReadonlySet<string>): void => {
    if (changed.size === 0) return;
    for (const symbol of changed)
      for (const listener of [...(listeners.get(symbol) ?? [])]) listener();
    for (const listener of [...all]) listener(changed);
  };

  return {
    get: (symbol) => entries.get(symbol),
    subscribe(symbol, listener) {
      const set = listeners.get(symbol) ?? new Set<() => void>();
      set.add(listener);
      listeners.set(symbol, set);
      return () => {
        set.delete(listener);
        if (set.size === 0) listeners.delete(symbol);
      };
    },
    subscribeAll(listener) {
      all.add(listener);
      return () => void all.delete(listener);
    },
    apply(items, nowMs) {
      const changed = new Set<string>();
      for (const item of items) {
        const values = tickerValues(item);
        if (values === null) continue; // no value is better than a wrong one
        const before = entries.get(values.symbol);
        const freshAtMs = values.serverStale
          ? (before?.freshAtMs ?? nowMs - SERVER_STALE_AFTER_MS)
          : nowMs;
        entries.set(values.symbol, { values, receivedAtMs: nowMs, freshAtMs });
        changed.add(values.symbol);
      }
      tell(changed);
    },
    drop(symbols) {
      const changed = new Set<string>();
      for (const symbol of symbols) if (entries.delete(symbol)) changed.add(symbol);
      tell(changed);
    },
  };
}

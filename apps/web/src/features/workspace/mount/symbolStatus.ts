/**
 * The delisted check at pane resolve (E15-S03 #476): each symbol a restored pane names is looked up
 * once against E08's catalogue (`lookupSymbol`, `GET /instruments/{symbol}`), shared across panes.
 * A 404, or status `Closed`, is `delisted`; no usable answer is `unchecked` and the pane mounts as
 * usual. Presentation only: the server validates every write.
 */
import { lookupSymbol, type Lookup } from "../../symbol-search/instrumentIndex";

export type SymbolState = "checking" | "listed" | "delisted" | "unchecked";
export type LookupFn = (symbol: string, signal: AbortSignal) => Promise<Lookup>;

export interface SymbolStatus {
  /** `checking` until the symbol's lookup settles; pure, so a render may read it. */
  get(symbol: string): SymbolState;
  /** Starts the symbol's lookup unless one has run or runs (from an effect, never a render). */
  check(symbol: string): void;
  subscribe(listener: () => void): () => void;
  /** Aborts the lookups in flight; their answers are dropped. */
  stop(): void;
}

const stateOf = (a: Lookup): SymbolState =>
  a.kind === "not_listed" || (a.kind === "status" && a.instrument.status === "Closed")
    ? "delisted"
    : a.kind === "unchecked"
      ? "unchecked"
      : "listed";

export function createSymbolStatus(lookup: LookupFn = lookupSymbol): SymbolStatus {
  const states = new Map<string, SymbolState>();
  const listeners = new Set<() => void>();
  const abort = new AbortController();
  const settle = (symbol: string, state: SymbolState): void => {
    if (abort.signal.aborted) return;
    states.set(symbol, state);
    for (const listener of [...listeners]) listener();
  };
  return {
    get: (symbol) => states.get(symbol) ?? "checking",
    check(symbol) {
      if (states.has(symbol) || abort.signal.aborted) return;
      states.set(symbol, "checking");
      lookup(symbol, abort.signal).then(
        (answer) => settle(symbol, stateOf(answer)),
        () => settle(symbol, "unchecked"),
      );
    },
    subscribe(listener) {
      listeners.add(listener);
      return () => listeners.delete(listener);
    },
    stop: () => abort.abort(),
  };
}

/**
 * The symbol-search runtime (E08-S09; E08-D05 §1, §3, D-9, D-10): the instrument index the shell starts, the
 * session's Recent symbols, SCR-102's open state and the opener a workspace registers, in one external store.
 */
import { useSyncExternalStore, type RefObject } from "react";
import { getShellState, subscribeShellState } from "../../shell/bootstrap/store";
import { createInstrumentIndex, type InstrumentIndex } from "./instrumentIndex";

/** The pane a commit changes (D-10): the last-focused symbol-bound panel in this window. */
export interface SymbolTarget {
  readonly pane: string; // "Chart 1"
  readonly symbol: string;
  readonly interval: string; // "1m", the chip's
  readonly intervalWords: string; // "1 minute", the spoken
  /** CMP-229 armed on the pane: the chip's ARMED pill; the commit disarms it (D-10, E30-D02). */
  readonly armed: boolean;
}

/**
 * What a workspace registers (E15 places a new chart, E12-S11 switches one): the target, or `null` ("Opens a new
 * chart"), and the symbol-selection event. With none, nothing can be committed, so SCR-102 never opens.
 */
export interface SymbolOpener {
  readonly target: SymbolTarget | null;
  readonly open: (symbol: string, where: "target" | "new-chart") => void;
  /** The target panel, where SCR-102 returns focus when its trigger is gone (E08-D05 §9.2). */
  readonly panel?: RefObject<HTMLElement | null>;
}

export interface SymbolSearchState {
  readonly index: InstrumentIndex | null;
  /** Newest first, at most 8, this session only (D-9's fallback, Q6). */
  readonly recent: readonly string[];
  readonly open: boolean;
  /** Openings so far: each one starts with an empty query. */
  readonly opened: number;
  readonly opener: SymbolOpener | null;
}

const EMPTY: SymbolSearchState = { index: null, recent: [], open: false, opened: 0, opener: null };
let state = EMPTY;
const listeners = new Set<() => void>();
const set = (patch: Partial<SymbolSearchState>): void => {
  state = { ...state, ...patch };
  for (const listener of [...listeners]) listener();
};
const subscribe = (listener: () => void): (() => void) => {
  listeners.add(listener);
  return () => void listeners.delete(listener);
};

export const getSymbolSearchState = (): SymbolSearchState => state;

/** One stored field: the selector returns a value the store holds, never a new object. */
export const useSymbolSearch = <T>(select: (current: SymbolSearchState) => T): T =>
  useSyncExternalStore(subscribe, () => select(state));

/**
 * `startShell`'s: the index reads once `/me` has answered (the route needs the session) and a workspace has bound an
 * opener, since nothing can show the list before one: then hourly, whatever the openers do (E08-D05 §3).
 */
export function startSymbolSearch(index: InstrumentIndex = createInstrumentIndex()): () => void {
  set({ index });
  let started = false;
  const sync = (): void => {
    if (started || getShellState().me === null || state.opener === null) return;
    started = true;
    index.start();
  };
  const unsubscribe = [subscribeShellState(sync), subscribe(sync)];
  sync();
  return () => {
    for (const off of unsubscribe) off();
    index.stop();
    if (state.index === index) set({ index: null, open: false });
  };
}

export function openSymbolSearch(): void {
  if (!state.open && state.index !== null && state.opener !== null)
    set({ open: true, opened: state.opened + 1 });
}

export function closeSymbolSearch(): void {
  if (state.open) set({ open: false });
}

export function rememberSymbol(symbol: string): void {
  set({ recent: [symbol, ...state.recent.filter((s) => s !== symbol)].slice(0, 8) });
}

/** A workspace registers or replaces its opener; `null` withdraws it and closes SCR-102. */
export function setSymbolOpener(opener: SymbolOpener | null): void {
  set(opener === null ? { opener, open: false } : { opener });
}

/** Tests: the empty store. */
export function resetSymbolSearch(): void {
  state.index?.stop();
  set(EMPTY);
}

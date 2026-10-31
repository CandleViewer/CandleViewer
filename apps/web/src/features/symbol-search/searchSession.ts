/**
 * The symbol-search runtime (E08-S09; E08-D05 §1, §3, D-9, D-10): the instrument index the shell starts, the
 * session's Recent symbols and lookups, SCR-102's open state, the opener a workspace registers and SCR-103's port, in
 * one external store.
 */
import { useEffect, useMemo, useState, useSyncExternalStore, type RefObject } from "react";
import { getShellState, subscribeShellState } from "../../shell/bootstrap/store";
import {
  createInstrumentIndex,
  lookupSymbol,
  type IndexSnapshot,
  type InstrumentIndex,
} from "./instrumentIndex";
import { createRevisionReread, type RevisionReread } from "./revisionReread";

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
  /**
   * The target panel, where SCR-102 returns focus when its trigger is gone (E08-D05 §9.2). It must take programmatic
   * focus (`tabIndex={-1}` at least): a panel that cannot leaves focus on the page.
   */
  readonly panel?: RefObject<HTMLElement | null>;
}

/** SCR-103's port (E08-S10): "View symbol info" shows once a host registers it. */
export interface SymbolInfoPort {
  readonly open: (symbol: string, from: { readonly source: "scr-102" | "scr-041" }) => void;
}

export interface SymbolSearchState {
  /**
   * In the store from the shell's start, but read only once a workspace binds the first opener (C's absence ruling):
   * `index !== null` does not mean it runs. A host that shows the list reads `useRunningIndex()`.
   */
  readonly index: InstrumentIndex | null;
  /** The index has started: it reads now, then hourly (E08-D05 §3). */
  readonly running: boolean;
  /** Newest first, at most 8, this session only (D-9's fallback, Q6). */
  readonly recent: readonly string[];
  readonly open: boolean;
  /** Openings so far: each one starts with an empty query. */
  readonly opened: number;
  readonly opener: SymbolOpener | null;
  /** Session lookups with no usable answer (§3 row 2): their Recent rows say so. */
  readonly unchecked: readonly string[];
  readonly info: SymbolInfoPort | null;
}

const EMPTY: SymbolSearchState = {
  index: null,
  running: false,
  recent: [],
  open: false,
  opened: 0,
  opener: null,
  unchecked: [],
  info: null,
};
let state = EMPTY;
/** The live session's read of the list on an `instrument_revision` (E08-S09); `null` outside `startSymbolSearch`'s life. */
let revisions: RevisionReread | null = null;
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

/** The index once it runs, else `null` (CR-CD-01): one reading of "running" for what shows the list and what re-reads it. */
const runningIndex = (s: SymbolSearchState): InstrumentIndex | null => (s.running ? s.index : null);

/** The shell's index once it runs, else `null`: what SCR-041's host passes (CR-CD-01). */
export const useRunningIndex = (): InstrumentIndex | null => useSymbolSearch(runningIndex);

/**
 * `startShell`'s: the index reads once `/me` has answered (the route needs the session) and a workspace has bound an
 * opener, since nothing can show the list before one: then hourly, whatever the openers do (E08-D05 §3).
 */
export function startSymbolSearch(index: InstrumentIndex = createInstrumentIndex()): () => void {
  set({ index });
  const own = createRevisionReread(() => runningIndex(state));
  revisions = own;
  let started = false;
  const sync = (): void => {
    if (started || getShellState().me === null || state.opener === null) return;
    started = true;
    index.start();
    set({ running: true });
  };
  const unsubscribe = [subscribeShellState(sync), subscribe(sync)];
  sync();
  return () => {
    for (const off of unsubscribe) off();
    own.stop();
    if (revisions === own) revisions = null;
    index.stop();
    if (state.index === index) set({ index: null, running: false, open: false });
  };
}

/**
 * The shell's WS client tells of each snapshot whose reason is `instrument_revision` (23 §7.4), with its topic: the list is
 * read again, once for a burst of them and only while the index runs (`revisionReread.ts`, E08-D05 §3).
 */
export function noteInstrumentRevision(channel: string): void {
  revisions?.note(channel);
}

/** SCR-102 can open: the index is in the store and a workspace has bound an opener (`/`'s `validWhen`). */
export const canOpenSymbolSearch = (): boolean => state.index !== null && state.opener !== null;

/** SCR-102's way in: the TopBar trigger, `/` (`global.symbol_search`, #305), later the palette's "Search symbols". */
export function openSymbolSearch(): void {
  if (!state.open && canOpenSymbolSearch()) set({ open: true, opened: state.opened + 1 });
}

export function closeSymbolSearch(): void {
  if (state.open) set({ open: false });
}

export function rememberSymbol(symbol: string): void {
  set({ recent: [symbol, ...state.recent.filter((s) => s !== symbol)].slice(0, 8) });
}

/** §6.3's "Remove from recent". */
export function forgetSymbol(symbol: string): void {
  set({ recent: state.recent.filter((s) => s !== symbol) });
}

/** SCR-103's host registers its port; `null` withdraws it, and "View symbol info" with it. */
export function setSymbolInfo(port: SymbolInfoPort | null): void {
  set({ info: port });
}

/** The session lookups in flight: each runs to its answer (at most 10 s), whatever mounts or unmounts meanwhile. */
const looking = new Set<string>();

/**
 * §3 row 2: a Recent, Favourite or current symbol missing from the Trading listing is looked up once a session, one at
 * a time, while a list is in memory. An answer joins the index's caches (`learn`: the status rule's, or the 404s'),
 * which starts the next; one with no usable answer is kept here, so its row says "Couldn't check Bybit for X just now.".
 */
export function useSessionLookups(
  index: InstrumentIndex,
  snapshot: IndexSnapshot,
  symbols: readonly string[],
): void {
  const unchecked = useSymbolSearch((s) => s.unchecked);
  const wanted = symbols.join(" ");
  const next = useMemo(() => {
    if (snapshot.phase !== "ready") return null;
    const seen = new Set([...snapshot.entries, ...snapshot.known].map((e) => e.symbol));
    for (const symbol of [...snapshot.unlisted, ...unchecked]) seen.add(symbol);
    return wanted.split(" ").find((symbol) => symbol !== "" && !seen.has(symbol)) ?? null;
  }, [snapshot, unchecked, wanted]);
  useEffect(() => {
    if (next === null || looking.has(next)) return;
    looking.add(next);
    void lookupSymbol(next, new AbortController().signal).then((answer) => {
      looking.delete(next);
      if (answer.kind !== "unchecked") index.learn(answer);
      else set({ unchecked: [...state.unchecked, next] });
    });
  }, [index, next]);
}

/**
 * §6.2 Refreshing: the snapshot a surface ranks. A re-read's list replaces the shown one only at the next keystroke,
 * so the rows and the active option stay put; any other change (a first list, a lookup's answer) shows at once.
 */
export function useHeldSnapshot(live: IndexSnapshot, query: string): IndexSnapshot {
  const [held, setHeld] = useState({ query, snapshot: live });
  const { phase, loadedAt } = held.snapshot;
  const reread =
    held.query === query &&
    phase === "ready" &&
    live.phase === "ready" &&
    loadedAt !== live.loadedAt;
  if (!reread && (held.query !== query || held.snapshot !== live))
    setHeld({ query, snapshot: live });
  return useMemo(
    () => (reread ? { ...live, entries: held.snapshot.entries } : live),
    [reread, live, held],
  );
}

/**
 * When the snapshot `live` arrived (ms): the waits and ages it names count from here, so no sentence ticks while the
 * user types. A surface passes it to `waitS` and to `searchView`.
 */
export function useArrival(live: IndexSnapshot): number {
  const [arrival, setArrival] = useState(() => ({ snapshot: live, at: Date.now() }));
  if (arrival.snapshot !== live) setArrival({ snapshot: live, at: Date.now() });
  return arrival.at;
}

/** A workspace registers or replaces its opener; `null` withdraws it and closes SCR-102. */
export function setSymbolOpener(opener: SymbolOpener | null): void {
  set(opener === null ? { opener, open: false } : { opener });
}

/** Tests: the empty store. */
export function resetSymbolSearch(): void {
  state.index?.stop();
  revisions?.stop();
  revisions = null; // the stopped handle goes with it: nothing is told to it
  looking.clear();
  set(EMPTY);
}

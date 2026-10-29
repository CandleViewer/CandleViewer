/**
 * "Checking a symbol" (E08-D05 §3, §6.2, §12.2): with a list in memory, a settled query that ranks
 * nothing and names nothing known is looked up (`lookupSymbol`: the query plus `USDT` when absent) after
 * a 300 ms rest, one lookup in flight; a newer query aborts it. The answer feeds the index (`learn`):
 * a Trading symbol joins the list, any other the status rule's cache, a 404 the not-listed cache.
 */
import { SYSTEM_CLOCK, lookupSymbol, type Clock, type Lookup } from "./instrumentIndex";
import { normaliseQuery, rankSymbols, type Instrument, type RankContext } from "./ranking";

const REST_MS = 300;
/** "Check again" is T2 (`search.check_cooldown`) this long after a check. */
const COOLDOWN_MS = 60_000;
/** `22`'s `Symbol` and the shipped 4–20 rule, with 3–16 characters before `USDT` (within both). */
const CHECKABLE = /^[A-Z0-9]{3,16}USDT$/;

/** The symbol a query may check, or `null` (V10: `usdt` is never checked). */
export function checkableSymbol(query: string): string | null {
  const normalised = normaliseQuery(query);
  const symbol = normalised.endsWith("USDT") ? normalised : `${normalised}USDT`;
  return CHECKABLE.test(symbol) ? symbol : null;
}

export interface CheckSnapshot {
  /**
   * `waiting`: the 300 ms rest; `checking`: "Checking Bybit for X…"; then the lookup's kind:
   * `listed`, `status`, `not_listed` (No matches) or `unchecked` ("Couldn't check Bybit for X just now.").
   */
  readonly phase: "idle" | "waiting" | "checking" | Lookup["kind"];
  readonly symbol: string | null;
  /** The answer, for `listed` and `status`. */
  readonly instrument: Instrument | null;
  /** When the last check settled (the clock's ms): "Checked with the server at 13:02 UTC." */
  readonly checkedAt: number | null;
  readonly coolingDown: boolean;
}

/** The index the check reads (its list and caches) and feeds; `InstrumentIndex` is one. */
export interface CheckIndex {
  readonly getSnapshot: () => RankContext;
  readonly learn: (answer: Lookup) => void;
}

export interface SymbolCheck {
  readonly subscribe: (listener: () => void) => () => void;
  readonly getSnapshot: () => CheckSnapshot;
  /** The settled query; one that ranks, names a known symbol or finds no list cancels the check. */
  readonly request: (query: string) => void;
  /** "Check again": the same symbol, at once; inert while waiting, checking or cooling down. */
  readonly checkAgain: () => void;
  /** Final: clears the timers and aborts the lookup in flight, whose answer is dropped. */
  readonly stop: () => void;
}

const IDLE: CheckSnapshot = {
  phase: "idle",
  symbol: null,
  instrument: null,
  checkedAt: null,
  coolingDown: false,
};

export function createSymbolCheck(index: CheckIndex, clock: Clock = SYSTEM_CLOCK): SymbolCheck {
  const listeners = new Set<() => void>();
  let snap = IDLE;
  let stopped = false;
  let rest: unknown = null;
  let cool: unknown = null;
  let controller: AbortController | null = null;

  const set = (patch: Partial<CheckSnapshot>): void => {
    snap = { ...snap, ...patch };
    for (const listener of listeners) {
      try {
        listener();
      } catch (error) {
        // A subscriber's own failure is raised on its own, as `lib/ws` does: the others are
        // still told, and the check goes on.
        clock.queueMicrotask(() => {
          throw error;
        });
      }
    }
  };
  const cancel = (): void => {
    if (rest !== null) clock.clearTimeout(rest);
    rest = null;
    controller?.abort();
    controller = null;
  };

  async function run(symbol: string): Promise<void> {
    const own = new AbortController();
    controller = own;
    set({ phase: "checking", symbol, instrument: null });
    const answer = await lookupSymbol(symbol, own.signal, clock);
    if (controller !== own) return; // superseded or stopped
    controller = null;
    index.learn(answer);
    if (cool !== null) clock.clearTimeout(cool);
    cool = clock.setTimeout(() => {
      cool = null;
      set({ coolingDown: false });
    }, COOLDOWN_MS);
    const instrument = "instrument" in answer ? answer.instrument : null;
    set({ phase: answer.kind, instrument, checkedAt: clock.now(), coolingDown: true });
  }

  return {
    subscribe(listener) {
      listeners.add(listener);
      return () => {
        listeners.delete(listener);
      };
    },
    getSnapshot: () => snap,
    request(query) {
      if (stopped) return;
      // §6.2: only with a list in memory, for a query that ranks nothing and names nothing known.
      const none = rankSymbols(query, index.getSnapshot()).kind === "none";
      const symbol = none ? checkableSymbol(query) : null;
      if (symbol !== null && symbol === snap.symbol) return; // the same query: nothing restarts
      cancel();
      if (symbol === null) {
        if (snap.phase !== "idle") set({ phase: "idle", symbol: null, instrument: null });
        return;
      }
      set({ phase: "waiting", symbol, instrument: null });
      rest = clock.setTimeout(() => {
        rest = null;
        void run(symbol);
      }, REST_MS);
    },
    checkAgain() {
      const { phase, symbol, coolingDown } = snap;
      const busy = phase === "waiting" || phase === "checking";
      if (stopped || symbol === null || coolingDown || busy) return;
      void run(symbol);
    },
    stop() {
      stopped = true;
      cancel();
      if (cool !== null) clock.clearTimeout(cool);
      cool = null;
    },
  };
}

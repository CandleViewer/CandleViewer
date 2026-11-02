/**
 * An amend's steps (E29-S02 #912, PR3a): `GET /instruments/{symbol}`'s `tick_size`, `qty_step` and
 * `min_order_qty`, read through symbol search's `lookupSymbol` (its 10 s deadline, its `Symbol`
 * rule and its strict reader; no second client) and kept per symbol for the session, at most
 * `MAX_SYMBOLS` (C-2.18, the oldest forgotten first).
 *
 * A step is never guessed (CMP-100's editor throws on a step it cannot use): until a lookup
 * answers with positive decimals, the symbol has none and its Edit is T2 (`no_step`). `get` only
 * reads; `load` asks once, never while a lookup is in flight, and after a failure only once
 * `RETRY_MS` has passed, so a render loop cannot hammer the route.
 */
import { lookupSymbol, type Lookup } from "../../symbol-search/instrumentIndex";
import { parseDecimal } from "../model/decimal";

export interface InstrumentSteps {
  /** The price and trigger step. */
  readonly tickSize: string;
  /** The quantity step (one lot). */
  readonly qtyStep: string;
  /** The least quantity, when the instrument names one. */
  readonly minOrderQty: string | null;
}

export interface StepsCache {
  /** The symbol's steps, or `null` until a lookup gave them. */
  get(symbol: string): InstrumentSteps | null;
  /** Asks for the symbol's steps unless held, in flight, or failed less than `RETRY_MS` ago. */
  load(symbol: string): void;
  subscribe(listener: () => void): () => void;
  /** Bumped each time a symbol's steps land. */
  getVersion(): number;
  /** Aborts the lookups in flight; nothing lands after it. */
  stop(): void;
}

export interface StepsCacheOptions {
  readonly lookup?: ((symbol: string, signal: AbortSignal) => Promise<Lookup>) | undefined;
  /** Monotonic ms for the retry wait; defaults to `performance.now`. */
  readonly now?: (() => number) | undefined;
  readonly max?: number | undefined;
}

export const MAX_SYMBOLS = 64;
/** A failed lookup is asked again after this long, on the next `load`. */
export const RETRY_MS = 30_000;

const positive = (text: unknown): string | null => {
  const parsed = parseDecimal(text);
  return parsed !== null && parsed.units > 0n && typeof text === "string" ? text : null;
};

/** A lookup's steps: an instrument whose tick and lot are positive decimals, else none. */
export function stepsOf(answer: Lookup): InstrumentSteps | null {
  if (answer.kind !== "listed" && answer.kind !== "status") return null;
  const tickSize = positive(answer.instrument.tick_size);
  const qtyStep = positive(answer.instrument.qty_step);
  if (tickSize === null || qtyStep === null) return null;
  return { tickSize, qtyStep, minOrderQty: positive(answer.instrument.min_order_qty) };
}

/** Drops the oldest keys past `max` (a `Map` keeps insertion order). */
function bound<V>(map: Map<string, V>, max: number): void {
  while (map.size > max) {
    const oldest = map.keys().next();
    if (oldest.done === true) return;
    map.delete(oldest.value);
  }
}

export function createStepsCache(options: StepsCacheOptions = {}): StepsCache {
  const lookup = options.lookup ?? lookupSymbol;
  const now = options.now ?? ((): number => performance.now());
  const max = options.max ?? MAX_SYMBOLS;
  const known = new Map<string, InstrumentSteps>();
  const failedAt = new Map<string, number>();
  const asking = new Set<string>();
  const listeners = new Set<() => void>();
  const abort = new AbortController();
  let version = 0;

  function land(symbol: string, steps: InstrumentSteps | null): void {
    asking.delete(symbol);
    if (abort.signal.aborted) return;
    if (steps === null) {
      failedAt.delete(symbol);
      failedAt.set(symbol, now());
      bound(failedAt, max);
      return;
    }
    failedAt.delete(symbol);
    known.delete(symbol);
    known.set(symbol, steps);
    bound(known, max);
    version += 1;
    for (const listener of [...listeners]) listener();
  }

  return {
    get: (symbol) => known.get(symbol) ?? null,
    load(symbol) {
      if (known.has(symbol) || asking.has(symbol) || abort.signal.aborted) return;
      const failed = failedAt.get(symbol);
      if (failed !== undefined && now() - failed < RETRY_MS) return;
      asking.add(symbol);
      void lookup(symbol, abort.signal).then(
        (answer) => land(symbol, stepsOf(answer)),
        () => land(symbol, null),
      );
    },
    subscribe(listener) {
      listeners.add(listener);
      return () => void listeners.delete(listener);
    },
    getVersion: () => version,
    stop() {
      abort.abort();
      asking.clear();
    },
  };
}

/**
 * SCR-100's instrument facts (E08-D07 §4.1, D20): each symbol's `price_scale` and whether it is delisted, from E08-S09's
 * client instrument index (`GET /instruments`, Trading only, paged, hourly). The shell's index while it runs; while no
 * workspace has started it, the page runs one of its own while it shows. A list symbol the Trading listing lacks is
 * looked up once a session (`GET /instruments/{symbol}`), so a delisted row reads as one; an unknown symbol is never
 * subscribed (a batched `ticker` naming one is refused whole, `23` §5.2).
 */
import { useEffect, useMemo, useRef, useSyncExternalStore } from "react";
import {
  createInstrumentIndex,
  lookupSymbol,
  type IndexSnapshot,
  type InstrumentIndex,
} from "../symbol-search/instrumentIndex";
import type { Instrument } from "../symbol-search/ranking";
import { useRunningIndex } from "../symbol-search/searchSession";

export type InstrumentSource = Pick<InstrumentIndex, "subscribe" | "getSnapshot" | "learn">;

/** Lookups a list may ask for at once: a list holds at most 200 symbols, and few of them stop trading. */
const MAX_LOOKUPS = 20;

/** The shell's running index, else the page's own, started while the page shows. */
export function useWatchlistIndex(): InstrumentSource {
  const shared = useRunningIndex();
  const own = useMemo(() => createInstrumentIndex(), []);
  useEffect(() => {
    if (shared !== null) return undefined;
    own.start();
    return () => own.stop();
  }, [shared, own]);
  return shared ?? own;
}

export interface InstrumentFacts {
  readonly snapshot: IndexSnapshot;
  /** Trading instruments and the session's looked-up ones, by symbol. */
  readonly bySymbol: ReadonlyMap<string, Instrument>;
}

export function useInstrumentFacts(source: InstrumentSource): InstrumentFacts {
  const snapshot = useSyncExternalStore(source.subscribe, source.getSnapshot, source.getSnapshot);
  const bySymbol = useMemo(() => {
    const map = new Map<string, Instrument>();
    for (const entry of [...snapshot.entries, ...snapshot.known])
      map.set(entry.symbol, entry.instrument);
    return map;
  }, [snapshot]);
  return { snapshot, bySymbol };
}

/** Delisted: `Instrument.delisted`, or a status neither Trading nor PreLaunch (E08-D07 D20). */
export const isDelisted = (instrument: Instrument | undefined): boolean =>
  instrument !== undefined &&
  (instrument.delisted === true ||
    (instrument.status !== undefined &&
      instrument.status !== "Trading" &&
      instrument.status !== "PreLaunch"));

/** Looks up, once while the page shows, the list symbols the listing lacks; the answers join the index's caches. */
export function useListLookups(
  source: InstrumentSource,
  facts: InstrumentFacts,
  symbols: readonly string[],
): void {
  const asked = useRef(new Set<string>());
  const inFlight = useRef(new Set<AbortController>());
  const missing =
    facts.snapshot.phase === "ready"
      ? symbols.filter((s) => !facts.bySymbol.has(s) && !facts.snapshot.unlisted.includes(s))
      : [];
  const key = missing.slice(0, MAX_LOOKUPS).join(",");
  useEffect(() => {
    if (key === "") return;
    for (const symbol of key.split(",")) {
      if (asked.current.has(symbol)) continue;
      asked.current.add(symbol);
      const controller = new AbortController();
      inFlight.current.add(controller);
      void lookupSymbol(symbol, controller.signal)
        .then((answer) => {
          if (!controller.signal.aborted) source.learn(answer);
        })
        .catch(() => undefined) // no usable answer: the row stays as it is
        .finally(() => inFlight.current.delete(controller));
    }
  }, [key, source]);
  useEffect(() => {
    const held = inFlight.current;
    return () => {
      for (const controller of held) controller.abort();
      held.clear();
    };
  }, []);
}

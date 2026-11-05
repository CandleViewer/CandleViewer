// E24-S07 (#782) slice 2: the recorded layer's read lifecycle (BQ 6, ruled 6624627875; `22` "Cadence"). Off: nothing
// is read. On: one read on enable and on each symbol change, then a re-read only after #780's feed has delivered a new
// print (`printSeq` moves), at most once every `MIN_INTERVAL_MS` from the last read's start: never per frame. A failed
// refresh keeps the layer, stale; a refused answer (BQ 7) draws nothing. Unmount, a symbol change or switching off
// aborts the read in flight and clears the timer.
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { createByPriceAnalytics, type ByPriceAnalytics } from "./analytics";
import {
  fetchLiquidationsByPrice,
  type ByPriceAnswer,
  type ByPriceRead,
  type ByPriceRequest,
} from "./byPriceRead";
import { layerOf, type ByPriceLayer } from "./model";

export const MIN_INTERVAL_MS = 5_000;

export interface ByPriceOptions {
  readonly symbol: string;
  /** `deriv.liq_by_price` (or the session's choice): false reads nothing. */
  readonly enabled: boolean;
  /** Moves whenever #780's feed delivers new prints for `symbol`. */
  readonly printSeq: number;
  readonly read?: ((req: ByPriceRequest) => Promise<ByPriceRead>) | undefined;
  readonly analytics?: ByPriceAnalytics | undefined;
}

export interface ByPriceView {
  readonly phase: "off" | "loading" | "ready" | "refused" | "failed";
  /** `null` unless `ready`. */
  readonly layer: ByPriceLayer | null;
  /** A refresh failed: the layer is the last good read, loaded at `loadedAtMs`. */
  readonly stale: boolean;
  readonly loadedAtMs: number | null;
  readonly retry: () => void;
}

interface Held {
  readonly key: string;
  readonly answer: ByPriceAnswer | null;
  readonly loadedAtMs: number | null;
  readonly outcome: "loading" | "ok" | "refused" | "failed";
}

export function useLiquidationsByPrice(o: ByPriceOptions): ByPriceView {
  const { symbol, enabled, printSeq } = o;
  const latest = useRef(o);
  latest.current = o;
  const pump = useRef<(() => void) | null>(null);
  const [tick, setTick] = useState(0);
  const [held, setHeld] = useState<Held | null>(null);
  const key = `${symbol}|${String(tick)}`;

  useEffect(() => {
    if (!enabled) {
      setHeld(null);
      return undefined;
    }
    setHeld({ key, answer: null, loadedAtMs: null, outcome: "loading" });
    const ctl = new AbortController();
    const analytics = latest.current.analytics ?? createByPriceAnalytics();
    let timer: ReturnType<typeof setTimeout> | undefined;
    let inFlight = false;
    let lastStartMs = Number.NEGATIVE_INFINITY;
    let readSeq = latest.current.printSeq;
    const run = async (): Promise<void> => {
      timer = undefined;
      inFlight = true;
      lastStartMs = Date.now();
      readSeq = latest.current.printSeq;
      const read = latest.current.read ?? fetchLiquidationsByPrice;
      const r: ByPriceRead = await Promise.resolve()
        .then(() => read({ symbol, signal: ctl.signal }))
        .catch(() => ({ kind: "failed", status: null, code: null }) as const);
      inFlight = false;
      if (ctl.signal.aborted) return;
      if (r.kind !== "ok")
        analytics.readFailed(symbol, r.kind === "refused" ? 200 : r.status, r.code);
      if (r.kind === "ok")
        setHeld({ key, answer: r.answer, loadedAtMs: Date.now(), outcome: "ok" });
      else if (r.kind === "refused")
        setHeld({ key, answer: null, loadedAtMs: null, outcome: "refused" });
      else
        setHeld((h) => ({
          ...(h?.key === key ? h : { key, answer: null, loadedAtMs: null }),
          outcome: "failed",
        }));
      next();
    };
    const next = (): void => {
      if (inFlight || timer !== undefined || ctl.signal.aborted) return;
      if (latest.current.printSeq === readSeq) return;
      timer = setTimeout(() => void run(), Math.max(0, lastStartMs + MIN_INTERVAL_MS - Date.now()));
    };
    pump.current = next;
    void run();
    return () => {
      ctl.abort();
      pump.current = null;
      if (timer !== undefined) clearTimeout(timer);
    };
  }, [enabled, symbol, key]);

  useEffect(() => {
    pump.current?.();
  }, [printSeq]);

  const retry = useCallback(() => setTick((n) => n + 1), []);
  const mine = enabled && held?.key === key ? held : null;
  const answer = mine?.answer ?? null;
  const layer = useMemo(() => (answer === null ? null : layerOf(answer)), [answer]);
  const phase: ByPriceView["phase"] = !enabled
    ? "off"
    : mine === null || mine.outcome === "loading"
      ? "loading"
      : mine.outcome === "refused"
        ? "refused"
        : layer === null
          ? "failed"
          : "ready";
  const ready = phase === "ready";
  return {
    phase,
    layer: ready ? layer : null,
    stale: ready && mine?.outcome === "failed",
    loadedAtMs: ready ? (mine?.loadedAtMs ?? null) : null,
    retry,
  };
}

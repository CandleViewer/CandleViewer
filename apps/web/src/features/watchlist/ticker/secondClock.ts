/**
 * SCR-100's one shared 1 Hz clock (E08-D07 D22, §8), on which every countdown and every stale age renders, never a
 * timer per row: the client's whole second, which the ages are measured in (a ticker item's arrival is the client's
 * time); a countdown adds the WS welcome's `clock_skew_ms` (`serverSkewMs`) to read server time. One interval, aligned
 * to the whole second, started by the first subscriber and cleared when the last one leaves; a tick notifies only when
 * the whole second changed. Plain code, never a statechart.
 */
import { useSyncExternalStore } from "react";
import { getActiveClient } from "../../../lib/ws/client/activeClient";

export const SECOND_MS = 1_000;

export interface SecondSource {
  readonly now: () => number;
  readonly setTimeout: (run: () => void, ms: number) => unknown;
  readonly clearTimeout: (id: unknown) => void;
  readonly setInterval: (run: () => void, ms: number) => unknown;
  readonly clearInterval: (id: unknown) => void;
}

/** Reads the globals on every call, so fake timers installed after import still apply. */
export const SYSTEM_SECOND_SOURCE: SecondSource = {
  now: () => Date.now(),
  setTimeout: (run, ms) => setTimeout(run, ms),
  // `id` is what this source's own timers returned; the casts only restore that type.
  clearTimeout: (id) => clearTimeout(id as ReturnType<typeof setTimeout>),
  setInterval: (run, ms) => setInterval(run, ms),
  clearInterval: (id) => clearInterval(id as ReturnType<typeof setInterval>),
};

export interface SecondClock {
  readonly subscribe: (listener: () => void) => () => void;
  /** The client's whole second, in epoch ms. */
  readonly getSnapshot: () => number;
}

/** `clock_skew_ms` (`23` §4.2): the server's clock less the client's, `0` before a `welcome`. */
export function serverSkewMs(): number {
  const skew = getActiveClient()?.diagnostics()?.clockSkewMs;
  return skew !== undefined && Number.isFinite(skew) ? skew : 0;
}

export function createSecondClock(source: SecondSource = SYSTEM_SECOND_SOURCE): SecondClock {
  const listeners = new Set<() => void>();
  let align: unknown = null;
  let interval: unknown = null;
  const read = (): number => Math.floor(source.now() / SECOND_MS) * SECOND_MS;
  let second = read();
  const tick = (): void => {
    const next = read();
    if (next === second) return;
    second = next;
    for (const listener of [...listeners]) listener();
  };
  const stop = (): void => {
    if (align !== null) source.clearTimeout(align);
    if (interval !== null) source.clearInterval(interval);
    align = null;
    interval = null;
  };
  return {
    subscribe(listener) {
      listeners.add(listener);
      if (align === null && interval === null) {
        second = read();
        // The first tick on the next whole second, then one a second.
        align = source.setTimeout(
          () => {
            align = null;
            tick();
            interval = source.setInterval(tick, SECOND_MS);
          },
          SECOND_MS - (source.now() % SECOND_MS),
        );
      }
      return () => {
        listeners.delete(listener);
        if (listeners.size === 0) stop();
      };
    },
    getSnapshot() {
      if (align === null && interval === null) second = read(); // idle: read the clock now
      return second;
    },
  };
}

/** The panel's one clock. */
export const secondClock: SecondClock = createSecondClock();

export function useSecondClock(clock: SecondClock = secondClock): number {
  return useSyncExternalStore(clock.subscribe, clock.getSnapshot, clock.getSnapshot);
}

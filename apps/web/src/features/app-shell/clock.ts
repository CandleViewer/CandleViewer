/**
 * The status bar's 1 Hz UTC clock (E10-S01 S4, #304; CMP-208): a store of its own in the shell
 * store's `useSyncExternalStore` pub/sub pattern, so a tick re-renders only the clock leaf, never
 * the shell, the chips or the route outlet (SCR-010 "never re-render the workspace subtree").
 *
 * One interval, started by the first subscriber and cleared when the last one leaves. A tick
 * allocates nothing but the formatted string, and notifies only when that string changed. The
 * 1 s interval is not aligned to the second boundary and timers drift, so the display is
 * approximate: a shown second can occasionally be skipped or held for up to one tick.
 */
import { useSyncExternalStore } from "react";

/** The time source, injectable for tests. */
export interface ClockSource {
  readonly now: () => number;
  readonly setInterval: (tick: () => void, ms: number) => unknown;
  readonly clearInterval: (id: unknown) => void;
}

/** Reads the globals on every call, so fake timers installed after import still apply. */
export const SYSTEM_CLOCK: ClockSource = {
  now: () => Date.now(),
  setInterval: (tick, ms) => setInterval(tick, ms),
  clearInterval: (id) => clearInterval(id as ReturnType<typeof setInterval>),
};

export const CLOCK_TICK_MS = 1_000;

const DAY_S = 86_400;
const pad = (n: number): string => (n < 10 ? `0${n}` : `${n}`);

/** "14:02:05 UTC" for epoch `ms`; no `Date` per tick. A non-finite time shows "--:--:-- UTC". */
export function formatUtcClock(ms: number): string {
  if (!Number.isFinite(ms)) return "--:--:-- UTC";
  const s = ((Math.floor(ms / 1000) % DAY_S) + DAY_S) % DAY_S;
  return `${pad(Math.floor(s / 3600))}:${pad(Math.floor(s / 60) % 60)}:${pad(s % 60)} UTC`;
}

export interface ClockStore {
  readonly subscribe: (listener: () => void) => () => void;
  readonly getSnapshot: () => string;
}

export function createClockStore(source: ClockSource = SYSTEM_CLOCK): ClockStore {
  const listeners = new Set<() => void>();
  let timer: unknown = null;
  let text = formatUtcClock(source.now());

  const tick = (): void => {
    const next = formatUtcClock(source.now());
    if (next === text) return;
    text = next;
    listeners.forEach((listener) => listener());
  };

  return {
    subscribe(listener) {
      listeners.add(listener);
      if (timer === null) timer = source.setInterval(tick, CLOCK_TICK_MS);
      return () => {
        listeners.delete(listener);
        if (listeners.size > 0 || timer === null) return;
        source.clearInterval(timer);
        timer = null;
      };
    },
    getSnapshot() {
      // Idle (no interval): read the clock now; equal strings keep `useSyncExternalStore` still.
      if (timer === null) text = formatUtcClock(source.now());
      return text;
    },
  };
}

/** The shell's one clock. */
export const utcClock: ClockStore = createClockStore();

export function useUtcClock(store: ClockStore = utcClock): string {
  return useSyncExternalStore(store.subscribe, store.getSnapshot, store.getSnapshot);
}

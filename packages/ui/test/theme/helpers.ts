import { afterEach } from "vitest";
import { THEME_CHANGE_EVENT, type ThemeChangeDetail } from "../../src/theme/index.js";

const stops: AbortController[] = [];

afterEach(() => {
  stops.splice(0).forEach((stop) => stop.abort());
  for (const name of ["theme", "density", "motion", "text-scale"]) {
    document.documentElement.removeAttribute(`data-${name}`);
  }
});

export function memoryStorage(initial: Record<string, string> = {}) {
  const data = new Map(Object.entries(initial));
  return {
    data,
    getItem: (key: string) => data.get(key) ?? null,
    setItem: (key: string, value: string) => void data.set(key, value),
  };
}

/**
 * `matchMedia` stub whose OS state can be flipped. Each query keeps its own listener set, so a disposer
 * that removes only one of them is detectable, and `set` notifies only the queries that changed.
 */
export function mediaStub(initial: { dark?: boolean; reduce?: boolean } = {}) {
  const state = { dark: initial.dark ?? true, reduce: initial.reduce ?? false };
  const listeners = { dark: new Set<() => void>(), reduce: new Set<() => void>() };
  const matchMedia = (query: string): MediaQueryList => {
    const key = query.includes("color-scheme") ? "dark" : "reduce";
    return {
      get matches() {
        return state[key];
      },
      addEventListener: (_type: string, listener: () => void) => void listeners[key].add(listener),
      removeEventListener: (_type: string, listener: () => void) =>
        void listeners[key].delete(listener),
    } as unknown as MediaQueryList;
  };
  return {
    matchMedia,
    listeners,
    set(next: { dark?: boolean; reduce?: boolean }) {
      const changed = (["dark", "reduce"] as const).filter(
        (k) => (next[k] ?? state[k]) !== state[k],
      );
      Object.assign(state, next);
      changed.forEach((key) => listeners[key].forEach((listener) => listener()));
    },
  };
}

/** Collects `candleviewer:themechange` payloads until the test ends. */
export function themeChanges(): ThemeChangeDetail[] {
  const stop = new AbortController();
  stops.push(stop);
  const seen: ThemeChangeDetail[] = [];
  document.addEventListener(
    THEME_CHANGE_EVENT,
    (event) => seen.push((event as CustomEvent<ThemeChangeDetail>).detail),
    { signal: stop.signal },
  );
  return seen;
}

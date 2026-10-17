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

/** `matchMedia` stub whose OS state can be flipped; `set` notifies `change` listeners like a browser. */
export function mediaStub(initial: { dark?: boolean; reduce?: boolean } = {}) {
  const state = { dark: initial.dark ?? true, reduce: initial.reduce ?? false };
  const listeners = new Set<() => void>();
  const matchMedia = (query: string): MediaQueryList =>
    ({
      get matches() {
        return query.includes("color-scheme") ? state.dark : state.reduce;
      },
      addEventListener: (_type: string, listener: () => void) => void listeners.add(listener),
      removeEventListener: (_type: string, listener: () => void) => void listeners.delete(listener),
    }) as unknown as MediaQueryList;
  return {
    matchMedia,
    listeners,
    set(next: { dark?: boolean; reduce?: boolean }) {
      Object.assign(state, next);
      listeners.forEach((listener) => listener());
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

import { useSyncExternalStore } from "react";

/**
 * The narrow breakpoint of conventions 39 (720 CSS px, `45rem` at the 16 px root): the same query as
 * `@media (max-width: 45rem)` in drawer.css, where a drawer over the page takes the full width.
 */
export const NARROW_QUERY = "(max-width: 45rem)";

/** One list for every subscribe and snapshot; rebuilt only if `window.matchMedia` itself is replaced. */
let cached: { readonly source: unknown; readonly list: MediaQueryList } | null = null;

const query = (): MediaQueryList | null => {
  if (typeof window === "undefined" || typeof window.matchMedia !== "function") return null;
  if (cached === null || cached.source !== window.matchMedia) {
    cached = { source: window.matchMedia, list: window.matchMedia(NARROW_QUERY) };
  }
  return cached.list;
};

const subscribe = (notify: () => void): (() => void) => {
  const list = query();
  list?.addEventListener("change", notify);
  return () => list?.removeEventListener("change", notify);
};

const snapshot = (): boolean => query()?.matches ?? false;

/**
 * True while the viewport is at the narrow breakpoint, and follows a resize. Without `matchMedia` (SSR,
 * an old engine) it is false: the wide behaviour.
 */
export function useNarrowViewport(): boolean {
  return useSyncExternalStore(subscribe, snapshot, () => false);
}

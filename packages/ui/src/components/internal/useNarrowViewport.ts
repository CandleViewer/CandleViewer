import { useSyncExternalStore } from "react";

/**
 * The narrow breakpoint of conventions 39 (720 CSS px, `45rem` at the 16 px root): the same query as
 * `@media (max-width: 45rem)` in drawer.css, where a drawer over the page takes the full width.
 */
export const NARROW_QUERY = "(max-width: 45rem)";

const query = (): MediaQueryList | null =>
  typeof window === "undefined" || typeof window.matchMedia !== "function"
    ? null
    : window.matchMedia(NARROW_QUERY);

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

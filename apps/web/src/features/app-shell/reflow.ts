/**
 * CMP-043's reflow breakpoint (`dialog.css`): 200 % zoom on the 1280 x 800 frame, and any viewport
 * at or under 640 x 400 CSS px (320 px wide at 400 % included). The scrim's band (`AppShell`) and
 * the nav rail's narrow mode (`NavRailFrame`, #304 S10, A11Y-F-0016) read the same query.
 */
import { useSyncExternalStore } from "react";

export const REFLOW_QUERY = "(max-width: 40rem), (max-height: 25rem)";

const media = (): MediaQueryList | null =>
  typeof window !== "undefined" && typeof window.matchMedia === "function"
    ? window.matchMedia(REFLOW_QUERY)
    : null;

function subscribe(listener: () => void): () => void {
  const list = media();
  list?.addEventListener("change", listener);
  return () => list?.removeEventListener("change", listener);
}

const read = (): boolean => media()?.matches === true;

/** Whether the viewport is at CMP-043's reflow breakpoint now; re-renders when it crosses it. */
export function useReflow(): boolean {
  return useSyncExternalStore(subscribe, read, () => false);
}

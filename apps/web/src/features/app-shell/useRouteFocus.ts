import { useEffect, useRef, type RefObject } from "react";
import { useLocation } from "react-router";

/**
 * The opt-in marker for a navigation that keeps focus where it is (#304 S10, BQ-12): an in-page
 * switch that changes a `:param` of the same screen (SCR-100's watchlist tabs on R-111, #4702)
 * passes `navigate(to, { state: { [ROUTE_FOCUS_KEEP]: true } })` (or `<Link state>`), so focus never
 * visits the `h1` on its way back to the tab. Every unmarked route change still moves focus.
 */
export const ROUTE_FOCUS_KEEP = "cvRouteFocusKeep";

const keepsFocus = (state: unknown): boolean =>
  typeof state === "object" &&
  state !== null &&
  (state as Record<string, unknown>)[ROUTE_FOCUS_KEEP] === true;

/**
 * Moves focus into the shell's `main` after a route change (E10-S01 S1; ticket "Route-change
 * behaviour"): to its first `h1`, else to `main` itself. The first render is left alone, so an
 * autofocused control on the landing screen keeps its focus. Keyed on the previous pathname, not a
 * first-run flag, so StrictMode's double effect run cannot count as a navigation. A heading that
 * is not focusable takes `tabindex="-1"` for the move and loses it on blur (`15` CMP-085, J20).
 */
export function useRouteFocus(mainRef: RefObject<HTMLElement>): void {
  const { pathname, state } = useLocation();
  const previous = useRef(pathname);
  const keep = keepsFocus(state);
  useEffect(() => {
    if (previous.current === pathname) return;
    previous.current = pathname;
    if (keep) return; // the marked navigation's own focus stays (ROUTE_FOCUS_KEEP)
    const main = mainRef.current;
    if (main === null) return;
    const heading = main.querySelector<HTMLElement>("h1");
    if (heading === null) {
      main.focus();
      return;
    }
    if (!heading.hasAttribute("tabindex")) {
      heading.setAttribute("tabindex", "-1");
      heading.addEventListener("blur", () => heading.removeAttribute("tabindex"), { once: true });
    }
    heading.focus();
  }, [pathname, mainRef, keep]);
}

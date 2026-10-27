import { useEffect, useRef, type RefObject } from "react";
import { useLocation } from "react-router";

/**
 * Moves focus into the shell's `main` after a route change (E10-S01 S1; ticket "Route-change
 * behaviour"): to its first `h1`, else to `main` itself. The first render is left alone, so an
 * autofocused control on the landing screen keeps its focus. Keyed on the previous pathname, not a
 * first-run flag, so StrictMode's double effect run cannot count as a navigation. A heading that
 * is not focusable takes `tabindex="-1"` for the move and loses it on blur (`15` CMP-085, J20).
 */
export function useRouteFocus(mainRef: RefObject<HTMLElement>): void {
  const { pathname } = useLocation();
  const previous = useRef(pathname);
  useEffect(() => {
    if (previous.current === pathname) return;
    previous.current = pathname;
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
  }, [pathname, mainRef]);
}

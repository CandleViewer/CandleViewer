/**
 * Shell chrome motion (E10-S01 S6, #304; E10-D04 §4 rows T-01–T-04): `transform` and `opacity`
 * only, never `width`, on the motion tokens. Reduced motion (the OS or the app's setting, both
 * resolved by the theme runtime into `data-motion`) gives the instant end state: no transition at
 * all, not a shorter one (D04 R-3). `theme.css` neutralises transitions under `data-motion="reduce"`
 * too; the inline `none` keeps the end state instant before the stylesheet loads.
 */
import { useSyncExternalStore } from "react";
import { appThemeStore } from "../../shell/bootstrap/themeStore";

export function useReducedMotion(): boolean {
  const store = appThemeStore();
  const read = (): boolean => store.getSnapshot().motion === "reduce";
  return useSyncExternalStore(store.subscribe, read, read);
}

type Duration = "fast" | "normal";
type Easing = "decelerate" | "accelerate" | "standard";

/** A `transition` over `transform` (and `opacity` when asked); `none` under reduced motion. */
export function slide(
  reduce: boolean,
  duration: Duration,
  easing: Easing,
  withOpacity = false,
): string {
  if (reduce) return "none";
  const timing = `var(--motion-duration-${duration}) cubic-bezier(var(--motion-easing-${easing}))`;
  return withOpacity ? `transform ${timing}, opacity ${timing}` : `transform ${timing}`;
}

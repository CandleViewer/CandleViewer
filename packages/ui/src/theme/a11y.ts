import type { ThemeStore } from "./store.js";

/**
 * Shortcut contract for the high-contrast toggle (`05-accessibility-standard.md` §3.2). The E10 hotkey
 * registry registers a command from it (fields named as in `KeymapCommand`, binding in its canonical
 * `Ctrl+Alt+Shift+Key` form) and calls `toggleHighContrastAnnounced`. It must not run the handler for a
 * key auto-repeat (`ignoreRepeat`; its `KeyEventLike` has no `repeat` field yet), and the handler ignores a
 * repeat too (`{ repeat: event.repeat }`), so holding the keys cannot flap the theme. This package never
 * listens for keys.
 */
export const HIGH_CONTRAST_SHORTCUT = {
  id: "global.toggle_high_contrast",
  defaultBinding: "Ctrl+Shift+H",
  label: "Toggle high-contrast theme",
  ignoreRepeat: true,
} as const;

/** Single replaceable home for the announcement copy (no copy layer exists in the package yet). */
export const THEME_ANNOUNCEMENTS = {
  highContrastOn: "High-contrast theme on",
  highContrastOff: "High-contrast theme off",
} as const;

const LIVE_REGION_ID = "cv-theme-live-region";

/** The hidden polite live region, created empty when missing: it must exist before the first announcement (05 §6.2). */
export function mountLiveRegion(doc: Document = document): HTMLElement {
  let region = doc.getElementById(LIVE_REGION_ID);
  if (region === null) {
    region = doc.createElement("div");
    region.id = LIVE_REGION_ID;
    region.setAttribute("role", "status");
    region.setAttribute("aria-live", "polite");
    region.setAttribute("aria-atomic", "true");
    // CSSOM writes (not a style attribute in markup), so a strict `style-src` still allows them.
    Object.assign(region.style, {
      position: "absolute",
      width: "0.0625rem",
      height: "0.0625rem",
      overflow: "hidden",
      clipPath: "inset(50%)",
      whiteSpace: "nowrap",
    });
    doc.body.appendChild(region);
  }
  return region;
}

/** Announces `message` through the live region (mount it at startup, see `mountLiveRegion`). */
export function announcePolite(message: string, doc: Document = document): void {
  mountLiveRegion(doc).textContent = message;
}

export interface ToggleHighContrastOptions {
  /** `KeyboardEvent.repeat`: a held key must not flap the theme, so a repeat changes nothing. */
  readonly repeat?: boolean;
  readonly announce?: (message: string) => void;
}

/** `Ctrl+Shift+H` handler: toggles high contrast and announces it; a repeat returns the unchanged state. */
export function toggleHighContrastAnnounced(
  store: ThemeStore,
  { repeat = false, announce = announcePolite }: ToggleHighContrastOptions = {},
): boolean {
  if (repeat) return store.getSnapshot().highContrast;
  const on = store.toggleHighContrast();
  announce(on ? THEME_ANNOUNCEMENTS.highContrastOn : THEME_ANNOUNCEMENTS.highContrastOff);
  return on;
}

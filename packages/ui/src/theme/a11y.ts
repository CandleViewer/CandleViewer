import type { ThemeStore } from "./store.js";

/**
 * Design-system shortcut contract for the high-contrast toggle (`05-accessibility-standard.md` §3.2).
 * The global hotkey registry is E10's: it registers `id`/`binding` and calls
 * `toggleHighContrastAnnounced` as the handler. The binding string uses the registry's canonical
 * `Ctrl+Alt+Shift+Key` form. This package never listens for keys itself.
 */
export const HIGH_CONTRAST_SHORTCUT = {
  id: "global.toggle_high_contrast",
  binding: "Ctrl+Shift+H",
  label: "Toggle high-contrast theme",
} as const;

/** Single replaceable home for the announcement copy (no copy layer exists in the package yet). */
export const THEME_ANNOUNCEMENTS = {
  highContrastOn: "High-contrast theme on",
  highContrastOff: "High-contrast theme off",
} as const;

const LIVE_REGION_ID = "cv-theme-live-region";

/** Announces `message` through one visually hidden polite live region, created outside React on first use. */
export function announcePolite(message: string, doc: Document = document): void {
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
  region.textContent = message;
}

/** `Ctrl+Shift+H` handler: toggles high contrast and announces the new state politely. */
export function toggleHighContrastAnnounced(
  store: ThemeStore,
  announce: (message: string) => void = announcePolite,
): boolean {
  const on = store.toggleHighContrast();
  announce(on ? THEME_ANNOUNCEMENTS.highContrastOn : THEME_ANNOUNCEMENTS.highContrastOff);
  return on;
}

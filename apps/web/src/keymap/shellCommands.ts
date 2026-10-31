/**
 * The shell's own commands that #305 adds (BQ-6): `Ctrl+\` cycles the landmark ring (E10-D04 G-04, `05` §3.4 rule 1)
 * and `Ctrl+Shift+M` toggles the reduced-motion override (E10-D04 G-03, E05-D03 §6.5). `Ctrl+Shift+H` is E05-T02's
 * `toggleHighContrastAnnounced`; KeymapHost registers all three.
 */
import { announcePolite, type ThemeStore } from "@candleviewer/ui";

/** E05-D03 §6.5's words. */
export const MOTION_ANNOUNCEMENTS = {
  on: "Reduced motion on",
  off: "Reduced motion off",
} as const;

/**
 * `Ctrl+Shift+M`: the resolved mode flips to an explicit choice, `on` or `off` (from `system`, the opposite of what
 * the OS resolves), persisted like SCR-117's, and said once, politely, through the theme's live region as
 * `Ctrl+Shift+H` is. The way back to `system` is SCR-117 only. Returns whether motion is now reduced.
 */
export function toggleReducedMotionAnnounced(
  store: ThemeStore,
  say: (message: string) => void = announcePolite,
): boolean {
  const reduce = store.getSnapshot().motion !== "reduce";
  store.setMotionOverride(reduce ? "on" : "off");
  say(reduce ? MOTION_ANNOUNCEMENTS.on : MOTION_ANNOUNCEMENTS.off);
  return reduce;
}

const LANDMARKS = [
  "header",
  "footer",
  "nav",
  "main",
  "aside",
  "section[aria-label]",
  "section[aria-labelledby]",
  '[role="banner"]',
  '[role="navigation"]',
  '[role="main"]',
  '[role="complementary"]',
  '[role="contentinfo"]',
  '[role="region"][aria-label]',
  '[role="region"][aria-labelledby]',
].join(", ");
const LANDMARK_ROLES = new Set([
  "banner",
  "navigation",
  "main",
  "complementary",
  "contentinfo",
  "region",
]);
/** A `header` or `footer` inside one of these is that section's, not the page's banner or contentinfo. */
const SECTIONING =
  'article, aside, main, nav, section, [role="article"], [role="complementary"], [role="main"], [role="navigation"], [role="region"]';

function isLandmark(el: Element): boolean {
  const role = el.getAttribute("role");
  if (role !== null) return LANDMARK_ROLES.has(role);
  const tag = el.tagName.toLowerCase();
  return (tag !== "header" && tag !== "footer") || el.parentElement?.closest(SECTIONING) === null;
}

/** The landmarks a press can reach, in DOM order: none hidden, inert or out of the accessibility tree. */
export function landmarkRing(root: ParentNode = document): HTMLElement[] {
  return [...root.querySelectorAll<HTMLElement>(LANDMARKS)].filter(
    (el) => isLandmark(el) && el.closest('[hidden], [inert], [aria-hidden="true"]') === null,
  );
}

/**
 * `Ctrl+\`: focus moves to the landmark after the one that holds it (from the page, the first), wrapping. One that
 * cannot take focus, as a CSS-hidden one cannot, is passed over (A11Y-305B-03). Nothing is announced: the reader
 * reports the landmark it focuses, by role and name. An open modal dialog keeps focus (`05` §3.4 rule 4). Returns the
 * landmark focused, or null when nothing moved.
 */
export function cycleRegion(doc: Document = document): HTMLElement | null {
  const modal = [...doc.querySelectorAll('[aria-modal="true"]')].some(
    (el) => el.closest("[inert]") === null,
  );
  const ring = landmarkRing(doc);
  if (modal) return null;
  const active = doc.activeElement;
  let at = -1; // the innermost landmark holding focus: the last, in DOM order, that contains it
  ring.forEach((el, i) => {
    if (active !== null && el.contains(active)) at = i;
  });
  for (let step = 1; step <= ring.length; step++) {
    const next = ring[(at + step) % ring.length];
    if (next === undefined) continue;
    const added = !next.hasAttribute("tabindex");
    if (added) next.setAttribute("tabindex", "-1");
    next.focus();
    if (doc.activeElement === next) return next;
    if (added) next.removeAttribute("tabindex"); // it took no focus: leave it as it was
  }
  return null;
}

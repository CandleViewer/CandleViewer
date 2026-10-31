// Reduced motion and the keyboard help (E11-S04 PR 2, 26 §12, README BQ-104 / BQ-105). The
// engine follows the app's resolved motion mode both ways and has no option of its own (C-22): the
// `16` §4 contract's `data-motion` on the document root at mount, then each
// `candleviewer:themechange` event's `detail.motion` (string literals: no `packages/ui` import).
// It never reads the media query. The keyboard help is a node in the DOM mirror (E11-S13 points
// `aria-describedby` at it); under reduce it says that inertia is off (E11-D06 §16, G-6).
// DOM program (tsconfig.dom.json): the document is reached through the container, never a global.

export const THEME_CHANGE_EVENT = "candleviewer:themechange";

export const KEY_HELP =
  "Left and Right arrows pan by one bar, ten with Shift. Home shows the first bar, End the " +
  "latest. Plus and minus zoom. Control+Home resets the view.";
/** E11-D06 §16's sentence, verbatim. */
export const REDUCED_MOTION_HELP =
  "Inertia is off while reduced motion is on — the chart stops where you release it.";

export const keyboardHelp = (reduce: boolean): string =>
  reduce ? `${KEY_HELP} ${REDUCED_MOTION_HELP}` : KEY_HELP;

/** The resolved mode at mount: `data-motion="reduce"` on the document root. */
export function readReducedMotion(doc: Document): boolean {
  return doc.documentElement.getAttribute("data-motion") === "reduce";
}

/**
 * Mounts the help node in `mirrorRoot` and follows the motion mode from `reduce`; `onChange`
 * runs once per change. Returns the detach function (the listener and the node go).
 */
export function watchMotion(
  doc: Document,
  mirrorRoot: HTMLElement,
  reduce: boolean,
  onChange: (reduce: boolean) => void,
): () => void {
  const help = doc.createElement("div");
  help.setAttribute("data-cv-keyboard-help", "");
  help.textContent = keyboardHelp(reduce);
  mirrorRoot.appendChild(help);
  let current = reduce;
  const onTheme = (e: Event): void => {
    const motion = (e as CustomEvent<{ motion?: unknown } | null>).detail?.motion;
    if (typeof motion !== "string" || (motion === "reduce") === current) return;
    current = motion === "reduce";
    help.textContent = keyboardHelp(current);
    onChange(current);
  };
  doc.addEventListener(THEME_CHANGE_EVENT, onTheme);
  return () => {
    doc.removeEventListener(THEME_CHANGE_EVENT, onTheme);
    help.remove();
  };
}

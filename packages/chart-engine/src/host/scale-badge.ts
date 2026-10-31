// The scale-lock badge (E11-S05, README BQ-124; E11-D03 §5, E11-D02 D7): a host-DOM button named
// "Price scale locked" at the bottom of the price gutter, shown exactly while autoscale is off
// (the `viewport` message's `autoScale`). Enter, Space or a click restores auto-fit; its colours are
// the theme's tokens. The "Locked" short form, the glyph and the tooltip are E11-S06's (CMP-188,
// README G-19).
// DOM program (tsconfig.dom.json); it reaches the document through the container only.
import { TIME_GUTTER_PX } from "../scene/layout-engine.js";

/** The badge's text and accessible name (E11-D01 D2: the same string). */
export const SCALE_BADGE_LABEL = "Price scale locked";

export interface ScaleBadge {
  /** Shows the badge while `locked`; idempotent. */
  set(locked: boolean): void;
  setTheme(colors: Readonly<Record<string, string>>): void;
  dispose(): void;
}

/** Input on the badge is the badge's: the chart's router never sees it as a plot gesture. */
const OWN = ["pointerdown", "pointerup", "pointermove", "dblclick", "wheel", "keydown"] as const;

export function createScaleBadge(
  container: HTMLElement,
  colors: Readonly<Record<string, string>>,
  restore: () => void,
): ScaleBadge {
  let theme = colors;
  let b: HTMLButtonElement | null = null; // made on the first lock: no DOM while auto
  const paint = (): void => {
    if (b === null) return;
    b.style.background = theme["color.surface.raised"] ?? "";
    b.style.borderColor = theme["color.border.strong"] ?? "";
    b.style.color = theme["color.text.primary"] ?? "";
  };
  const make = (): HTMLButtonElement => {
    const el = container.ownerDocument.createElement("button");
    el.setAttribute("type", "button");
    el.setAttribute("data-cv-scale-badge", "");
    el.textContent = SCALE_BADGE_LABEL;
    const s = el.style;
    s.position = "absolute";
    s.right = "0px";
    s.bottom = `${TIME_GUTTER_PX}px`;
    s.minHeight = "24px"; // the 24 px hit box (E11-D02 HPE-R2-5)
    s.borderStyle = "solid";
    s.borderWidth = "1px";
    const stop = (e: Event): void => e.stopPropagation();
    for (const t of OWN) el.addEventListener(t, stop);
    el.addEventListener("click", restore); // a native button clicks on Enter and Space too
    return el;
  };
  let shown = false;
  return {
    set(locked: boolean): void {
      if (locked === shown) return;
      shown = locked;
      if (!locked) {
        // Activated from the keyboard, the badge goes while it holds focus: hand focus to the
        // container (focusable once E11-S13 gives it its stop) rather than drop it to <body>.
        // The axis stop of E11-D03 D7 is E11-S06's (README G-19).
        if (b !== null && b.ownerDocument.activeElement === b)
          container.focus({ preventScroll: true });
        b?.remove();
        return;
      }
      b ??= make();
      paint();
      container.appendChild(b);
    },
    setTheme(next: Readonly<Record<string, string>>): void {
      theme = next;
      paint();
    },
    dispose(): void {
      shown = false;
      b?.remove();
    },
  };
}

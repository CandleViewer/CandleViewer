import type { Page } from "@playwright/test";
import { contrastRatio } from "../../../../tools/contrast/color-math.mjs";

/** WCAG 2.2 SC 1.4.11 / 2.4.13 floor for the focus indicator against the adjacent background. */
export const FOCUS_CONTRAST_MIN = 3;

export interface FocusStyle {
  readonly outlineStyle: string;
  readonly outlineWidth: string;
  readonly outlineColor: string;
  readonly boxShadow: string;
}

export interface FocusIndicator {
  readonly present: boolean;
  /** Contrast of the indicator colour (composited over the background) against it; null when absent. */
  readonly ratio: number | null;
  readonly ok: boolean;
}

type Rgba = readonly [number, number, number, number];

const RGB = /rgba?\(\s*(\d+)[ ,]+(\d+)[ ,]+(\d+)(?:\s*[,/]\s*([\d.]+%?))?\s*\)/;

/** First `rgb()/rgba()` colour in a computed-style string, or null (`none`, `transparent`, `color()`). */
export function parseRgba(css: string): Rgba | null {
  const m = RGB.exec(css);
  if (!m) return null;
  const a = m[4] === undefined ? 1 : m[4].endsWith("%") ? parseFloat(m[4]) / 100 : parseFloat(m[4]);
  return [Number(m[1]), Number(m[2]), Number(m[3]), a];
}

const hex = ([r, g, b]: readonly [number, number, number]): string =>
  `#${[r, g, b].map((v) => Math.round(v).toString(16).padStart(2, "0")).join("")}`;

/**
 * The indicator is the outline when it has style and width, else the box-shadow. Judged with the same
 * `contrastRatio` as the token linter (tools/contrast/color-math.mjs): a second formula could disagree
 * with the linter and make a failure unfalsifiable.
 */
export function judgeFocusIndicator(style: FocusStyle, background: string): FocusIndicator {
  const bg = parseRgba(background);
  const outline =
    style.outlineStyle !== "none" && parseFloat(style.outlineWidth) > 0
      ? parseRgba(style.outlineColor)
      : null;
  const colour = outline ?? parseRgba(style.boxShadow);
  if (colour === null || bg === null) return { present: colour !== null, ratio: null, ok: false };
  const [r, g, b, a] = colour;
  const over = (c: number, under: number): number => c * a + under * (1 - a);
  const solid = [over(r, bg[0]), over(g, bg[1]), over(b, bg[2])] as const;
  const ratio = contrastRatio(hex(solid), hex([bg[0], bg[1], bg[2]]));
  return { present: true, ratio, ok: ratio >= FOCUS_CONTRAST_MIN };
}

/** Read the focused element's indicator style and the first non-transparent ancestor background. */
export async function assertFocusIndicator(page: Page): Promise<FocusIndicator> {
  const read = await page.evaluate(() => {
    const el = document.activeElement;
    if (!el) return null;
    const cs = getComputedStyle(el);
    let bg = "rgb(255, 255, 255)";
    for (let n: Element | null = el; n; n = n.parentElement) {
      const c = getComputedStyle(n).backgroundColor;
      if (!/^rgba\(.*,\s*0\)$/.test(c) && c !== "transparent") {
        bg = c;
        break;
      }
    }
    return {
      style: {
        outlineStyle: cs.outlineStyle,
        outlineWidth: cs.outlineWidth,
        outlineColor: cs.outlineColor,
        boxShadow: cs.boxShadow,
      },
      bg,
    };
  });
  return read === null
    ? { present: false, ratio: null, ok: false }
    : judgeFocusIndicator(read.style, read.bg);
}

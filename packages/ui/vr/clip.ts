/**
 * A cell's capture area (E05-T04): what the story paints, not the 1920x1080 page. ADR-0019's tolerance is a
 * share of the capture's pixels, so on a whole page a token change on one button (well under 1% of it) would
 * pass; clipped to the story, the same change is a large share. An overlay's flat scrim over the viewport is
 * no part of what it paints (`isBackdrop`): a dialog is captured as the dialog. A component that changes size
 * changes the capture's size, which fails whatever the tolerance. The page side (`collectPaint`) only
 * measures; the decisions are `clipFor`'s, in Node, where they are unit-tested.
 */

/** A box in document CSS pixels: left, top, right, bottom. */
export type Box = readonly [number, number, number, number];

/** What decides whether an element paints, and how far past its box. */
export interface ElementPaint {
  readonly box: Box;
  readonly tag: string;
  readonly background: string;
  readonly backgroundImage: string;
  readonly boxShadow: string;
  /** Outline style, width and offset. */
  readonly outline: readonly [string, string, string];
  /** Each side's border width, style and colour. */
  readonly borders: readonly (readonly [string, string, string])[];
  /** A `::before` or `::after` with content. */
  readonly pseudo: boolean;
  /** The computed `position`: `fixed` and `absolute` boxes are out of the flow. */
  readonly position: string;
  /** Whether the element holds visible text itself (a text node child). */
  readonly ownText: boolean;
}

export interface PaintDump {
  /** The page's size as Playwright's full-page screenshot measures it; the clip stays inside it. */
  readonly page: readonly [number, number];
  /** The viewport's size: a backdrop covers all of it. */
  readonly viewport: readonly [number, number];
  readonly elements: readonly ElementPaint[];
  /** The visible text runs. */
  readonly text: readonly Box[];
}

export interface Clip {
  readonly x: number;
  readonly y: number;
  readonly width: number;
  readonly height: number;
}

/** Antialiasing and the browser's own focus ring bleed a few pixels past a box. */
const EDGE = 4;
/** An edge within this distance of a whole pixel is that pixel: float noise never moves a clip by one. */
const SNAP = 0.01;
/** Elements that paint their box whatever their styles say (an input's value is no text node). */
const GRAPHIC = new Set(
  "canvas iframe img input meter progress select svg textarea video".split(" "),
);

/**
 * In the page: every visible element box with its paint styles, and every visible text run. Playwright
 * serialises this function, so it closes over nothing. A visually-hidden box (1 px, clipped: the a11y reason
 * text) and everything in it are skipped, as are the shapes inside an `<svg>` (the svg box counts).
 */
export function collectPaint(): PaintDump {
  const elements: ElementPaint[] = [];
  const text: Box[] = [];
  const skipped = new Set<Element>();
  const box = (rect: DOMRect): Box => [
    rect.left + scrollX,
    rect.top + scrollY,
    rect.right + scrollX,
    rect.bottom + scrollY,
  ];
  for (const element of document.body.querySelectorAll("*")) {
    const parent = element.parentElement;
    if (parent !== null && (skipped.has(parent) || parent.closest("svg") !== null)) {
      skipped.add(element);
      continue;
    }
    if (!element.checkVisibility({ opacityProperty: true, visibilityProperty: true })) continue;
    const rect = element.getBoundingClientRect();
    const style = getComputedStyle(element);
    if (rect.width <= 1 && rect.height <= 1 && /^(?:hidden|clip)/.test(style.overflow)) {
      skipped.add(element);
      continue;
    }
    const side = (name: string): readonly [string, string, string] => [
      style.getPropertyValue(`border-${name}-width`),
      style.getPropertyValue(`border-${name}-style`),
      style.getPropertyValue(`border-${name}-color`),
    ];
    const content = (pseudo: string): string => getComputedStyle(element, pseudo).content;
    const runs = [...element.childNodes].filter(
      (node) => node.nodeType === Node.TEXT_NODE && node.textContent?.trim(),
    );
    elements.push({
      box: box(rect),
      tag: element.localName,
      background: style.backgroundColor,
      backgroundImage: style.backgroundImage,
      boxShadow: style.boxShadow,
      outline: [style.outlineStyle, style.outlineWidth, style.outlineOffset],
      borders: ["top", "right", "bottom", "left"].map(side),
      pseudo: ["::before", "::after"].some(
        (pseudo) => !["none", "normal"].includes(content(pseudo)),
      ),
      position: style.position,
      ownText: runs.length > 0,
    });
    for (const node of runs) {
      const range = document.createRange();
      range.selectNodeContents(node);
      text.push(box(range.getBoundingClientRect()));
    }
  }
  // Playwright's own full-page size, so the clip is never trimmed to a different bound than this one.
  const { body, documentElement: root } = document;
  const page: [number, number] = [
    Math.max(
      body.scrollWidth,
      root.scrollWidth,
      body.offsetWidth,
      root.offsetWidth,
      body.clientWidth,
      root.clientWidth,
    ),
    Math.max(
      body.scrollHeight,
      root.scrollHeight,
      body.offsetHeight,
      root.offsetHeight,
      body.clientHeight,
      root.clientHeight,
    ),
  ];
  return { page, viewport: [innerWidth, innerHeight], elements, text };
}

const px = (value: string): number => Number.parseFloat(value) || 0;

/** Whether a computed colour paints: neither `transparent` nor an alpha of 0 (`rgba(r, g, b, 0)`, `/ 0`). */
export function opaque(color: string): boolean {
  if (color === "" || color === "transparent") return false;
  const channels = /^rgba?\(([^)]*)\)$/.exec(color)?.[1]?.split(",") ?? [];
  const alpha = /\/\s*([\d.]+%?)\s*\)$/.exec(color)?.[1] ?? channels[3];
  return alpha === undefined || px(alpha) > 0;
}

/** How far a computed `box-shadow` reaches past its box: the farthest outer shadow's offset, blur and spread. */
export function shadowReach(boxShadow: string): number {
  if (boxShadow === "none") return 0;
  let reach = 0;
  for (const shadow of boxShadow.split(/,(?![^(]*\))/)) {
    if (/\binset\b/.test(shadow)) continue;
    const lengths = shadow.replace(/[a-z-]+\([^)]*\)/gi, "").match(/-?[\d.]+px/g) ?? [];
    const [x = 0, y = 0, blur = 0, spread = 0] = lengths.map(px);
    reach = Math.max(reach, Math.max(Math.abs(x), Math.abs(y)) + blur + spread);
  }
  return reach;
}

/** How far past its box an element's outline reaches (0 when it draws none). */
const outlineReach = ({ outline: [style, width, offset] }: ElementPaint): number =>
  style === "none" ? 0 : Math.max(0, px(width) + px(offset));

/** Whether any side draws a border: a width, a visible style and a colour that paints. */
const hasBorder = (element: ElementPaint): boolean =>
  element.borders.some(
    ([width, style, color]) =>
      px(width) > 0 && style !== "none" && style !== "hidden" && opaque(color),
  );

/** How far past its box an element paints, or undefined when it paints nothing of its own. */
export function reachOf(element: ElementPaint): number | undefined {
  const outline = outlineReach(element);
  const shadow = shadowReach(element.boxShadow);
  const border = hasBorder(element);
  const paints =
    GRAPHIC.has(element.tag) ||
    element.pseudo ||
    border ||
    shadow > 0 ||
    outline > 0 ||
    element.backgroundImage !== "none" ||
    opaque(element.background);
  return paints ? Math.max(shadow, outline) : undefined;
}

/**
 * An overlay's scrim: out of the flow (`fixed`, or `absolute` in a fixed layer), covering the whole viewport,
 * and painting a flat fill and nothing of its own (no text, border, outline, shadow, image, pseudo-element).
 * A page-sized capture would hide a change on the dialog over it in 2% of 2 Mpx, so it is left out of the
 * capture area; the scrim that the dialog's shadow and edge fall on is still in the image.
 */
export function isBackdrop(
  element: ElementPaint,
  [width, height]: readonly [number, number],
): boolean {
  const [l, t, r, b] = element.box;
  return (
    (element.position === "fixed" || element.position === "absolute") &&
    l <= 0 &&
    t <= 0 &&
    r >= width &&
    b >= height &&
    opaque(element.background) &&
    element.backgroundImage === "none" &&
    !element.ownText &&
    !element.pseudo &&
    !GRAPHIC.has(element.tag) &&
    !hasBorder(element) &&
    outlineReach(element) === 0 &&
    shadowReach(element.boxShadow) === 0
  );
}

/**
 * The capture area: the union of every painting box but a backdrop, each grown by its shadow or outline,
 * plus a 4 px edge, on whole pixels and inside the page. Each edge goes outward to a whole pixel unless it
 * lies within `SNAP` of one, so only a layout that really moved changes the image's size. A story that
 * paints nothing is captured whole.
 */
export function clipFor({ page: [width, height], viewport, elements, text }: PaintDump): Clip {
  const painted: [Box, number][] = text.map((box) => [box, 0]);
  for (const element of elements) {
    if (isBackdrop(element, viewport)) continue;
    const reach = reachOf(element);
    if (reach !== undefined) painted.push([element.box, reach]);
  }
  let [left, top, right, bottom] = [Infinity, Infinity, -Infinity, -Infinity];
  for (const [[l, t, r, b], reach] of painted) {
    if (r <= l || b <= t) continue; // an empty box paints nothing, whatever its shadow
    left = Math.min(left, Math.floor(l - reach + SNAP));
    top = Math.min(top, Math.floor(t - reach + SNAP));
    right = Math.max(right, Math.ceil(r + reach - SNAP));
    bottom = Math.max(bottom, Math.ceil(b + reach - SNAP));
  }
  const x = Math.max(0, left - EDGE);
  const y = Math.max(0, top - EDGE);
  const clipRight = Math.min(width, right + EDGE);
  const clipBottom = Math.min(height, bottom + EDGE);
  return clipRight > x && clipBottom > y
    ? { x, y, width: clipRight - x, height: clipBottom - y }
    : { x: 0, y: 0, width, height };
}

const sameClip = (a: Clip, b: Clip): boolean =>
  a.x === b.x && a.y === b.y && a.width === b.width && a.height === b.height;

/**
 * The capture area once it holds still: measured, then again after `wait` (two animation frames in the
 * spec), until two measures in a row agree. An area still moving after `tries` measures comes back with
 * every box it took (`moving`), and the cell fails naming them; `moving` is empty for a still one.
 */
export async function stableClip(
  measure: () => Promise<Clip>,
  wait: () => Promise<void>,
  tries: number,
): Promise<{ readonly clip: Clip; readonly moving: readonly Clip[] }> {
  let last = await measure();
  const seen = [last];
  for (let taken = 1; taken < tries; taken += 1) {
    await wait();
    const clip = await measure();
    if (sameClip(clip, last)) return { clip, moving: [] };
    seen.push(clip);
    last = clip;
  }
  return { clip: last, moving: seen };
}

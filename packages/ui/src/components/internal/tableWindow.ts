// CMP-049's virtualisation seam (E08-D07 §4.6, D6; `14` SCR-100 "virtualised beyond 60 rows"): the host draws a
// window of a long list and the table reports which rows its region shows. Pure geometry, so it is unit tested
// without a layout.

/** What the region shows, in its scroll coordinates (CSS px). */
export interface RowsInViewInput {
  /** The region's `scrollTop`. */
  readonly scrollTop: number;
  /** The region's `clientHeight`. */
  readonly viewHeight: number;
  /** Where the first body row starts, in the region's scroll coordinates (the caption and header above it). */
  readonly bodyTop: number;
  /** The sticky header row's height: it covers the top of the view once the body scrolls under it. */
  readonly headerHeight: number;
  /** One body row's height. */
  readonly rowHeight: number;
  /** Rows in the whole list. */
  readonly total: number;
}

/** The absolute rows in view, first and last inclusive. */
export interface RowsInView {
  readonly first: number;
  readonly last: number;
}

/**
 * The absolute indices of the body rows a region shows below its sticky header: a row partly in view counts.
 * `undefined` while nothing is laid out (no row height) or the list is empty.
 */
export function rowsInView({
  scrollTop,
  viewHeight,
  bodyTop,
  headerHeight,
  rowHeight,
  total,
}: RowsInViewInput): RowsInView | undefined {
  if (!(rowHeight > 0) || total <= 0) return undefined;
  const top = Math.max(scrollTop + headerHeight, bodyTop) - bodyTop;
  const bottom = scrollTop + viewHeight - bodyTop;
  const clamp = (row: number): number => Math.min(Math.max(row, 0), total - 1);
  const first = clamp(Math.floor(top / rowHeight));
  const last = clamp(Math.ceil(bottom / rowHeight) - 1);
  return { first, last: Math.max(first, last) };
}

/**
 * Spacer rows before the first drawn row so that it lands on the child position its absolute index has: the zebra
 * (`:nth-child(even)`) then follows the list, not the window. One spacer holds the height; an even offset adds an
 * empty one.
 */
export const leadingSpacers = (offset: number): 0 | 1 | 2 =>
  offset <= 0 ? 0 : offset % 2 === 1 ? 1 : 2;

/** One child of a windowed body, in order: a drawn row, a spacer holding undrawn rows' height, or an empty pad. */
export type BodyPart =
  | { readonly kind: "row"; readonly r: number }
  | { readonly kind: "spacer"; readonly key: string; readonly rows: number }
  | { readonly kind: "pad"; readonly key: string };

/** The keys of the spacers before the first drawn run, between two runs and after the last one. */
const GAP_KEYS = [
  ["cv-pad", "cv-before"],
  ["cv-gap-pad", "cv-gap"],
] as const;

/**
 * A windowed body's children (E29-D05 §5.3 G-01: the window plus, at most, the one focused row outside it): each
 * drawn row at its absolute index `r` (1 is the list's first row), the undrawn rows between them held by one spacer
 * per gap, and an empty pad before a spacer where the next row would otherwise sit on a child of the wrong parity,
 * so the zebra follows the list (`leadingSpacers`' rule, for every gap). `drawn` is ascending and within 1..total.
 */
export function bodyParts(drawn: readonly number[], total: number): readonly BodyPart[] {
  const parts: BodyPart[] = [];
  let previous = 0;
  let gap = 0;
  for (const r of drawn) {
    if (r - previous > 1) {
      const [pad, spacer] = GAP_KEYS[Math.min(gap, GAP_KEYS.length - 1)] ?? GAP_KEYS[0];
      // The row lands at child `parts.length + 2` after one spacer: that child's parity must be the row's.
      if (parts.length % 2 !== r % 2) parts.push({ kind: "pad", key: pad });
      parts.push({ kind: "spacer", key: spacer, rows: r - previous - 1 });
      gap += 1;
    }
    parts.push({ kind: "row", r });
    previous = r;
  }
  if (total > previous) parts.push({ kind: "spacer", key: "cv-after", rows: total - previous });
  return parts;
}

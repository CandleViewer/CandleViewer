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

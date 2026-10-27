import type { JSX } from "react";

export interface SkeletonProps {
  /** `chart` is a plain block for a chart-sized slot in a card, a row or a tile; a chart pane uses CMP-029. */
  shape?: "text" | "row" | "card" | "chart";
  /** Text lines (default 3), rows, cards or blocks (default 1); a whole number from 1 to 50. */
  count?: number;
  /** The host's surface: `overlay` (a drawer or a popover loading) moves the blocks one step up (D02 H3). */
  surface?: "base" | "overlay";
}

const MAX_COUNT = 50;
const ROW_CELLS = 3;
const CARD_LINES = 2;

const lines = (n: number): JSX.Element[] =>
  Array.from({ length: n }, (_, i) => <span key={i} className="cv-skeleton__block" />);

/**
 * CMP-015: a loading placeholder, hidden from assistive technology. The host carries `aria-busy="true"` and the
 * words that announce the wait once. The shimmer is CSS only, stops after about 5 s and never runs under reduced
 * motion; the fill is then a static two-tone.
 */
export function Skeleton({
  shape = "text",
  count = shape === "text" ? 3 : 1,
  surface = "base",
}: SkeletonProps): JSX.Element {
  const n = Number.isFinite(count) ? Math.min(MAX_COUNT, Math.max(1, Math.floor(count))) : 1;
  const items =
    shape === "text"
      ? lines(n)
      : Array.from({ length: n }, (_, i) => (
          <span key={i} className={`cv-skeleton__${shape}`}>
            {shape === "row" ? lines(ROW_CELLS) : null}
            {shape === "card" ? lines(CARD_LINES + 1) : null}
            {shape === "chart" ? <span className="cv-skeleton__block" /> : null}
          </span>
        ));
  return (
    <span
      className="cv-skeleton"
      data-cmp="CMP-015"
      data-shape={shape}
      data-surface={surface === "overlay" ? "overlay" : undefined}
      aria-hidden="true"
    >
      {items}
    </span>
  );
}

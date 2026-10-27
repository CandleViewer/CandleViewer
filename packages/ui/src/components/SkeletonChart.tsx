import type { CSSProperties, JSX } from "react";

export interface SkeletonChartProps {
  /** The price pane plus sub-panes (default 1: the price pane alone); a whole number from 1 to 6. */
  paneCount?: number;
}

/** Illustrative candles (D02 §5.1 "Skeleton geometry"): enough for a wide pane; the pane clips the rest. */
const CANDLES = 96;
const AXIS_LABELS = 5;
const MAX_PANES = 6;

/** A deterministic walk, as percentages of the pane height: wick top and height, body top and height. */
const silhouette = Array.from({ length: CANDLES }, (_, i) => {
  const mid = 50 + 22 * Math.sin(i / 7) + 8 * Math.sin(i / 2.3);
  const body = 4 + 6 * Math.abs(Math.sin(i * 1.7));
  const wick = body + 4 + 4 * Math.abs(Math.cos(i * 1.3));
  const pct = (v: number): string => `${v.toFixed(1)}%`;
  return {
    "--cv-wick-top": pct(mid - wick / 2),
    "--cv-wick-h": pct(wick),
    "--cv-body-top": pct(mid - body / 2),
    "--cv-body-h": pct(body),
  } as CSSProperties;
});

const bars = Array.from({ length: CANDLES }, (_, i) => ({
  "--cv-body-h": `${(30 + 50 * Math.abs(Math.sin(i * 0.9))).toFixed(1)}%`,
})) as CSSProperties[];

/**
 * CMP-029: the chart pane's loading placeholder: a candle silhouette with price and time axis blocks, hidden from
 * assistive technology. The chart region carries `aria-busy="true"`, and the host's CMP-038 words sit over it,
 * outside this node. The shimmer is CMP-015's.
 */
export function SkeletonChart({ paneCount = 1 }: SkeletonChartProps): JSX.Element {
  const panes = Number.isFinite(paneCount)
    ? Math.min(MAX_PANES, Math.max(1, Math.floor(paneCount)))
    : 1;
  return (
    <div className="cv-skeleton-chart" data-cmp="CMP-029" aria-hidden="true">
      {Array.from({ length: panes }, (_, p) => (
        <div key={p} className="cv-skeleton-chart__pane" data-sub={p > 0 ? "" : undefined}>
          <div className="cv-skeleton-chart__plot">
            {(p === 0 ? silhouette : bars).map((style, i) => (
              <span key={i} className="cv-skeleton-chart__candle" style={style}>
                {p === 0 ? <span className="cv-skeleton__block cv-skeleton-chart__wick" /> : null}
                <span className="cv-skeleton__block cv-skeleton-chart__body" />
              </span>
            ))}
          </div>
          <div className="cv-skeleton-chart__axis">
            {Array.from({ length: p === 0 ? AXIS_LABELS : 2 }, (_, i) => (
              <span key={i} className="cv-skeleton__block" />
            ))}
          </div>
        </div>
      ))}
      <div className="cv-skeleton-chart__time">
        {Array.from({ length: AXIS_LABELS }, (_, i) => (
          <span key={i} className="cv-skeleton__block" />
        ))}
      </div>
    </div>
  );
}

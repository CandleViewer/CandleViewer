import type { JSX } from "react";

/** The most points a sparkline draws; a longer series keeps its latest window (the rolling-N of Deep Stats). */
export const SPARKLINE_MAX_POINTS = 200;

/** E22's floor for price series: the y-range spans at least ±0.5 % of the first value. */
const DEFAULT_FLOOR_RATIO = 0.005;

/** The line keeps the drawn 0.15–0.85 height margins, so the stroke never touches the box edge. */
const MARGIN = 0.15;

export type SparklineTrend = "up" | "down" | "flat";

export interface SparklineProps {
  /** The series, oldest first. Non-finite values are skipped; more than 200 keep the latest 200. */
  data: readonly number[];
  /** The box in CSS px (the drawn 64 × 16 by default); the line scales with it, the stroke does not. */
  width?: number;
  height?: number;
  /** Strokes net up in `color.buy`, net down in `color.sell`, flat in `color.neutral`; else `text.tertiary`. */
  colorBySign?: boolean;
  /**
   * E22's y-range floor: the domain spans at least ±`floorRatio` × |first value| around the series'
   * midpoint, so a near-flat series draws near-flat. 0.005 (±0.5 %) suits prices; Deep Stats sets its own
   * per data kind; 0 turns the floor off.
   */
  floorRatio?: number;
}

/** The finite values a sparkline draws and names: the latest 200. */
export function sparklineSeries(data: readonly number[]): number[] {
  const finite = data.filter((v) => Number.isFinite(v));
  return finite.slice(-SPARKLINE_MAX_POINTS);
}

/** The net change, first to last, as a percentage of |first| rounded to one decimal; null without one. */
function netChange(series: readonly number[]): { trend: SparklineTrend; pct: string | null } {
  const first = series[0];
  const last = series[series.length - 1];
  if (first === undefined || last === undefined || series.length < 2) {
    return { trend: "flat", pct: null };
  }
  if (first === 0) {
    // No percentage of zero exists: the direction alone.
    return { trend: last > 0 ? "up" : last < 0 ? "down" : "flat", pct: null };
  }
  const pct = ((last - first) / Math.abs(first)) * 100;
  const shown = Math.abs(pct).toFixed(1);
  if (shown === "0.0") return { trend: "flat", pct: null };
  return { trend: pct > 0 ? "up" : "down", pct: `${shown}%` };
}

/**
 * The accessible name, in the catalogue's form: "up 3.2% over 20 bars", "down 3.2% over 20 bars",
 * "unchanged over 20 bars"; "no trend over 1 bar" and "no data" below two points.
 */
export function sparklineSummary(data: readonly number[]): { name: string; trend: SparklineTrend } {
  const series = sparklineSeries(data);
  const n = series.length;
  if (n === 0) return { name: "no data", trend: "flat" };
  const bars = `${n} ${n === 1 ? "bar" : "bars"}`;
  if (n === 1) return { name: `no trend over ${bars}`, trend: "flat" };
  const { trend, pct } = netChange(series);
  if (trend === "flat") return { name: `unchanged over ${bars}`, trend };
  return { name: `${trend}${pct === null ? "" : ` ${pct}`} over ${bars}`, trend };
}

/** The y domain: the series' min..max, widened about its midpoint to E22's floor. */
export function sparklineDomain(
  series: readonly number[],
  floorRatio: number = DEFAULT_FLOOR_RATIO,
): { lo: number; hi: number } {
  let lo = Infinity;
  let hi = -Infinity;
  for (const v of series) {
    if (v < lo) lo = v;
    if (v > hi) hi = v;
  }
  if (lo > hi) return { lo: 0, hi: 0 };
  const floor = 2 * Math.max(0, floorRatio) * Math.abs(series[0] ?? 0);
  if (hi - lo >= floor) return { lo, hi };
  const mid = (lo + hi) / 2;
  return { lo: mid - floor / 2, hi: mid + floor / 2 };
}

const round = (v: number): number => Math.round(v * 100) / 100;

/** The polyline points in the `0 0 width height` box; a zero span draws a level line at mid-height. */
export function sparklinePoints(
  series: readonly number[],
  width: number,
  height: number,
  floorRatio?: number,
): string {
  const n = series.length;
  if (n === 0) return "";
  const { lo, hi } = sparklineDomain(series, floorRatio);
  const span = hi - lo;
  const top = height * MARGIN;
  const band = height * (1 - 2 * MARGIN);
  const yOf = (v: number): number =>
    round(span === 0 ? height / 2 : top + band * (1 - (v - lo) / span));
  // A single point draws as a level stroke across the box.
  if (n === 1) return `0,${yOf(series[0] ?? lo)} ${round(width)},${yOf(series[0] ?? lo)}`;
  const step = width / (n - 1);
  const out: string[] = [];
  for (let i = 0; i < n; i += 1) out.push(`${round(i * step)},${yOf(series[i] ?? lo)}`);
  return out.join(" ");
}

/**
 * CMP-024: a tiny inline trend line. A static `role="img"` named by its trend summary; the line is
 * `aria-hidden`, the data lives in the parent row's DOM-mirror table, and nothing is focusable. It
 * redraws instantly (no draw-in) and the 1.5 px stroke never scales with the box.
 */
export function Sparkline({
  data,
  width = 64,
  height = 16,
  colorBySign = false,
  floorRatio,
}: SparklineProps): JSX.Element {
  const series = sparklineSeries(data);
  const { name, trend } = sparklineSummary(series);
  const points = sparklinePoints(series, width, height, floorRatio);
  return (
    <svg
      className="cv-sparkline"
      data-cmp="CMP-024"
      data-trend={trend}
      data-color-by-sign={colorBySign ? "" : undefined}
      role="img"
      aria-label={name}
      width={width}
      height={height}
      viewBox={`0 0 ${width} ${height}`}
      preserveAspectRatio="none"
      focusable="false"
    >
      {points === "" ? null : (
        <polyline
          className="cv-sparkline__line"
          points={points}
          aria-hidden="true"
          fill="none"
          // The icon-grid weight (slice 2 §4.1 "Data-ink stroke"): a glyph constant, no token.
          strokeWidth={1.5}
          vectorEffect="non-scaling-stroke"
        />
      )}
    </svg>
  );
}

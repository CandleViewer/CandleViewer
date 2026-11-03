import { COPY } from "./copy";
import { parts } from "./text";

/** S-19's word: what a figure the server does not serve reads (W-05, first line). */
export const NOT_CONNECTED: string = parts("W-05")[0] ?? COPY["W-05"];

/** A figure as served: a finite number with its unit, else "Not connected yet", never 0 (R-2). */
export function formatFigure(value: number | null | undefined, unit: string): string {
  if (typeof value !== "number" || !Number.isFinite(value)) return NOT_CONNECTED;
  return `${new Intl.NumberFormat("en-US", { maximumFractionDigits: 2 }).format(value)} ${unit}`;
}

/** A percentage as served; `null`, a missing or a non-finite value reads S-19's word. */
export function formatPercent(value: number | null | undefined): string {
  return formatFigure(value, "%");
}

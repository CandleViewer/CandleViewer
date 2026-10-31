// Wheel and region maths (E11-S04 PR 1, README BQ-99 to BQ-101): DOM-free, shared by the host
// router (main thread) and the worker's gestures, so both sides classify a point the same way.
import { PRICE_GUTTER_PX, TIME_GUTTER_PX } from "../scene/layout-engine.js";

/** `WheelEvent.deltaMode` 1 (lines) in px; mode 2 (pages) is one plot height. */
export const DELTA_LINE_PX = 16;
/** A wheel row's zoom: `exp(-px · k)`, so 100 px down zooms out by e^0.2 (BQ-70: > 1 is in). */
export const WHEEL_ZOOM_PER_PX = 0.002;
/** A time-axis drag's spacing change: `exp(dx · k)`, a drag right widens the bars. */
export const AXIS_DRAG_PER_PX = 0.005;

/** The modifiers column: Shift, Ctrl, Alt, Meta and, on a wheel row, its pan class (BQ-99). */
export const MOD = { shift: 1, ctrl: 2, alt: 4, meta: 8, pan: 16 } as const;

/** Where a point falls in the layout's rects (BQ-101); the corner counts as the price axis. */
export const REGION = { plot: 0, time: 1, price: 2 } as const;
export type Region = (typeof REGION)[keyof typeof REGION];

/** The plot's width for a canvas `width` CSS px wide: the price gutter is not plot (RULED (5)). */
export const plotWidthOf = (width: number): number => Math.max(0, width - PRICE_GUTTER_PX);

/** The plot's height for a canvas `height` CSS px high (the time gutter below it). */
export const plotHeightOf = (height: number): number => Math.max(0, height - TIME_GUTTER_PX);

export function regionAt(x: number, y: number, width: number, height: number): Region {
  if (x >= plotWidthOf(width)) return REGION.price;
  return y >= plotHeightOf(height) ? REGION.time : REGION.plot;
}

/** `deltaMode` 0 / 1 / 2 to px: ×1, ×16, ×the plot height (the ticket's normalisation). */
export function wheelPx(delta: number, mode: number, pageHeight: number): number {
  if (mode === 1) return delta * DELTA_LINE_PX;
  return mode === 2 ? delta * pageHeight : delta;
}

export const wheelFactor = (px: number): number => Math.exp(-px * WHEEL_ZOOM_PER_PX);
export const axisDragFactor = (dxPx: number): number => Math.exp(dxPx * AXIS_DRAG_PER_PX);

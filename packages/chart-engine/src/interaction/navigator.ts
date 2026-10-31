// The keyboard equivalents (E11-S04 PR 2, 26 §3.11, README BQ-106 to BQ-109): which keys the
// chart takes, and what each does to the viewport. Every move is a cut (BQ-110). `←/→` pan by a
// bar (Shift: ten) until E11-S13's data cursor (C-21); `Home` puts bar 0 at the left edge, `End`
// the latest bar `DEFAULT_RIGHT_OFFSET` bars in from the right; `Ctrl+Home` and the plot's
// double-click restore the default spacing, then `End`; `+/-` zoom by 1.1 (Shift: 1.25) about the
// pointer's last plot x, else the latest bar. DOM-free: the host router and the worker share it.
import { DEFAULT_BAR_SPACING, clampSpacing, type ChartViewport } from "../viewport/Viewport.js";
import { indexToScreen } from "../viewport/transform.js";
import { KEY } from "../worker/protocol.js";
import { MOD } from "./wheel.js";

/** Empty bars right of the latest one after `End` (the E11-D03 board's value; O-5 unvalued). */
export const DEFAULT_RIGHT_OFFSET = 12;
/** Bars a `Shift+←/→` pans. */
export const SHIFT_BARS = 10;
/** `+/-` zoom steps (E11-D02 / D06): plain and with Shift. */
export const KEY_ZOOM = 1.1;
export const KEY_ZOOM_SHIFT = 1.25;

export const isSpace = (key: string, code: string): boolean => key === " " || code === "Space";

/**
 * The `KEY` code for a keydown, or 0 when the chart leaves it to the page: Alt and Meta chords
 * (browser history, replay ticks, the OS) and Ctrl chords but `Ctrl+Home` (replay's `Ctrl+←/→`,
 * browser zoom `Ctrl+=/-`). Space is `isSpace`'s, not a code here.
 */
export function keyCode(key: string, code: string, mods: number): number {
  if ((mods & (MOD.alt | MOD.meta)) !== 0) return 0;
  if ((mods & MOD.ctrl) !== 0) return key === "Home" ? KEY.home : 0;
  if (key === "ArrowLeft") return KEY.left;
  if (key === "ArrowRight") return KEY.right;
  if (key === "Home") return KEY.home;
  if (key === "End") return KEY.end;
  if (key === "+" || key === "=" || code === "NumpadAdd") return KEY.zoomIn;
  if (key === "-" || key === "_" || code === "NumpadSubtract") return KEY.zoomOut;
  return 0;
}

/** `End`: the latest bar `DEFAULT_RIGHT_OFFSET` bars in (≤ visibleBars − 1), at `spacing`. */
export function toEnd(vp: ChartViewport, spacing = vp.barSpacing): boolean {
  const visible = vp.plotWidth / clampSpacing(spacing);
  const offset = Math.min(DEFAULT_RIGHT_OFFSET, visible - 1);
  return vp.scrollTo(vp.map.length + offset - visible, spacing);
}

/**
 * `Ctrl+Home` and the plot's double-click: the default spacing, then `End`, and every locked pane
 * back to auto (E11-S05 BQ-119; `Ctrl+Home` stays a time reset, BQ-123).
 */
export function resetView(vp: ChartViewport): boolean {
  const moved = toEnd(vp, DEFAULT_BAR_SPACING);
  return vp.restoreAuto() || moved;
}

/** The `+/-` anchor: the pointer's last plot x, else the latest bar, else the right edge. */
export function zoomAnchor(vp: ChartViewport, pointerX: number): number {
  if (Number.isFinite(pointerX)) return pointerX;
  const n = vp.map.length;
  return n > 0 ? indexToScreen(vp, n - 1) : vp.plotWidth;
}

/** Applies key `code` with `mods`; true when the viewport changed. */
export function navigate(vp: ChartViewport, code: number, mods: number, pointerX: number): boolean {
  const shift = (mods & MOD.shift) !== 0;
  const ctrl = (mods & MOD.ctrl) !== 0;
  switch (code) {
    case KEY.left:
    case KEY.right:
      return vp.scrollTo(vp.leftIndex + (shift ? SHIFT_BARS : 1) * (code === KEY.left ? -1 : 1));
    case KEY.home:
      return ctrl ? resetView(vp) : vp.scrollTo(0);
    case KEY.end:
      return toEnd(vp);
    case KEY.zoomIn:
    case KEY.zoomOut: {
      if (ctrl || (mods & MOD.meta) !== 0) return false; // browser and app zoom
      const step = shift ? KEY_ZOOM_SHIFT : KEY_ZOOM;
      return vp.zoomAt(zoomAnchor(vp, pointerX), code === KEY.zoomIn ? step : 1 / step);
    }
    default:
      return false;
  }
}

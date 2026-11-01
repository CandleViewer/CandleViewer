// The axis stops' keys (E11-S06, README BQ-194 to BQ-196; E11-D02 §7.1, §7.2): a key row's `y`
// slot names the stop it was pressed on (0 plot, 1 time axis, 2 price axis). On the price axis
// `↑/↓` compress / expand the range 10 % about its centre (`Shift`: 25 %), `PageUp/PageDown`
// shift it by half its height, each engaging the lock, and `Home` restores auto-fit. On the time
// axis `←/→` pan 10 % of the width (`Shift`: one width), `+/-` zoom ×1.1 (`Shift`: ×1.25) about
// the centre, `Home` fits every loaded bar, `End` goes live and `Ctrl+Home` restores the default
// spacing. Each returns the `SAY` code its announcement uses; `none` when nothing changed. Step
// sizes are constants until SCR-031 exposes them. DOM-free: the host stop and the worker share it.
import { SAY } from "../axes/axis-model.js";
import { DEFAULT_BAR_SPACING, type ChartViewport } from "../viewport/Viewport.js";
import { KEY } from "../worker/protocol.js";
import { KEY_ZOOM, KEY_ZOOM_SHIFT, toEnd } from "./navigator.js";
import { MOD } from "./wheel.js";

/** A key row's target, in its `y` slot (BQ-194). */
export const TARGET = { plot: 0, time: 1, price: 2 } as const;
export const PRICE_KEY_STEP = 0.1;
export const PRICE_KEY_STEP_SHIFT = 0.25;
export const PRICE_KEY_PAGE = 0.5;
export const TIME_KEY_PAN = 0.1;

const NAMED: Readonly<Record<string, number>> = {
  ArrowUp: KEY.up,
  ArrowDown: KEY.down,
  PageUp: KEY.pageUp,
  PageDown: KEY.pageDown,
  ArrowLeft: KEY.left,
  ArrowRight: KEY.right,
  Home: KEY.home,
  End: KEY.end,
};

/** An axis stop's keydown as a `KEY` code; 0 leaves it to the page (Alt, Meta, Ctrl chords). */
export function axisKeyCode(key: string, code: string, mods: number): number {
  if ((mods & (MOD.alt | MOD.meta)) !== 0) return 0;
  if ((mods & MOD.ctrl) !== 0) return key === "Home" ? KEY.home : 0;
  if (key === "+" || key === "=" || code === "NumpadAdd") return KEY.zoomIn;
  if (key === "-" || key === "_" || code === "NumpadSubtract") return KEY.zoomOut;
  return NAMED[key] ?? 0;
}

/** A price-axis key on `pane` (BQ-195). */
export function priceAxisKey(vp: ChartViewport, pane: number, code: number, mods: number): number {
  const p = vp.panes[pane];
  if (p === undefined || !(p.plotHeight > 0)) return SAY.none;
  const wasAuto = p.autoScale;
  const step = (mods & MOD.shift) !== 0 ? PRICE_KEY_STEP_SHIFT : PRICE_KEY_STEP;
  const mid = p.plotTop + p.plotHeight / 2;
  let changed = false;
  if (code === KEY.up) changed = vp.zoomPrice(pane, mid, 1 / (1 - step));
  else if (code === KEY.down) changed = vp.zoomPrice(pane, mid, 1 - step);
  else if (code === KEY.pageUp || code === KEY.pageDown) {
    vp.setScale(pane, { auto: false });
    const dy = (code === KEY.pageUp ? 1 : -1) * p.plotHeight * PRICE_KEY_PAGE;
    changed = vp.panPrice(pane, dy) || wasAuto;
  } else if (code === KEY.home) {
    return vp.setScale(pane, { auto: true }) ? SAY.priceAuto : SAY.none;
  }
  if (!changed) return SAY.none;
  return wasAuto ? SAY.priceLocked : SAY.priceRange;
}

/** A time-axis key (BQ-196). */
export function timeAxisKey(vp: ChartViewport, code: number, mods: number): number {
  const w = vp.plotWidth;
  const shift = (mods & MOD.shift) !== 0;
  switch (code) {
    case KEY.left:
    case KEY.right: {
      const dx = (code === KEY.left ? 1 : -1) * (shift ? w : w * TIME_KEY_PAN);
      return vp.pan(dx) ? SAY.timeRange : SAY.none;
    }
    case KEY.zoomIn:
    case KEY.zoomOut: {
      const f = shift ? KEY_ZOOM_SHIFT : KEY_ZOOM;
      return vp.zoomAt(w / 2, code === KEY.zoomIn ? f : 1 / f) ? SAY.spacing : SAY.none;
    }
    case KEY.home:
      if ((mods & MOD.ctrl) !== 0) {
        return vp.zoomAt(w, DEFAULT_BAR_SPACING / vp.barSpacing) ? SAY.defaultSpacing : SAY.none;
      }
      return vp.map.length > 0 && vp.scrollTo(0, w / vp.map.length) ? SAY.fitted : SAY.none;
    case KEY.end:
      return toEnd(vp) ? SAY.live : SAY.none;
    default:
      return SAY.none;
  }
}

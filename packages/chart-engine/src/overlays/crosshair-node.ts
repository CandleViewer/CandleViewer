// The crosshair's lines (E11-S07, CMP-190; E11-D02 §7.3, E11-D06 §5.2): one `line` batch in the
// main pane's foreground layer, written on the CPU in the line program's space (device px, y up)
// only when the intersection, the plot, the DPR or the theme moved. Both lines are dashed 4 / 4 ×
// the hairline width in `color.crosshair`, snapped with `snapStroke` so each covers whole device
// pixels. A remote (synced) crosshair is a dashed vertical at `opacity.muted`, drawn only while
// there is no local cursor. Hiding is instant (BQ-16, G-row: the 100 ms fade needs a per-node
// alpha uniform). The node is its own vertex source, so the 2D painter draws the same instances.
// The ring grows only with the plot (doubling); a steady or moving frame allocates nothing.
import { parseHex } from "../axes/grid.js";
import { PROGRAM } from "../scene/instance-layout.js";
import { ContentNode } from "../scene/node.js";
import type { BatchSink } from "../scene/pool.js";
import { hairlineDevicePx, snapStroke } from "../viewport/pixels.js";

export const CROSSHAIR_NODE_ID = "main/crosshair";
export const CROSSHAIR_TOKEN = "color.crosshair";
/** The remote crosshair's alpha token (a number as text); 0.7 when the theme has none. */
export const MUTED_TOKEN = "opacity.muted";
export const MUTED_DEFAULT = 0.7;
const STRIDE = 9;
const DASH = 4;
/** dpr, deviceH, plot x, y, w, h, local, x, y, remote x, stack y, h. */
const SIG = 12;

type Theme = Readonly<Record<string, string>>;

/** The plot rect in CSS px, `[x, y, w, h]` (the layout engine's `Rect`). */
export type PlotRect = readonly [number, number, number, number];

export class CrosshairNode extends ContentNode {
  /** The instance ring (`VertexSource`): empty until the first line. */
  data = new Float32Array(0);
  readonly head = 0;
  readonly stride = STRIDE;
  count = 0;
  /** RGBA, local then remote. */
  readonly colors = new Float32Array(8);
  /** Rewrites (tests and the bench). */
  writes = 0;
  private palette: Theme | null = null;
  private readonly sig = new Float64Array(SIG).fill(Number.NaN);
  private readonly cur = new Float64Array(SIG);
  private width = 1;
  private dpr = 1;
  private deviceH = 0;

  /**
   * The lines for a local cursor at (`x`, `y`) when `local`, else the remote vertical at
   * `remoteX` (NaN: none), clipped to `plot`; CSS px over a store `deviceH` device px high.
   * E11-S09 (BQ-23): the vertical runs through `stack`'s rows (every pane), the horizontal only
   * through the hovered pane's `plot`: still one ring, one draw. True when the instances changed
   * (the caller re-uploads the ring).
   */
  write(
    theme: Theme,
    dpr: number,
    deviceH: number,
    plot: PlotRect,
    local: boolean,
    x: number,
    y: number,
    remoteX: number,
    stack: PlotRect = plot,
  ): boolean {
    const c = this.cur;
    c[0] = dpr;
    c[1] = deviceH;
    c[2] = plot[0];
    c[3] = plot[1];
    c[4] = plot[2];
    c[5] = plot[3];
    c[6] = local ? 1 : 0;
    c[7] = local ? x : Number.NaN;
    c[8] = local ? y : Number.NaN;
    c[9] = local ? Number.NaN : remoteX;
    c[10] = stack[1];
    c[11] = stack[3];
    let same = theme === this.palette;
    for (let i = 0; i < SIG; i += 1) {
      if (!Object.is(c[i], this.sig[i])) same = false;
      this.sig[i] = c[i] as number;
    }
    if (same) return false;
    const [px, py, pw, ph] = plot;
    const vx = local ? x : remoteX;
    const v = vx >= px && vx <= px + pw;
    const h = local && y >= py && y <= py + ph;
    if (!v && !h) {
      // Nothing to draw: an empty ring stays as it is (no re-upload, no collect for the caller).
      const had = this.count > 0;
      this.count = 0;
      return had;
    }
    if (theme !== this.palette) this.setTheme(theme);
    this.writes += 1;
    this.count = 0;
    this.dpr = dpr;
    this.deviceH = deviceH;
    this.width = hairlineDevicePx(dpr);
    const sy = stack[1];
    const sh = stack[3];
    this.reserve(dpr, pw, Math.max(ph, sh));
    if (v) this.vLine(vx, sy, sy + sh, local ? 0 : 4);
    if (h) this.hLine(y, px, px + pw, 0);
    return true;
  }

  /** Forces the next `write` to rewrite (a restored context re-uploads the ring). */
  invalidate(): void {
    this.palette = null;
  }

  collect(sink: BatchSink): boolean {
    const e = sink.append();
    e.nodeId = this.id;
    e.program = PROGRAM.line;
    e.texture = 0;
    e.first = 0;
    e.count = this.count;
    return true;
  }

  private setTheme(theme: Theme): void {
    this.palette = theme;
    const k = this.colors;
    parseHex(theme[CROSSHAIR_TOKEN], k, 0);
    const m = Number(theme[MUTED_TOKEN]);
    const muted = Number.isFinite(m) && m > 0 && m <= 1 ? m : MUTED_DEFAULT;
    k.copyWithin(4, 0, 4);
    k[7] = (k[3] as number) * muted;
  }

  /** Room for both lines over the plot: grows (doubling) only when the plot or DPR does. */
  private reserve(dpr: number, w: number, h: number): void {
    const period = 2 * DASH * this.width;
    const need = (Math.ceil((w * dpr) / period) + Math.ceil((h * dpr) / period) + 4) * STRIDE;
    if (need <= this.data.length) return;
    let n = Math.max(STRIDE * 128, this.data.length);
    while (n < need) n *= 2;
    this.data = new Float32Array(n);
  }

  /** A dashed vertical at CSS x from y0 to y1 (top to bottom), the dashes from the top. */
  private vLine(x: number, y0: number, y1: number, color: number): void {
    const d = this.dpr;
    const xx = snapStroke(x, d, this.width) * d;
    const top = this.deviceH - y0 * d;
    const bottom = this.deviceH - y1 * d;
    const dash = DASH * this.width;
    for (let y = top; y > bottom; y -= 2 * dash) {
      this.put(xx, Math.max(bottom, y - dash), xx, y, color);
    }
  }

  /** A dashed horizontal at CSS y from x0 to x1, the dashes from the left. */
  private hLine(y: number, x0: number, x1: number, color: number): void {
    const d = this.dpr;
    const yy = this.deviceH - snapStroke(y, d, this.width) * d;
    const right = x1 * d;
    const dash = DASH * this.width;
    for (let x = x0 * d; x < right; x += 2 * dash) {
      this.put(x, yy, Math.min(right, x + dash), yy, color);
    }
  }

  private put(x0: number, y0: number, x1: number, y1: number, color: number): void {
    let o = this.count * STRIDE;
    if (o + STRIDE > this.data.length) return; // reserve() sized it; never reached
    const f = this.data;
    f[o++] = x0;
    f[o++] = y0;
    f[o++] = x1;
    f[o++] = y1;
    f[o++] = this.width;
    for (let i = 0; i < 4; i += 1) f[o++] = this.colors[color + i] as number;
    this.count += 1;
  }
}

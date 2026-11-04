// Gridlines and axis rules (E11-S06, README BQ-192, BQ-193; E11-D02 §4): one `line` batch in the
// main pane's background layer, written on the CPU in the line program's space (device px, y up)
// whenever the axes change, never per frame otherwise. Every line is a hairline of
// `hairlineDevicePx(dpr)` device px snapped with `snapStroke`, so it covers whole device pixels at
// any DPR (no grey fringe); boundary lines are dashed 4 / 4 × that width. The node is its own
// vertex source (the backend reads `data`, `head`, `stride`), so the 2D painter draws the very
// same instances. Colours come from theme tokens (hex), parsed once per theme.
import { PROGRAM } from "../scene/instance-layout.js";
import { ContentNode } from "../scene/node.js";
import type { BatchSink } from "../scene/pool.js";
import { hairlineDevicePx, snapStroke } from "../viewport/pixels.js";

export const GRID_NODE_ID = "main/axes-grid";
const STRIDE = 9;
/** BQ-193: minor, major, boundary and axis-rule tokens, in `TIER` order. */
export const GRID_TOKENS = [
  "color.grid.line",
  "color.border.default",
  "color.text.tertiary",
  "color.border.default",
] as const;
export const TIER = { minor: 0, major: 1, boundary: 2, rule: 3 } as const;
const DASH = 4;

/** `#rgb`, `#rrggbb` or `#rrggbbaa` into `out` at `at` (0..1); anything else is mid grey. */
export function parseHex(css: string | undefined, out: Float32Array, at: number): void {
  const m = /^#([0-9a-f]{3}|[0-9a-f]{6}|[0-9a-f]{8})$/i.exec(css ?? "")?.[1] ?? "808080";
  const hex = m.length === 3 ? m.replace(/./g, "$&$&") : m;
  for (let i = 0; i < 4; i += 1) {
    const byte = hex.slice(2 * i, 2 * i + 2);
    out[at + i] = byte === "" ? 1 : Number.parseInt(byte, 16) / 255;
  }
}

export class AxisGrid extends ContentNode {
  /**
   * The instance ring (`VertexSource`): empty until the first line, so an axis-less chart holds
   * no GPU bytes; it grows by doubling, and a new identity re-uploads in full.
   */
  data = new Float32Array(0);
  readonly head = 0;
  readonly stride = STRIDE;
  count = 0;
  /** RGBA per `TIER`. */
  readonly colors = new Float32Array(16);
  private dpr = 1;
  private deviceH = 0;
  private width = 1;

  /** Starts a rewrite for a store `deviceH` device px high at `dpr`. */
  begin(dpr: number, deviceH: number): void {
    this.count = 0;
    this.dpr = dpr;
    this.deviceH = deviceH;
    this.width = hairlineDevicePx(dpr);
  }

  /** A horizontal hairline at CSS y from x0 to x1. */
  hLine(y: number, x0: number, x1: number, tier: number): void {
    const d = this.dpr;
    const yy = this.deviceH - snapStroke(y, d, this.width) * d;
    this.put(x0 * d, yy, x1 * d, yy, tier);
  }

  /** A vertical hairline at CSS x from y0 to y1 (top to bottom), dashed when `dashed`. */
  vLine(x: number, y0: number, y1: number, tier: number, dashed = false): void {
    const d = this.dpr;
    const xx = snapStroke(x, d, this.width) * d;
    const top = this.deviceH - y0 * d;
    const bottom = this.deviceH - y1 * d;
    if (!dashed) {
      this.put(xx, bottom, xx, top, tier);
      return;
    }
    const dash = DASH * this.width;
    for (let y = top; y > bottom; y -= 2 * dash) {
      this.put(xx, Math.max(bottom, y - dash), xx, y, tier);
    }
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

  private put(x0: number, y0: number, x1: number, y1: number, tier: number): void {
    let o = this.count * STRIDE;
    if (o + STRIDE > this.data.length) {
      const next = new Float32Array(Math.max(STRIDE * 128, this.data.length * 2));
      next.set(this.data);
      this.data = next;
    }
    const f = this.data;
    f[o++] = x0;
    f[o++] = y0;
    f[o++] = x1;
    f[o++] = y1;
    f[o++] = this.width;
    for (let i = 0; i < 4; i += 1) f[o++] = this.colors[tier * 4 + i] as number;
    this.count += 1;
  }
}

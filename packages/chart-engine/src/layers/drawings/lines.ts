// The `drawing-line` instance ring (E14-T03 slice 2): line-type records (segment, ray, line, hline,
// vline, polyline) as one instance per drawn segment, in chart space (int bar index and tick plus
// fractions, the pane block re-projects them), so a pan or zoom rewrites nothing. Writes compare
// first: only the instances whose floats changed are reported for upload (a drag: one instance).
// Width is device px (style.width × dpr), rebuilt on a DPR change only. DOM- and GL-free.
import type { VertexSource } from "../../gl/buffers.js";
import { attributeOffset, INSTANCE_LAYOUTS, PROGRAM } from "../../scene/instance-layout.js";
import type { DrawingRecord } from "./project.js";

export const LINE_STRIDE = (INSTANCE_LAYOUTS[PROGRAM.drawingLine] as { stride: number }).stride;
const P0 = attributeOffset(PROGRAM.drawingLine, "a_p0");
const FRAC = attributeOffset(PROGRAM.drawingLine, "a_frac");
const STYLE = attributeOffset(PROGRAM.drawingLine, "a_style");
const COLOR = attributeOffset(PROGRAM.drawingLine, "a_color");
/** An anchor's int part stays inside the int32 uniform base; past it the line is off screen. */
const INT_MAX = 2 ** 30;
const EXTEND = { segment: 0, polyline: 0, ray: 1, line: 2, hline: 2, vline: 2 } as const;

/** Instances a record draws: one per segment of a visible line-type kind, else none. */
export function lineCount(r: DrawingRecord): number {
  const { kind, visible } = r.input;
  if (visible === false || !Object.hasOwn(EXTEND, kind)) return 0;
  return kind === "polyline" ? r.idx.length - 1 : 1;
}

export class LineInstances implements VertexSource {
  data = new Float32Array(LINE_STRIDE * 64);
  ints = new Int32Array(this.data.buffer);
  readonly head = 0;
  readonly stride = LINE_STRIDE;
  count = 0;
  /** Instances changed by the last `encode`: [lo, hi), empty when lo >= hi. */
  lo = 0;
  hi = 0;
  private dirty = false;

  /** Writes every record's instances in draw order; a pan never calls this. */
  encode(order: readonly DrawingRecord[], dpr: number): void {
    let total = 0;
    for (let i = 0; i < order.length; i += 1) total += lineCount(order[i] as DrawingRecord);
    this.lo = Infinity;
    this.hi = 0;
    if (total * LINE_STRIDE > this.data.length) this.grow(total);
    let at = 0;
    for (let i = 0; i < order.length; i += 1) {
      const r = order[i] as DrawingRecord;
      const n = lineCount(r);
      const kind = r.input.kind as keyof typeof EXTEND;
      for (let s = 0; s < n; s += 1) {
        // hline / vline: a second point one bar right / one tick up, extended both ways.
        const b = kind === "polyline" ? s + 1 : kind === "hline" || kind === "vline" ? 0 : 1;
        const di = kind === "hline" ? 1 : 0;
        const dt = kind === "vline" ? 1 : 0;
        this.write(at, r, s, b, di, dt, EXTEND[kind], dpr);
        at += 1;
      }
    }
    this.count = at;
    if (this.lo > this.hi) this.lo = this.hi = 0;
  }

  private grow(total: number): void {
    let cap = this.data.length / LINE_STRIDE;
    while (cap < total) cap *= 2;
    this.data = new Float32Array(cap * LINE_STRIDE); // a new identity: the GPU re-uploads in full
    this.ints = new Int32Array(this.data.buffer);
  }

  private write(
    i: number,
    r: DrawingRecord,
    a: number,
    b: number,
    di: number,
    dt: number,
    extend: number,
    dpr: number,
  ): void {
    const o = i * LINE_STRIDE;
    this.dirty = false;
    this.anchor(o + P0, o + FRAC, r.idx[a] as number, r.tick[a] as number);
    this.anchor(o + P0 + 2, o + FRAC + 2, (r.idx[b] as number) + di, (r.tick[b] as number) + dt);
    const { colour, width, dash } = r.input.style;
    this.f(o + STYLE, width * dpr);
    this.f(o + STYLE + 1, dash);
    this.f(o + STYLE + 2, extend);
    this.f(o + STYLE + 3, 0);
    for (let c = 0; c < 4; c += 1) this.f(o + COLOR + c, ((colour >>> (24 - 8 * c)) & 255) / 255);
    if (!this.dirty) return;
    this.lo = Math.min(this.lo, i);
    this.hi = Math.max(this.hi, i + 1);
  }

  /** (bar index, tick) as clamped int parts at `io` and float fractions at `fo`. */
  private anchor(io: number, fo: number, idx: number, tick: number): void {
    const ix = Math.min(INT_MAX, Math.max(-INT_MAX, Math.floor(idx)));
    const it = Math.floor(tick);
    this.i(io, ix);
    this.i(io + 1, it);
    this.f(fo, Math.abs(idx - ix) < 1 ? idx - ix : 0);
    this.f(fo + 1, tick - it);
  }

  private f(o: number, v: number): void {
    const was = this.data[o];
    this.data[o] = v;
    if (this.data[o] !== was) this.dirty = true;
  }

  private i(o: number, v: number): void {
    if (this.ints[o] !== v) this.dirty = true;
    this.ints[o] = v;
  }
}

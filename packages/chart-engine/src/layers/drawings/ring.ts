// The drawings layer's instance rings (E14-T03): what `drawing-line` and `drawing-fill` share. A
// ring is a `VertexSource` of fixed-stride instances whose every word is written compare-first,
// so an encode reports only the instances that changed ([lo, hi), uploaded alone: a drag is one
// instance) and a pan, which never encodes, uploads nothing. Anchors are chart space: an int
// (bar index, tick) and their fractions' float bits, one ivec4 the pane block re-projects (BQ-75).
// DOM- and GL-free.
import type { AttributeLayout, VertexSource } from "../../scene/gpu-types.js";
import { INSTANCE_LAYOUTS } from "../../scene/instance-layout.js";

/** An anchor's int part stays inside the int32 uniform base; past it the shape is off screen. */
const INT_MAX = 2 ** 30;

/** A program's VAO int bindings: every `INSTANCE_LAYOUTS` row at location = its row. */
export function attributesOf(program: number): AttributeLayout {
  const layout = INSTANCE_LAYOUTS[program];
  return {
    stride: layout?.stride ?? 0,
    ints: (layout?.attributes ?? []).map(([, offset, size], at) => [at, offset, size] as const),
  };
}

export class InstanceRing implements VertexSource {
  data: Float32Array;
  ints: Int32Array;
  readonly head = 0;
  count = 0;
  /** Instances changed by the last encode: [lo, hi), empty when lo >= hi. */
  lo = 0;
  hi = 0;
  private dirty = false;

  constructor(readonly stride: number) {
    this.data = new Float32Array(stride * 64);
    this.ints = new Int32Array(this.data.buffer);
  }

  /** Starts an encode of `total` instances: capacity first (a new array uploads in full). */
  protected begin(total: number): void {
    this.lo = Infinity;
    this.hi = 0;
    if (total * this.stride <= this.data.length) return;
    let cap = this.data.length / this.stride;
    while (cap < total) cap *= 2;
    this.data = new Float32Array(cap * this.stride);
    this.ints = new Int32Array(this.data.buffer);
  }

  /** Ends it: `count` instances, the changed range normalised. */
  protected end(count: number): void {
    this.count = count;
    if (this.lo > this.hi) this.lo = this.hi = 0;
  }

  /** Before an instance's words. */
  protected open(): void {
    this.dirty = false;
  }

  /** After them: instance `i` joins the changed range if any word differed. */
  protected close(i: number): void {
    if (!this.dirty) return;
    this.lo = Math.min(this.lo, i);
    this.hi = Math.max(this.hi, i + 1);
  }

  /** One `ivec4` anchor at `o`: the clamped int (bar index, tick), then their fractions' bits. */
  protected anchor(o: number, idx: number, tick: number): void {
    const ix = Math.min(INT_MAX, Math.max(-INT_MAX, Math.floor(idx)));
    const it = Math.floor(tick);
    this.i(o, ix);
    this.i(o + 1, it);
    this.f(o + 2, Math.abs(idx - ix) < 1 ? idx - ix : 0);
    this.f(o + 3, tick - it);
  }

  /** 0xRRGGBBAA as four floats in 0..1 at `o`. */
  protected rgba(o: number, colour: number): void {
    for (let c = 0; c < 4; c += 1) this.f(o + c, ((colour >>> (24 - 8 * c)) & 255) / 255);
  }

  protected f(o: number, v: number): void {
    const was = this.data[o];
    this.data[o] = v;
    if (this.data[o] !== was) this.dirty = true;
  }

  protected i(o: number, v: number): void {
    if (this.ints[o] !== v) this.dirty = true;
    this.ints[o] = v;
  }
}

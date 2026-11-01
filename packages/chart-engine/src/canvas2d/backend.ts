// The Canvas 2D backend (E11-T05, 26 §3.4, README BQ-84 to BQ-88): `degraded-2d`'s peer of
// `GLBackend` behind the same `RenderBackend`, so the runtime never knows which one draws (S3).
// It walks `drawList[0, count)`, buckets every instance by (program, colour, line width) and
// paints each bucket with one path and one `fill` or `stroke` (BQ-95: O(buckets), not O(bars)).
// Buckets flush at each layer boundary, so the layer order holds. A pan uploads nothing: the
// instance rings are read where they live at draw time. No allocation per frame once warm.
import type { BackendFailure, RenderBackend } from "../gl/backend.js";
import type { VertexSource } from "../gl/buffers.js";
import type { PaneUniformSource } from "../gl/submit.js";
import { DrawTrace } from "../gl/trace.js";
import type { RetainedBatch } from "../scene/batch-builder.js";
import { attributeOffset, INSTANCE_LAYOUTS, PROGRAM } from "../scene/instance-layout.js";
import { LABEL_STRIDE, TextBatch } from "../text/text-batch.js";
import type { PaneUniforms } from "../viewport/transform.js";
import type { Ctx2DLike } from "./ctx2d.js";
import { type PaintArgs, PAINTERS } from "./painters.js";

interface Slot {
  readonly source: VertexSource;
  /** The int32 view of `of` (the bar-cell's integer cell), remade when the ring reallocates. */
  ints: Int32Array;
  of: Float32Array | null;
}

interface Bucket {
  readonly program: number;
  readonly css: string;
  /** Line width in `u_viewport` px; 0 for a fill. */
  readonly width: number;
  /** (draw-list index, float offset) pairs of this frame's run. */
  refs: Int32Array;
  n: number;
  run: number;
}

/** Distinct styles kept warm; past this the table is dropped and rebuilt (a theme churn guard). */
export const MAX_BUCKETS = 1024;
/** Each program's colour offset (`sdf-text` has none and is never bucketed: its colour is 0). */
const COLOR = INSTANCE_LAYOUTS.map(
  (l) => l.attributes.find(([name]) => name === "a_color")?.[1] ?? 0,
);
const WIDTH = attributeOffset(PROGRAM.line, "a_width");
/**
 * A line width in 1/16 px, in [1, 65535]: the bucket key and the stroked width agree, and a
 * hairline, NaN or huge width never becomes 0 (a canvas ignores `lineWidth = 0` and keeps the last).
 */
const sixteenths = (v: number | undefined): number =>
  v === undefined || !Number.isFinite(v) ? 1 : Math.min(Math.max(Math.round(v * 16), 1), 65535);
const EMPTY = new Int32Array(0);
/**
 * The host-loaded CSS face the 2D label painter sets. No generic family: the engine never names a
 * fallback; if the host has not loaded the face, the browser's substitution is the host's (C-104).
 */
export const FONT_2D = '"JetBrains Mono"';
const ALIGN = ["left", "center", "right"] as const;

const byte = (v: number | undefined): number => {
  const b = Math.round((v ?? 0) * 255);
  return b > 255 ? 255 : b > 0 ? b : 0; // NaN and negatives clamp to 0
};

export class Canvas2DBackend implements RenderBackend {
  readonly trace = new DrawTrace();
  /** Labels not painted because the context has no `fillText` (C-104, internal). */
  labelsSkipped = 0;
  readonly failure: BackendFailure | null = null;
  readonly drawsIn2d = true;
  readonly loss = null;
  readonly gpuMemoryMbEstimate = 0;
  /** Unused: 2D draws label strings, not glyphs (the GL text uniforms' slot, BQ-267). */
  readonly textUniforms = new Float32Array(8);
  private panes: PaneUniformSource | null = null;
  private background: string | undefined;
  private readonly slots = new Map<string, Slot>();
  private readonly buckets = new Map<number, Bucket>();
  /** This run's buckets in first-seen order. */
  private readonly order: Bucket[] = [];
  /** Per draw-list index, this frame: the batch's slot and pane block. */
  private readonly frameSlots: (Slot | undefined)[] = [];
  private readonly frameBlocks: (PaneUniforms | null)[] = [];
  private run = 1;
  /** The last label size and its CSS font: rebuilt only when the size changes. */
  private fontPx = -1;
  private font = "";
  private readonly args: PaintArgs = {
    data: new Float32Array(0),
    ints: EMPTY,
    at: 0,
    block: null,
    w: 0,
    h: 0,
  };

  /** `ctx` null: no 2D context on this canvas, so nothing is drawn (the runtime still reports). */
  constructor(private readonly ctx: Ctx2DLike | null) {}

  /** A no-op: the 2D path reads each ring at draw time, so a pan or patch uploads nothing. */
  uploadSubRange(): void {}

  takeUploadedBytes(): number {
    return 0;
  }

  setPaneUniforms(source: PaneUniformSource | null): void {
    this.panes = source;
  }

  /** Mirrors `GlBuffers.attach`: the first ring a node is given is the one it keeps. */
  attach(nodeId: string, source: VertexSource): void {
    if (!this.slots.has(nodeId)) this.slots.set(nodeId, { source, ints: EMPTY, of: null });
  }

  setBackground(css: string | undefined): void {
    this.background = css;
  }

  /** No texture in 2D: label runs paint with `fillText` from their strings (E11-S11 PR B). */
  uploadAtlas(): void {}

  dispose(): void {
    this.slots.clear();
    this.buckets.clear();
    this.frameSlots.length = 0; // no released node's slot outlives the backend
  }

  /** A padded `bw` × `bh` store is clipped to its exact top-left `w` × `h` (BQ-149). */
  submit(
    list: readonly RetainedBatch[],
    count: number,
    w: number,
    h: number,
    bw = w,
    bh = h,
  ): null {
    const ctx = this.ctx;
    const clip = ctx?.clip !== undefined && (bw !== w || bh !== h) ? ctx : null;
    if (clip !== null) {
      clip.save?.();
      clip.beginPath();
      clip.rect(0, 0, w, h);
      clip.clip?.();
    }
    try {
      return this.draw(list, count, w, h);
    } finally {
      clip?.restore?.();
    }
  }

  private draw(list: readonly RetainedBatch[], count: number, w: number, h: number): null {
    const trace = this.trace;
    trace.begin();
    const ctx = this.ctx;
    if (ctx === null) return null;
    ctx.clearRect(0, 0, w, h);
    const bg = this.background;
    if (bg !== undefined && bg !== "") {
      ctx.fillStyle = bg;
      ctx.fillRect(0, 0, w, h);
    }
    this.args.w = w;
    this.args.h = h;
    let layer = Number.NaN;
    for (let i = 0; i < count; i += 1) {
      const b = list[i] as RetainedBatch; // i < count <= list.length
      if (b.layer !== layer) {
        this.flush(ctx);
        layer = b.layer;
      }
      const slot = this.slots.get(b.nodeId);
      this.frameSlots[i] = slot;
      if (slot === undefined) continue; // no attached ring (the layers attach, E12/E18): no draw
      const block = this.panes === null ? null : this.panes(b);
      this.frameBlocks[i] = block;
      const layout = INSTANCE_LAYOUTS[b.program];
      const painter = PAINTERS[b.program] ?? null;
      const src = slot.source;
      if (src instanceof TextBatch && src.mode === "labels" && b.program === PROGRAM.sdfText) {
        this.flush(ctx); // the layer's shapes first: labels sit on top of them
        this.labels(ctx, src, Math.min(b.count, src.labels));
        trace.draws += 1;
        if (trace.enabled) trace.nodes.push(b.nodeId);
        continue;
      }
      const { data, head, stride } = src;
      // sdf-text (BQ-88), a cell batch with no pane block, or a ring narrower than its layout.
      if (painter === null || layout === undefined || stride < layout.stride) {
        trace.skipped += 1;
        continue;
      }
      if (b.program === PROGRAM.barCell && block === null) {
        trace.skipped += 1;
        continue;
      }
      if (slot.of !== data) {
        slot.ints = new Int32Array(data.buffer, data.byteOffset, data.length);
        slot.of = data;
      }
      const capacity = Math.floor(data.length / stride);
      const n = Math.min(b.count, capacity);
      for (let j = 0; j < n; j += 1) {
        const at = ((head + b.first + j) % capacity) * stride;
        this.push(this.bucketOf(b.program, data, at), i, at);
      }
      if (trace.enabled) trace.nodes.push(b.nodeId);
    }
    this.flush(ctx);
    return null;
  }

  /** A label batch's strings with `fillText` (C-104): axes and drawings; cells stay reduced. */
  private labels(ctx: Ctx2DLike, t: TextBatch, n: number): void {
    if (ctx.fillText === undefined) {
      this.labelsSkipped += n; // a context with no text API: counted, never silent
      return;
    }
    // The text state is put back after, so no later painter inherits it (no save/restore: the
    // padded-store clip owns that pair).
    const { font, textAlign, textBaseline, fillStyle } = ctx;
    ctx.textBaseline = "middle";
    for (let i = 0; i < n; i += 1) {
      const o = i * LABEL_STRIDE;
      const px = t.lab[o + 2] ?? 0;
      if (px !== this.fontPx) {
        this.fontPx = px;
        this.font = `${px}px ${FONT_2D}`;
      }
      ctx.font = this.font;
      ctx.textAlign = ALIGN[Math.round((t.lab[o + 3] ?? 0) * 2)] ?? "left";
      ctx.fillStyle = t.inks[i] ?? "";
      ctx.fillText(t.texts[i] ?? "", t.lab[o] ?? 0, t.lab[o + 1] ?? 0);
    }
    if (font !== undefined) ctx.font = font;
    if (textAlign !== undefined) ctx.textAlign = textAlign;
    if (textBaseline !== undefined) ctx.textBaseline = textBaseline;
    ctx.fillStyle = fillStyle;
  }

  /** The instance's bucket, joined to this run on first use. */
  private bucketOf(program: number, data: Float32Array, at: number): Bucket {
    const c = at + (COLOR[program] ?? 0);
    const rgba = byte(data[c]) * 0x1000000 + byte(data[c + 1]) * 0x10000;
    const packed = rgba + byte(data[c + 2]) * 0x100 + byte(data[c + 3]);
    const width = program === PROGRAM.line ? sixteenths(data[at + WIDTH]) : 0;
    const key = (program * 65536 + width) * 2 ** 32 + packed;
    let bucket = this.buckets.get(key);
    if (bucket === undefined) {
      if (this.buckets.size >= MAX_BUCKETS) this.buckets.clear();
      const css = `rgba(${byte(data[c])}, ${byte(data[c + 1])}, ${byte(data[c + 2])}, ${byte(data[c + 3]) / 255})`;
      bucket = { program, css, width: width / 16, refs: new Int32Array(64), n: 0, run: 0 };
      this.buckets.set(key, bucket);
    }
    if (bucket.run !== this.run) {
      bucket.run = this.run;
      bucket.n = 0;
      this.order.push(bucket);
    }
    return bucket;
  }

  /** Appends a ref pair, doubling the bucket's array when full (amortised: none once warm). */
  private push(b: Bucket, i: number, at: number): void {
    if (b.n + 2 > b.refs.length) {
      const next = new Int32Array(b.refs.length * 2);
      next.set(b.refs);
      b.refs = next;
    }
    b.refs[b.n] = i;
    b.refs[b.n + 1] = at;
    b.n += 2;
  }

  /** Paints this run's buckets: one path and one fill or stroke each. */
  private flush(ctx: Ctx2DLike): void {
    const trace = this.trace;
    const a = this.args;
    let program = -1;
    for (let k = 0; k < this.order.length; k += 1) {
      const bucket = this.order[k] as Bucket;
      const paint = PAINTERS[bucket.program];
      if (paint === null || paint === undefined || bucket.n === 0) continue;
      ctx.beginPath();
      for (let r = 0; r < bucket.n; r += 2) {
        const i = bucket.refs[r] ?? 0;
        const slot = this.frameSlots[i] as Slot; // set when the ref was pushed
        a.data = slot.source.data;
        a.ints = slot.ints;
        a.at = bucket.refs[r + 1] ?? 0;
        a.block = this.frameBlocks[i] ?? null;
        paint(ctx, a);
      }
      if (bucket.program === PROGRAM.line) {
        const v = a.block?.floats[4] ?? a.w;
        ctx.lineWidth = bucket.width * (v > 0 ? a.w / v : 0);
        ctx.strokeStyle = bucket.css;
        ctx.stroke();
      } else {
        ctx.fillStyle = bucket.css;
        ctx.fill();
      }
      trace.draws += 1;
      if (bucket.program !== program) {
        program = bucket.program;
        trace.programSwitches += 1;
      }
    }
    this.order.length = 0;
    this.run += 1;
  }
}

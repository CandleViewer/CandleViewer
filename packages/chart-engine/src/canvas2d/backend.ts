// The Canvas 2D backend (E11-T05, 26 §3.4, README BQ-84 to BQ-88): `degraded-2d`'s peer of
// `GLBackend` behind the same `RenderBackend`, so the runtime never knows which one draws (S3).
// It walks `drawList[0, count)`, buckets every instance by (program, colour, line width) and
// paints each bucket with one path and one `fill` or `stroke` (BQ-95: O(buckets), not O(bars)).
// Buckets flush at each layer boundary, so the layer order holds. A pan uploads nothing: the
// instance rings are read where they live at draw time. No allocation per frame once warm.
import type { BackendFailure, RenderBackend } from "../gl/backend.js";
import type { VertexSource } from "../gl/buffers.js";
import type { BatchUniforms, BatchUniformSource, PaneUniformSource } from "../gl/submit.js";
import { CANDLE_DIR, CANDLE_STRIDE } from "../layers/candle/ring.js";
import { PALETTE } from "../layers/candle/palette.js";
import { DASH_LUT } from "../gl/shaders/drawing-line.js";
import { DrawTrace } from "../gl/trace.js";
import type { RetainedBatch } from "../scene/batch-builder.js";
import { attributeOffset, INSTANCE_LAYOUTS, PROGRAM } from "../scene/instance-layout.js";
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
const STYLE = attributeOffset(PROGRAM.drawingLine, "a_style");
const FILL = attributeOffset(PROGRAM.drawingFill, "a_fill");
const STROKE = attributeOffset(PROGRAM.drawingFill, "a_stroke");
const FSTYLE = attributeOffset(PROGRAM.drawingFill, "a_style");
const SOLID: readonly number[] = [];

/** A `drawing-line` bucket's dash index and the [dash, gap] it strokes with (set per flush). */
interface Dash {
  readonly index: number;
  readonly pattern: number[];
}
/**
 * A line width in 1/16 px, in [1, 65535]: the bucket key and the stroked width agree, and a
 * hairline, NaN or huge width never becomes 0 (a canvas ignores `lineWidth = 0` and keeps the last).
 */
const sixteenths = (v: number | undefined): number =>
  v === undefined || !Number.isFinite(v) ? 1 : Math.min(Math.max(Math.round(v * 16), 1), 65535);
const EMPTY = new Int32Array(0);

const byte = (v: number | undefined): number => {
  const b = Math.round((v ?? 0) * 255);
  return b > 255 ? 255 : b > 0 ? b : 0; // NaN and negatives clamp to 0
};

export class Canvas2DBackend implements RenderBackend {
  readonly trace = new DrawTrace();
  readonly failure: BackendFailure | null = null;
  readonly drawsIn2d = true;
  readonly loss = null;
  readonly gpuMemoryMbEstimate = 0;
  private panes: PaneUniformSource | null = null;
  private own: BatchUniformSource | null = null;
  private background: string | undefined;
  private readonly slots = new Map<string, Slot>();
  private readonly buckets = new Map<number, Bucket>();
  /** This run's buckets in first-seen order. */
  private readonly order: Bucket[] = [];
  /** Per draw-list index, this frame: the batch's slot and pane block. */
  private readonly frameSlots: (Slot | undefined)[] = [];
  private readonly frameBlocks: (PaneUniforms | null)[] = [];
  private readonly frameBatches: (BatchUniforms | null)[] = [];
  private run = 1;
  /** Per `drawing-line` bucket: kept apart, so the other buckets' shape and path are unchanged. */
  private readonly dashes = new WeakMap<Bucket, Dash>(); // dies with its bucket
  /** The last stroke set round caps or a dash (`drawing-line`). */
  private dashed = false;
  private readonly args: PaintArgs = {
    data: new Float32Array(0),
    ints: EMPTY,
    at: 0,
    block: null,
    batch: null,
    sub: 0,
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

  setBatchUniforms(source: BatchUniformSource | null): void {
    this.own = source;
  }

  /** Mirrors `GlBuffers.attach`: the first ring a node is given is the one it keeps. */
  attach(nodeId: string, source: VertexSource): void {
    if (!this.slots.has(nodeId)) this.slots.set(nodeId, { source, ints: EMPTY, of: null });
  }

  setBackground(css: string | undefined): void {
    this.background = css;
  }

  dispose(): void {
    this.slots.clear();
    this.buckets.clear();
    this.frameSlots.length = 0; // no released node's slot outlives the backend
  }

  submit(list: readonly RetainedBatch[], count: number, w: number, h: number): null {
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
      const { data, head, stride } = slot.source;
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
      if (b.program === PROGRAM.candle) {
        const blk = this.own === null ? null : this.own(b);
        this.frameBatches[i] = blk;
        if (blk === null || block === null) trace.skipped += 1;
        else this.candles(blk, slot.ints, i);
        if (trace.enabled) trace.nodes.push(b.nodeId);
        continue;
      }
      const capacity = Math.floor(data.length / stride);
      const n = Math.min(b.count, capacity);
      if (b.program === PROGRAM.drawingFill) {
        for (let j = 0; j < n; j += 1)
          this.fillRefs(data, ((head + b.first + j) % capacity) * stride, i);
      } else if (b.program === PROGRAM.drawingLine) {
        // E14-T03: decided once per batch, so the other programs' per-instance path is unchanged.
        for (let j = 0; j < n; j += 1) {
          const at = ((head + b.first + j) % capacity) * stride;
          this.push(this.drawingBucket(data, at), i, at);
        }
      } else {
        for (let j = 0; j < n; j += 1) {
          const at = ((head + b.first + j) % capacity) * stride;
          this.push(this.bucketOf(b.program, data, at), i, at);
        }
      }
      if (trace.enabled) trace.nodes.push(b.nodeId);
    }
    this.flush(ctx);
    return null;
  }

  /**
   * E12-S06: a candle part's live bars, slot for slot through the batch's (head, mask, n), into
   * the palette rows' buckets: the wick, or the body by direction; an up body's tint is a second
   * ref (`sub` 1) in the tint bucket, after its outline's.
   */
  private candles(blk: BatchUniforms, ints: Int32Array, i: number): void {
    const part = blk.ints[0] ?? 0; // scalar locals: no per-frame array
    const head = blk.ints[1] ?? 0;
    const mask = blk.ints[2] ?? 0;
    const n = blk.ints[3] ?? 0;
    const pal = blk.palette;
    for (let j = 0; j < n; j += 1) {
      const at = ((head + j) & mask) * CANDLE_STRIDE;
      if (at < 0 || at + CANDLE_STRIDE > ints.length) break; // a ring shorter than its block
      const dir = ((ints[at + 4] ?? 0) >> 4) & 3;
      let row: number = PALETTE.wick;
      if (part === 1 && dir === CANDLE_DIR.up) row = PALETTE.up;
      else if (part === 1 && dir === CANDLE_DIR.down) row = PALETTE.down;
      this.push(this.bucketOf(PROGRAM.candle, pal, row * 4, 0), i, at * 2);
      if (part === 1 && dir === CANDLE_DIR.up) {
        this.push(this.bucketOf(PROGRAM.candle, pal, PALETTE.upTint * 4, 0), i, at * 2 + 1);
      }
    }
  }

  /** The instance's bucket, joined to this run on first use. */
  private bucketOf(
    program: number,
    data: Float32Array,
    at: number,
    colour = COLOR[program] ?? 0,
  ): Bucket {
    const c = at + colour;
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

  /**
   * `drawing-line`'s bucket: keyed by its dash too, above every program's key (below 2^53: (16 +
   * 2) × 2^16 × 2^32), its width the instance's device px.
   */
  private drawingBucket(data: Float32Array, at: number): Bucket {
    const index = Math.min(Math.max(Math.round(data[at + STYLE + 1] ?? 0), 0), 2);
    const width = sixteenths(data[at + STYLE]);
    return this.styled(
      PROGRAM.drawingLine,
      data,
      at + (COLOR[PROGRAM.drawingLine] ?? 0),
      width,
      index,
      16 + index,
    );
  }

  /**
   * A drawings bucket (E14-T03): `drawing-line` strokes (slots 16-18 by dash), `drawing-fill`
   * fills (19, width 0) and ellipse rings (20-22 by dash): keys stay below 2^53 for any slot < 32.
   */
  private styled(
    program: number,
    data: Float32Array,
    c: number,
    width: number,
    index: number,
    slot: number,
  ): Bucket {
    const rgba = byte(data[c]) * 0x1000000 + byte(data[c + 1]) * 0x10000;
    const packed = rgba + byte(data[c + 2]) * 0x100 + byte(data[c + 3]);
    const key = (slot * 65536 + width) * 2 ** 32 + packed;
    let bucket = this.buckets.get(key);
    if (bucket === undefined) {
      if (this.buckets.size >= MAX_BUCKETS) this.buckets.clear();
      // The drawings' colours are premultiplied (flatten opacity, BQ-4); CSS takes straight alpha.
      const al = data[c + 3] ?? 0;
      const un = (v: number | undefined): number => byte(al > 0 ? (v ?? 0) / al : 0);
      const css = `rgba(${un(data[c])}, ${un(data[c + 1])}, ${un(data[c + 2])}, ${byte(al) / 255})`;
      bucket = { program, css, width: width / 16, refs: new Int32Array(64), n: 0, run: 0 };
      this.buckets.set(key, bucket);
      if (width > 0) this.dashes.set(bucket, { index, pattern: [0, 0] });
    }
    if (bucket.run !== this.run) {
      bucket.run = this.run;
      bucket.n = 0;
      this.order.push(bucket);
    }
    return bucket;
  }

  /** `drawing-fill`'s instance: its fill (ref sub 0) when visible, an ellipse's ring (sub 1). */
  private fillRefs(data: Float32Array, at: number, i: number): void {
    if ((data[at + FILL + 3] ?? 0) > 0)
      this.push(this.styled(PROGRAM.drawingFill, data, at + FILL, 0, 0, 19), i, at * 2);
    if ((data[at + FSTYLE] ?? 0) !== 1) return;
    const index = Math.min(Math.max(Math.round(data[at + FSTYLE + 2] ?? 0), 0), 2);
    const width = sixteenths(data[at + FSTYLE + 1]);
    this.push(
      this.styled(PROGRAM.drawingFill, data, at + STROKE, width, index, 20 + index),
      i,
      at * 2 + 1,
    );
  }

  /**
   * Round caps and the LUT's pattern for a `drawing-line` bucket, so a dash is its core plus a cap
   * at each end, as the shader's capsule; `null` after one: a `line` gets butt caps, no dash.
   */
  private dash(ctx: Ctx2DLike, bucket: Bucket | null, width: number): void {
    const d = bucket === null ? undefined : this.dashes.get(bucket);
    this.dashed = d !== undefined;
    ctx.lineCap = d === undefined ? "butt" : "round";
    const core = DASH_LUT[d?.index ?? 0]?.[0] ?? 0;
    const period = DASH_LUT[d?.index ?? 0]?.[1] ?? 0;
    if (d !== undefined) {
      d.pattern[0] = core * width;
      d.pattern[1] = (period - core) * width;
    }
    ctx.setLineDash?.(d !== undefined && period > 0 ? d.pattern : SOLID);
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
      // A candle or drawing-fill ref carries its sub-part in the low bit (per bucket, not per ref).
      const candle = bucket.program === PROGRAM.candle;
      const twin = candle || bucket.program === PROGRAM.drawingFill;
      for (let r = 0; r < bucket.n; r += 2) {
        const i = bucket.refs[r] ?? 0;
        const slot = this.frameSlots[i] as Slot; // set when the ref was pushed
        a.data = slot.source.data;
        a.ints = slot.ints;
        const at = bucket.refs[r + 1] ?? 0;
        a.at = twin ? at >> 1 : at;
        a.sub = twin ? at & 1 : 0;
        a.batch = candle ? (this.frameBatches[i] ?? null) : null;
        a.block = this.frameBlocks[i] ?? null;
        paint(ctx, a);
      }
      if (bucket.program === PROGRAM.line) {
        const v = a.block?.floats[4] ?? a.w;
        ctx.lineWidth = bucket.width * (v > 0 ? a.w / v : 0);
        ctx.strokeStyle = bucket.css;
        if (this.dashed) this.dash(ctx, null, 0);
        ctx.stroke();
      } else if (bucket.program === PROGRAM.drawingLine || bucket.width > 0) {
        const v = a.block?.floats[4] ?? a.w;
        const width = bucket.width * (v > 0 ? a.w / v : 0);
        ctx.lineWidth = width;
        ctx.strokeStyle = bucket.css;
        this.dash(ctx, bucket, width);
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

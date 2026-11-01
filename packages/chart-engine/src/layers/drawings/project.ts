// The drawings node (E14-T03 slice 1): records keep anchors in chart space (µs time, tick) with
// each bar index cached against the bar map, so a pan or zoom (TRANSFORM) rewrites none (slice 2's
// shader re-projects from the pane uniforms) and a drag (DATA) re-indexes only what it replaced.
// Bounds go through the shared transform (E11-S03). No GL calls (26 §3.1); DOM-free (C-2.16).
import { Dirty } from "../../scene/dirty.js";
import type { FrameCtx } from "../../scene/frame-context.js";
import { ContentNode } from "../../scene/node.js";
import type { MutationRange } from "../../model/counters.js";
import { PROGRAM } from "../../scene/instance-layout.js";
import type { BatchSink } from "../../scene/pool.js";
import { indexAt, indexToScreen, priceToScreen } from "../../viewport/transform.js";
import type { IndexTimeMap, ViewportState } from "../../viewport/types.js";
import { MAX_DRAWINGS, type SetDrawings } from "./model.js";
import { toRecord, type DrawingRecord } from "./record.js";
import { FillInstances } from "./fills.js";
import { LineInstances } from "./lines.js";
import { DrawingSet } from "./set.js";

export { toRecord, type DrawingRecord } from "./record.js";

/** Widens a chart-space box [idxMin, tickMin, idxMax, tickMax] to (i, k). */
function corner(box: Float64Array, i: number, k: number): void {
  box[0] = Math.min(box[0] as number, i);
  box[1] = Math.min(box[1] as number, k);
  box[2] = Math.max(box[2] as number, i);
  box[3] = Math.max(box[3] as number, k);
}

/** Caches each anchor's bar index under `map` and the chart-space box. */
export function reindex(r: DrawingRecord, map: IndexTimeMap, stamp: number): void {
  const { idx, tick, box } = r;
  box[0] = box[1] = Infinity;
  box[2] = box[3] = -Infinity;
  for (let a = 0; a < idx.length; a += 1) {
    idx[a] = indexAt(map, r.t[a] as number);
    corner(box, idx[a] as number, tick[a] as number);
  }
  if (r.input.kind === "band") {
    // The parallelogram's fourth corner: p2 + (p1 - p0).
    const i3 = (idx[2] as number) + (idx[1] as number) - (idx[0] as number);
    corner(box, i3, (tick[2] as number) + (tick[1] as number) - (tick[0] as number));
  }
  r.stamp = stamp;
}

/** The scratch a pass writes: [x0, y0, x1, y1]; then the plot as [width, top, bottom]. */
const SEG = new Float64Array(4);
const PLOT = new Float64Array(3);
/** A direction shorter than this is a point: no 1/dx blows up to ±Infinity or NaN. */
const EPS = 1e-9;
/** Bounds are clamped to ±1e7 CSS px before the Float32 write: always finite. */
const LIMIT = 1e7;
// NaN, which validated anchors cannot produce, would clamp to -LIMIT: a visible record's box is
// always finite, and only a hidden one is NaN (the documented "not on screen").
const px = (v: number): number => (v > LIMIT ? LIMIT : v >= -LIMIT ? v : -LIMIT);
function seg(x0: number, y0: number, x1: number, y1: number): void {
  SEG[0] = x0;
  SEG[1] = y0;
  SEG[2] = x1;
  SEG[3] = y1;
}

/**
 * a + s·d from where it enters the plot (s <= 0, an extended line only) to where it leaves it
 * (s >= 1): the segment a..a+d itself is always kept, so its anchors stay inside.
 */
function extend(ax: number, ay: number, dx: number, dy: number, both: boolean): void {
  const w = PLOT[0] as number;
  const top = PLOT[1] as number;
  const bottom = PLOT[2] as number;
  let hi = Infinity;
  let lo = -Infinity;
  if (Math.abs(dx) > EPS) {
    hi = Math.max(-ax / dx, (w - ax) / dx);
    lo = Math.min(-ax / dx, (w - ax) / dx);
  }
  if (Math.abs(dy) > EPS) {
    hi = Math.min(hi, Math.max((top - ay) / dy, (bottom - ay) / dy));
    lo = Math.max(lo, Math.min((top - ay) / dy, (bottom - ay) / dy));
  }
  const end = Number.isFinite(hi) ? Math.max(1, hi) : 1;
  const start = both && Number.isFinite(lo) ? Math.min(0, lo) : 0;
  seg(ax + start * dx, ay + start * dy, ax + end * dx, ay + end * dy);
}

/**
 * A record's screen box on pane 0 (until E11-S09) in CSS px at `out[o..o+4]`, padded by half the
 * stroke; NaN when hidden. Every anchor of a visible drawing projects inside it.
 */
export function screenBounds(vp: ViewportState, r: DrawingRecord, out: Float32Array, o: number) {
  const { kind, visible, style } = r.input;
  if (visible === false) return void out.fill(Number.NaN, o, o + 4);
  const { idx, tick, box } = r;
  PLOT[0] = vp.plotWidth;
  PLOT[1] = vp.panes[0]?.plotTop ?? 0;
  PLOT[2] = PLOT[1] + (vp.panes[0]?.plotHeight ?? 0);
  const x0 = indexToScreen(vp, idx[0] as number);
  if (kind === "hline") {
    const y = priceToScreen(vp, 0, tick[0] as number);
    seg(0, y, PLOT[0], y);
  } else if (kind === "vline") seg(x0, PLOT[1], x0, PLOT[2]);
  else if (kind === "ray" || kind === "line") {
    const ay = priceToScreen(vp, 0, tick[0] as number);
    const dy = priceToScreen(vp, 0, tick[1] as number) - ay;
    extend(x0, ay, indexToScreen(vp, idx[1] as number) - x0, dy, kind === "line");
  } else {
    // Monotone on both axes in every scale mode, so the box's corners bound every anchor.
    const y0 = priceToScreen(vp, 0, box[1] as number);
    const y1 = priceToScreen(vp, 0, box[3] as number);
    seg(indexToScreen(vp, box[0] as number), y0, indexToScreen(vp, box[2] as number), y1);
  }
  const pad = style.width / 2;
  out[o] = px(Math.min(SEG[0] as number, SEG[2] as number) - pad);
  out[o + 1] = px(Math.min(SEG[1] as number, SEG[3] as number) - pad);
  out[o + 2] = px(Math.max(SEG[0] as number, SEG[2] as number) + pad);
  out[o + 3] = px(Math.max(SEG[1] as number, SEG[3] as number) + pad);
}

/**
 * The `drawing-fill` batch's node (slice 3): the batch builder keeps one batch per node, so the
 * fills ride a sibling attached right after its `DrawingsNode`, which encodes for both and marks
 * it DATA; its own update does nothing, its collect reads the owner's fill ring.
 */
export class DrawingFillsNode extends ContentNode {
  constructor(
    id: string,
    readonly fills: FillInstances,
  ) {
    super(id);
  }

  collect(sink: BatchSink): boolean {
    const e = sink.append();
    e.nodeId = this.id;
    e.program = PROGRAM.drawingFill;
    e.texture = 0;
    e.first = 0;
    e.count = this.fills.count;
    return true;
  }
}

export class DrawingsNode extends ContentNode {
  readonly set = new DrawingSet<DrawingRecord>(toRecord);
  /** [x0, y0, x1, y1] per drawing in `set.order`, CSS px; reused, never reallocated. */
  readonly bounds = new Float32Array(4 * MAX_DRAWINGS);
  /** Set by every bounds pass, cleared by the runtime's post (≤ 1 a frame). */
  boundsDirty = false;
  /** Counters: a pan re-indexes no record, a one-drawing drag one a frame. */
  reindexed = 0;
  boundsPasses = 0;
  /** The `drawing-line` ring (slice 2): rewritten on DATA, a re-index or a DPR change only. */
  readonly lines = new LineInstances();
  /** The `drawing-fill` ring and its batch's node (slice 3), attached after this one. */
  readonly fills = new FillInstances();
  readonly fillNode: DrawingFillsNode;
  /** Encodes so far: a pan adds none. */
  encodes = 0;
  /** Where a ring's changed instance range goes: the runtime's `BatchBuilder.patch`. */
  onRange: ((nodeId: string, r: MutationRange) => void) | null = null;
  private readonly range = { op: "patch" as const, from: 0, to: 0, indexShift: 0 };
  private map: IndexTimeMap | null = null;
  private mapLength = -1;
  private stamp = 0;
  private dpr = 0;

  constructor(id: string) {
    super(id);
    this.fillNode = new DrawingFillsNode(`${id}/fills`, this.fills);
  }

  /** A `setDrawings`: DATA on this node only; a refusal changes nothing (E14-X01 DR29). */
  apply(cmd: SetDrawings): string | null {
    const why = this.set.apply(cmd);
    if (why === null) this.dirty |= Dirty.DATA;
    return why;
  }

  override update(ctx: FrameCtx): void {
    const vp = ctx.viewport;
    if (vp.map !== this.map || vp.map.length !== this.mapLength) {
      this.map = vp.map;
      this.mapLength = vp.map.length;
      this.stamp += 1; // a new bar map re-indexes every record once
    }
    const order = this.set.order;
    let encode = (this.dirty & (Dirty.DATA | Dirty.STYLE)) !== 0 || vp.dpr !== this.dpr;
    for (let i = 0; i < order.length; i += 1) {
      const r = order[i] as DrawingRecord;
      if (r.stamp !== this.stamp) {
        reindex(r, vp.map, this.stamp);
        this.reindexed += 1;
        encode = true;
      }
      screenBounds(vp, r, this.bounds, 4 * i);
    }
    this.boundsPasses += 1;
    this.boundsDirty = true;
    if (!encode) return; // TRANSFORM alone: the shader re-projects from the pane block
    this.dpr = vp.dpr;
    this.lines.encode(order, vp.dpr);
    this.fills.encode(order, vp.dpr);
    this.encodes += 1;
    this.fillNode.dirty |= Dirty.DATA; // collected after this node: its count is this encode's
    this.report(this.id, this.lines.lo, this.lines.hi);
    this.report(this.fillNode.id, this.fills.lo, this.fills.hi);
  }

  private report(nodeId: string, lo: number, hi: number): void {
    if (lo >= hi) return;
    this.range.from = lo;
    this.range.to = hi;
    this.onRange?.(nodeId, this.range);
  }

  /** One `drawing-line` batch for every line-type drawing (26 §3.10: ≤ 3 draws for the layer). */
  collect(sink: BatchSink): boolean {
    const e = sink.append();
    e.nodeId = this.id;
    e.program = PROGRAM.drawingLine;
    e.texture = 0;
    e.first = 0;
    e.count = this.lines.count;
    return true;
  }
}

// The drawings adapter (E14-T04, #359; BQ-01 (a)): a drawing as the engine knows it before E14-T03's
// `DrawingInput` lands (`DrawingPickSource`: id, tool, anchors in (µs, tick), width, z, lock,
// visibility, fib levels), registered into the E11-S08 object index as a `Pickable`. Tools map to
// a family (22 `DrawingTool`, open-ended: an unknown tool is its anchors' polyline). Families the
// index tests natively (segment, ray, box, horizontal and vertical lines) take its own geometry;
// the others (extended lines, ellipses, fib level sets, channels, polylines) are bucketed by their
// box and measured by a `hitTest` over anchors projected into a per-drawing scratch, so a pick
// allocates nothing. Rays and extended lines are clipped to the plot first (ticket Technical
// notes). A hidden drawing is kept here but never in the index; one handle per anchor.
import { indexAt, priceToScreen, timeAt, timeToScreen } from "../viewport/transform.js";
import { clipToBox, distToEllipse, distToSegment } from "./geometry.js";
import type { Anchor, ObjectIndex, PickGeometry } from "./ObjectIndex.js";

/**
 * The narrow seam T03's `DrawingInput` maps onto (BQ-01, ruling 6653052281). Internal to `src/hit/`
 * (not a root export, not in 26 §8): it only carries T04's tests until E14-T03 PR 1, then collapses
 * into one `DrawingInput` to `Pickable` function. It is not a third drawing model. `id` is the
 * E14-T02 store's stable local `Handle`, never the server id.
 */
export interface DrawingPickSource {
  readonly id: string;
  readonly tool: string;
  /** Flat `[time µs, tick, …]`. */
  readonly anchors: ArrayLike<number>;
  readonly widthPx: number;
  readonly zIndex: number;
  readonly locked: boolean;
  readonly visible: boolean;
  readonly levels?: readonly number[];
}

const [POLYLINE, RAY, LINE, HLINE, VLINE, BOX, ELLIPSE, FIB, CHANNEL, POINT] = [
  0, 1, 2, 3, 4, 5, 6, 7, 8, 9,
];

/** 22 `DrawingTool` → family (a Map: no prototype keys); others are their anchors' polyline. */
const TOOLS = new Map<string, number>();
for (const [family, tools] of [
  [RAY, "ray"],
  [LINE, "extended_line"],
  [HLINE, "horizontal_line"],
  [VLINE, "vertical_line"],
  [BOX, "rectangle measure price_range date_range long_position short_position"],
  [ELLIPSE, "ellipse"],
  [FIB, "fib_retracement fib_extension"],
  [CHANNEL, "parallel_channel"],
] as const) {
  for (const tool of tools.split(" ")) TOOLS.set(tool, family);
}
export const DEFAULT_FIB_LEVELS = [0, 0.236, 0.382, 0.5, 0.618, 0.786, 1] as const;
/** A one-anchor drawing with no line of its own (a text note) picks within this radius. */
export const POINT_RADIUS_PX = 6;

export interface DrawingRecord {
  readonly id: string;
  readonly tool: string;
  readonly family: number;
  /** Flat `[t, p, …]`, owned here; drags rewrite it in place (same length). */
  anchors: Float64Array;
  widthPx: number;
  zIndex: number;
  locked: boolean;
  visible: boolean;
  levels: readonly number[];
  /** Projected anchors `[x, y, …]` in CSS px, rewritten by every measure. */
  readonly xy: Float64Array;
  readonly hitTest: ((x: number, y: number, tol: number) => number) | undefined;
}

/** The clip box (the plot, padded by the threshold) and the clip output, reused. */
const CLIP: [number, number, number, number] = [0, 0, 0, 0];
const SEG = new Float64Array(4);

export class DrawingAdapter {
  private readonly records = new Map<string, DrawingRecord>();

  constructor(private readonly index: ObjectIndex) {}

  get size(): number {
    return this.records.size;
  }

  get(id: string): DrawingRecord | undefined {
    return this.records.get(id);
  }

  /** Every drawing, registration order (Map order); the caller must not mutate it. */
  all(): IterableIterator<DrawingRecord> {
    return this.records.values();
  }

  /** Registers or replaces a drawing; a hidden one leaves the index. Throws on bad anchors. */
  upsert(src: DrawingPickSource): DrawingRecord {
    const n = src.anchors.length;
    if (n < 2 || n % 2 !== 0) throw new RangeError("chart-engine: a drawing needs anchors");
    const family = TOOLS.get(src.tool) ?? (n === 2 ? POINT : POLYLINE);
    const old = this.records.get(src.id);
    if (old !== undefined) this.index.unregister(src.id);
    const rec: DrawingRecord = {
      id: src.id,
      tool: src.tool,
      family,
      anchors: Float64Array.from(src.anchors),
      widthPx: src.widthPx,
      zIndex: src.zIndex,
      locked: src.locked,
      visible: src.visible,
      levels: src.levels ?? DEFAULT_FIB_LEVELS,
      xy: new Float64Array(n),
      hitTest: undefined,
    };
    const custom = family === LINE || family === ELLIPSE || family === FIB;
    const measured = custom || family === CHANNEL || (family === POLYLINE && n > 4);
    const full: DrawingRecord = measured
      ? { ...rec, hitTest: (x, y, tol) => this.distance(full, x, y, tol) }
      : rec;
    this.records.set(src.id, full);
    try {
      if (full.visible) this.register(full);
    } catch (e) {
      this.records.delete(src.id);
      throw e;
    }
    return full;
  }

  remove(id: string): boolean {
    this.index.unregister(id);
    return this.records.delete(id);
  }

  /** New anchors (same count) for a registered drawing: the index re-buckets it. */
  setAnchors(rec: DrawingRecord, anchors: ArrayLike<number>): void {
    rec.anchors.set(anchors);
    if (rec.visible) this.index.move(rec.id, this.geometry(rec), this.handles(rec));
  }

  /** Screen-space anchors `[x, y, …]` (the handle centres) into `rec.xy`. */
  project(rec: DrawingRecord): Float64Array {
    const vp = this.index.viewport;
    const pane = this.index.pane;
    const a = rec.anchors;
    for (let i = 0; i < a.length; i += 2) {
      rec.xy[i] = timeToScreen(vp, a[i] as number);
      rec.xy[i + 1] = priceToScreen(vp, pane, a[i + 1] as number);
    }
    return rec.xy;
  }

  /** The body distance in CSS px (Infinity off it); `tol` pads the clip box only. */
  distance(rec: DrawingRecord, x: number, y: number, tol: number): number {
    const xy = this.project(rec);
    this.clipBox(tol + rec.widthPx);
    const n = xy.length;
    const ax = xy[0] as number;
    const ay = xy[1] as number;
    const bx = xy[2] as number;
    const by = xy[3] as number;
    switch (rec.family) {
      case LINE:
        return clipToBox(ax, ay, bx, by, -Infinity, Infinity, CLIP, SEG) ? segDist(x, y) : Infinity;
      case ELLIPSE:
        return distToEllipse(x, y, ax, ay, bx, by);
      case FIB:
        return this.fibDistance(rec, x, y);
      case CHANNEL: {
        // Under three anchors (mid-creation) the channel is its first edge.
        const cx = n >= 6 ? (xy[4] as number) : ax;
        const cy = n >= 6 ? (xy[5] as number) : ay;
        const d0 = distToSegment(x, y, ax, ay, bx, by);
        return Math.min(d0, distToSegment(x, y, cx, cy, cx + bx - ax, cy + by - ay));
      }
      default: {
        let d = Infinity;
        for (let i = 0; i + 3 < n; i += 2) {
          const s = distToSegment(
            x,
            y,
            xy[i] as number,
            xy[i + 1] as number,
            xy[i + 2] as number,
            xy[i + 3] as number,
          );
          if (s < d) d = s;
        }
        return d;
      }
    }
  }

  private register(rec: DrawingRecord): void {
    this.index.registerPickable({
      id: rec.id,
      kind: "drawing",
      paneId: this.index.paneId,
      zIndex: rec.zIndex,
      geometry: this.geometry(rec),
      widthPx: rec.widthPx,
      handles: this.handles(rec),
      ...(rec.hitTest !== undefined && { hitTest: rec.hitTest }),
    });
  }

  /** Re-shows (registers) or hides (unregisters) a drawing; the record is kept. */
  setVisible(rec: DrawingRecord, visible: boolean): void {
    if (rec.visible === visible) return;
    rec.visible = visible;
    if (visible) this.register(rec);
    else this.index.unregister(rec.id);
  }

  private handles(rec: DrawingRecord): Anchor[] {
    const out: Anchor[] = [];
    for (let i = 0; i < rec.anchors.length; i += 2) {
      out.push({ t: rec.anchors[i] as number, p: rec.anchors[i + 1] as number });
    }
    return out;
  }

  /** The index's bucketing shape: native where it measures exactly, else the anchors' box. */
  private geometry(rec: DrawingRecord): PickGeometry {
    const a = rec.anchors;
    const [t0, p0] = [a[0] as number, a[1] as number];
    const [t1, p1] = a.length >= 4 ? [a[2] as number, a[3] as number] : [t0, p0];
    switch (rec.family) {
      case POINT:
        return { type: "point", t: t0, p: p0, radiusPx: POINT_RADIUS_PX };
      case HLINE:
        return { type: "hline", p: p0 };
      case VLINE:
        return { type: "vline", t: t0 };
      case RAY:
      case LINE: // unbounded either way: the always-tested list, measured by the clip
        return { type: "ray", t0, p0, t1, p1 };
      case BOX:
        return a.length === 4 ? { type: "rect", t0, p0, t1, p1 } : this.extent(rec);
      case POLYLINE:
        return a.length === 4 ? { type: "segment", t0, p0, t1, p1 } : this.extent(rec);
      default:
        return this.extent(rec);
    }
  }

  /** The box over every anchor (and a channel's fourth corner, a fib's levels). */
  private extent(rec: DrawingRecord): PickGeometry {
    const a = rec.anchors;
    let [tl, th, pl, ph] = [Infinity, -Infinity, Infinity, -Infinity];
    const take = (t: number, p: number): void => {
      [tl, th, pl, ph] = [Math.min(tl, t), Math.max(th, t), Math.min(pl, p), Math.max(ph, p)];
    };
    for (let i = 0; i < a.length; i += 2) take(a[i] as number, a[i + 1] as number);
    const map = this.index.viewport.map;
    if (rec.family === CHANNEL && a.length >= 6) {
      // The fourth corner a2 + (a1 - a0), shifted in bars (time is not linear across gaps).
      const shift = indexAt(map, a[2] as number) - indexAt(map, a[0] as number);
      take(
        timeAt(map, indexAt(map, a[4] as number) + shift),
        (a[5] as number) + (a[3] as number) - (a[1] as number),
      );
    }
    if (rec.family === FIB) {
      for (let i = 0; i < rec.levels.length; i += 1) take(tl, this.levelTick(rec, i));
    }
    return { type: "rect", t0: tl, p0: pl, t1: th, p1: ph };
  }

  /** Level i's tick: from the first anchor by the first leg (from the third for an extension). */
  private levelTick(rec: DrawingRecord, i: number): number {
    const a = rec.anchors;
    const base = a.length >= 6 ? (a[5] as number) : (a[1] as number);
    return base + ((a[3] as number) - (a[1] as number)) * (rec.levels[i] as number);
  }

  private levelY(rec: DrawingRecord, i: number): number {
    return priceToScreen(this.index.viewport, this.index.pane, this.levelTick(rec, i));
  }

  /** Each level is a horizontal segment over the anchors' x span; the leg counts too. */
  private fibDistance(rec: DrawingRecord, x: number, y: number): number {
    const xy = rec.xy;
    let [xl, xh] = [Infinity, -Infinity];
    for (let i = 0; i < xy.length; i += 2) {
      xl = Math.min(xl, xy[i] as number);
      xh = Math.max(xh, xy[i] as number);
    }
    let d = distToSegment(x, y, xy[0] as number, xy[1] as number, xy[2] as number, xy[3] as number);
    for (let i = 0; i < rec.levels.length; i += 1) {
      const ly = this.levelY(rec, i);
      d = Math.min(d, distToSegment(x, y, xl, ly, xh, ly));
    }
    return d;
  }

  /** The plot box padded by `pad` px: what lies past it cannot be within tolerance. */
  private clipBox(pad: number): void {
    const vp = this.index.viewport;
    const p = vp.panes[this.index.pane];
    CLIP[0] = -pad;
    CLIP[1] = (p?.plotTop ?? 0) - pad;
    CLIP[2] = vp.plotWidth + pad;
    CLIP[3] = (p?.plotTop ?? 0) + (p?.plotHeight ?? 0) + pad;
  }
}

/** The distance to the clipped segment in SEG. */
const segDist = (x: number, y: number): number =>
  distToSegment(x, y, SEG[0] as number, SEG[1] as number, SEG[2] as number, SEG[3] as number);

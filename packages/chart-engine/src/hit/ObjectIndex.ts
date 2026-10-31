// The object index (E11-S08, 26 §3.9 item 2): one pane's pickable objects in a uniform grid kept
// in world space (BQ-127): x in fractional bar index, y in ticks, cells ~64 CSS px at build. A pan
// or an autoscale moves no object between cells (under log too, as below), so
// nothing is re-projected per frame: a query converts its ring through the current transform and
// projects only the candidates it finds (BQ-128). Under log a segment is drawn straight on screen,
// which is straight in (bar index, ln price): it is placed along that curve, and a mode switch is
// one rebuild (G-27). A rebuild runs only when the cell size drifts
// outside [¼, 4] of 64 px, and not during a gesture unless the ring would read more than RING_MAX
// buckets. Horizontal and vertical lines sit in 1-D bands; rays, and objects padded past CELL_PX,
// in an always-tested list (BQ-129), so the ring never outgrows one cell of pad. A pick
// allocates nothing: visit stamps, a max-scan in place of a sort, a caller-owned result.
import type { MutationRange } from "../model/counters.js";
import {
  indexAt,
  priceAt,
  priceToScreen,
  screenToPrice,
  screenToTime,
  timeToScreen,
} from "../viewport/transform.js";
import type { ViewportState } from "../viewport/types.js";
import { HitCounters, PICK_KINDS, type PickKind } from "./counters.js";
import {
  distToCircle,
  distToRay,
  distToRect,
  distToSegment,
  toleranceFor,
  type PointerType,
} from "./geometry.js";

/** Anchors are (µs time, tick); `radiusPx` and every width are CSS px. */
export type PickGeometry =
  | {
      readonly type: "segment" | "ray" | "rect";
      readonly t0: number;
      readonly p0: number;
      readonly t1: number;
      readonly p1: number;
    }
  | { readonly type: "hline"; readonly p: number }
  | { readonly type: "vline"; readonly t: number }
  | { readonly type: "point"; readonly t: number; readonly p: number; readonly radiusPx: number };

export interface Anchor {
  readonly t: number;
  readonly p: number;
}

/** BQ-132: the internal registration contract E14, E22 and E31 register through. */
export interface Pickable {
  readonly id: string;
  readonly kind: PickKind;
  readonly paneId: string;
  readonly zIndex: number;
  readonly geometry: PickGeometry;
  readonly widthPx: number;
  /** Control points on or inside the body; one within tolerance makes the pick a handle. */
  readonly handles?: readonly Anchor[];
  /** A custom body distance in CSS px (Infinity for a miss), replacing the geometry's. */
  readonly hitTest?: (x: number, y: number, tolerancePx: number) => number;
}

export interface PickHit {
  id: string | null;
  kind: PickKind | "none";
  part: "body" | "handle";
  /** The handle's position in `handles`, -1 for the body. */
  handle: number;
  distancePx: number;
}

export const createPickHit = (): PickHit => ({
  id: null,
  kind: "none",
  part: "body",
  handle: -1,
  distancePx: Infinity,
});

/** BQ-138 ceilings: objects per pane, and cells one object may span before it joins the list. */
export const MAX_OBJECTS = 10_000;
export const MAX_CELLS = 4_096;
export const CELL_PX = 64;
/** The most buckets a query reads before it rebuilds even mid-gesture. */
export const RING_MAX = 1_024;
const TABLE = 4_096; // buckets per table, a power of two (a spatial hash: collisions add candidates)
const MASK = TABLE - 1;
const [SEGMENT, RAY, RECT, HLINE, VLINE, POINT] = [0, 1, 2, 3, 4, 5];
const TYPES = { segment: SEGMENT, ray: RAY, rect: RECT, hline: HLINE, vline: VLINE, point: POINT };
const [GRID, HBAND, VBAND, UNBOUNDED] = [0, 1, 2, 3];

const hash2 = (cx: number, cy: number): number =>
  (Math.imul(cx | 0, 0x9e3779b1) ^ Math.imul(cy | 0, 0x85ebca77)) & MASK;
const hash1 = (c: number): number => Math.imul(c | 0, 0x9e3779b1) & MASK;
/** Buckets are created on first use, so an index costs nothing until objects land. */
const table = (): (number[] | undefined)[] => new Array<number[] | undefined>(TABLE);

interface Entry {
  readonly id: string;
  readonly kind: PickKind;
  readonly z: number;
  readonly seq: number;
  readonly width: number;
  readonly hitTest: Pickable["hitTest"];
  type: number;
  t0: number;
  p0: number;
  t1: number;
  p1: number;
  r: number;
  handles: Float64Array;
  table: number;
  readonly keys: number[];
  /** An anchor outside the loaded bars (extrapolated, BQ-66): re-placed when the map grows. */
  outside: boolean;
  /** The first time anchor's grid index when placed, for `staleEntries`. */
  gf: number;
}

export class ObjectIndex {
  readonly counters = new HitCounters();
  /** Set by the input stage: a drifted grid waits for the gesture's end (BQ-127). */
  gesture = false;
  private readonly entries: (Entry | undefined)[] = [];
  private readonly free: number[] = [];
  private readonly byId = new Map<string, number>();
  private readonly tables = [table(), table(), table()];
  private readonly unbounded: number[] = [];
  private readonly outside = new Set<number>();
  /** `outside` copied before re-placing (re-adding to a Set while iterating it revisits). */
  private readonly redo: number[] = [];
  private stamps = new Uint32Array(64);
  private epoch = 0;
  private seq = 0;
  private live = 0;
  /**
   * Cell size in bars and ticks; `shift` rebases stored bar indices after a prepend (BQ-133).
   * `maxPad` is the widest grid or band object's pad, at most CELL_PX; a rebuild recomputes it.
   */
  private cw = 0;
  private ch = 0;
  private shift = 0;
  private maxPad = 0;
  private pending = false;
  private best = -1;
  private bestDist = Infinity;
  private bestHandle = -1;
  /** The y mapping the grid was placed under: log, and its price origin and tick size. */
  private log = false;
  private origin = 0;
  private tick = 0;

  constructor(
    private readonly vp: ViewportState,
    readonly pane = 0,
    readonly paneId = "main",
    private readonly now?: () => number,
  ) {}

  get size(): number {
    return this.live;
  }

  registerPickable(p: Pickable): void {
    if (!(PICK_KINDS as readonly string[]).includes(p.kind)) {
      throw new RangeError(
        `chart-engine: kind ${p.kind} is not pickable here (registerStructural)`,
      );
    }
    if (p.paneId !== this.paneId)
      throw new RangeError(`chart-engine: pane ${p.paneId} is not ours`);
    if (this.byId.has(p.id)) throw new RangeError(`chart-engine: pickable ${p.id} exists`);
    if (this.live >= MAX_OBJECTS) throw new RangeError("chart-engine: pickable ceiling reached");
    if (!Number.isFinite(p.zIndex) || !(p.widthPx >= 0 && p.widthPx < Infinity)) {
      throw new RangeError("chart-engine: zIndex and widthPx must be finite");
    }
    const e: Entry = {
      id: p.id,
      kind: p.kind,
      z: p.zIndex,
      seq: (this.seq += 1),
      width: p.widthPx,
      hitTest: p.hitTest,
      type: 0,
      t0: 0,
      p0: 0,
      t1: 0,
      p1: 0,
      r: 0,
      handles: new Float64Array(),
      table: GRID,
      keys: [],
      outside: false,
      gf: 0,
    };
    setShape(e, p.geometry, p.handles); // validates before any slot is taken
    const slot = this.free.pop() ?? this.entries.length;
    if (this.cw === 0) this.scale();
    this.entries[slot] = e;
    this.byId.set(p.id, slot);
    if (slot >= this.stamps.length) {
      const next = new Uint32Array(this.stamps.length * 2);
      next.set(this.stamps);
      this.stamps = next;
    }
    this.live += 1;
    this.counters.registered[p.kind] += 1;
    this.place(slot);
  }

  /** New geometry (and handles) for a registered object; only its own buckets change. */
  move(id: string, geometry: PickGeometry, handles?: readonly Anchor[]): void {
    const slot = this.byId.get(id);
    const e = slot === undefined ? undefined : this.entries[slot];
    if (slot === undefined || e === undefined) throw new RangeError(`chart-engine: no ${id}`);
    setShape(e, geometry, handles);
    this.unplace(slot);
    this.place(slot);
  }

  unregister(id: string): boolean {
    const slot = this.byId.get(id);
    const e = slot === undefined ? undefined : this.entries[slot];
    if (slot === undefined || e === undefined) return false;
    this.unplace(slot);
    this.entries[slot] = undefined;
    this.byId.delete(id);
    this.free.push(slot);
    this.live -= 1;
    this.counters.registered[e.kind] -= 1;
    return true;
  }

  /**
   * A BarStore mutation (BQ-133; E12 wires it, G-23). A prepend or an eviction rebases every
   * stored index in O(1); objects with an extrapolated anchor are re-placed when the map grows
   * (O(outside)). An eviction also makes one O(N) pass for the objects whose anchor it cut off
   * (off the pick path); a `replace` is a counted rebuild.
   */
  onMutation(range: MutationRange): void {
    if (range.op === "patch") return;
    if (range.op === "replace") return this.rebuild();
    if (range.op === "prepend") this.shift += range.indexShift;
    else if (range.indexShift > 0) {
      this.shift -= range.indexShift;
      const first = this.vp.map.indexToTime(0);
      for (let s = 0; s < this.entries.length; s += 1) {
        const e = this.entries[s];
        if (e !== undefined && e.type !== HLINE && Math.min(e.t0, e.t1) < first)
          this.outside.add(s);
      }
    }
    this.redo.length = 0;
    for (const s of this.outside) this.redo.push(s);
    for (let i = 0; i < this.redo.length; i += 1) {
      const s = this.redo[i] as number;
      this.unplace(s);
      this.place(s);
    }
  }

  /**
   * The front-most object within tolerance of (x, y) (BQ-131): zIndex desc, then a handle before
   * the body within one object, distance asc, the later registration. x is the transform's plot
   * x, y the canvas y, in CSS px. Reads the ring's buckets, the bands and the unbounded list only.
   */
  pick(x: number, y: number, pointer: PointerType, out: PickHit): boolean {
    const t0 = this.now?.() ?? 0;
    const tol = toleranceFor(pointer);
    this.begin();
    if (this.live > 0 && this.ready()) {
      if ((this.pending && !this.gesture) || this.remapped()) this.rebuild();
      if (!this.scan(x, y, tol, false)) {
        this.rebuild();
        this.scan(x, y, tol, true);
      }
    }
    if (this.now !== undefined) this.counters.observe((this.now() - t0) * 1_000);
    return this.finish(out);
  }

  /** The brute-force reference: every object, the same precise test and order. */
  pickLinear(x: number, y: number, pointer: PointerType, out: PickHit): boolean {
    const tol = toleranceFor(pointer);
    this.begin();
    if (this.ready()) for (let s = 0; s < this.entries.length; s += 1) this.test(s, x, y, tol);
    return this.finish(out);
  }

  /** Projected bounds [x0, y0, x1, y1] in CSS px, widened by half the width (E11-S13, G-22). */
  boundsOf(id: string, out: number[]): boolean {
    const slot = this.byId.get(id);
    const e = slot === undefined ? undefined : this.entries[slot];
    if (e === undefined) return false;
    const { plotTop, plotHeight } = this.vp.panes[this.pane] ?? { plotTop: 0, plotHeight: 0 };
    let x0 = this.x(e.t0);
    let y0 = this.y(e.p0);
    let x1 = this.x(e.t1);
    let y1 = this.y(e.p1);
    if (e.type === HLINE) [x0, x1, y1] = [0, this.vp.plotWidth, y0];
    if (e.type === VLINE) [y0, y1, x1] = [plotTop, plotTop + plotHeight, x0];
    if (e.type === POINT) [x1, y1] = [x0, y0];
    if (e.type === RAY) {
      const far =
        (this.vp.plotWidth + plotHeight + Math.abs(x0) + Math.abs(y0) + 1) /
        (Math.hypot(x1 - x0, y1 - y0) || 1);
      x1 = Math.min(this.vp.plotWidth, Math.max(0, x0 + (x1 - x0) * far));
      y1 = Math.min(plotTop + plotHeight, Math.max(plotTop, y0 + (y1 - y0) * far));
    }
    const pad = e.width / 2 + (e.type === POINT ? e.r : 0);
    out[0] = Math.min(x0, x1) - pad;
    out[1] = Math.min(y0, y1) - pad;
    out[2] = Math.max(x0, x1) + pad;
    out[3] = Math.max(y0, y1) + pad;
    return true;
  }

  /** Objects whose placement no longer matches the map (0 after any mutation): a test probe. */
  staleEntries(): number {
    let stale = 0;
    this.entries.forEach((e, s) => {
      if (e === undefined) return;
      const moved = e.type !== HLINE && Math.abs(this.gfOf(e.t0) - e.gf) > 1e-6;
      const lost = e.table !== UNBOUNDED && e.keys.some((h) => !this.bucket(e, h).includes(s));
      if (moved || lost) stale += 1;
    });
    return stale;
  }

  private ready(): boolean {
    return (this.vp.panes[this.pane]?.plotHeight ?? 0) > 0 && this.vp.barSpacing > 0;
  }

  private x(t: number): number {
    return timeToScreen(this.vp, t);
  }

  private y(p: number): number {
    return priceToScreen(this.vp, this.pane, p);
  }

  private gfOf(t: number): number {
    return indexAt(this.vp.map, t) - this.shift;
  }

  private bucket(e: Entry, h: number): number[] {
    const t = this.tables[e.table] as (number[] | undefined)[];
    return (t[h] ??= []);
  }

  /**
   * The ring's buckets; false when the grid must rebuild first (drift, or more than RING_MAX
   * buckets). Drift is measured at the plot's middle, where the build set 64 px, so a rebuild
   * settles it, and the pad is at most CELL_PX, so the ring spans a few cells. A `forced` scan
   * (just rebuilt) whose ring still exceeds RING_MAX tests every object: a guard, bounded by
   * MAX_OBJECTS, that a linear y does not reach.
   */
  private scan(x: number, y: number, tol: number, forced: boolean): boolean {
    const r = tol + this.maxPad;
    const fa = indexAt(this.vp.map, screenToTime(this.vp, x - r)) - this.shift;
    const fb = indexAt(this.vp.map, screenToTime(this.vp, x + r)) - this.shift;
    const pa = screenToPrice(this.vp, this.pane, y + r);
    const pb = screenToPrice(this.vp, this.pane, y - r);
    const cx0 = Math.floor(Math.min(fa, fb) / this.cw);
    const cx1 = Math.floor(Math.max(fa, fb) / this.cw);
    const cy0 = Math.floor(Math.min(pa, pb) / this.ch);
    const cy1 = Math.floor(Math.max(pa, pb) / this.ch);
    const pxX = this.cw * this.vp.barSpacing;
    const mid = screenToPrice(this.vp, this.pane, this.middle());
    const pxY = Math.abs(this.y(mid) - this.y(mid + this.ch));
    const lo = CELL_PX / 4;
    const hi = CELL_PX * 4;
    const drift = !(pxX >= lo && pxX <= hi && pxY >= lo && pxY <= hi);
    // A ring past the price domain (log y far off the plot) is non-finite: never walked.
    const wide = !((cx1 - cx0 + 1) * (cy1 - cy0 + 1) <= RING_MAX);
    if (forced) {
      if (wide) {
        for (let s = 0; s < this.entries.length; s += 1) this.test(s, x, y, tol);
        return true;
      }
    } else if (wide || (drift && !this.gesture)) {
      return false;
    }
    this.pending ||= drift;
    const grid = this.tables[GRID] as (number[] | undefined)[];
    const hb = this.tables[HBAND] as (number[] | undefined)[];
    const vb = this.tables[VBAND] as (number[] | undefined)[];
    for (let cx = cx0; cx <= cx1; cx += 1) {
      for (let cy = cy0; cy <= cy1; cy += 1) this.testAll(grid[hash2(cx, cy)], x, y, tol);
      this.testAll(vb[hash1(cx)], x, y, tol);
    }
    for (let cy = cy0; cy <= cy1; cy += 1) this.testAll(hb[hash1(cy)], x, y, tol);
    this.testAll(this.unbounded, x, y, tol);
    return true;
  }

  private testAll(slots: readonly number[] | undefined, x: number, y: number, tol: number): void {
    if (slots === undefined) return;
    for (let i = 0; i < slots.length; i += 1) this.test(slots[i] as number, x, y, tol);
  }

  private begin(): void {
    this.best = -1;
    this.bestDist = Infinity;
    this.bestHandle = -1;
    this.counters.lastCandidates = 0;
    this.epoch = (this.epoch + 1) >>> 0;
    if (this.epoch === 0) {
      this.stamps.fill(0);
      this.epoch = 1;
    }
  }

  private finish(out: PickHit): boolean {
    const e = this.best >= 0 ? this.entries[this.best] : undefined;
    out.id = e?.id ?? null;
    out.kind = e?.kind ?? "none";
    out.part = this.bestHandle >= 0 ? "handle" : "body";
    out.handle = this.bestHandle;
    out.distancePx = this.bestDist;
    this.counters.candidatesTested += this.counters.lastCandidates;
    return e !== undefined;
  }

  /** One candidate, once per pick: the precise test, then the max-scan against the best so far. */
  private test(s: number, x: number, y: number, tol: number): void {
    const e = this.entries[s];
    if (e === undefined || this.stamps[s] === this.epoch) return;
    this.stamps[s] = this.epoch;
    this.counters.lastCandidates += 1;
    const thr = e.width / 2 + tol;
    let d: number;
    if (e.hitTest !== undefined) d = e.hitTest(x, y, tol);
    else if (e.type === HLINE) d = Math.abs(y - this.y(e.p0));
    else if (e.type === VLINE) d = Math.abs(x - this.x(e.t0));
    else if (e.type === POINT) d = distToCircle(x, y, this.x(e.t0), this.y(e.p0), e.r);
    else {
      const ax = this.x(e.t0);
      const ay = this.y(e.p0);
      const bx = this.x(e.t1);
      const by = this.y(e.p1);
      if (e.type === SEGMENT) d = distToSegment(x, y, ax, ay, bx, by);
      else if (e.type === RAY) d = distToRay(x, y, ax, ay, bx, by);
      else d = distToRect(x, y, ax, ay, bx, by);
    }
    if (!(d <= thr)) return;
    let handle = -1;
    for (let i = 0; i < e.handles.length; i += 2) {
      const dh = Math.hypot(
        x - this.x(e.handles[i] as number),
        y - this.y(e.handles[i + 1] as number),
      );
      if (dh <= thr && (handle < 0 || dh < d)) {
        handle = i / 2;
        d = dh;
      }
    }
    const b = this.best >= 0 ? this.entries[this.best] : undefined;
    const wins =
      b === undefined ||
      e.z > b.z ||
      (e.z === b.z && (d < this.bestDist || (d === this.bestDist && e.seq > b.seq)));
    if (!wins) return;
    this.best = s;
    this.bestDist = d;
    this.bestHandle = handle;
  }

  /** The pane draws log y (the transform's own test) with another origin or tick than placed. */
  private remapped(): boolean {
    const p = this.vp.panes[this.pane];
    const log = this.logY();
    if (log !== this.log) return true;
    return log && p !== undefined && (p.priceOrigin !== this.origin || p.tickSize !== this.tick);
  }

  private logY(): boolean {
    const p = this.vp.panes[this.pane];
    return p?.scaleMode === "log" && priceAt(p, Math.floor(p.priceLow)) > 0;
  }

  /** Cell size from the current transform: CELL_PX of bars and of ticks at the plot's middle. */
  private middle(): number {
    const p = this.vp.panes[this.pane];
    return (p?.plotTop ?? 0) + (p?.plotHeight ?? 0) / 2;
  }

  private scale(): void {
    const mid = this.middle();
    const ch = Math.abs(
      screenToPrice(this.vp, this.pane, mid) - screenToPrice(this.vp, this.pane, mid + CELL_PX),
    );
    this.cw = CELL_PX / this.vp.barSpacing;
    this.ch = ch > 0 && ch < Infinity ? ch : 1;
    const p = this.vp.panes[this.pane];
    this.log = this.logY();
    this.origin = p?.priceOrigin ?? 0;
    this.tick = p?.tickSize ?? 0;
  }

  /** A full re-placement at the current scale (O(N), counted); off the pick path but drift. */
  private rebuild(): void {
    this.scale();
    for (const t of this.tables) t.fill(undefined);
    this.unbounded.length = 0;
    this.outside.clear();
    this.pending = false;
    this.maxPad = 0;
    this.counters.indexRebuilds += 1;
    for (let s = 0; s < this.entries.length; s += 1) {
      const e = this.entries[s];
      if (e !== undefined) {
        e.keys.length = 0;
        this.place(s);
      }
    }
  }

  private add(e: Entry, s: number, h: number): void {
    const b = this.bucket(e, h);
    if (b.includes(s)) return;
    b.push(s);
    e.keys.push(h);
  }

  private place(s: number): void {
    const e = this.entries[s] as Entry;
    // Every placement names its table from the shape, so a move never inherits the old one.
    e.table = e.type === HLINE ? HBAND : e.type === VLINE ? VBAND : GRID;
    const pad = e.width / 2 + (e.type === POINT ? e.r : 0);
    const n = this.vp.map.length;
    const first = n > 0 ? this.vp.map.indexToTime(0) : Infinity;
    const last = n > 0 ? this.vp.map.indexToTime(n - 1) : -Infinity;
    const timed = e.type !== HLINE;
    e.outside = timed && (Math.min(e.t0, e.t1) < first || Math.max(e.t0, e.t1) > last);
    if (e.outside) this.outside.add(s);
    else this.outside.delete(s);
    e.gf = timed ? this.gfOf(e.t0) : 0;
    const x0 = e.gf / this.cw;
    const y0 = e.p0 / this.ch;
    const x1 = timed ? this.gfOf(e.t1) / this.cw : 0;
    const y1 = e.p1 / this.ch;
    if (pad > CELL_PX) return this.unbound(e, s); // a fat line or a big bubble never widens the ring
    this.maxPad = Math.max(this.maxPad, pad);
    if (e.type === HLINE || e.type === VLINE) {
      return this.add(e, s, hash1(Math.floor(e.type === HLINE ? y0 : x0)));
    }
    if (e.type === POINT) return this.add(e, s, hash2(Math.floor(x0), Math.floor(y0)));
    const [ax, ay, bx, by] = [Math.floor(x0), Math.floor(y0), Math.floor(x1), Math.floor(y1)];
    const nx = Math.abs(bx - ax) + 1;
    const ny = Math.abs(by - ay) + 1;
    const cells = e.type === RECT ? nx * ny : nx + ny - 1;
    if (e.type === SEGMENT && this.log) return this.bend(e, s, x0, x1, nx + ny);
    if (e.type === RAY || !(cells <= MAX_CELLS)) return this.unbound(e, s);
    if (e.type === RECT) {
      for (let cx = Math.min(ax, bx); cx <= Math.max(ax, bx); cx += 1) {
        for (let cy = Math.min(ay, by); cy <= Math.max(ay, by); cy += 1)
          this.add(e, s, hash2(cx, cy));
      }
      return;
    }
    this.walk(e, s, x0, y0, x1, y1, cells);
  }

  private unbound(e: Entry, s: number): void {
    e.table = UNBOUNDED;
    e.keys.push(-1);
    this.unbounded.push(s);
  }

  /**
   * A segment under log: straight in (bar index, ln price), so its ticks bend. It is cut into `n`
   * pieces, each at most one cell wide; a piece is monotone in both axes, so the box of its end
   * cells holds it, and the boxes cost at most 4n cells. A non-positive price joins the list.
   */
  private bend(e: Entry, s: number, x0: number, x1: number, span: number): void {
    const a = Math.log(this.origin + e.p0 * this.tick);
    const b = Math.log(this.origin + e.p1 * this.tick);
    const n = Math.max(1, span);
    if (!(Number.isFinite(a) && Number.isFinite(b)) || 4 * n > MAX_CELLS) {
      return this.unbound(e, s);
    }
    let cx = Math.floor(x0);
    let cy = Math.floor(e.p0 / this.ch);
    for (let i = 1; i <= n; i += 1) {
      const u = i / n;
      const p = i === n ? e.p1 : (Math.exp(a + (b - a) * u) - this.origin) / this.tick;
      const nx = Math.floor(x0 + (x1 - x0) * u);
      const ny = Math.floor(p / this.ch);
      for (let x = Math.min(cx, nx); x <= Math.max(cx, nx); x += 1) {
        for (let y = Math.min(cy, ny); y <= Math.max(cy, ny); y += 1) this.add(e, s, hash2(x, y));
      }
      cx = nx;
      cy = ny;
    }
  }

  /** Amanatides–Woo: the cells a segment crosses, at most `cells` of them. */
  private walk(e: Entry, s: number, x0: number, y0: number, x1: number, y1: number, cells: number) {
    let cx = Math.floor(x0);
    let cy = Math.floor(y0);
    const dx = x1 - x0;
    const dy = y1 - y0;
    const sx = dx > 0 ? 1 : -1;
    const sy = dy > 0 ? 1 : -1;
    const ddx = dx !== 0 ? 1 / Math.abs(dx) : Infinity;
    const ddy = dy !== 0 ? 1 / Math.abs(dy) : Infinity;
    let tx = dx !== 0 ? (sx > 0 ? cx + 1 - x0 : x0 - cx) * ddx : Infinity;
    let ty = dy !== 0 ? (sy > 0 ? cy + 1 - y0 : y0 - cy) * ddy : Infinity;
    for (let i = 0; i < cells; i += 1) {
      this.add(e, s, hash2(cx, cy));
      if (tx < ty) {
        cx += sx;
        tx += ddx;
      } else {
        cy += sy;
        ty += ddy;
      }
    }
  }

  private unplace(s: number): void {
    const e = this.entries[s] as Entry;
    // A slot missing from its structure is a no-op, never a splice or swap of someone else's.
    if (e.table === UNBOUNDED) {
      const i = this.unbounded.indexOf(s);
      if (i >= 0) this.unbounded.splice(i, 1);
    } else {
      for (const h of e.keys) {
        const b = this.bucket(e, h);
        const i = b.indexOf(s);
        if (i < 0) continue;
        b[i] = b[b.length - 1] as number;
        b.pop();
      }
    }
    e.keys.length = 0;
    this.outside.delete(s);
  }
}

const finite = (...v: number[]): boolean => v.every((n) => Number.isFinite(n));

/** Validates (BQ-138: finite anchors, a finite radius) and writes the shape into the entry. */
function setShape(e: Entry, g: PickGeometry, handles: readonly Anchor[] = []): void {
  const type = TYPES[g.type] as number | undefined;
  const [t0, p0, t1, p1, r] =
    g.type === "hline"
      ? [0, g.p, 0, g.p, 0]
      : g.type === "vline"
        ? [g.t, 0, g.t, 0, 0]
        : g.type === "point"
          ? [g.t, g.p, g.t, g.p, g.radiusPx]
          : [g.t0, g.p0, g.t1, g.p1, 0];
  const h = handles.flatMap((a) => [a.t, a.p]);
  if (type === undefined || !finite(t0, p0, t1, p1, r, ...h) || r < 0) {
    throw new RangeError("chart-engine: a pickable anchor or radius is not finite");
  }
  Object.assign(e, { type, t0, p0, t1, p1, r, handles: Float64Array.from(h) });
}

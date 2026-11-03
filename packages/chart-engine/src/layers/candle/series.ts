// CandleSeries (E12-S06): the candle plugin, and through `BarSeries` the OHLC one. Three host
// nodes draw with the `candle` program: candles the wick and the body, OHLC bars the stem and the
// ticks (exactly two draws per series, BQ-1), and both the gap seam (BQ-8), a third batch whose
// draw happens only while a `gap_before` bar is in view, and the marks (E12-S10, D06 §7), a fourth
// whose draw happens only while a forming or amended bar is in view at L0. It owns the batch blocks the submit loop
// binds per batch (the part and the ring's head, mask and length), the per-frame geometry and the
// palette, written in place (no per-frame allocation). A theme without a candle token makes it
// undrawable (BQ-4), never a fallback colour. Hit-testing reads the same geometry twin.
// E12-S07: the hollow shape (the same hosts, ring and program; parts 5 / 6 at L0) and `setShape`,
// which switches candles / hollow / OHLC in place: the parts are the per-frame `u_batch.x`, so a
// switch rewrites nothing on the GPU but the ring's derived bits (`CandleRing.setMode`).
import type { AttributeLayout, BatchUniforms, VertexSource } from "../../scene/gpu-types.js";
import type { SceneGraph } from "../../scene/graph.js";
import { PROGRAM } from "../../scene/instance-layout.js";
import { type HostContext, type HostDeps, type HostedPlugin, SeriesHost } from "../host.js";
import {
  CANDLE_PART,
  candleGeometry,
  candleRect,
  GEOM,
  GEOM_FLOATS,
  HOLLOW_FROM,
  MARKS_FROM,
  OHLC_TICKS_FROM,
  PART_VERTICES,
} from "./geometry.js";
import { HaRing } from "./heikin-ashi.js";
import { candlePalette, PALETTE_FLOATS, PaletteError } from "./palette.js";
import { BAR_FLAG, type BarStore } from "../../model/BarStore.js";
import type { MutationRange } from "../../model/counters.js";
import { MarkRing } from "./marks.js";
import { CANDLE_STRIDE, type CandleRing, type RingFollower } from "./ring.js";
import { SeamRing } from "./seams.js";

/** The ring as the `candle` shader's `layout(location)` ints: a_ohlc at 0, a_meta at 1. */
export const CANDLE_ATTRIBUTES: AttributeLayout = {
  stride: CANDLE_STRIDE,
  ints: [
    [0, 0, 4],
    [1, 4, 1],
  ],
};
export type SeriesShape = "candles" | "hollow" | "bars";
/**
 * Host names and the parts they declare, per shape: two bar parts, the seam, the state marks. A
 * host draws the part its block names each frame, so a shape switch keeps the hosts mounted for
 * the first shape.
 */
export const SERIES_PARTS: Readonly<Record<SeriesShape, readonly (readonly [string, number])[]>> = {
  candles: [
    ["wick", CANDLE_PART.wick],
    ["body", CANDLE_PART.body],
    ["seam", CANDLE_PART.seam],
    ["marks", CANDLE_PART.marks],
  ],
  hollow: [
    ["wick", CANDLE_PART.hollowWick],
    ["body", CANDLE_PART.hollowBody],
    ["seam", CANDLE_PART.seam],
    ["marks", CANDLE_PART.marks],
  ],
  bars: [
    ["stem", CANDLE_PART.stem],
    ["ticks", CANDLE_PART.ticks],
    ["seam", CANDLE_PART.seam],
    ["marks", CANDLE_PART.marks],
  ],
};
/** The draw-trace label prefix per shape (`series.candle.wick`, `series.ohlc.ticks`, …). */
const LABEL: Readonly<Record<SeriesShape, string>> = {
  candles: "series.candle",
  hollow: "series.hollow",
  bars: "series.ohlc",
};
const SEAM = 2; // the seam's block and host index
const MARKS = 3; // the marks' block and host index

/** A bar pick (caller-owned, reused): the bar, the part under the point, its distance. */
export interface BarHit {
  index: number;
  part: number;
  distancePx: number;
}
export const createBarHit = (): BarHit => ({ index: -1, part: -1, distancePx: Infinity });

/**
 * A bar's live state (E12-S10, caller-owned, reused): forming (`confirm: false`), amended (a late
 * trade corrected it) and stale (the series is flagged stale and the bar is forming; BQ-4: a flag
 * only, no canvas change). The readout, cursor and DOM mirror say the words; the engine draws the
 * marks and never announces.
 */
export interface BarState {
  forming: boolean;
  amended: boolean;
  stale: boolean;
}
export const createBarState = (): BarState => ({ forming: false, amended: false, stale: false });

const RECT = new Float64Array(4);

/** The series' seams and marks behind the ring's one follower call site. */
class SeriesFollower implements RingFollower {
  constructor(
    private readonly seams: SeamRing,
    private readonly marks: MarkRing,
  ) {}

  sync(store: BarStore, r: MutationRange, rewrite: boolean): void {
    this.seams.sync(store, r, rewrite);
    this.marks.sync(store, r, rewrite);
  }
}

export class CandleSeries implements HostedPlugin {
  readonly palette = new Float32Array(PALETTE_FLOATS);
  readonly geom = new Float32Array(GEOM_FLOATS);
  /** The `gap_before` bars (BQ-8), synced with the ring. */
  readonly seams: SeamRing;
  /** The forming and amended bars' marks (E12-S10), synced with the ring. */
  readonly marks: MarkRing;
  /** Per host: `u_batch` = (part, head, mask, length), the shared geometry and palette. */
  readonly blocks: readonly BatchUniforms[];
  /** Per host, the instance source its VAO reads: the ring twice, the seams, the marks. */
  readonly sources: readonly VertexSource[];
  /** The mounted host nodes in `SERIES_PARTS` order; replaced on a remount (degraded-2d init). */
  hosts: readonly SeriesHost[] = [];
  /** False while the theme lacks a candle token: the hosts are hidden. */
  drawable = false;
  /** BQ-12 (`CandleOptions.isTimeAligned`, default true): false never draws the seam. */
  timeAligned = true;
  /** BQ-4 (E12-S10): the app's feed watchdog says the series is stale; read by `barState` only. */
  stale = false;
  /** The seam and mark list versions `dirtyHosts` last saw. */
  private seenSeams = -1;
  private seenMarks = -1;

  /** The shape drawn now (`setShape`); the hosts keep the names of the shape they mounted as. */
  shape: SeriesShape;
  private readonly mounted: SeriesShape;

  constructor(
    readonly ring: CandleRing,
    shape: SeriesShape = "candles",
  ) {
    this.shape = shape;
    this.mounted = shape;
    if (shape === "hollow") ring.setMode(null, true, ring.ha); // `setKind` rewrites a synced ring
    this.seams = new SeamRing(ring);
    this.marks = new MarkRing(ring);
    ring.follower = new SeriesFollower(this.seams, this.marks);
    this.sources = [ring, ring, this.seams, this.marks];
    this.blocks = SERIES_PARTS[shape].map(([name, part]) => ({
      ints: Int32Array.of(part, 0, 0, 0),
      geom: this.geom,
      palette: this.palette,
      vertices: PART_VERTICES[part] ?? 4,
      label: `${LABEL[shape]}.${name}`,
      instances: part === CANDLE_PART.seam || part === CANDLE_PART.marks ? 0 : -1,
    }));
  }

  /**
   * Declares the calling host's part only (a host keeps nothing else): `ctx` is one of `hosts`,
   * so a TRANSFORM frame, which re-collects every host, costs one declaration per host. Any
   * other context gets every part: a host of an earlier mount (a degraded-2d re-init replaces
   * `hosts`, and BQ-46 keeps the old nodes, hidden, in the graph) or a test calling `collect`
   * directly. That stays correct, as `SeriesHost.instances` keeps only its own part.
   */
  collect(ctx: HostContext): void {
    const parts = SERIES_PARTS[this.mounted];
    const at = (this.hosts as readonly HostContext[]).indexOf(ctx);
    const end = at < 0 ? parts.length : at + 1;
    for (let i = at < 0 ? 0 : at; i < end; i += 1) {
      const part = (parts[i] as readonly [string, number])[1];
      const src =
        part === CANDLE_PART.seam
          ? this.seams
          : part === CANDLE_PART.marks
            ? this.marks
            : this.ring;
      ctx.instances(src, "candle", part);
    }
  }

  /**
   * E12-S07: draws as `shape`, Heikin-Ashi on or off, from the next frame. The batches' labels
   * change; the ring is rewritten in place once when its hollow bits or the HA transform turn on
   * or off (`CandleRing.setMode`); the `HaRing` exists only while HA is on (BQ-3).
   */
  setKind(shape: SeriesShape, heikinAshi: boolean, store: BarStore): void {
    const ring = this.ring;
    ring.setMode(store, shape === "hollow", heikinAshi ? (ring.ha ?? new HaRing()) : null);
    this.shape = shape;
    const names = SERIES_PARTS[shape];
    for (let p = 0; p < this.blocks.length; p += 1) {
      const name = (names[p] as readonly [string, number])[0];
      (this.blocks[p] as BatchUniforms).label = `${LABEL[shape]}.${name}`;
    }
  }

  get heikinAshi(): boolean {
    return this.ring.ha !== null;
  }

  /** The host-id prefix of the shape the hosts mounted as (`series.candle`, `series.ohlc`, …). */
  get mountLabel(): string {
    return LABEL[this.mounted];
  }

  /** Adds the hosts to pane `paneId`'s series layer as `<base>.<name>` (`SERIES_PARTS`). */
  mount(graph: SceneGraph, paneId: string, base: string, deps: HostDeps): readonly SeriesHost[] {
    this.hosts = SERIES_PARTS[this.mounted].map(([name, part]) => {
      const host = new SeriesHost(`${base}.${name}`, this, deps, { part, program: PROGRAM.candle });
      graph.addNode(paneId, "series", host);
      host.visible = this.drawable;
      return host;
    });
    this.ring.nodes.length = 0;
    this.seams.nodes.length = 0;
    this.marks.nodes.length = 0;
    for (let i = 0; i < this.hosts.length; i += 1) {
      const id = (this.hosts[i] as SeriesHost).id;
      (i === SEAM ? this.seams.nodes : i === MARKS ? this.marks.nodes : this.ring.nodes).push(id);
    }
    return this.hosts;
  }

  /** Resolves the palette (theme load only); the refusal, else null. Hides or shows the hosts. */
  setTheme(theme: Readonly<Record<string, string>>, inverted = false): PaletteError | null {
    let err: PaletteError | null = null;
    try {
      candlePalette(theme, inverted, this.palette);
    } catch (e) {
      if (!(e instanceof PaletteError)) throw e;
      err = e;
    }
    this.drawable = err === null;
    for (const h of this.hosts) h.visible = this.drawable;
    return err;
  }

  /**
   * Per frame, before submission: the geometry, the ring's state and the parts, in place. OHLC
   * bars under 5 CSS px draw the candle mark (D06 §3.2): their two batches switch to the wick and
   * body parts. Hollow candles under 3 CSS px draw the candle's mark (D06 §4.2, §5.5). The seam
   * draws only while a `gap_before` bar lies in logical [first, last]; the marks only while a
   * forming or amended bar does and the spacing is L0's (D06 §7.1: none at L1 / L2, where the
   * words alone carry the state).
   */
  frame(spacingCss: number, dpr: number, first = 0, last = -1, plotTop = 0, plotBottom = 0): void {
    candleGeometry(spacingCss, dpr, this.geom);
    this.geom[GEOM.plotTop] = plotTop * dpr; // the seam stops at the plot rect's edges
    this.geom[GEOM.plotBottom] = plotBottom > 0 ? plotBottom * dpr : 0;
    const r = this.ring;
    const head = r.head;
    const mask = r.capacity - 1;
    const shape = this.shape;
    const ohlc = shape === "bars" && spacingCss >= OHLC_TICKS_FROM;
    const hollow = shape === "hollow" && spacingCss >= HOLLOW_FROM;
    for (let p = 0; p < this.blocks.length; p += 1) {
      const blk = this.blocks[p] as BatchUniforms;
      const ints = blk.ints;
      if (p < SEAM) {
        const part = ohlc
          ? p === 0
            ? CANDLE_PART.stem
            : CANDLE_PART.ticks
          : hollow
            ? p === 0
              ? CANDLE_PART.hollowWick
              : CANDLE_PART.hollowBody
            : p;
        ints[0] = part;
        blk.vertices = PART_VERTICES[part] ?? 4;
      }
      ints[1] = head;
      ints[2] = mask;
      ints[3] = r.length;
    }
    const s = this.seams;
    const show = this.timeAligned && s.count > 0 && mask >= 0 && s.anyIn(first, last, head, mask);
    (this.blocks[SEAM] as BatchUniforms).instances = show ? s.count : 0;
    const m = this.marks;
    const l0 = spacingCss >= MARKS_FROM;
    const marks = l0 && m.count > 0 && mask >= 0 && m.anyIn(first, last, head, mask);
    (this.blocks[MARKS] as BatchUniforms).instances = marks ? m.count : 0;
  }

  /**
   * After a data sync: the hosts to re-collect, as a bitmask over `hosts`. The two bar parts
   * always (the ring's length moved); the seam and the marks only when their list changed since
   * the last call, as their batch's count is their buffer's capacity and their uploads go through
   * `patch` either way (E12-S10: a live tick re-collects two hosts, not four).
   */
  dirtyHosts(): number {
    let mask = (1 << SEAM) - 1;
    if (this.seams.changes !== this.seenSeams) mask |= 1 << SEAM;
    if (this.marks.changes !== this.seenMarks) mask |= 1 << MARKS;
    this.seenSeams = this.seams.changes;
    this.seenMarks = this.marks.changes;
    return mask;
  }

  /**
   * Bar `index`'s state (E12-S10) into `out`, from the ring's meta word (the flags as drawn);
   * false (and all false) when there is no such bar. Allocation-free: a mirror or readout pass
   * may call it per visible bar.
   */
  barState(index: number, out: BarState): boolean {
    out.forming = out.amended = out.stale = false;
    const r = this.ring;
    if (!(index >= 0 && index < r.length) || r.capacity === 0) return false;
    const meta = r.ints[((r.head + index) & (r.capacity - 1)) * CANDLE_STRIDE + 4] ?? 0;
    out.forming = (meta & BAR_FLAG.forming) !== 0;
    out.amended = (meta & BAR_FLAG.amended) !== 0;
    out.stale = this.stale && out.forming;
    return true;
  }

  /**
   * The bar under a point (E12-S06 hit-testing): `index` is the structural index's bar (the slot
   * under x); its drawn parts, from the geometry twin with the last frame's blocks, are measured
   * against (x, y) in CSS px. A hit is within `tolCss` of a part; `out` gets the nearest part and
   * the distance in CSS px. `k`, `indexBase`, `tickBase`: the pane block the frame drew with.
   */
  hitTest(
    x: number,
    y: number,
    index: number,
    k: ArrayLike<number>,
    indexBase: number,
    tickBase: number,
    tolCss: number,
    out: BarHit,
  ): boolean {
    out.index = -1;
    out.part = -1;
    out.distancePx = Infinity;
    const r = this.ring;
    if (!this.drawable || !(index >= 0 && index < r.length) || r.capacity === 0) return false;
    const at = ((r.head + index) & (r.capacity - 1)) * CANDLE_STRIDE;
    const v = r.ints;
    if (at + CANDLE_STRIDE > v.length) return false;
    const dpr = this.geom[GEOM.dpr] ?? 1;
    const px = x * dpr;
    const py = y * dpr;
    const o = v[at] as number;
    const hi = v[at + 1] as number;
    const lo = v[at + 2] as number;
    const c = v[at + 3] as number;
    const mark = (v[at + 4] as number) >> 4;
    let best = Infinity;
    let part = -1;
    for (let b = 0; b < SEAM; b += 1) {
      const p = (this.blocks[b] as BatchUniforms).ints[0] ?? 0;
      for (let sub = 0; sub < (p === CANDLE_PART.ticks ? 2 : 1); sub += 1) {
        candleRect(p, index, o, hi, lo, c, mark, k, indexBase, tickBase, this.geom, RECT, sub);
        const w = RECT[2] as number;
        if (w <= 0) continue;
        const rx = RECT[0] as number;
        const ry = RECT[1] as number;
        const dx = Math.max(rx - px, 0, px - (rx + w));
        const dy = Math.max(ry - py, 0, py - (ry + (RECT[3] as number)));
        const d = Math.hypot(dx, dy) / dpr;
        if (d < best) {
          best = d;
          part = p;
        }
      }
    }
    if (!(best <= tolCss)) return false;
    out.index = index;
    out.part = part;
    out.distancePx = best;
    return true;
  }
}

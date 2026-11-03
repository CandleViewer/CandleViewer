// CandleSeries (E12-S06): the candle plugin, and through `BarSeries` the OHLC one. Three host
// nodes draw with the `candle` program: candles the wick and the body, OHLC bars the stem and the
// ticks (exactly two draws per series, BQ-1), and both the gap seam (BQ-8), a third batch whose
// draw happens only while a `gap_before` bar is in view. It owns the batch blocks the submit loop
// binds per batch (the part and the ring's head, mask and length), the per-frame geometry and the
// palette, written in place (no per-frame allocation). A theme without a candle token makes it
// undrawable (BQ-4), never a fallback colour. Hit-testing reads the same geometry twin.
// E12-S07: the hollow shape (the same hosts, ring and program; parts 5 / 6 at L0) and `setShape`,
// which switches candles / hollow / OHLC in place: the parts are the per-frame `u_batch.x`, so a
// switch rewrites nothing on the GPU but the ring's derived bits (`CandleRing.setMode`).
// E12-S09 PR 1 (#421): the candle tier (BQ-04): L1 the hairline mark over the ring; L2 the column
// parts 7 / 8 over a `ColumnEntries` (BQ-03), still two draws. Attaching the entries as the two
// hosts' L2 source is the runtime's (PR 2); hit-testing an L2 column is PR 2's too.
import type { AttributeLayout, BatchUniforms, VertexSource } from "../../scene/gpu-types.js";
import type { BarStore } from "../../model/BarStore.js";
import type { ColumnEntries } from "./columns.js";
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
  OHLC_TICKS_FROM,
  PART_VERTICES,
} from "./geometry.js";
import { HaRing } from "./heikin-ashi.js";
import { candlePalette, PALETTE_FLOATS, PaletteError } from "./palette.js";
import { CANDLE_STRIDE, type CandleRing } from "./ring.js";
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
 * Host names and the parts they declare, per shape: two marks, then the seam. A host draws the
 * part its block names each frame, so a shape switch keeps the hosts mounted for the first shape.
 */
export const SERIES_PARTS: Readonly<Record<SeriesShape, readonly (readonly [string, number])[]>> = {
  candles: [
    ["wick", CANDLE_PART.wick],
    ["body", CANDLE_PART.body],
    ["seam", CANDLE_PART.seam],
  ],
  hollow: [
    ["wick", CANDLE_PART.hollowWick],
    ["body", CANDLE_PART.hollowBody],
    ["seam", CANDLE_PART.seam],
  ],
  bars: [
    ["stem", CANDLE_PART.stem],
    ["ticks", CANDLE_PART.ticks],
    ["seam", CANDLE_PART.seam],
  ],
};
/** The draw-trace label prefix per shape (`series.candle.wick`, `series.ohlc.ticks`, …). */
const LABEL: Readonly<Record<SeriesShape, string>> = {
  candles: "series.candle",
  hollow: "series.hollow",
  bars: "series.ohlc",
};
const SEAM = 2; // the seam's block and host index

/** A bar pick (caller-owned, reused): the bar, the part under the point, its distance. */
export interface BarHit {
  index: number;
  part: number;
  distancePx: number;
}
export const createBarHit = (): BarHit => ({ index: -1, part: -1, distancePx: Infinity });

const RECT = new Float64Array(4);

export class CandleSeries implements HostedPlugin {
  readonly palette = new Float32Array(PALETTE_FLOATS);
  readonly geom = new Float32Array(GEOM_FLOATS);
  /** The `gap_before` bars (BQ-8), synced with the ring. */
  readonly seams: SeamRing;
  /** Per host: `u_batch` = (part, head, mask, length), the shared geometry and palette. */
  readonly blocks: readonly BatchUniforms[];
  /** Per host, the instance source its VAO reads: the ring twice, then the seams. */
  readonly sources: readonly VertexSource[];
  /** The mounted host nodes in `SERIES_PARTS` order; replaced on a remount (degraded-2d init). */
  hosts: readonly SeriesHost[] = [];
  /** False while the theme lacks a candle token: the hosts are hidden. */
  drawable = false;
  /** BQ-12 (`CandleOptions.isTimeAligned`, default true): false never draws the seam. */
  timeAligned = true;

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
    ring.seams = this.seams;
    this.sources = [ring, ring, this.seams];
    this.blocks = SERIES_PARTS[shape].map(([name, part]) => ({
      ints: Int32Array.of(part, 0, 0, 0),
      geom: this.geom,
      palette: this.palette,
      vertices: PART_VERTICES[part] ?? 4,
      label: `${LABEL[shape]}.${name}`,
      instances: part === CANDLE_PART.seam ? 0 : -1,
    }));
  }

  collect(ctx: HostContext): void {
    const parts = SERIES_PARTS[this.mounted];
    for (let i = 0; i < parts.length; i += 1) {
      const part = (parts[i] as readonly [string, number])[1];
      ctx.instances(part === CANDLE_PART.seam ? this.seams : this.ring, "candle", part);
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
    for (let i = 0; i < this.hosts.length; i += 1) {
      const id = (this.hosts[i] as SeriesHost).id;
      (i === SEAM ? this.seams.nodes : this.ring.nodes).push(id);
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
   * draws only while a `gap_before` bar lies in logical [first, last]. E12-S09: from `tier` 1
   * every shape draws the candle mark (D06 §5.5); at 2 with `columns`, the two batches draw its
   * entries as parts 7 / 8 (`u_batch` = (part, 0, -1, count)); without, the L1 mark.
   */
  frame(
    spacingCss: number,
    dpr: number,
    first = 0,
    last = -1,
    plotTop = 0,
    plotBottom = 0,
    tier = 0,
    columns: ColumnEntries | null = null,
  ): void {
    candleGeometry(spacingCss, dpr, this.geom, tier);
    const l0 = !(tier >= 1); // candleGeometry's clamp: NaN and below 1 are L0
    const l2 = tier >= 2 && columns !== null;
    this.geom[GEOM.plotTop] = plotTop * dpr; // the seam stops at the plot rect's edges
    this.geom[GEOM.plotBottom] = plotBottom > 0 ? plotBottom * dpr : 0;
    const r = this.ring;
    const head = r.head;
    const mask = r.capacity - 1;
    const shape = this.shape;
    const ohlc = l0 && shape === "bars" && spacingCss >= OHLC_TICKS_FROM;
    const hollow = l0 && shape === "hollow" && spacingCss >= HOLLOW_FROM;
    for (let p = 0; p < this.blocks.length; p += 1) {
      const blk = this.blocks[p] as BatchUniforms;
      const ints = blk.ints;
      if (p !== SEAM && l2) {
        const part = p === 0 ? CANDLE_PART.columnWick : CANDLE_PART.columnSpan;
        ints[0] = part;
        ints[1] = 0;
        ints[2] = -1;
        ints[3] = (columns as ColumnEntries).count;
        blk.instances = ints[3];
        blk.vertices = PART_VERTICES[part] ?? 4;
        continue;
      }
      if (p !== SEAM) {
        if (blk.instances !== -1) blk.instances = -1; // back from L2
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
      if (p >= CANDLE_PART.columnWick) continue; // an L2 column's pick is PR 2's
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

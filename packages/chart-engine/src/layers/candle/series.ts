// CandleSeries (E12-S06): the candle plugin, and through `BarSeries` the OHLC one. Three host
// nodes draw with the `candle` program: candles the wick and the body, OHLC bars the stem and the
// ticks (exactly two draws per series, BQ-1), and both the gap seam (BQ-8), a third batch whose
// draw happens only while a `gap_before` bar is in view. It owns the batch blocks the submit loop
// binds per batch (the part and the ring's head, mask and length), the per-frame geometry and the
// palette, written in place (no per-frame allocation). A theme without a candle token makes it
// undrawable (BQ-4), never a fallback colour. Hit-testing reads the same geometry twin.
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
  OHLC_TICKS_FROM,
  PART_VERTICES,
} from "./geometry.js";
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
export type SeriesShape = "candles" | "bars";
/** Host names and the parts they declare, per shape: two marks, then the seam. */
export const SERIES_PARTS: Readonly<Record<SeriesShape, readonly (readonly [string, number])[]>> = {
  candles: [
    ["wick", CANDLE_PART.wick],
    ["body", CANDLE_PART.body],
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

  constructor(
    readonly ring: CandleRing,
    readonly shape: SeriesShape = "candles",
  ) {
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
    const parts = SERIES_PARTS[this.shape];
    for (let i = 0; i < parts.length; i += 1) {
      const part = (parts[i] as readonly [string, number])[1];
      ctx.instances(part === CANDLE_PART.seam ? this.seams : this.ring, "candle", part);
    }
  }

  /** Adds the hosts to pane `paneId`'s series layer as `<base>.<name>` (`SERIES_PARTS`). */
  mount(graph: SceneGraph, paneId: string, base: string, deps: HostDeps): readonly SeriesHost[] {
    this.hosts = SERIES_PARTS[this.shape].map(([name, part]) => {
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
   * body parts. The seam draws only while a `gap_before` bar lies in logical [first, last].
   */
  frame(spacingCss: number, dpr: number, first = 0, last = -1): void {
    candleGeometry(spacingCss, dpr, this.geom);
    const r = this.ring;
    const head = r.head;
    const mask = r.capacity - 1;
    const ohlc = this.shape === "bars" && spacingCss >= OHLC_TICKS_FROM;
    for (let p = 0; p < this.blocks.length; p += 1) {
      const blk = this.blocks[p] as BatchUniforms;
      const ints = blk.ints;
      if (p !== SEAM) {
        const part =
          this.shape === "candles" || !ohlc ? p : p === 0 ? CANDLE_PART.stem : CANDLE_PART.ticks;
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
    const dir = ((v[at + 4] as number) >> 4) & 3;
    let best = Infinity;
    let part = -1;
    for (let b = 0; b < SEAM; b += 1) {
      const p = (this.blocks[b] as BatchUniforms).ints[0] ?? 0;
      for (let sub = 0; sub < (p === CANDLE_PART.ticks ? 2 : 1); sub += 1) {
        candleRect(p, index, o, hi, lo, c, dir, k, indexBase, tickBase, this.geom, RECT, sub);
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

// RibbonSeries (E12-S07 PR B, E12-D06 §3.2, §5.5, R-2): the line, area and baseline plugin. Six
// host nodes draw with the `ribbon` program over the series' `CandleRing` through its own
// `RibbonSource` view (the ring's words plus the guard slot, so a GPU buffer of its own): two
// fills, the base line, the stroke, the joins and the last disc, in that order. A kind draws
// a subset and the others skip (`instances` 0): line 3 draws, area 4, baseline 6 (plan §3).
// A pan writes uniforms only: `frame` rewrites the blocks in place (part, head, mask, n, B); a
// kind switch among the three changes the parts and labels, nothing on the GPU. B (BQ-9) is
// the first visible bar's close, or the user's tick. A theme without `color.chart.line` makes
// only this family undrawable (BQ-7). Hit-testing reads the same geometry twin. No DOM.
import type { SceneGraph } from "../../scene/graph.js";
import { PROGRAM } from "../../scene/instance-layout.js";
import { projectRel } from "../../viewport/transform.js";
import { PaletteError, RIBBON_PALETTE_FLOATS, ribbonPalette } from "../candle/palette.js";
import { CANDLE_STRIDE, type CandleRing } from "../candle/ring.js";
import { FLAG_GAP_BEFORE } from "../candle/seams.js";
import type { BarHit } from "../candle/series.js";
import { type HostContext, type HostDeps, type HostedPlugin, SeriesHost } from "../host.js";
import {
  RIBBON_GEOM,
  RIBBON_GEOM_FLOATS,
  RIBBON_PART,
  RIBBON_PART_NAMES,
  ribbonGeometry,
  ribbonX,
  segmentDistance,
} from "./geometry.js";

export type RibbonKind = "line" | "area" | "baseline";
export const isRibbonKind = (k: string): k is RibbonKind =>
  k === "line" || k === "area" || k === "baseline";

/** Host names in mount (and so draw) order: the fills under the base line under the line. */
export const RIBBON_HOSTS = ["fill", "fill2", "base", "stroke", "join", "last"] as const;
const OFF = -1;
/** Per kind, each host's part (`RIBBON_PART`), `OFF` for a host that does not draw. */
export const RIBBON_PARTS: Readonly<Record<RibbonKind, readonly number[]>> = {
  line: [OFF, OFF, OFF, RIBBON_PART.stroke, RIBBON_PART.join, RIBBON_PART.last],
  area: [RIBBON_PART.fill, OFF, OFF, RIBBON_PART.stroke, RIBBON_PART.join, RIBBON_PART.last],
  baseline: [
    RIBBON_PART.above,
    RIBBON_PART.below,
    RIBBON_PART.base,
    RIBBON_PART.stroke,
    RIBBON_PART.join,
    RIBBON_PART.last,
  ],
};

/**
 * The ribbon's instance source: the ring's words and its guard slot (`guarded`), read in place;
 * `slots` is the wrap modulus, so `GlBuffers` uploads a range at the ring's own physical slots.
 */
export class RibbonSource {
  readonly stride = CANDLE_STRIDE;
  constructor(readonly ring: CandleRing) {}
  get data(): Float32Array {
    return this.ring.guarded;
  }
  get head(): number {
    return this.ring.head;
  }
  get slots(): number {
    return this.ring.capacity;
  }
  /** `InstanceRing`: a draw covers every physical slot; the shader collapses the empty ones. */
  get capacity(): number {
    return this.ring.capacity;
  }
  get length(): number {
    return this.ring.length;
  }
}

/**
 * A host's batch block: the backend's batch uniforms (src/gl/submit.ts) structurally, so this
 * layer imports nothing from src/gl (the runtime and the bench hand it to the backend as is).
 */
export interface RibbonBlock {
  readonly ints: Int32Array;
  readonly geom: Float32Array;
  readonly palette: Float32Array;
  vertices: number;
  label: string;
  instances: number;
  base: number;
}

/** The word offset of logical bar `i` in a ring of `cap` slots at `head` (no closure per pick). */
const at = (head: number, cap: number, i: number): number =>
  ((head + i) & (cap - 1)) * CANDLE_STRIDE;

export class RibbonSeries implements HostedPlugin {
  readonly palette = new Float32Array(RIBBON_PALETTE_FLOATS);
  readonly geom = new Float32Array(RIBBON_GEOM_FLOATS);
  readonly source: RibbonSource;
  /** Per host: `u_batch` = (part, head, mask, n), `u_base`, the geometry and palette. */
  readonly blocks: readonly RibbonBlock[];
  hosts: readonly SeriesHost[] = [];
  /** False while the theme lacks a line-family token: the hosts are hidden. */
  drawable = false;
  /** False while the series draws as a candle kind (the runtime's switch): hidden too. */
  active = true;
  /** BQ-9: the user's base B (a tick from the series' origin), else null: the first visible close. */
  baseTick: number | null = null;
  kind: RibbonKind;

  constructor(
    readonly ring: CandleRing,
    kind: RibbonKind = "line",
  ) {
    this.kind = kind;
    this.source = new RibbonSource(ring);
    this.blocks = RIBBON_HOSTS.map(() => ({
      ints: Int32Array.of(0, 0, 0, 0),
      geom: this.geom,
      palette: this.palette,
      vertices: 4,
      label: "",
      instances: 0,
      base: 0,
    }));
    this.setKind(kind);
  }

  collect(ctx: HostContext): void {
    for (let h = 0; h < RIBBON_HOSTS.length; h += 1) ctx.instances(this.source, "ribbon", h);
  }

  /** Draws as `kind` from the next frame: the parts and labels (the caller re-resolves the
   * palette with `setTheme`, which is per kind). Nothing on the GPU. */
  setKind(kind: RibbonKind): void {
    this.kind = kind;
    const parts = RIBBON_PARTS[kind];
    for (let h = 0; h < this.blocks.length; h += 1) {
      const part = parts[h] ?? OFF;
      const name = part === OFF ? RIBBON_HOSTS[h] : RIBBON_PART_NAMES[part];
      (this.blocks[h] as RibbonBlock).label = `series.${kind}.${name ?? ""}`;
    }
  }

  /** Adds the hosts to pane `paneId`'s series layer as `<base>.<name>`; the ring patches them. */
  mount(graph: SceneGraph, paneId: string, base: string, deps: HostDeps): readonly SeriesHost[] {
    this.hosts = RIBBON_HOSTS.map((name, part) => {
      const host = new SeriesHost(`${base}.${name}`, this, deps, { part, program: PROGRAM.ribbon });
      graph.addNode(paneId, "series", host);
      host.visible = this.drawable && this.active;
      return host;
    });
    this.ring.nodes.length = 0;
    for (let i = 0; i < this.hosts.length; i += 1) {
      this.ring.nodes.push((this.hosts[i] as SeriesHost).id);
    }
    return this.hosts;
  }

  /** Shows or hides the hosts (the runtime's switch between the candle and the line family). */
  setActive(on: boolean): void {
    this.active = on;
    for (const h of this.hosts) h.visible = this.drawable && on;
  }

  /**
   * Resolves the palette for the current kind (theme load and kind switches only: a line needs
   * only `color.chart.line`, area and baseline their tints' tokens too); the refusal, else null.
   * Hides or shows the hosts.
   */
  setTheme(theme: Readonly<Record<string, string>>, inverted = false): PaletteError | null {
    let err: PaletteError | null = null;
    try {
      ribbonPalette(theme, inverted, this.palette, this.kind);
    } catch (e) {
      if (!(e instanceof PaletteError)) throw e;
      err = e;
    }
    this.drawable = err === null;
    this.setActive(this.active);
    return err;
  }

  /**
   * Per frame, before submission: the geometry and every block, in place. B is the user's tick
   * or the close of the first visible bar (`first`, clamped to the bars held); the base line and
   * the area fill stop at the plot rect's right and bottom edges (CSS px); the last disc
   * reads the last close. A host the kind does not use draws nothing (`instances` 0).
   */
  frame(spacingCss: number, dpr: number, first = 0, plotRight = 0, plotBottom = 0): void {
    ribbonGeometry(spacingCss, dpr, this.geom, plotRight, plotBottom); // CSS px; 0: the canvas
    const r = this.ring;
    const head = r.head;
    const mask = r.capacity - 1;
    const n = r.length;
    const v = r.ints;
    let lastClose = 0;
    let b = 0;
    if (n > 0 && mask >= 0) {
      lastClose = v[((head + n - 1) & mask) * CANDLE_STRIDE + 3] ?? 0;
      const f = Math.min(n - 1, Math.max(0, first));
      b = this.baseTick ?? v[((head + f) & mask) * CANDLE_STRIDE + 3] ?? 0;
    }
    const parts = RIBBON_PARTS[this.kind];
    for (let h = 0; h < this.blocks.length; h += 1) {
      const blk = this.blocks[h] as RibbonBlock;
      const part = parts[h] ?? OFF;
      const ints = blk.ints;
      ints[0] = part === OFF ? 0 : part;
      ints[1] = head;
      ints[2] = mask;
      ints[3] = n;
      const single = part === RIBBON_PART.last || part === RIBBON_PART.base;
      blk.instances = part === OFF || n === 0 ? 0 : single ? 1 : -1;
      blk.base = part === RIBBON_PART.last ? lastClose : b;
    }
  }

  /**
   * The nearest point of the drawn line to (x, y), CSS px: bar `index` (the structural index's
   * slot under x) and its two segments (none across a gap, R-2), from the geometry twin with the
   * last frame's pane block. A hit is within `tolCss` of the stroke; `out.index` is the nearer
   * bar of the nearest segment, `out.part` `RIBBON_PART.stroke`.
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
    const n = r.length;
    const cap = r.capacity;
    if (!this.drawable || !this.active || !(index >= 0 && index < n) || cap === 0) return false;
    const g = this.geom;
    const dpr = g[RIBBON_GEOM.dpr] ?? 1;
    const l2 = (g[RIBBON_GEOM.l2] ?? 0) > 0.5;
    const px = x * dpr;
    const py = y * dpr;
    const v = r.ints;
    const h = r.head;
    const xi = ribbonX(index, k, indexBase, l2);
    const yi = projectRel(k, (v[at(h, cap, index) + 3] ?? 0) - tickBase);
    let best = Math.hypot(px - xi, py - yi);
    let pick = index;
    for (let a = index - 1; a <= index; a += 1) {
      if (a < 0 || a + 1 >= n || ((v[at(h, cap, a + 1) + 4] ?? 0) & FLAG_GAP_BEFORE) !== 0)
        continue;
      const ax = ribbonX(a, k, indexBase, l2);
      const ay = projectRel(k, (v[at(h, cap, a) + 3] ?? 0) - tickBase);
      const bx = ribbonX(a + 1, k, indexBase, l2);
      const by = projectRel(k, (v[at(h, cap, a + 1) + 3] ?? 0) - tickBase);
      const d = segmentDistance(px, py, ax, ay, bx, by);
      if (d >= best) continue;
      best = d;
      pick = Math.hypot(px - ax, py - ay) <= Math.hypot(px - bx, py - by) ? a : a + 1;
    }
    const css = Math.max(0, best - (g[RIBBON_GEOM.stroke] ?? 0) * 0.5) / dpr;
    if (!(css <= tolCss)) return false;
    out.index = pick;
    out.part = RIBBON_PART.stroke;
    out.distancePx = css;
    return true;
  }
}

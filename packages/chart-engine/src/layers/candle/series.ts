// CandleSeries (E12-S06): the candle plugin. Two host nodes, the wick (part 0) and the body
// (part 1), draw one CandleRing with the `candle` program: exactly two draws per series (BQ-1).
// It owns the two batch blocks the submit loop binds per batch: the part and the ring's (head,
// mask, length), the per-frame geometry and the palette, written in place (no per-frame
// allocation). A theme without a candle token makes it undrawable (BQ-4), never a fallback colour.
import type { AttributeLayout } from "../../gl/buffers.js";
import type { BatchUniforms } from "../../gl/submit.js";
import type { SceneGraph } from "../../scene/graph.js";
import { PROGRAM } from "../../scene/instance-layout.js";
import { type HostContext, type HostDeps, type HostedPlugin, SeriesHost } from "../host.js";
import { candleGeometry } from "./geometry.js";
import { candlePalette, PALETTE_FLOATS, PaletteError } from "./palette.js";
import { CANDLE_STRIDE, type CandleRing } from "./ring.js";

/** The ring as the `candle` shader's `layout(location)` ints: a_ohlc at 0, a_meta at 1. */
export const CANDLE_ATTRIBUTES: AttributeLayout = {
  stride: CANDLE_STRIDE,
  ints: [
    [0, 0, 4],
    [1, 4, 1],
  ],
};
export const CANDLE_PARTS = ["wick", "body"] as const;

export class CandleSeries implements HostedPlugin {
  readonly palette = new Float32Array(PALETTE_FLOATS);
  readonly geom = new Float32Array(4);
  /** Per part: `u_batch` = (part, head, mask, length), the shared geometry and palette. */
  readonly blocks: readonly BatchUniforms[];
  /** The mounted host nodes, wick then body; replaced on a remount (the degraded-2d init). */
  hosts: readonly SeriesHost[] = [];
  /** False while the theme lacks a candle token: the hosts are hidden. */
  drawable = false;

  constructor(readonly ring: CandleRing) {
    this.blocks = CANDLE_PARTS.map((_, part) => ({
      ints: Int32Array.of(part, 0, 0, 0),
      geom: this.geom,
      palette: this.palette,
      vertices: 0,
    }));
  }

  collect(ctx: HostContext): void {
    ctx.instances(this.ring, "candle", 0);
    ctx.instances(this.ring, "candle", 1);
  }

  /** Adds the two hosts to pane `paneId`'s series layer as `<base>.wick` / `<base>.body`. */
  mount(graph: SceneGraph, paneId: string, base: string, deps: HostDeps): readonly SeriesHost[] {
    this.hosts = CANDLE_PARTS.map((name, part) => {
      const host = new SeriesHost(`${base}.${name}`, this, deps, { part, program: PROGRAM.candle });
      graph.addNode(paneId, "series", host);
      host.visible = this.drawable;
      return host;
    });
    this.ring.nodes.length = 0;
    for (const h of this.hosts) this.ring.nodes.push(h.id);
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

  /** Per frame, before submission: the geometry and the ring's state, in place. */
  frame(spacingCss: number, dpr: number): void {
    candleGeometry(spacingCss, dpr, this.geom);
    const r = this.ring;
    for (let p = 0; p < this.blocks.length; p += 1) {
      const ints = (this.blocks[p] as BatchUniforms).ints;
      ints[1] = r.head;
      ints[2] = r.capacity - 1;
      ints[3] = r.length;
    }
  }
}

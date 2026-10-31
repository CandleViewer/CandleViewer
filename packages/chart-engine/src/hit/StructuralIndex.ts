// The structural index (E11-S08, 26 §3.9 item 1, BQ-137): the chart is a regular grid, so the
// pane, bar and price level under a point are analytic, O(1), through the shared transform. Cells,
// ladder rows and profile rows resolve through a per-pane resolver (E18 / E21 register, G-26) and
// are never stored in the object grid. DOM-free; the result goes into a caller-owned slot.
import { screenToIndex, screenToPrice } from "../viewport/transform.js";
import type { ViewportState } from "../viewport/types.js";

type Rect = readonly [number, number, number, number];

/** What the layout engine exposes (`LayoutEngine` fits it structurally). */
export interface StructuralLayout {
  readonly panes: readonly { readonly id: string; readonly rect: Rect; readonly priceAxis: Rect }[];
  readonly timeAxis: Rect;
}

export type StructuralRegion = "plot" | "price" | "time" | "none";

/** Bar and price level to an id (a footprint cell, a ladder or profile row), or null. */
export type StructuralResolver = (barIndex: number, priceLevel: number) => string | null;

export interface StructuralHit {
  paneId: string | null;
  pane: number;
  region: StructuralRegion;
  barIndex: number;
  /** The integer tick level, `round(screenToPrice)`. */
  priceLevel: number;
  /** The plot region's resolver answer. */
  objectId: string | null;
}

export const createStructuralHit = (): StructuralHit => ({
  paneId: null,
  pane: -1,
  region: "none",
  barIndex: 0,
  priceLevel: 0,
  objectId: null,
});

const inside = (r: Rect, x: number, y: number): boolean =>
  x >= r[0] && x < r[0] + r[2] && y >= r[1] && y < r[1] + r[3];

export class StructuralIndex {
  private readonly resolvers = new Map<string, StructuralResolver>();

  constructor(
    private readonly vp: ViewportState,
    private readonly layout: StructuralLayout,
  ) {}

  /** One resolver per pane; a second replaces the first. Returns its removal. */
  registerStructural(paneId: string, resolve: StructuralResolver): () => void {
    this.resolvers.set(paneId, resolve);
    return () => {
      if (this.resolvers.get(paneId) === resolve) this.resolvers.delete(paneId);
    };
  }

  /** (x, y) in canvas CSS px; the time axis reports the bar, the price axis the level. */
  pickStructural(x: number, y: number, out: StructuralHit): StructuralHit {
    out.paneId = null;
    out.pane = -1;
    out.region = "none";
    out.objectId = null;
    const panes = this.layout.panes;
    let px = 0;
    for (let i = 0; i < panes.length; i += 1) {
      const p = panes[i] as (typeof panes)[number];
      const region = inside(p.rect, x, y) ? "plot" : inside(p.priceAxis, x, y) ? "price" : null;
      if (region === null) continue;
      out.paneId = p.id;
      out.pane = i;
      out.region = region;
      px = p.rect[0];
      break;
    }
    if (out.region === "none" && inside(this.layout.timeAxis, x, y)) {
      out.region = "time";
      px = this.layout.timeAxis[0];
    }
    out.barIndex = screenToIndex(this.vp, x - px);
    out.priceLevel = out.pane >= 0 ? Math.round(screenToPrice(this.vp, out.pane, y)) : 0;
    if (out.region === "plot" && out.paneId !== null) {
      out.objectId = this.resolvers.get(out.paneId)?.(out.barIndex, out.priceLevel) ?? null;
    }
    return out;
  }
}

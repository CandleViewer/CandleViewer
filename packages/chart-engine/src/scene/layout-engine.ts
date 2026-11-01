// The layout engine (E11-S01 PR3): pane rects, the price- and time-axis gutters and the panes'
// height ratios, normalised over the panes (BQ-S13). As the scheduler's layout hook it recomputes
// only when a pane it lays out is LAYOUT-dirty (BQ-43). DOM-free; rects are allocated per pane once.
import { Dirty } from "./dirty.js";
import type { SceneGraph } from "./graph.js";
import { normaliseShares } from "./pane-shares.js";

/** x, y, width, height. */
export type Rect = [number, number, number, number];

export interface PaneLayout {
  readonly id: string;
  /** The pane's weight; `share` is its normalised part of the stack (E11-S09, BQ-3). */
  ratio: number;
  share: number;
  readonly rect: Rect; // the plot area
  readonly priceAxis: Rect; // its right-hand gutter
}

const put = (r: Rect, x: number, y: number, w: number, h: number): void => {
  r[0] = x;
  r[1] = y;
  r[2] = w;
  r[3] = h;
};

/** `Pane.setHeightRatio`'s bound (src/api/pane.ts), checked again at this boundary. */
function checkRatio(r: number): number {
  if (Number.isFinite(r) && r > 0 && r <= 1) return r;
  throw new RangeError("chart-engine: a pane height ratio must be in (0, 1]");
}

/** The price-axis gutter right of each pane and the time-axis gutter below them, CSS px. */
export const PRICE_GUTTER_PX = 64;
export const TIME_GUTTER_PX = 24;

export class LayoutEngine {
  readonly panes: PaneLayout[] = [];
  readonly timeAxis: Rect = [0, 0, 0, 0];
  width = 0;
  height = 0;
  computes = 0; // recomputations so far: LAYOUT frames only
  private readonly weights: number[] = [];
  private readonly shares: number[] = [];

  constructor(
    private readonly graph: SceneGraph,
    /** E11-S06 (BQ-201): measured from the widest price label (`setPriceGutter`). */
    public priceGutter = PRICE_GUTTER_PX,
    readonly timeGutter = TIME_GUTTER_PX,
  ) {}

  /** The axes' measured gutter: LAYOUT only when the width changes (BQ-201). */
  setPriceGutter(px: number): void {
    if (!(px > 0) || px === this.priceGutter) return;
    this.priceGutter = px;
    this.graph.markResize();
  }

  /** Lays out a pane already in the graph, below the others. */
  addPane(id: string, ratio = 1): void {
    if (this.graph.get(id)?.kind !== "pane") throw new RangeError(`unknown pane ${id}`);
    const rect: Rect = [0, 0, 0, 0];
    this.panes.push({ id, ratio: checkRatio(ratio), share: 1, rect, priceAxis: [0, 0, 0, 0] });
    this.reshare();
  }

  /** E11-S09 (BQ-2): drops a pane's row; the others share its height (`false`: unknown id). */
  removePane(id: string): boolean {
    const i = this.panes.findIndex((p) => p.id === id);
    if (i < 0) return false;
    this.panes.splice(i, 1);
    this.reshare();
    return true;
  }

  /** E11-S09 (BQ-3): every listed pane's weight at once; an id not laid out is ignored. */
  setWeights(weights: ReadonlyMap<string, number>): void {
    for (const p of this.panes) {
      const w = weights.get(p.id);
      if (w !== undefined) p.ratio = checkRatio(w);
    }
    this.reshare();
  }

  setSize(width: number, height: number): void {
    if (width === this.width && height === this.height) return;
    this.width = Math.max(0, width);
    this.height = Math.max(0, height);
    this.graph.markResize();
  }

  /** One ratio moves every pane's height, so every pane is marked LAYOUT. */
  setHeightRatio(id: string, ratio: number): void {
    const pane = this.panes.find((p) => p.id === id);
    if (pane === undefined) throw new RangeError(`unknown pane ${id}`);
    pane.ratio = checkRatio(ratio);
    this.reshare();
  }

  /** The layout stage, every frame: `true` when it recomputed. Allocates nothing. */
  run(): boolean {
    const { panes, width, height } = this;
    let i = 0;
    for (; i < panes.length; i += 1) {
      if (((this.graph.get((panes[i] as PaneLayout).id)?.dirty ?? 0) & Dirty.LAYOUT) !== 0) break;
    }
    if (i === panes.length) return false;
    let sum = 0;
    for (i = 0; i < panes.length; i += 1) sum += (panes[i] as PaneLayout).ratio;
    const plotW = Math.max(0, width - this.priceGutter);
    const plotH = Math.max(0, height - this.timeGutter);
    let acc = 0;
    let y = 0;
    for (i = 0; i < panes.length; i += 1) {
      const p = panes[i] as PaneLayout;
      acc += p.ratio;
      const bottom = Math.round((plotH * acc) / sum); // cumulative: the panes tile plotH exactly
      put(p.rect, 0, y, plotW, bottom - y);
      put(p.priceAxis, plotW, y, width - plotW, bottom - y);
      y = bottom;
    }
    put(this.timeAxis, 0, plotH, plotW, height - plotH);
    this.computes += 1;
    return true;
  }

  /** The weights changed: the shares again (BQ-3's one function) and every pane LAYOUT. */
  private reshare(): void {
    const { panes, weights, shares } = this;
    for (let i = 0; i < panes.length; i += 1) weights[i] = (panes[i] as PaneLayout).ratio;
    normaliseShares(weights, panes.length, shares);
    for (let i = 0; i < panes.length; i += 1) (panes[i] as PaneLayout).share = shares[i] as number;
    weights.length = shares.length = panes.length;
    this.graph.markResize();
  }
}

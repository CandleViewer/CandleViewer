// The layout engine (E11-S01 PR3): pane rects, the price- and time-axis gutters and the panes'
// height ratios, normalised over the panes (BQ-S13). As the scheduler's layout hook it recomputes
// only when a pane it lays out is LAYOUT-dirty (BQ-43). DOM-free; rects are allocated per pane once.
import { Dirty } from "./dirty.js";
import type { SceneGraph } from "./graph.js";

/** x, y, width, height. */
export type Rect = [number, number, number, number];

export interface PaneLayout {
  readonly id: string;
  ratio: number;
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

export class LayoutEngine {
  readonly panes: PaneLayout[] = [];
  readonly timeAxis: Rect = [0, 0, 0, 0];
  width = 0;
  height = 0;
  computes = 0; // recomputations so far: LAYOUT frames only

  constructor(
    private readonly graph: SceneGraph,
    readonly priceGutter = 64,
    readonly timeGutter = 24,
  ) {}

  /** Lays out a pane already in the graph, below the others. */
  addPane(id: string, ratio = 1): void {
    if (this.graph.get(id)?.kind !== "pane") throw new RangeError(`unknown pane ${id}`);
    this.panes.push({ id, ratio: checkRatio(ratio), rect: [0, 0, 0, 0], priceAxis: [0, 0, 0, 0] });
    this.graph.markResize();
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
    this.graph.markResize();
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
}

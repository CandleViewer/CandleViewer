// The layout engine (E11-S01 PR3): pane rects, the price- and time-axis gutters and the panes'
// height ratios, normalised over the panes (BQ-S13). As the scheduler's layout hook it recomputes
// only when a pane it lays out is LAYOUT-dirty (BQ-43). DOM-free; rects are allocated per pane once.
// E11-S09 (#446 BQ-11, the proposed default): a pane below the minimum height collapses to a stub
// row; its weight is kept, so a restore gives back max(its last share, the minimum).
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
  /** BQ-11: laid out as a `stubPx` row; its weight (and so its share) is remembered. */
  collapsed: boolean;
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

/** BQ-11: the minimum pane height, `max(48, 3 x the axis label box)` (E11-D02 §8). */
export const MIN_PANE_PX = 48;
export const minPaneHeight = (labelBoxPx = 0): number => Math.max(MIN_PANE_PX, 3 * labelBoxPx);
/** BQ-11: a collapsed pane's stub row, compact and dense; comfortable is 32 (E11-D02 §8). */
export const STUB_PX = 24;
export const STUB_PX_COMFORTABLE = 32;
/** E11-D02 §8: the splitter's hit band, 12 px each side of a pane boundary. */
export const SPLITTER_BAND_PX = 24;

/** `dragSplitter`'s outcome: the boundary moved, a pane collapsed or restored, or nothing. */
export const SPLIT = { none: 0, moved: 1, collapsed: 2, restored: 3 } as const;

export class LayoutEngine {
  readonly panes: PaneLayout[] = [];
  readonly timeAxis: Rect = [0, 0, 0, 0];
  width = 0;
  height = 0;
  computes = 0; // recomputations so far: LAYOUT frames only
  /** BQ-11: the minimum expanded pane height and the stub row, CSS px. */
  minPanePx = MIN_PANE_PX;
  stubPx = STUB_PX;
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
    const priceAxis: Rect = [0, 0, 0, 0];
    this.panes.push({ id, ratio: checkRatio(ratio), share: 1, collapsed: false, rect, priceAxis });
    this.reshare();
  }

  /** E11-S09 (BQ-2): drops a pane's row; the others share its height (`false`: unknown id). */
  removePane(id: string): boolean {
    const i = this.panes.findIndex((p) => p.id === id);
    if (i < 0) return false;
    this.panes.splice(i, 1);
    // Never a stack of stubs only: the last pane left expanded stays expanded.
    if (this.panes.every((p) => p.collapsed)) for (const p of this.panes) p.collapsed = false;
    this.reshare();
    return true;
  }

  /**
   * BQ-11: collapses a pane to its stub, or restores it to max(its last share, the minimum).
   * `false` when nothing changed: an unknown id, the same state, or collapsing the last
   * expanded pane (the stack always shows one plot).
   */
  setCollapsed(id: string, collapsed: boolean): boolean {
    const pane = this.panes.find((p) => p.id === id);
    if (pane === undefined || pane.collapsed === collapsed) return false;
    if (collapsed && this.expanded() === 1) return false;
    pane.collapsed = collapsed;
    if (!collapsed) this.raiseToMinimum(pane);
    this.reshare();
    return true;
  }

  /**
   * BQ-11: a restored pane gets max(its last share, the minimum) of the height the expanded
   * panes tile, computed over those panes (stubs keep their rows): its weight w must satisfy
   * `avail * w / (others + w) >= minPanePx`. The others keep their proportions; past a weight of
   * 1, every weight scales down together.
   */
  private raiseToMinimum(pane: PaneLayout): void {
    let others = 0;
    let stubs = 0;
    for (const p of this.panes) {
      if (p.collapsed) stubs += 1;
      else if (p !== pane) others += p.ratio;
    }
    const avail = this.plotHeight() - stubs * this.stubPx;
    const min = this.minPanePx + 1e-6; // an integer height survives the cumulative rounding
    if (others <= 0 || avail <= min || (avail * pane.ratio) / (others + pane.ratio) >= min) return;
    const w = (min * others) / (avail - min);
    const scale = Math.max(1, w);
    if (scale > 1) for (const p of this.panes) p.ratio /= scale;
    pane.ratio = checkRatio(Math.min(1, w / scale));
  }

  /**
   * BQ-11, E11-D02 §8: the boundary below pane `i` moves `dy` CSS px. Only the two panes beside
   * it change height; the others keep theirs. A pane pushed below the minimum collapses (its
   * weight kept); a drag that would grow a collapsed pane restores it. Computed from the weights,
   * not the last rects, so several moves in one frame compose; the layout reflows once a frame.
   */
  dragSplitter(i: number, dy: number): number {
    const a = this.panes[i];
    const b = this.panes[i + 1];
    if (a === undefined || b === undefined || dy === 0 || !Number.isFinite(dy)) return SPLIT.none;
    if (a.collapsed || b.collapsed) {
      const grow = a.collapsed && dy > 0 ? a : b.collapsed && dy < 0 ? b : null;
      return grow !== null && this.setCollapsed(grow.id, false) ? SPLIT.restored : SPLIT.none;
    }
    let stubs = 0;
    let sum = 0;
    for (const p of this.panes) {
      if (p.collapsed) stubs += 1;
      else sum += p.ratio;
    }
    const avail = Math.max(1, this.plotHeight() - stubs * this.stubPx);
    const ha = (avail * a.ratio) / sum;
    const hb = (avail * b.ratio) / sum;
    const under = ha + dy < this.minPanePx ? a : hb - dy < this.minPanePx ? b : null;
    if (under !== null) return this.setCollapsed(under.id, true) ? SPLIT.collapsed : SPLIT.none;
    // Heights follow the weights in proportion, so the pair's weight total is unchanged.
    const wa = (sum * (ha + dy)) / avail;
    const wb = (sum * (hb - dy)) / avail;
    // Weights stay in (0, 1]: past 1, every weight scales down together (the shares are equal).
    const scale = Math.max(1, wa, wb);
    if (scale > 1) for (const p of this.panes) p.ratio /= scale;
    a.ratio = checkRatio(wa / scale);
    b.ratio = checkRatio(wb / scale);
    this.reshare();
    return SPLIT.moved;
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
    let stubs = 0;
    for (i = 0; i < panes.length; i += 1) {
      const p = panes[i] as PaneLayout;
      if (p.collapsed) stubs += 1;
      else sum += p.ratio;
    }
    const plotW = Math.max(0, width - this.priceGutter);
    const plotH = Math.max(0, height - this.timeGutter);
    // BQ-11: stubs take their fixed row; the expanded panes tile the rest by weight.
    const stub = Math.min(this.stubPx, Math.floor(plotH / Math.max(1, panes.length)));
    const avail = plotH - stubs * stub;
    let acc = 0;
    let used = 0; // the expanded panes' cumulative bottom inside `avail`
    let y = 0;
    for (i = 0; i < panes.length; i += 1) {
      const p = panes[i] as PaneLayout;
      let h = stub;
      if (!p.collapsed) {
        acc += p.ratio;
        const bottom = Math.round((avail * acc) / sum); // cumulative: the panes tile plotH exactly
        h = bottom - used;
        used = bottom;
      }
      put(p.rect, 0, y, plotW, h);
      put(p.priceAxis, plotW, y, width - plotW, h);
      y += h;
    }
    put(this.timeAxis, 0, plotH, plotW, height - plotH);
    this.computes += 1;
    return true;
  }

  /** The panes' rows: the canvas height above the time strip. */
  private plotHeight(): number {
    return Math.max(0, this.height - this.timeGutter);
  }

  private expanded(): number {
    let n = 0;
    for (const p of this.panes) if (!p.collapsed) n += 1;
    return n;
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

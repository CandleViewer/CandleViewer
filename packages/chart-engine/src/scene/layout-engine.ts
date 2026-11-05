// The layout engine (E11-S01 PR3): pane rects, the price- and time-axis gutters and the panes'
// height ratios, normalised over the panes (BQ-S13). As the scheduler's layout hook it recomputes
// only when a pane it lays out is LAYOUT-dirty (BQ-43). DOM-free; rects are allocated per pane once.
// E11-S09 (BQ-11): shares sum to exactly 1, whole pixels tile the plot, a pane under the minimum
// collapses to a labelled stub and restores to max(last share, minimum).
import { Dirty } from "./dirty.js";
import type { SceneGraph } from "./graph.js";

/** x, y, width, height. */
export type Rect = [number, number, number, number];

export interface PaneLayout {
  readonly id: string;
  /** E11-S09 (BQ-1): the stable pane key the facade minted (the wire's `pane`). */
  key: number;
  /** The normalised share (BQ-11): the open panes' shares sum to exactly 1; 0 while collapsed. */
  share: number;
  /** The share before it collapsed: a restore gives back max(lastShare, the minimum). */
  lastShare: number;
  collapsed: boolean;
  readonly rect: Rect; // the plot area (a collapsed pane's: its stub row)
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

/** E11-D02 §8 (D02:96): a pane's minimum height, max(48 px, 3 × the axis label box). */
export const minPanePx = (labelBoxPx: number): number => Math.max(48, 3 * labelBoxPx);
/** The collapsed stub row (D02:95): 32 px comfortable, 24 px compact and dense. */
export const STUB_PX = { comfortable: 32, compact: 24 } as const;
/** The comfortable axis label box (`type.num.base` 13 px in a 16 px box, D02 §6). */
export const LABEL_BOX_PX = 16;

/** The price-axis gutter right of each pane and the time-axis gutter below them, CSS px. */
export const PRICE_GUTTER_PX = 64;
export const TIME_GUTTER_PX = 24;

export class LayoutEngine {
  readonly panes: PaneLayout[] = [];
  readonly timeAxis: Rect = [0, 0, 0, 0];
  width = 0;
  height = 0;
  computes = 0; // recomputations so far: LAYOUT frames only

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

  /** The stub row and the minimum pane height, CSS px (`setChrome`; comfortable by default). */
  stubPx: number = STUB_PX.comfortable;
  minPx = minPanePx(LABEL_BOX_PX);
  /** A share mutation awaits its collapse check at the next sized recompute (BQ-11). */
  private settle = false;

  /** The density's stub row and label box (D02:95-96); LAYOUT only when one changes. */
  setChrome(stubPx: number, labelBoxPx: number): void {
    const min = minPanePx(labelBoxPx);
    if (!(stubPx > 0) || (stubPx === this.stubPx && min === this.minPx)) return;
    [this.stubPx, this.minPx] = [stubPx, min];
    this.graph.markResize();
  }

  byKey(key: number): PaneLayout | undefined {
    return this.panes.find((p) => p.key === key);
  }

  /**
   * Lays out a pane already in the graph, below the others (BQ-11): `share` defaults to an equal
   * share, 1 / (open panes + 1), and the other open panes rescale proportionally into the rest.
   */
  addPane(id: string, share?: number, key = this.panes.length): void {
    if (this.graph.get(id)?.kind !== "pane") throw new RangeError(`unknown pane ${id}`);
    const r = share === undefined ? 1 / (this.openCount() + 1) : checkRatio(share);
    const p = { id, key, share: r, lastShare: r, collapsed: false } as const;
    this.panes.push({ ...p, rect: [0, 0, 0, 0], priceAxis: [0, 0, 0, 0] });
    this.setShares([[id, r]]);
  }

  /** Takes a pane out; the others' shares are renormalised (its graph node is the caller's). */
  removePane(id: string): void {
    this.panes.splice(this.panes.indexOf(this.pane(id)), 1);
    this.reopenLast();
    this.normalise();
    this.graph.markResize();
  }

  /**
   * E11-S09 (BQ-11a): `into` keeps its slot and node but takes `from`'s key, share and collapse;
   * `from`'s row goes. The first slot holds the content, so removing its key while other panes
   * remain hands it the next pane's identity, and the slot order matches the facade's.
   */
  absorb(into: string, from: string): void {
    const [a, b] = [this.pane(into), this.pane(from)];
    [a.key, a.share, a.lastShare] = [b.key, b.share, b.lastShare];
    if (a.collapsed !== b.collapsed) this.show(a, !b.collapsed);
    this.panes.splice(this.panes.indexOf(b), 1);
    this.reopenLast();
    this.normalise();
    this.graph.markResize();
  }

  /** The degraded-2d handoff (BQ-10): each slot takes the old slot's key, share and collapse. */
  copyFrom(rows: readonly Readonly<PaneLayout>[]): void {
    for (let i = 0; i < rows.length && i < this.panes.length; i += 1) {
      const [a, b] = [this.panes[i] as PaneLayout, rows[i] as PaneLayout];
      [a.key, a.share, a.lastShare] = [b.key, b.share, b.lastShare];
      if (a.collapsed !== b.collapsed) this.show(a, !b.collapsed);
    }
    this.graph.markResize();
  }

  /** The last open pane never folds: a removal that leaves only stubs reopens the last one. */
  private reopenLast(): void {
    const last = this.panes.at(-1);
    if (last === undefined || this.openCount() > 0) return;
    this.show(last, true);
    last.share = 1;
  }

  setSize(width: number, height: number): void {
    if (width === this.width && height === this.height) return;
    this.width = Math.max(0, width);
    this.height = Math.max(0, height);
    this.graph.markResize();
  }

  /** `Pane.setHeightRatio`: this pane takes `ratio`, the other open panes rescale into the rest. */
  setHeightRatio(id: string, ratio: number): void {
    this.setShares([[id, ratio]]);
  }

  /**
   * The worker owns the ratios (BQ-3): each listed pane takes its share (a collapsed one is
   * restored with it), the unlisted open panes share the rest in proportion, and the result is
   * normalised. A pane that lands below the minimum collapses at the next sized recompute.
   */
  setShares(entries: readonly (readonly [string, number])[]): void {
    const listed = new Set<PaneLayout>();
    for (const [id, r] of entries) {
      const p = this.pane(id);
      p.share = checkRatio(r);
      if (p.collapsed) this.show(p, true);
      listed.add(p);
    }
    let taken = 0;
    let rest = 0;
    let others = 0;
    for (const p of this.panes) {
      if (p.collapsed) continue;
      if (listed.has(p)) taken += p.share;
      else [rest, others] = [rest + p.share, others + 1];
    }
    const room = Math.max(0, 1 - taken);
    for (const p of this.panes) {
      if (p.collapsed || listed.has(p)) continue;
      p.share = rest > 0 ? (p.share / rest) * room : room / others;
    }
    this.normalise();
    this.settle = true;
    this.graph.markResize();
  }

  /** Collapse to the stub, or restore to max(last share, minimum); false when refused or a no-op. */
  setCollapsed(id: string, collapsed: boolean): boolean {
    const p = this.pane(id);
    if (p.collapsed === collapsed || (collapsed && this.openCount() <= 1)) return false;
    if (collapsed) {
      this.fold(p);
      this.graph.markResize();
      return true;
    }
    const plotH = this.plotHeight() - this.stubPx * (this.collapsedCount() - 1);
    const min = plotH > 0 ? this.minPx / plotH : 0;
    this.setShares([[id, Math.min(1, Math.max(p.lastShare, min))]]);
    return true;
  }

  /** The layout stage, every frame: `true` when it recomputed. Allocates nothing. */
  run(): boolean {
    const { panes, width } = this;
    let i = 0;
    for (; i < panes.length; i += 1) {
      if (((this.graph.get((panes[i] as PaneLayout).id)?.dirty ?? 0) & Dirty.LAYOUT) !== 0) break;
    }
    if (i === panes.length) return false;
    const plotW = Math.max(0, width - this.priceGutter);
    const plotH = this.plotHeight();
    if (this.settle && plotH > 0) this.collapseBelowMinimum(plotH);
    // BQ-11 rider: the stubs' fixed px come out first, the open panes share the rest by
    // cumulative rounding, and the last open pane takes the remainder: px tile plotH exactly.
    const stub = this.stubHeight(plotH);
    const avail = plotH - stub * this.collapsedCount();
    let last = -1;
    for (i = 0; i < panes.length; i += 1) if (!(panes[i] as PaneLayout).collapsed) last = i;
    let acc = 0;
    let used = 0;
    let y = 0;
    for (i = 0; i < panes.length; i += 1) {
      const p = panes[i] as PaneLayout;
      let h = stub;
      if (!p.collapsed) {
        acc += p.share;
        const bottom = i === last ? avail : Math.min(avail, Math.round(avail * acc));
        h = bottom - used;
        used = bottom;
      }
      put(p.rect, 0, y, plotW, h);
      put(p.priceAxis, plotW, y, width - plotW, h);
      y += h;
    }
    put(this.timeAxis, 0, plotH, plotW, this.height - plotH);
    this.computes += 1;
    return true;
  }

  private plotHeight(): number {
    return Math.max(0, this.height - this.timeGutter);
  }

  /** Each stub's px: the row, or an equal part of a plot too short for every stub. */
  private stubHeight(plotH: number): number {
    const n = this.collapsedCount();
    return n === 0 ? 0 : Math.min(this.stubPx, Math.floor(plotH / n));
  }

  /** A share mutation's check (D02:367): the smallest open pane under the minimum folds, again. */
  private collapseBelowMinimum(plotH: number): void {
    this.settle = false;
    for (let guard = this.panes.length; guard > 0 && this.openCount() > 1; guard -= 1) {
      const avail = plotH - this.stubHeight(plotH) * this.collapsedCount();
      let victim: PaneLayout | null = null;
      for (let i = 0; i < this.panes.length; i += 1) {
        const p = this.panes[i] as PaneLayout;
        if (p.collapsed || avail * p.share >= this.minPx - 1e-6) continue; // 48 / 400 * 400
        if (victim === null || p.share < victim.share) victim = p;
      }
      if (victim === null) return;
      this.fold(victim);
    }
  }

  private fold(p: PaneLayout): void {
    p.lastShare = p.share;
    this.show(p, false);
    this.normalise();
  }

  private show(p: PaneLayout, open: boolean): void {
    p.collapsed = !open;
    if (!open) p.share = 0;
    this.graph.setVisible(p.id, open); // a collapsed pane draws nothing; its rings are kept
  }

  /** Shares over the open panes, summing to exactly 1: the last open pane takes the remainder. */
  private normalise(): void {
    let sum = 0;
    let last = -1;
    const panes = this.panes;
    for (let i = 0; i < panes.length; i += 1) {
      const p = panes[i] as PaneLayout;
      if (!p.collapsed) [sum, last] = [sum + p.share, i];
    }
    const n = this.openCount();
    let acc = 0;
    for (let i = 0; i < last; i += 1) {
      const p = panes[i] as PaneLayout;
      if (p.collapsed) continue;
      p.share = sum > 0 ? p.share / sum : 1 / n;
      acc += p.share;
    }
    if (last >= 0) (panes[last] as PaneLayout).share = Math.max(0, 1 - acc);
  }

  private openCount(): number {
    return this.panes.length - this.collapsedCount();
  }

  private collapsedCount(): number {
    let n = 0;
    for (let i = 0; i < this.panes.length; i += 1)
      if ((this.panes[i] as PaneLayout).collapsed) n += 1;
    return n;
  }

  private pane(id: string): PaneLayout {
    const p = this.panes.find((q) => q.id === id);
    if (p === undefined) throw new RangeError(`unknown pane ${id}`);
    return p;
  }
}

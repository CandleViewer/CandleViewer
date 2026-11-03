// `candle-lod` scene (E12-S09 PR 1, #421 BQ-07 / BQ-12): one candle series of `n` bars (5k, 50k,
// 100k) at a pinned tier through the scheduler, the batch builder and `GLBackend` (the fake GL in
// tests). L0 and L1 draw the ring at 6 and 2 px a bar (the last W / s bars in view). L2 draws a
// `ColumnEntries` over a synthetic, test-only grid that puts all n bars across the plot
// (W / n device px a bar: 100k "zoomed to fit", which the 0.05 px clamp forbids a real viewport,
// BQ-07), its columns from a bench-local one-pass fold, a stand-in for E11-S12's decimator (#418),
// not its code; the last bar is forming, so it is its own entry (BQ-05). Here the scene does the
// L2 source attach that PR 2's runtime will. Steps: `pan` (L0 / L1 uniforms only; L2 a full re-fold
// of the shifted grid) and `tick` (the forming bar patched, then the frame). The unit test counts
// draws, uploads and allocations; candle-lod.perf.test.ts times the frames.
import { GLBackend } from "../../src/gl/backend.js";
import type { GL2Like } from "../../src/gl/gl-types.js";
import { type ColumnSource, ColumnEntries, foldEnd } from "../../src/layers/candle/columns.js";
import { CandleRing } from "../../src/layers/candle/ring.js";
import { CANDLE_ATTRIBUTES, CandleSeries } from "../../src/layers/candle/series.js";
import { BAR_FLAG, BarStore } from "../../src/model/BarStore.js";
import { BatchBuilder } from "../../src/scene/batch-builder.js";
import type { FrameCallback } from "../../src/scene/frame-clock.js";
import { FrameScheduler } from "../../src/scene/frame-scheduler.js";
import { SceneGraph } from "../../src/scene/graph.js";
import { ChartViewport, createPaneUniforms, writePaneUniforms } from "../../src/viewport/index.js";
import { candleBars } from "./candle-series.js";

const THEME = {
  "color.candle.up": "#26a69a",
  "color.candle.down": "#ef5350",
  "color.candle.wick": "#787b86",
  "color.surface.canvas": "#131722",
};
const W = 1600;
const H = 900;
/** CSS px a bar at L0 and L1 (D06 §5.2's sample steps). */
export const LOD_SPACING = [6, 2, 0.05] as const;
const EMPTY_LO = 2 ** 31 - 1;
const EMPTY_HI = -(2 ** 31);

export class CandleLodBench {
  readonly graph = new SceneGraph();
  readonly store = new BarStore();
  readonly ring: CandleRing;
  readonly series: CandleSeries;
  readonly entries: ColumnEntries;
  readonly builder: BatchBuilder;
  readonly scheduler: FrameScheduler;
  readonly viewport: ChartViewport;
  readonly backend: GLBackend;
  /** The bench's fold output: W columns of (minLow, maxHigh, firstOpen, lastClose). */
  readonly columns: ColumnSource = {
    ints: new Int32Array(W * 4),
    stride: 4,
    count: W,
    firstColumn: 0,
  };
  private readonly uniforms = createPaneUniforms();
  private readonly live = candleBars(1);
  private readonly px: number;
  private offset = 0;
  private pending: FrameCallback | null = null;
  private readonly warm: number;

  constructor(
    readonly n: number,
    gl: GL2Like,
    readonly tier: 0 | 1 | 2,
    private readonly now: () => number = () => 0,
  ) {
    this.graph.addPane("main");
    this.viewport = new ChartViewport(this.store);
    this.viewport.setSize(W, H, 1);
    this.viewport.setPanePlot(0, 0, H);
    this.backend = new GLBackend(gl, null);
    this.backend.setPaneUniforms(() => this.uniforms);
    this.builder = new BatchBuilder(this.graph, this.backend);
    this.ring = new CandleRing(this.builder);
    this.series = new CandleSeries(this.ring);
    this.entries = new ColumnEntries(W, this.builder);
    const deps = { viewport: this.viewport, pane: 0, theme: () => this.theme };
    const blocks = new Map<string, (typeof this.series.blocks)[number]>();
    const hosts = this.series.mount(this.graph, "main", "series.candle.0.0", deps);
    if (tier === 2) {
      this.ring.nodes.length = 0; // PR 2's runtime: the two marks read the entries at L2
      this.entries.nodes.push(...hosts.slice(0, 2).map((h) => h.id));
    }
    hosts.forEach((h, p) => {
      blocks.set(h.id, this.series.blocks[p] as (typeof this.series.blocks)[number]);
      const src = tier === 2 && p < 2 ? this.entries : (this.series.sources[p] ?? this.ring);
      this.backend.attach(h.id, src, CANDLE_ATTRIBUTES);
    });
    this.backend.setBatchUniforms((b) => blocks.get(b.nodeId) ?? null);
    this.series.setTheme(THEME);
    const clock = {
      now: (): number => this.now(),
      requestFrame: (cb: FrameCallback): number => ((this.pending = cb), 1),
      cancel: (): null => (this.pending = null),
    };
    this.scheduler = new FrameScheduler(this.graph, clock, {
      build: (sink) => this.builder.build(sink),
      submit: () => {
        const vp = this.viewport;
        const first = Math.floor(vp.leftIndex);
        const last = Math.floor(vp.leftIndex + vp.plotWidth / vp.barSpacing);
        this.series.frame(vp.barSpacing, vp.dpr, first, last, 0, H, this.tier, this.entries);
        writePaneUniforms(this.viewport, 0, this.uniforms);
        this.uniforms.floats[4] = W;
        this.uniforms.floats[5] = H;
        this.backend.submit(this.builder.drawList, this.builder.drawCount, W, H);
      },
      viewport: this.viewport,
    });
    const all = candleBars(n);
    (all.flags as Uint8Array)[n - 1] = BAR_FLAG.forming;
    this.ring.sync(this.store, this.store.replace(all));
    this.viewport.setPriceInfo(0, 0, 1);
    const shown = tier === 2 ? n : Math.floor(W / LOD_SPACING[tier]);
    this.viewport.setTimeRange((n - shown) * 60e6, (n - 1) * 60e6);
    this.px = W / n;
    this.live.flags?.fill(BAR_FLAG.forming);
    this.fold();
    this.frame(0);
    this.tick(16); // warm-up: the first forming-bar patch and its sub-upload
    this.warm = this.allocations();
  }

  private readonly theme = {
    palette: "default" as const,
    convention: "standard" as const,
    colors: THEME,
  };

  private frame(t: number): void {
    this.scheduler.wake();
    const cb = this.pending;
    this.pending = null;
    cb?.(t);
  }

  /** L2: the bench's one-pass fold of [0, foldEnd) on the synthetic grid, then the entries. */
  private fold(): void {
    if (this.tier !== 2) return;
    const v = this.columns.ints;
    for (let j = 0; j < W; j += 1) {
      v[j * 4] = EMPTY_LO;
      v[j * 4 + 1] = EMPTY_HI;
    }
    const { open, high, low, close } = this.store.columns;
    const s = this.store;
    const mask = s.capacity - 1;
    const end = foldEnd(s);
    for (let i = 0; i < end; i += 1) {
      const col = Math.floor((i + 0.5 - this.offset) * this.px);
      if (col < 0 || col >= W) continue;
      const p = (s.ringHead + i) & mask;
      const at = col * 4;
      if ((v[at + 1] as number) === EMPTY_HI) v[at + 2] = open[p] as number;
      if ((low[p] as number) < (v[at] as number)) v[at] = low[p] as number;
      if ((high[p] as number) > (v[at + 1] as number)) v[at + 1] = high[p] as number;
      v[at + 3] = close[p] as number;
    }
    const forming = Math.floor((s.length - 0.5 - this.offset) * this.px);
    this.entries.write(this.columns, s, forming);
  }

  private markData(): void {
    for (const h of this.series.hosts) this.graph.markData(h.id);
  }

  /** A pan frame: L0 / L1 TRANSFORM only; L2 a 3 px shift of the grid, re-folded. */
  pan(t: number): void {
    const dx = t % 32 < 16 ? 3 : -3;
    if (this.tier === 2) {
      this.offset -= dx / this.px;
      this.fold();
      this.markData();
    } else this.viewport.pan(dx);
    this.graph.markViewport();
    this.frame(t);
  }

  /** A tick frame: the forming bar patched (merge), then the frame. */
  tick(t: number): void {
    const { store, ring, live } = this;
    live.time[0] = (this.n - 1) * 60e6;
    live.close[0] = 1_000 + ((t >> 4) & 3); // a new close every frame
    ring.sync(store, store.append(live, true));
    this.fold();
    this.markData();
    this.frame(t);
  }

  /** Objects made past warm-up: batches, GL objects, ring and entry arrays. Must stay 0. */
  allocations(): number {
    const { sink, queue } = this.scheduler;
    const gl = this.backend.registry.stats.created + this.ring.rewrites + this.entries.grown;
    return sink.pool.created + this.builder.pool.created + this.graph.rebuilds + queue.grown + gl;
  }

  get allocationsSinceWarm(): number {
    return this.allocations() - this.warm;
  }
}

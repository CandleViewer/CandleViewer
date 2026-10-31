// The public API surface, transcribed from docs/plan/26-chart-engine-design.md §8 (E11-T01).
// Every declaration between the "§8 verbatim" markers keeps §8's names, members and member
// types. §8 names several supporting types without defining them; they are defined below the
// markers, each as the narrowest shape the engine needs today (package README "Design deltas").
// Types only: no React, no DOM globals, no I/O here (C-2.16). `HTMLElement` is a type reference.

// ---- §8 verbatim ----------------------------------------------------------

export interface ChartOptions {
  container: HTMLElement;
  runMode?: "worker" | "inline"; // default 'worker' when OffscreenCanvas exists
  theme: ThemeTokens;
  locale?: string; // default 'en-GB'
  timeZone?: "UTC" | string; // default 'UTC'
  density?: "comfortable" | "compact" | "dense";
  syncGroup?: string;
  maxBars?: number; // default 200_000
  memoryBudgetMb?: number; // default 600
}

export interface Chart {
  readonly panes: readonly Pane[];
  addPane(opts: PaneOptions): Pane;
  removePane(id: PaneId): void;
  readonly timeScale: TimeScale;
  setTheme(theme: ThemeTokens): void;
  setDensity(d: Density): void;
  subscribe<E extends keyof ChartEvents>(e: E, cb: (p: ChartEvents[E]) => void): Unsubscribe;
  takeScreenshot(opts?: { scale?: number }): Promise<Blob>;
  getStats(): FrameStats;
  dispose(): void;
  // Design delta BQ-3 (05-accessibility-standard.md §6.1; E11-T01 accessibility notes): the DOM
  // mirror anchor and the visible-window / focused-unit query surface, frozen from day one.
  getDomMirrorRoot(): HTMLElement;
  getVisibleWindow(): VisibleWindow | null;
  getFocusedUnit(): FocusedUnit | null;
}

export interface Pane {
  readonly id: PaneId;
  readonly priceScale: PriceScale;
  addSeries<T extends SeriesType>(type: T, opts: SeriesOptionsMap[T]): SeriesHandle<T>;
  addOverlay(plugin: OverlayPlugin, opts?: unknown): OverlayHandle;
  addIndicator(plugin: IndicatorPlugin, params: Record<string, number | string>): IndicatorHandle;
  setHeightRatio(r: number): void;
  remove(): void;
}

export type SeriesType =
  | "candles"
  | "bars"
  | "line"
  | "area"
  | "baseline"
  | "footprint"
  | "profile"
  | "heatmap"
  | "bubbles"
  | "histogram";

export interface SeriesOptionsMap {
  candles: CandleOptions;
  footprint: FootprintOptions;
  profile: ProfileOptions;
  heatmap: HeatmapOptions;
  bubbles: BubbleOptions;
  bars: CandleOptions;
  line: LineOptions;
  area: LineOptions;
  baseline: LineOptions;
  histogram: HistogramOptions;
}

export interface SeriesHandle<T extends SeriesType> {
  setData(data: SeriesDataMap[T]): void; // full replace (transfers buffers)
  append(data: SeriesDeltaMap[T]): void; // incremental
  prependHistory(data: SeriesDataMap[T]): void; // scroll-back paging
  setOptions(opts: Partial<SeriesOptionsMap[T]>): void;
  setVisible(v: boolean): void;
  remove(): void;
}

// ---- Data shapes (all typed arrays, transferable) -------------------------

export interface CandleData {
  time: Float64Array; // µs epoch
  open: Int32Array; // price in ticks
  high: Int32Array;
  low: Int32Array;
  close: Int32Array;
  volume: Float32Array;
  priceOrigin: number;
  tickSize: number;
}

export interface FootprintData {
  barIndexOffsets: Uint32Array; // length = bars + 1, prefix sums into cells
  cellPriceLevel: Int32Array; // ticks from priceOrigin
  cellBidVol: Float32Array;
  cellAskVol: Float32Array;
  cellTradeCount: Uint16Array;
  priceOrigin: number;
  tickSize: number;
}

export interface HeatmapColumnData {
  time: number; // µs epoch
  priceOrigin: number;
  priceStep: number;
  rows: number;
  sizes: Float32Array; // length = rows
  estimated?: boolean;
}

export interface FootprintOptions {
  cellType: "volume" | "bid-ask" | "delta" | "delta-total";
  displayMode: "profile" | "box";
  imbalanceRatio: number; // default 3.0 (= 300 %)
  imbalanceStack: number; // default 3
  noiseFilter: number; // min volume per cell to render text
  textLod: "auto" | "always" | "never";
  colorScale: "delta" | "volume" | "imbalance";
}

export interface HeatmapOptions {
  colorScale: "linear" | "log";
  trailMs: number; // default 4 h
  bidColorToken: string; // default token 'liquidity.bid' (green)
  askColorToken: string; // default token 'liquidity.ask' (red)
  maxRows: number; // default 512
  cadenceMs: number; // default 100
}

// ---- Interaction & trading overlays --------------------------------------

export interface OrderLine {
  id: string;
  price: number; // ticks
  kind: "entry" | "stop" | "take-profit" | "position" | "alert" | "liquidation";
  side: "buy" | "sell";
  label: string;
  draggable: boolean;
  accountId?: string; // fan-out: multiple lines may share a price
}

export interface ChartEvents {
  crosshair: { time: number; price: number; barIndex: number; cell?: FootprintCellRef };
  click: { time: number; price: number; button: number; modifiers: Modifiers };
  orderLineDragged: { id: string; price: number; commit: boolean };
  drawingChanged: { drawing: Drawing; phase: "create" | "update" | "delete" };
  viewportChanged: { timeStart: number; timeEnd: number; barSpacing: number };
  visibleRangeNeedsData: { fromTime: number; toTime: number }; // triggers paging
  frameStats: FrameStats;
  error: {
    code: string;
    message: string;
    recoverable: boolean;
    /**
     * On `ENGINE_CONTEXT_LOST` (BQ-64) and `ENGINE_NO_WEBGL2` (E11-T05, BQ-90) only; the UI never
     * parses `message`. The second names what `degraded-2d` reduces and why, as codes.
     */
    details?:
      | { attempt: number; maxAttempts: number; nextTryMs: number }
      | {
          reducedCapabilities: (
            "footprint-text" | "heatmap" | "bubbles" | "profile-shading" | "gpu-effects"
          )[];
          reason: "no-webgl2" | "context-failed" | "compile-failed" | "restore-failed" | "forced";
        };
  };
}

export interface FrameStats {
  fps: number;
  frameTimeMsP50: number;
  frameTimeMsP95: number;
  drawCalls: number;
  triangles: number;
  uploadedBytesPerSec: number;
  lodCandles: 0 | 1 | 2;
  lodFootprint: 0 | 1 | 2 | 3;
  gpuMemoryMbEstimate: number;
  renderProfile: "full" | "reduced" | "degraded-2d";
}

// ---- Plugin API ----------------------------------------------------------

export interface RenderContext {
  readonly viewport: Viewport;
  readonly theme: ThemeTokens;
  rect(x: number, y: number, w: number, h: number, colorToken: string): void;
  line(x0: number, y0: number, x1: number, y1: number, style: LineStyle): void;
  glyphRun(x: number, y: number, text: string, style: TextStyle): void;
  quadBatch(instances: Float32Array, stride: number, program: "cell" | "disc" | "bar"): void;
  texture(id: TextureId, rect: Rect, uv: Rect, lut: LutId): void;
}

export interface SeriesPlugin<D, O> {
  readonly type: string;
  attach(ctx: PluginContext): void;
  onData(data: D, op: "set" | "append" | "prepend"): void;
  onOptions(opts: Partial<O>): void;
  collect(ctx: RenderContext): void;
  hitTest(pt: Point): PickResult | null;
  priceRange(visibleBars: Range): { low: number; high: number } | null;
  detach(): void;
}

export interface IndicatorPlugin {
  readonly id: string;
  readonly params: ParamSpec[];
  readonly outputs: OutputSpec[];
  compute(bars: BarView, params: Params, out: OutputBuffers): void; // full
  update(bars: BarView, params: Params, out: OutputBuffers, from: number): void; // incremental
}

// ---- end §8 verbatim ------------------------------------------------------

// ---- Types §8 names but does not define (narrowest shape; README "Design deltas") ----

/**
 * The theme token object (§5 rule 1): the host resolves design-system tokens and hands them in;
 * the engine never imports the design system. `colors` maps token names (for example
 * `color.chart.background`, `color.candle.up`) to CSS colour strings. Same shape as the
 * pre-§8 `EngineTheme` palette seam (BQ-2), so one token object feeds both.
 */
export interface ThemeTokens {
  readonly palette: "default" | "cvd-safe";
  readonly convention: "standard" | "inverted";
  readonly colors: Readonly<Record<string, string>>;
}

export type Density = "comfortable" | "compact" | "dense";

/** Opaque pane id, minted by `Chart.addPane`. */
export type PaneId = string & { readonly __brand: "PaneId" };

export interface PaneOptions {
  /** Share of the chart height, in (0, 1]; default 1. */
  heightRatio?: number;
  /**
   * E11-S05 (README BQ-121, C-35): the persisted scale, applied at `addPane`; the lock is session
   * state and never part of it.
   */
  priceScale?: {
    mode?: "linear" | "log" | "percent" | "indexed";
    inverted?: boolean;
    includeDrawings?: boolean;
    priceOnly?: boolean;
    marginTop?: number;
    marginBottom?: number;
  };
}

export type Unsubscribe = () => void;

/** A µs-epoch time window (inclusive start, exclusive end). */
export interface TimeRange {
  from: number;
  to: number;
}

/** A price window in ticks from the series' `priceOrigin`. */
export interface PriceRange {
  low: number;
  high: number;
}

export interface TimeScale {
  getVisibleRange(): TimeRange | null;
  setVisibleRange(range: TimeRange): void;
}

export interface PriceScale {
  getVisibleRange(): PriceRange | null;
  /** `false` is the lock (E11-D03: auto is the Lock's off state, C-30). */
  setAutoScale(on: boolean): void;
  // E11-S05 (README BQ-121): widened with inline literal types; §8's verbatim block is untouched.
  /** Log while unavailable is refused and the mode stays (`getState().logReason` says why). */
  setMode(mode: "linear" | "log" | "percent" | "indexed"): void;
  setInverted(on: boolean): void;
  /** Margins are fractions of the window, each in [0, 0.45]; a RangeError otherwise. */
  setOptions(opts: {
    includeDrawings?: boolean;
    priceOnly?: boolean;
    marginTop?: number;
    marginBottom?: number;
  }): void;
  /** The state the renderer last reported (`requestedMode` is what the app persists). */
  getState(): {
    mode: "linear" | "log" | "percent" | "indexed";
    requestedMode: "linear" | "log" | "percent" | "indexed";
    inverted: boolean;
    autoScale: boolean;
    includeDrawings: boolean;
    priceOnly: boolean;
    marginTop: number;
    marginBottom: number;
    logAvailable: boolean;
    logReason: "non-positive" | "no-price-origin" | null;
    /** Percent / indexed: the anchor bar's close in ticks; null when none. */
    anchorTick: number | null;
  };
}

export interface OverlayHandle {
  setOptions(opts: unknown): void;
  remove(): void;
}

export interface IndicatorHandle {
  setParams(params: Record<string, number | string>): void;
  remove(): void;
}

// Option bags §8 maps but leaves to their owning tickets (E12 candles/lines, E13 profile/bubbles).
export interface CandleOptions {
  upColorToken: string;
  downColorToken: string;
}

export interface LineOptions {
  colorToken: string;
  lineWidth: number;
}

export interface HistogramOptions {
  colorToken: string;
}

export interface ProfileOptions {
  valueAreaPercent: number; // default 70
}

export interface BubbleOptions {
  minSizeQty: number;
}

/** Line / area / baseline / histogram values: one f64 per µs-epoch time. */
export interface LineData {
  time: Float64Array;
  value: Float64Array;
}

/** A volume/delta profile (§3.3 ProfileStore). */
export interface ProfileData {
  priceLevel: Int32Array; // ticks from priceOrigin
  volume: Float32Array;
  delta: Float32Array;
  priceOrigin: number;
  tickSize: number;
}

/** Trade bubbles: one per trade cluster. `side` is 0 = sell, 1 = buy. */
export interface BubbleData {
  time: Float64Array;
  price: Int32Array; // ticks from priceOrigin
  size: Float32Array;
  side: Uint8Array;
  priceOrigin: number;
  tickSize: number;
}

/** Full-replace payloads per series type (`setData`, `prependHistory`). */
export interface SeriesDataMap {
  candles: CandleData;
  bars: CandleData;
  line: LineData;
  area: LineData;
  baseline: LineData;
  histogram: LineData;
  footprint: FootprintData;
  profile: ProfileData;
  heatmap: readonly HeatmapColumnData[];
  bubbles: BubbleData;
}

/**
 * Incremental payloads per series type (`append`). §8 types `append` for every series type, so
 * every type has an entry; the merge rule differs by type (26 §3.3 mutation API):
 * - `candles`, `bars`, `line`, `area`, `baseline`, `histogram`: the payload's first bar patches
 *   the last bar held when their times are equal, and the rest append (`patchLastBar`,
 *   `appendBars`).
 * - `footprint`: upserts the payload's cells by bar index (`upsertFootprintCells(barIndex,
 *   cells)`); it never patches or appends a whole bar.
 * - `profile`: replaces the profile held (`replaceProfile(period, data)`); there is no partial
 *   merge.
 * - `heatmap`: pushes one column (`pushHeatmapColumn`).
 * - `bubbles`: appends; earlier bubbles are never patched.
 * E11-T03 (the stores) and E12 confirm or change these rules before E12 builds on them.
 */
export interface SeriesDeltaMap {
  candles: CandleData;
  bars: CandleData;
  line: LineData;
  area: LineData;
  baseline: LineData;
  histogram: LineData;
  footprint: FootprintData;
  profile: ProfileData;
  heatmap: HeatmapColumnData;
  bubbles: BubbleData;
}

export interface FootprintCellRef {
  barIndex: number;
  priceLevel: number; // ticks from priceOrigin
}

export interface Modifiers {
  shift: boolean;
  ctrl: boolean;
  alt: boolean;
  meta: boolean;
}

/** A drawing as far as the event channel needs it; the drawing model is E14's. */
export interface Drawing {
  readonly id: string;
  readonly kind: string;
}

export interface Viewport {
  readonly widthPx: number;
  readonly heightPx: number;
  readonly pixelRatio: number;
  readonly timeStart: number;
  readonly timeEnd: number;
}

export interface LineStyle {
  colorToken: string;
  width: number;
  dash?: readonly number[];
}

export interface TextStyle {
  colorToken: string;
  sizeClass: "xs" | "sm" | "md";
  align?: "left" | "center" | "right";
}

export type TextureId = number & { readonly __brand: "TextureId" };
export type LutId = number & { readonly __brand: "LutId" };

export interface Rect {
  x: number;
  y: number;
  w: number;
  h: number;
}

export interface Point {
  x: number;
  y: number;
}

/** A bar-index range, inclusive. */
export interface Range {
  from: number;
  to: number;
}

export interface PluginContext {
  readonly theme: ThemeTokens;
  requestRender(): void;
}

export interface PickResult {
  readonly kind: string;
  readonly id?: string;
  readonly distancePx: number;
}

export interface ParamSpec {
  readonly name: string;
  readonly kind: "number" | "string";
  readonly default: number | string;
}

export interface OutputSpec {
  readonly name: string;
  readonly kind: "line" | "histogram";
}

export type Params = Readonly<Record<string, number | string>>;
export type OutputBuffers = Readonly<Record<string, Float64Array>>;

/** A read-only columnar view over a bar store. */
export interface BarView extends Readonly<CandleData> {
  readonly length: number;
}

/** §3.12 overlay lifecycle: draws above series and may be interactive. */
export interface OverlayPlugin {
  readonly id: string;
  attach(ctx: PluginContext): void;
  onViewport(viewport: Viewport): void;
  collect(ctx: RenderContext): void;
  hitTest(pt: Point): PickResult | null;
  detach(): void;
}

/** The bars the DOM mirror must materialise (05 §6.1). */
export interface VisibleWindow {
  readonly timeStart: number;
  readonly timeEnd: number;
  readonly firstBarIndex: number;
  readonly lastBarIndex: number;
}

/** The unit keyboard focus is on (05 §6.1): a bar, a footprint cell or a DOM-ladder row. */
export interface FocusedUnit {
  readonly kind: "bar" | "cell" | "row";
  readonly paneId: PaneId;
  readonly barIndex: number;
  readonly priceLevel?: number;
}

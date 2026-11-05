// The render runtime (E11-T02): the one implementation of the worker side of §6. The worker entry
// (`render-worker.ts`) runs it behind `postMessage`; `RunMode.inline` runs the SAME module on the
// main thread behind a synchronous bus (26 §2), so only throughput differs between the modes.
// One runtime drives every chart registered with it from one frame callback, in registration
// order (§3.2 rule 1), each through its own `FrameScheduler` (E11-S01), and parks when nothing
// is dirty (§3.2 rule 5). No DOM types here (C-2.16): the canvas is reached structurally, as an
// OffscreenCanvas and an HTMLCanvasElement both fit. The runtime holds only the `RenderBackend`
// seam (E11-T05, README BQ-85): `openBackend` picks WebGL2 or Canvas 2D, and the loss wiring asks
// for the optional `LossCapable` hooks, so no line here branches on which backend draws (S3).
// E12-S06: the runtime owns one `BarStore` and its `CandleRing` per `addSeries` id; the main
// series (the first on pane 0) is the viewport's time map (G-8) and rebases the ObjectIndex
// (G-23). A refused batch (F-01 decode, F-02 store) leaves the store byte-identical. PR 2: OHLC
// `bars` draw through `BarSeries`; a plot pick that misses every object tries the series' bars
// (the geometry twin); a frame posts `dataState` when its visible range empties or fills, and an
// empty one hides the background layer (the grid, BQ-9). E12-S07: `setSeriesKind` (and the
// `heikinAshi` series option) redraws a series as candles, hollow candles or OHLC bars, with
// Heikin-Ashi on or off, over the same store (no data resent); Heikin-Ashi with a footprint is
// refused (`ENGINE_SERIES_INCOMPATIBLE`) and the series keeps drawing. Two metrics:
// `series_type_switch_duration_ms{target}` (the switch to the end of the next frame) and
// `series_incompatible_combination_total{combination}`.
import { AxisModel, SAY, UPDATE } from "../axes/axis-model.js";
import { GRID_NODE_ID } from "../axes/grid.js";
import type { RenderBackend } from "../gl/backend.js";
import { ContextLoss, type LossDetails } from "../gl/context-loss.js";
import { type OpenedBackend, openBackend } from "../gl/open-backend.js";
import {
  createPickHit,
  createStructuralHit,
  ObjectIndex,
  StructuralIndex,
  toleranceFor,
  type PickHit,
  type StructuralHit,
} from "../hit/index.js";
import { Gestures } from "../interaction/gestures.js";
import { CandleRing } from "../layers/candle/ring.js";
import { BarSeries } from "../layers/candle/bars.js";
import {
  type BarHit,
  CANDLE_ATTRIBUTES,
  CandleSeries,
  createBarHit,
} from "../layers/candle/series.js";
import type { HostDeps, HostTheme } from "../layers/host.js";
import type { BatchUniforms } from "../gl/submit.js";
import { type BarBatch, BarStore } from "../model/BarStore.js";
import { ModelRejection, type MutationRange, RangeSlot } from "../model/counters.js";
import { plotWidthOf } from "../interaction/wheel.js";
import * as scene from "../scene/index.js";
import { performanceStageMarker, type PerformanceTimeline } from "../scene/stage-marks.js";
import { AtlasService, type AtlasCounters, type AtlasDetails } from "../text/atlas.js";
import type { ChartFont, TextPlatform } from "../text/platform.js";
import {
  AutoScaler,
  ChartViewport,
  createPaneUniforms,
  type PriceExtentSource,
  type IndexTimeMap,
  type PaneUniforms,
  EMPTY_TIME_MAP,
  backingPx,
  screenToTime,
  writePaneUniforms,
} from "../viewport/index.js";
import {
  BACKGROUND_TOKEN,
  DecodeError,
  decodeBars,
  ENGINE_DECODE_ERROR,
  ENGINE_PANE_CAP,
  ENGINE_NO_WEBGL2,
  ENGINE_ATLAS_GENERATION_FAILED,
  fontsOk,
  ENGINE_SERIES_INCOMPATIBLE,
  INPUT,
  INPUT_STRIDE,
  MAX_PANES,
  rejectReason,
  RESTART_BACKOFF_MS,
  STORE_IDS,
  type BarSeriesKind,
  type BufferLayout,
  type ChartConfig,
  type CapabilityReport,
  type ChartId,
  type Command,
  type DataOp,
  type DegradeDetails,
  type ExportRejectReason,
  type FromWorker,
  type LodLevels,
  type PaneScaleRow,
  type PickPointer,
  type RunMode,
  type StoreId,
  type ThemeLut,
  type ToWorker,
  type SyncOrigin,
} from "./protocol.js";
import {
  DEFAULT_SYNC_MODES,
  ENGINE_SYNC_REFUSED,
  SyncGroups,
  SyncPublication,
  SyncRefused,
  type SyncGroup,
  type SyncModes,
} from "../sync/SyncGroup.js";

type LayoutMsg = Extract<FromWorker, { t: "layout" }>;

/** A pane without sources (every pane but 0 until E12): shared, so autoscale allocates nothing. */
const NO_SOURCES: readonly PriceExtentSource[] = Object.freeze([]);

/** The canvas members the runtime touches, common to OffscreenCanvas and HTMLCanvasElement. */
interface CanvasLike {
  width: number;
  height: number;
  getContext(id: "2d" | "webgl2", attributes?: object): unknown;
  convertToBlob?: (opts: { type: string }) => Promise<unknown>;
  toBlob?: (cb: (blob: unknown) => void, type: string) => void;
  addEventListener?(type: string, cb: (ev: { preventDefault(): void }) => void): void;
  removeEventListener?(type: string, cb: (ev: { preventDefault(): void }) => void): void;
}

export interface RuntimeDeps {
  readonly runMode: RunMode;
  post(msg: FromWorker): void;
  /** Schedules one frame callback (the worker's or the page's rAF). */
  requestFrame(cb: () => void): void;
  now(): number;
  /** One-shot timer: the context-restore attempts wait on it (BQ-49); it may return its cancel. */
  setTimer(cb: () => void, ms: number): void | (() => void);
  /** The capability probe behind the `ready` report; run once, on the first frame. */
  probe(): CapabilityReport;
  /** Test-only (E11-S04, BQ-111): bars for every chart's viewport until E12 wires the store. */
  readonly timeMap?: IndexTimeMap;
  /** Internal (E11-S05, BQ-116): pane 0's price sources for autoscale until E12 attaches them. */
  readonly priceSources?: readonly PriceExtentSource[];
  /** The atlas's font, raster and cache platform (E11-S11, BQ-261); null or absent: none here. */
  readonly text?: TextPlatform | null;
  /** The timeline bench-mode charts mark their stages on (E11-T06); unused outside bench mode. */
  readonly timeline?: PerformanceTimeline;
}

export interface RenderRuntime {
  /** Handles one inbound message. Never throws: a bad message becomes an `error` event. */
  handle(msg: unknown): void;
  /** Charts registered (read by tests and the host's restart bookkeeping). */
  readonly size: number;
  /** Internal (E11-S08, BQ-132): a chart's pick indices, which E14, E22 and E31 register in. */
  pickIndex(id: ChartId): { objects: ObjectIndex; structural: StructuralIndex } | undefined;
  /**
   * Internal (E11-S10, BQ-152): `cb(from, to)` runs once per DPR change, after the backing store
   * is resized and before the next frame. The SDF atlas ignores it: classes and DPR are shader
   * scales, so a DPR change never regenerates (E11-K01 BQ-175).
   * Returns the unsubscribe function; undefined for an unknown chart. A listener that throws
   * posts a recoverable error for its chart and the others still run.
   */
  onDprChange(id: ChartId, cb: (from: number, to: number) => void): (() => void) | undefined;
  /** Internal (BQ-153): a chart's resize counters. */
  resizeCounters(id: ChartId): Readonly<ResizeCounters> | undefined;
  /** Internal (E11-S11, BQ-272): `engine.atlas.*`; null until a WebGL2 chart with fonts opens. */
  atlasCounters(): Readonly<AtlasCounters> | null;
  /** Internal (E12-S06): one `addSeries` id's store and instance ring. */
  series(id: ChartId, series: number): SeriesEntry | undefined;
  /** Internal (E12-S06): `engine.data.rejected{reason}`, per chart. */
  dataRejected(id: ChartId): Readonly<Record<string, number>> | undefined;
  /** Internal (E12-S06, BQ-9): a chart's scene graph, read by tests (the hidden grid layer). */
  graph(id: ChartId): scene.SceneGraph | undefined;
  /** Internal (E12-S07): the series-kind metrics, per chart. */
  seriesMetrics(id: ChartId): Readonly<SeriesMetrics> | undefined;
  /** Internal (E11-S09, BQ-14): each pane's x words as last submitted; `FrameStats` stays frozen. */
  paneStats(id: ChartId): PaneStat[] | undefined;
  /** Internal (E11-S09 PR 2a, BQ-13/BQ-14): the sync and pane counters; `FrameStats` stays frozen. */
  syncCounters(id: ChartId): SyncCounters | undefined;
}

/** One pane's shared-time evidence (BQ-14): its key, the chart's range and its block's x words. */
/** BQ-14: the AC's instrumentation, by metric name (internal; read by tests and the bench). */
export interface SyncCounters {
  /** `engine.sync.propagations_per_frame`: the chart's group in the last frame, and the most. */
  readonly propagationsPerFrame: number;
  readonly propagationsPerFrameMax: number;
  /** `engine.sync.group_members`: the chart's group size (0 out of every group). */
  readonly groupMembers: number;
  /** `engine.sync.echoes`, runtime-wide: a publication handed back to its own chart; must be 0. */
  readonly echoes: number;
  /** Peer publications this chart applied. */
  readonly applied: number;
  /** The peer crosshair it draws (µs; null: none) and its own, as the last frame resolved. */
  readonly remoteCrosshair: number | null;
  readonly crosshair: number | null;
  /** `engine.panes.collapsed`: the chart's collapsed panes. */
  readonly panesCollapsed: number;
}

export interface PaneStat {
  readonly key: number;
  readonly timeStart: number;
  readonly timeEnd: number;
  /** `u_indexBase`, bar spacing (device px) and the index fraction, from the pane's block. */
  readonly xWords: readonly [number, number, number];
}

/** Upper bounds of `series_type_switch_duration_ms`' buckets (the 100 ms budget is one); the last is open. */
export const SWITCH_BUCKETS_MS = [5, 10, 25, 50, 100, 250, Infinity] as const;

/** E12-S07's two series-kind metrics (internal, read by tests and the bench; not on §8's FrameStats). */
export interface SeriesMetrics {
  /** `series_type_switch_duration_ms{target}`: counts per `SWITCH_BUCKETS_MS` bucket. */
  readonly switchDurationMs: Record<string, Uint32Array>;
  /** `series_incompatible_combination_total{combination}`. */
  readonly incompatible: Record<string, number>;
  /** The switch awaiting its frame: its target and start (an injected clock), else null. */
  pending: string | null;
  pendingAt: number;
}

/** One runtime-owned series (E12-S06): its store is the CPU truth, the ring its GPU mirror. */
export interface SeriesEntry {
  /** The kind drawn now (E12-S07: `setSeriesKind` changes it). */
  kind: BarSeriesKind;
  readonly pane: number;
  readonly store: BarStore;
  readonly ring: CandleRing;
  /** The plugin drawing it: a `CandleSeries` for candles and hollow, a `BarSeries` for OHLC bars. */
  readonly candle: CandleSeries;
  /** A bar pick's `objectId` (`series.<id>`), made once. */
  readonly pickId: string;
}

/** `engine.resize.*` (BQ-153): backing-store reallocations and DPR changes, per chart. */
export interface ResizeCounters {
  reallocations: number;
  dprChanges: number;
  lastDpr: number;
}

/** Frame stats are posted at most once per this interval outside bench mode (§6: 1 Hz). */
export const FRAME_SAMPLE_MS = 1000;

interface Instance {
  readonly id: ChartId;
  canvas: CanvasLike;
  theme: ThemeLut;
  readonly config: ChartConfig;
  /** The shared transform (E11-S03): pan, zoom and `setViewport` all go through it. */
  readonly viewport: ChartViewport;
  /** Autoscale, the log guard and the anchor, once per frame before the uniforms (E11-S05). */
  readonly autoscale: AutoScaler;
  /** The axes (E11-S06): ticks, decimation, the grid node and the labels the mirror lists. */
  readonly axes: AxisModel;
  /** The retained labels or the stops' names changed: post `axes` with the next frame. */
  axesDirty: boolean;
  /** Pane 0's GPU block, rewritten once per frame before submission. */
  readonly uniforms: PaneUniforms;
  /** E11-S09 (BQ-10): every pane's block, by layout slot ([0] is `uniforms`: content is pane 0's
   * until E12 mounts series per pane); and the layout count last posted (BQ-4). */
  readonly paneBlocks: PaneUniforms[];
  layoutPosted: number;
  /** M1: the layout compute `placePanes` and blocks 1.. last followed (-1: a transform moved). */
  placedAt: number;
  blocksAt: number;
  /** E11-S09 PR 1b: a splitter key's `seq`, echoed once as the next `layout`'s `ack`; -1 none. */
  ack: number;
  ready: boolean;
  /** The scheduler's requested frame, run by the shared callback; null while parked. */
  readonly slot: { frame: scene.FrameCallback | null };
  readonly graph: scene.SceneGraph;
  readonly layout: scene.LayoutEngine;
  readonly scheduler: scene.FrameScheduler;
  readonly builder: scene.BatchBuilder;
  /** The backend: undefined until the first frame opens it (WebGL2 or Canvas 2D, BQ-85). */
  readonly gpu: { backend: RenderBackend | undefined; readonly forced: boolean };
  /** True while the context is lost: frames stay requested but do not run (BQ-49). */
  parked: boolean;
  /** True while the container is 0×0 or hidden (BQ-147): like `parked`, nothing is allocated. */
  suspended: boolean;
  /** The DPR the backing store is sized at, its listeners (BQ-152) and counters (BQ-153). */
  dpr: number;
  /**
   * The exact size drawn (device px, BQ-149): the top-left sub-rect of a padded backing store.
   * The clip space, picking and the transform use it, never the padding.
   */
  readonly exact: { width: number; height: number };
  readonly dprListeners: Set<(from: number, to: number) => void>;
  readonly resizes: ResizeCounters;
  loss: ContextLoss | null;
  /** Removes the context-loss listeners. */
  detach: (() => void) | null;
  viewportDirty: boolean;
  summary: string;
  a11yDirty: boolean;
  lod: LodLevels;
  lastFrameAt: number;
  /** Pointer, wheel, touch and key routing plus the glide (E11-S04). */
  readonly gestures: Gestures;
  /** One pane's object and structural indices (E11-S08) and their reused result slots. */
  readonly objects: ObjectIndex;
  readonly structural: StructuralIndex;
  readonly hit: PickHit;
  readonly where: StructuralHit;
  /** The last hover pick posted, (objectId, part, handle): edge-triggered (BQ-134). */
  readonly hover: { id: string | null; part: PickHit["part"]; handle: number };
  readonly elements: Record<StoreId, number>;
  /** `init.fonts`, checked on their own (a bad option never rejects the init, BQ-258). */
  readonly fonts: readonly ChartFont[] | "invalid" | undefined;
  /** E12-S06: the `addSeries` ids, their stores and rings; the main series' id, else -1. */
  readonly series: Map<number, SeriesEntry>;
  /** The same entries as an array, in insertion order: the pick path iterates it (no iterator). */
  readonly seriesList: SeriesEntry[];
  main: number;
  /** `engine.data.rejected{reason}`: a model `RejectReason`, or `decode` (F-01, the wire). */
  readonly dataRejected: Record<string, number>;
  /** E12-S06: the mounted candle series (an array: the frame loop iterates it, no iterator). */
  readonly candles: CandleSeries[];
  /** Node id → its batch block, read by the backend per batch (`setBatchUniforms`). */
  readonly blocks: Map<string, BatchUniforms>;
  /** The theme as plugins read it, rebuilt on `setTheme` only. */
  hostTheme: HostTheme;
  /** Mount generations: node ids stay unique across a remove and a re-add (no node removal). */
  mounts: number;
  /** BQ-9: the last `dataState` posted (null before the first frame), and the bar pick's slot. */
  dataState: "empty" | "ready" | null;
  readonly barHit: BarHit;
  readonly kinds: SeriesMetrics;
  /** E11-S09 PR 2a (BQ-13): a gesture or command moved the time range since the last publish. */
  localMoved: boolean;
  /** The local crosshair (µs; null: none) and whether it moved since the last publish. */
  crosshair: number | null;
  crosshairMoved: boolean;
  /** A peer's crosshair, applied by sync only (never the summary, `a11y` or readout). */
  remoteCrosshair: number | null;
  /** BQ-9/BQ-17: the group, its modes, the relay switch and this chart's publication counter. */
  group: SyncGroup<Instance> | undefined;
  modes: SyncModes;
  relay: boolean;
  syncSeq: number;
  applied: number;
  /** The origin of the sync applied since the last render, for the `viewport` rows (BQ-26). */
  readonly syncFrom: { worker: string; chart: ChartId; seq: number };
  syncFromPending: boolean;
  /** A peer's sync landed since this chart's last prepare: the tick prepares it again. */
  synced: boolean;
  readonly applySync: (p: SyncPublication) => void;
}

/** The ObjectIndex's rebuild after the main series is removed (a `replace` of nothing). */
const CLEARED: MutationRange = new RangeSlot().set("replace", 0, 0, 0);

/** The plugin-facing theme (§8 `ThemeTokens`' shape) over the token LUT the worker holds. */
const hostTheme = (colors: ThemeLut): HostTheme => ({
  palette: "default",
  convention: "standard",
  colors,
});

const summarise = (timeUs: number): string => {
  const d = new Date(Math.floor(timeUs / 1000));
  return Number.isFinite(d.getTime()) ? d.toISOString() : "";
};

/** A notice's details for `ChartEvents.error`'s `message` (BQ-S3: §8 has no details field). */
const describe = (n: scene.FrameNotice): string => {
  const ms = scene.FRAME_STAGES.map((s, i) => `${s}=${n.timings[i]?.toFixed(2)}`).join(" ");
  const lod = n.from === n.to ? "" : `LOD ${n.from} -> ${n.to}; `;
  const head = `${lod}frame ${n.totalMs.toFixed(2)} ms, worst stage ${n.stage}`;
  return `${head}; ms: ${ms} layout=${n.layoutMs.toFixed(2)}`;
};

export function createRenderRuntime(deps: RuntimeDeps): RenderRuntime {
  const charts = new Map<ChartId, Instance>();
  const gridRange = new RangeSlot();
  let scheduled = false;
  let report: CapabilityReport | null = null;
  /** One CPU atlas per runtime, uploaded into each chart's context (BQ-277). */
  let atlas: AtlasService | null = null;

  const fail = (id: ChartId | null, message: string): void => {
    deps.post({ t: "error", id, code: ENGINE_DECODE_ERROR, message, recoverable: true });
  };

  const touch = (inst: Instance): void => {
    inst.scheduler.wake();
  };

  // ---- E11-S09 PR 2a: sync groups (26 §3.5, BQ-7, BQ-12, BQ-13) -------------------------------
  const groups = new SyncGroups<Instance>();
  /** `init.config.workerId`, host-assigned (BQ-7); "" until one is given. */
  let workerId = "";
  let echoes = 0;
  /** The charts prepared this tick (reused: no per-frame allocation) and the inbound slot. */
  const prepared: Instance[] = [];
  const inbound = new SyncPublication();

  /** Moves `inst` into `id` (null: none); a cap is a recoverable `ENGINE_SYNC_REFUSED`. */
  function joinGroup(inst: Instance, id: string | null): boolean {
    try {
      inst.group = groups.join(inst, id);
      return true;
    } catch (e) {
      if (!(e instanceof SyncRefused)) throw e;
      deps.post({
        t: "error",
        id: inst.id,
        code: ENGINE_SYNC_REFUSED,
        message: e.message,
        recoverable: true,
      });
      return false;
    }
  }

  /** A peer's publication: never sets `localMoved` or the local crosshair (echo-free, BQ-13). */
  function applySync(inst: Instance, p: SyncPublication): void {
    if (p.chart === inst.id && p.worker === workerId) {
      echoes += 1; // by construction unreachable: flush skips the publisher, dispatch drops ours
      return;
    }
    inst.applied += 1;
    if (p.hasTime && inst.modes.time) {
      inst.gestures.stop();
      moved(inst, inst.viewport.setTimeRange(p.timeStart, p.timeEnd));
    }
    if (p.hasCrosshair && inst.modes.crosshair && p.crosshair !== inst.remoteCrosshair) {
      inst.remoteCrosshair = p.crosshair;
      touch(inst);
    }
    inst.syncFrom.worker = p.worker;
    inst.syncFrom.chart = p.chart;
    inst.syncFrom.seq = p.seq;
    inst.syncFromPending = true;
    inst.synced = true;
  }

  /** 26 §3.5 step 3: stage the chart's local moves for its group, once per frame. */
  function publish(inst: Instance): void {
    const time = inst.localMoved;
    const cross = inst.crosshairMoved;
    if (!time && !cross) return;
    inst.localMoved = false;
    inst.crosshairMoved = false;
    const g = inst.group;
    const vp = inst.viewport;
    if (
      g === undefined ||
      !g.publish(inst, time, vp.timeStart, vp.timeEnd, cross, inst.crosshair)
    ) {
      return;
    }
    inst.syncSeq += 1;
    g.pub.worker = workerId;
    g.pub.seq = inst.syncSeq;
    if (inst.relay) relay(inst, g);
  }

  /** BQ-8: the publication for the main-thread relay (2b), one per chart per frame at most. */
  function relay(inst: Instance, g: SyncGroup<Instance>): void {
    const p = g.pub;
    deps.post({
      t: "sync",
      id: inst.id,
      groupId: g.id,
      ...(p.hasTime && { timeRange: [p.timeStart, p.timeEnd] as const }),
      ...(p.hasCrosshair && { crosshair: p.crosshair }),
      origin: { worker: p.worker, chart: p.chart, seq: p.seq },
    });
  }

  /** BQ-7: a sync from another worker (or the legacy host), applied to every local member. */
  function receive(msg: Extract<ToWorker, { t: "sync" }>): void {
    const g = groups.get(msg.groupId);
    if (g === undefined) return;
    const o: SyncOrigin | undefined = msg.origin;
    if (o !== undefined) {
      if (workerId !== "" && o.worker === workerId) return; // our own broadcast, relayed back
      if (!g.accept(o.worker, o.chart, o.seq)) return; // stale
    }
    const p = inbound;
    p.hasTime = msg.timeRange !== undefined;
    p.timeStart = msg.timeRange?.[0] ?? 0;
    p.timeEnd = msg.timeRange?.[1] ?? 0;
    p.hasCrosshair = msg.crosshair !== undefined;
    p.crosshair = msg.crosshair ?? null;
    p.worker = o?.worker ?? "";
    p.chart = o?.chart ?? -1;
    p.seq = o?.seq ?? 0;
    g.deliver(-1, p);
  }

  /** One chart's scene: slot 0 is the `main` pane (key 0); E11-S09's commands stack more. */
  function createScene(
    slot: Instance["slot"],
    gpu: Instance["gpu"],
    canvas: () => CanvasLike,
    render: () => void,
    opened: (o: OpenedBackend) => void,
    viewport: ChartViewport,
    dataState: () => void,
    axes: AxisModel,
    prepare: () => void,
  ) {
    const graph = new scene.SceneGraph();
    graph.addPane("main");
    graph.addNode("main", "background", axes.grid);
    const layout = new scene.LayoutEngine(graph);
    layout.addPane("main", undefined, 0);
    const builder = new scene.BatchBuilder(graph, {
      uploadSubRange: (b, from, to) => gpu.backend?.uploadSubRange(b, from, to),
    });
    const clock = { now: () => deps.now(), requestFrame, cancel: () => (slot.frame = null) };
    function requestFrame(cb: scene.FrameCallback): number {
      slot.frame = cb;
      if (!scheduled) deps.requestFrame(tick);
      scheduled = true;
      return 1;
    }
    const scheduler = new scene.FrameScheduler(graph, clock, {
      layout: () => {
        dataState(); // before collect and build: the background layer's visibility (BQ-9)
        layout.run();
        prepare(); // the axes see this frame's layout and view before collect (E11-S06)
      },
      build: (sink) => {
        open(); // before the first build, so its full uploads reach the GPU
        builder.build(sink);
      },
      submit: render,
      viewport,
    });
    function open(): void {
      if (gpu.backend !== undefined) return;
      const o = openBackend(canvas(), (report ??= deps.probe()), gpu.forced, deps.now);
      gpu.backend = o.backend;
      opened(o);
    }
    return { graph, layout, scheduler, builder };
  }

  /** Starts the runtime's atlas on the first WebGL2 chart that passes fonts (E11-S11 PR A). */
  function startAtlas(fonts: readonly ChartFont[]): void {
    if (atlas !== null) return;
    atlas = new AtlasService({
      platform: deps.text ?? null,
      now: () => deps.now(),
      setTimer: (cb, ms) => deps.setTimer(cb, ms),
      // A lost context takes the rows as its CPU copy and uploads them once restored (BQ-266).
      ready: (img) => charts.forEach((inst) => inst.gpu.backend?.uploadAtlas(img)),
      emit: (code, message, recoverable, details) =>
        deps.post({
          t: "error",
          id: null,
          code,
          message,
          recoverable,
          ...(details && { details }),
        }),
    });
    void atlas.start(fonts);
  }

  /** Re-requests a frame a park held back, or wakes the scheduler. */
  function kick(inst: Instance): void {
    if (inst.slot.frame === null) touch(inst);
    else if (!scheduled) {
      scheduled = true;
      deps.requestFrame(tick);
    }
  }

  /** The first frame chose the backend: say why it is not WebGL2, and watch a lossy one. */
  function opened(inst: Instance, { backend, degraded }: OpenedBackend): void {
    type Details = LossDetails | DegradeDetails | AtlasDetails;
    const post = (code: string, message: string, recoverable: boolean, d?: Details): void =>
      deps.post({ t: "error", id: inst.id, code, message, recoverable, ...(d && { details: d }) });
    backend.setPaneUniforms(() => inst.uniforms); // one pane until E11-S09 (BQ-45)
    // Only a WebGL2 chart samples the atlas: a 2D one never costs a build (E11-S11 PR A).
    if (!backend.drawsIn2d && backend.failure === null) {
      if (inst.fonts !== undefined && inst.fonts !== "invalid") startAtlas(inst.fonts);
      // A malformed option, or a chart that opens after the atlas failed: told with its own id
      // (skip and disclose, BQ-259); an earlier chart had the id-null broadcast.
      const failure =
        inst.fonts === "invalid"
          ? {
              message: "Chart fonts option malformed; chart text is not drawn",
              details: { atlasReason: "font-load" as const },
            }
          : atlas?.failure;
      if (failure) post(ENGINE_ATLAS_GENERATION_FAILED, failure.message, false, failure.details);
    }
    if (atlas?.image) backend.uploadAtlas(atlas.image);
    backend.setBatchUniforms((b) => inst.blocks.get(b.nodeId) ?? null); // E12-S06
    for (const c of inst.candles) attachCandle(backend, c);
    backend.attach(GRID_NODE_ID, inst.axes.grid); // the grid is its own instance ring
    if (degraded !== null) {
      const { reason, message, reducedCapabilities } = degraded;
      post(ENGINE_NO_WEBGL2, message, true, { reducedCapabilities, reason }); // BQ-90
    }
    const lossy = backend.loss;
    const c = inst.canvas;
    if (lossy === null || typeof c.addEventListener !== "function") return;
    const loss = new ContextLoss({
      backoffMs: RESTART_BACKOFF_MS,
      now: () => deps.now(),
      setTimer: (cb, ms) => deps.setTimer(cb, ms),
      park: () => {
        inst.parked = true;
        inst.gestures.stop(); // context loss ends a glide where it is (BQ-103)
        lossy.invalidate();
      },
      rebuild: () => lossy.restore(),
      resume: () => {
        inst.parked = false;
        inst.graph.markAllData(); // the GPU mirrors are rebuilt; the scene graph is untouched
        inst.axes.invalidate(); // the grid's ring re-uploads with the next frame (E11-S06)
        kick(inst);
      },
      giveUp: () => inst.scheduler.dispose(), // slot.frame === null for good; the host swaps
      emit: post,
    });
    const onLost = (ev: { preventDefault(): void }): void => loss.lost(ev);
    const onRestored = (): void => loss.restored();
    c.addEventListener("webglcontextlost", onLost);
    c.addEventListener("webglcontextrestored", onRestored);
    inst.loss = loss;
    inst.detach = () => {
      c.removeEventListener?.("webglcontextlost", onLost);
      c.removeEventListener?.("webglcontextrestored", onRestored);
    };
  }

  /** Stops a chart's loop and frees its GL objects and listeners. */
  function retire(inst: Instance): void {
    inst.scheduler.dispose();
    inst.loss?.cancel(); // a pending attempt's timer must not post for a retired chart
    inst.detach?.();
    inst.gpu.backend?.dispose();
  }

  /** After a viewport setter: TRANSFORM, never DATA, so buffers are reused (a uniform write). */
  function moved(inst: Instance, changed: boolean): void {
    if (!changed) return;
    inst.viewportDirty = true;
    inst.graph.markViewport();
    touch(inst);
  }

  function crosshairAt(inst: Instance, timeUs: number | null): void {
    if (timeUs !== inst.crosshair) {
      inst.crosshair = timeUs;
      inst.crosshairMoved = true;
      if (inst.group !== undefined) touch(inst); // published on the next frame (BQ-13)
    }
    const summary = timeUs === null ? "" : summarise(timeUs);
    if (summary === inst.summary) return;
    inst.summary = summary;
    inst.a11yDirty = true;
    touch(inst);
  }

  /**
   * The layout hook's second half, before collect (E11-S06): autoscale (once per frame per key
   * change, BQ-116), then the axes. A new gutter width lays the chart out again, narrows the plot
   * and refits on the new width before the axes rebuild; a rebuilt grid rewrites its ring.
   */
  function prepare(inst: Instance): void {
    placePanes(inst);
    if (inst.autoscale.update()) inst.viewportDirty = true;
    const { axes, layout, viewport: vp } = inst;
    let r = axes.update(vp, layout, inst.theme);
    if ((r & UPDATE.gutter) !== 0) {
      layout.setPriceGutter(axes.gutter.width);
      layout.run();
      placePanes(inst);
      // In this frame, before collect: TRANSFORM without a wake, so no second frame follows.
      if (vp.setSize(plotWidthOf(layout.width, layout.priceGutter), vp.height, vp.dpr)) {
        inst.viewportDirty = true;
        inst.graph.markViewport();
        // The narrower plot can change the visible bars, so refit now: else render's refit moves
        // the price range after the axes were built, and a static chart (no wake) keeps them stale.
        inst.autoscale.update();
      }
      r = axes.update(vp, layout, inst.theme);
    }
    if ((r & UPDATE.grid) !== 0) {
      inst.graph.markData(GRID_NODE_ID);
      inst.builder.patch(GRID_NODE_ID, gridRange.set("replace", 0, axes.grid.count, 0));
    }
    if ((r & UPDATE.labels) !== 0) inst.axesDirty = true;
  }

  /** BQ-11: each pane's price plot is its laid-out row; a changed row is a TRANSFORM (no wake). */
  function placePanes(inst: Instance): void {
    const { layout, viewport: vp } = inst;
    if (inst.placedAt === layout.computes) return; // the rows change only on a recompute
    inst.placedAt = layout.computes;
    for (let i = 0; i < layout.panes.length; i += 1) {
      const r = (layout.panes[i] as scene.PaneLayout).rect;
      const p = vp.panes[i];
      if (p === undefined || (p.plotTop === r[1] && p.plotHeight === r[3])) continue;
      vp.setPanePlot(i, r[1], r[3]);
      inst.graph.markViewport(); // the `viewport` message carries no plot rect: nothing to post
    }
  }

  /**
   * E11-S09 (BQ-2): a pane under the facade's key. A known key only takes `share`; a keyless sole
   * slot (every key was removed) is adopted; else a pane is appended below the others, up to
   * `MAX_PANES` (C-2.18). LAYOUT only: no ring is re-uploaded.
   */
  function addPane(inst: Instance, key: number, share: number | undefined): void {
    const { layout } = inst;
    const known = layout.byKey(key) ?? (layout.panes.length === 1 ? layout.byKey(-1) : undefined);
    if (known !== undefined) {
      known.key = key;
      inst.graph.markResize(); // the `layout` message names the key
      if (share !== undefined) layout.setHeightRatio(known.id, share);
    } else if (layout.panes.length >= MAX_PANES) {
      const message = `chart ${inst.id} already has ${MAX_PANES} panes`;
      return deps.post({
        t: "error",
        id: inst.id,
        code: ENGINE_PANE_CAP,
        message,
        recoverable: true,
      });
    } else appendPane(inst, key, share);
    touch(inst);
  }

  /** A pane node, a layout row, a transform and a block, below the others. */
  function appendPane(inst: Instance, key: number, share: number | undefined): void {
    const id = `pane.${key}`;
    inst.graph.addPane(id);
    inst.layout.addPane(id, share, key);
    inst.viewport.addPane();
    inst.paneBlocks.push(createPaneUniforms());
  }

  /**
   * BQ-11a: the sole pane is never removed, only left keyless. Slot 0 (`main`) holds the content
   * until E12 mounts series per pane, so removing its key while others remain hands it the next
   * pane's key, share, collapse and transform; that pane's node, row and block go.
   */
  function removePane(inst: Instance, key: number): boolean {
    const { layout } = inst;
    const p = layout.byKey(key);
    if (p === undefined) {
      fail(inst.id, `no pane ${key} on chart ${inst.id}`);
      return false;
    }
    inst.gestures.pane = 0; // the slots shift: a price gesture re-targets on the next pointer
    if (layout.panes.length === 1) {
      p.key = -1;
      inst.graph.markResize();
      touch(inst);
      return true;
    }
    let i = layout.panes.indexOf(p);
    let gone = p;
    if (i === 0) {
      gone = layout.panes[1] as scene.PaneLayout;
      layout.absorb(p.id, gone.id);
    } else layout.removePane(p.id);
    inst.graph.removePane(gone.id); // detached: the graph stays bounded under churn
    inst.viewport.removePane(i);
    if (i === 0) i = 1; // [0] stays `uniforms`; blocks 1.. are rewritten on the recompute
    inst.paneBlocks.splice(i, 1);
    touch(inst);
    return true;
  }

  /** BQ-3: the listed keys' shares; an unknown key refuses the whole command. */
  function setShares(inst: Instance, shares: readonly (readonly [number, number])[]): boolean {
    const ids: [string, number][] = [];
    for (const [key, share] of shares) {
      const p = inst.layout.byKey(key);
      if (p === undefined) {
        fail(inst.id, `no pane ${key} on chart ${inst.id}`);
        return false;
      }
      ids.push([p.id, share]);
    }
    inst.layout.setShares(ids);
    touch(inst);
    return true;
  }

  /** F-13 (BQ-92): no export while the pixels cannot be trusted; the reason, never a stale PNG. */
  function exportRefusal(inst: Instance): ExportRejectReason | null {
    const phase = inst.loss?.phase ?? "live";
    if (inst.gpu.backend?.failure || phase === "failed") return "backend-failed";
    // The driver's truth too: a context lost before its event is dispatched would encode blank.
    if (inst.gpu.backend?.loss?.isContextLost() === true) return "context-lost";
    if (phase !== "live" || inst.parked) return "context-lost"; // parked: mid-loss
    return inst.suspended ? "suspended" : null; // BQ-148: a hidden chart has no current pixels
  }

  /**
   * A `resize` (E11-S10): 0 on either axis suspends the chart with nothing allocated (BQ-147);
   * otherwise the backing store is set (counted only when it changes), and a DPR change marks
   * every pane LAYOUT and STYLE and tells the listeners before the next frame (BQ-152).
   */
  function resize(inst: Instance, msg: Extract<ToWorker, { t: "resize" }>): void {
    const { width: w, height: h, dpr } = msg;
    const ew = backingPx(w, dpr);
    const eh = backingPx(h, dpr);
    inst.gestures.stop();
    inst.suspended = ew === 0 || eh === 0;
    if (inst.suspended) return; // the requested frame is kept, as a parked chart's is
    inst.exact.width = ew;
    inst.exact.height = eh;
    // BQ-149: the host's padded store (validated >= exact), reallocated only when it changes.
    const bw = msg.backingWidth ?? ew;
    const bh = msg.backingHeight ?? eh;
    const c = inst.canvas;
    if (c.width !== bw || c.height !== bh) {
      // Only the axis that changed is written: a same-value write may still reset a real bitmap.
      if (c.width !== bw) c.width = bw;
      if (c.height !== bh) c.height = bh;
      inst.resizes.reallocations += 1;
    }
    moved(inst, inst.viewport.setSize(plotWidthOf(w, inst.layout.priceGutter), h, dpr));
    inst.layout.setSize(w, h); // LAYOUT: recomputed on the next frame only
    const from = inst.dpr;
    if (dpr !== from) {
      inst.dpr = dpr;
      inst.resizes.dprChanges += 1;
      inst.resizes.lastDpr = dpr;
      inst.graph.markResize();
      inst.graph.markTheme();
      // A throwing listener fails its own chart, recoverably, as a frame does; it never stops
      // the other listeners or the resize (E11-T02).
      for (const cb of inst.dprListeners) {
        try {
          cb(from, dpr);
        } catch (e) {
          fail(inst.id, e instanceof Error ? e.message : "dpr listener failed");
        }
      }
    }
    kick(inst); // resumes a suspended chart within one frame
  }

  function exportPng(inst: Instance, reqId: number): void {
    const c = inst.canvas;
    const reason = exportRefusal(inst);
    if (reason !== null) {
      deps.post({ t: "exported", id: inst.id, reqId, blob: null, reason });
      return;
    }
    // WebGL2 clears its drawing buffer after presentation: draw now, in the encoding task.
    if (inst.gpu.backend !== undefined) render(inst);
    const done = (blob: unknown): void => deps.post({ t: "exported", id: inst.id, reqId, blob });
    if (typeof c.convertToBlob === "function") {
      c.convertToBlob({ type: "image/png" }).then(done, () => done(null));
    } else if (typeof c.toBlob === "function") {
      c.toBlob(done, "image/png");
    } else done(null);
  }

  /** The structural answer, then the object index in the plot (one pane until E11-S09). */
  function locate(inst: Instance, x: number, y: number, pointer: PickPointer, obj = true): void {
    const { hit, where } = inst;
    inst.structural.pickStructural(x, y, where);
    hit.id = null;
    hit.kind = "none";
    hit.part = "body";
    hit.handle = -1;
    if (where.region !== "plot" || !obj) return;
    inst.objects.gesture = inst.gestures.active; // a drifted grid waits for the gesture (BQ-127)
    if (inst.objects.pick(x, y, pointer, hit)) return;
    pickBar(inst, x, y, toleranceFor(pointer));
  }

  /**
   * E12-S06: the bar under (x, y) on pane 0, after every object missed. The structural index gave
   * the bar (the slot under x); each series on the pane measures its drawn parts there through the
   * geometry twin, with the last frame's pane block: what is hit is what was drawn. The topmost
   * (last added) series wins a tie.
   */
  function pickBar(inst: Instance, x: number, y: number, tol: number): void {
    const { hit, where, barHit } = inst;
    if (where.pane !== 0) return;
    const u = inst.uniforms;
    const i0 = u.ints[0] ?? 0;
    const t0 = u.ints[1] ?? 0;
    let best = Infinity;
    const list = inst.seriesList;
    for (let i = 0; i < list.length; i += 1) {
      const s = list[i] as SeriesEntry;
      if (s.pane !== 0) continue;
      const c = s.candle;
      if (!c.hitTest(x, y, where.barIndex, u.floats, i0, t0, tol, barHit)) continue;
      if (barHit.distancePx > best) continue;
      best = barHit.distancePx;
      hit.id = s.pickId;
      hit.kind = "bar";
      hit.part = "body";
      hit.handle = -1;
      hit.distancePx = best;
    }
  }

  /** BQ-136: `bar` and `price` on every reply; a miss is `none`, or `axis` in a gutter. */
  function postPick(inst: Instance, reqId?: number): void {
    const { hit, where } = inst;
    const gutter = where.region === "price" || where.region === "time";
    deps.post({
      t: "pick",
      id: inst.id,
      objectId: hit.id,
      kind: hit.id !== null ? hit.kind : gutter ? "axis" : "none",
      bar: where.barIndex,
      price: where.priceLevel,
      ...(hit.id !== null && { part: hit.part }),
      ...(hit.handle >= 0 && { handle: hit.handle }),
      ...(reqId !== undefined && { reqId }),
    });
  }

  /**
   * BQ-134: one pick per `input` message, at its last move, none during a drag or glide; posted
   * only when (objectId, part, handle) changes, so leaving an object posts one `objectId: null`.
   */
  function hover(inst: Instance, touch: boolean, ev: Float32Array): void {
    let i = ev.length - INPUT_STRIDE;
    while (i >= 0 && ev[i] !== INPUT.move && ev[i] !== INPUT.leave) i -= INPUT_STRIDE;
    const { hit, hover: h } = inst;
    if (i >= 0 && ev[i] === INPUT.leave) {
      // G-29: the pointer left the canvas, so a hovered object posts its one `objectId: null`.
      if (h.id === null) return;
      locate(inst, ev[i + 1] as number, ev[i + 2] as number, "mouse", false);
    } else if (i < 0 || inst.gestures.active) return;
    else locate(inst, ev[i + 1] as number, ev[i + 2] as number, touch ? "touch" : "mouse");
    if (h.id === hit.id && h.part === hit.part && h.handle === hit.handle) return;
    h.id = hit.id;
    h.part = hit.part;
    h.handle = hit.handle;
    postPick(inst);
  }

  /** E12-S06: a store and ring for `sid`; the first series on pane 0 becomes the main one. */
  function addSeries(inst: Instance, sid: number, kind: BarSeriesKind, pane: number): void {
    if (inst.series.has(sid)) {
      fail(inst.id, `series ${sid} already exists on chart ${inst.id}`);
      return;
    }
    const store = new BarStore();
    const ring = new CandleRing(inst.builder);
    const candle = kind === "bars" ? new BarSeries(ring) : new CandleSeries(ring, kind);
    const entry: SeriesEntry = { kind, pane, store, ring, candle, pickId: `series.${sid}` };
    inst.series.set(sid, entry);
    inst.seriesList.push(entry);
    mountCandle(inst, sid, candle);
    themeCandle(inst, candle);
    if (pane === 0 && inst.main < 0) {
      inst.main = sid;
      inst.viewport.setMap(store); // G-8: the store is the runtime's IndexTimeMap
      moved(inst, true);
    }
  }

  /**
   * E12-S06: the candle's two hosts in this scene, under fresh ids, their blocks registered and
   * (once the backend exists) their VAOs over the ring's one shared buffer.
   */
  function mountCandle(inst: Instance, sid: number, c: CandleSeries): void {
    const deps: HostDeps = { viewport: inst.viewport, pane: 0, theme: () => inst.hostTheme };
    const base = `${c.mountLabel}.${sid}.${inst.mounts++}`;
    const hosts = c.mount(inst.graph, "main", base, deps);
    for (let p = 0; p < hosts.length; p += 1) {
      inst.blocks.set((hosts[p] as { id: string }).id, c.blocks[p] as BatchUniforms);
    }
    inst.candles.push(c);
    const backend = inst.gpu.backend;
    if (backend !== undefined) attachCandle(backend, c);
  }

  function attachCandle(backend: RenderBackend, c: CandleSeries): void {
    const hs = c.hosts;
    for (let p = 0; p < hs.length; p += 1) {
      backend.attach((hs[p] as { id: string }).id, c.sources[p] ?? c.ring, CANDLE_ATTRIBUTES);
    }
  }

  /**
   * BQ-9: `dataState` when the main series' visible range empties or fills (edge-triggered; the
   * first frame always posts). While empty the background layer (the grid) is hidden; the app
   * draws SCR-047 over the canvas. Runs once per frame, before collect.
   */
  function dataState(inst: Instance): void {
    const n = inst.series.get(inst.main)?.store.length ?? 0;
    const vp = inst.viewport;
    const first = Math.max(0, Math.floor(vp.leftIndex));
    const last = Math.min(n - 1, Math.floor(vp.leftIndex + vp.plotWidth / vp.barSpacing));
    const state = last >= first ? "ready" : "empty";
    if (state === inst.dataState) return;
    inst.dataState = state;
    inst.graph.setVisible(`main/${scene.LAYER_ORDER[0]}`, state === "ready");
    deps.post({ t: "dataState", id: inst.id, state });
  }

  /** BQ-4: a theme without a candle token is a recoverable error and no series drawn. */
  function themeCandle(inst: Instance, c: CandleSeries): void {
    const err = c.setTheme(inst.theme);
    if (err !== null) {
      deps.post({
        t: "error",
        id: inst.id,
        code: err.code,
        message: err.message,
        recoverable: true,
      });
    }
  }

  /**
   * E12-S07: series `sid` redrawn as `kind`, Heikin-Ashi on or off, over its own store (no data
   * resent, viewport and scale untouched). HA with a footprint, or over OHLC bars (D06 §3.3
   * defines it over candles), is refused: counted, posted as a recoverable
   * `ENGINE_SERIES_INCOMPATIBLE`, and nothing changes, so the series keeps drawing.
   */
  function setSeriesKind(inst: Instance, sid: number, kind: BarSeriesKind, ha: boolean): void {
    const s = inst.series.get(sid);
    if (s === undefined) {
      fail(inst.id, `no series ${sid} on chart ${inst.id}`);
      return;
    }
    const m = inst.kinds;
    if (ha && (inst.elements.footprint > 0 || kind === "bars")) {
      const other = kind === "bars" ? "bars" : "footprint";
      refuse(inst, `heikin-ashi+${other}`, `series ${sid}: Heikin-Ashi cannot draw with ${other}`);
      return;
    }
    m.pending = ha ? `${kind}+heikin-ashi` : kind;
    m.pendingAt = deps.now();
    s.candle.setKind(kind, ha, s.store);
    s.kind = kind;
    for (const h of s.candle.hosts) inst.graph.markData(h.id);
    touch(inst);
  }

  /** E12-S07: one refused combination: counted and posted; the caller changes nothing. */
  function refuse(inst: Instance, combination: string, why: string): void {
    const m = inst.kinds.incompatible;
    m[combination] = (m[combination] ?? 0) + 1;
    deps.post({
      t: "error",
      id: inst.id,
      code: ENGINE_SERIES_INCOMPATIBLE,
      message: `${why}; the previous combination keeps drawing`,
      recoverable: true,
    });
  }

  /** E12-S07: a series drawing Heikin-Ashi, else -1 (a footprint batch is refused against it). */
  function haSeries(inst: Instance): number {
    const list = inst.seriesList;
    for (let i = 0; i < list.length; i += 1) {
      const s = list[i] as SeriesEntry;
      if (s.candle.heikinAshi) return i;
    }
    return -1;
  }

  function removeSeries(inst: Instance, sid: number): void {
    const gone = inst.series.get(sid);
    if (!inst.series.delete(sid)) {
      fail(inst.id, `no series ${sid} on chart ${inst.id}`);
      return;
    }
    if (gone !== undefined) inst.seriesList.splice(inst.seriesList.indexOf(gone), 1);
    const c = gone?.candle ?? null;
    if (c !== null) {
      // No node removal yet (BQ-46): the hosts stay hidden, their batches unpatched and undrawn.
      for (const h of c.hosts) {
        h.visible = false;
        inst.blocks.delete(h.id);
      }
      c.ring.nodes.length = 0;
      c.seams.nodes.length = 0;
      inst.candles.splice(inst.candles.indexOf(c), 1);
      inst.graph.markTheme();
      touch(inst);
    }
    if (sid !== inst.main) return;
    inst.main = -1;
    inst.viewport.setMap(deps.timeMap ?? EMPTY_TIME_MAP);
    inst.objects.onMutation(CLEARED);
    moved(inst, true);
  }

  /** `patch` by time: the batch's first bar must be a bar the store holds (the live bar's fix). */
  function patchAt(store: BarStore, b: BarBatch): MutationRange {
    const k = b.time.length;
    const t = k > 0 ? (b.time[0] as number) : Number.NaN;
    const at = k > 0 ? store.timeToIndex(t) : store.length;
    if (k > 0 && (at < 0 || store.indexToTime(at) !== t)) {
      store.counters.reject("range", "patch names a bar time the series does not hold");
    }
    return store.patch(at, b);
  }

  /**
   * A `bars` batch for series `sid` (E12-S06): decoded and F-01-checked, applied to its store
   * (F-02, append-merge), mirrored into its ring; the main series rebases the ObjectIndex (G-23)
   * and sets the pane's price frame. A refusal counts `engine.data.rejected{reason}` and posts a
   * recoverable `ENGINE_DECODE_ERROR`; the store is left byte-identical.
   */
  function storeBars(
    inst: Instance,
    sid: number,
    op: DataOp,
    l: BufferLayout,
    buf: ArrayBuffer,
  ): void {
    try {
      const s = inst.series.get(sid);
      if (s === undefined) throw new DecodeError(`no series ${sid} on chart ${inst.id}`);
      const b = decodeBars(l, buf);
      const { store } = s;
      let r: MutationRange;
      if (op === "replace") r = store.replace(b);
      else if (op === "append") r = store.append(b, true);
      else if (op === "prepend") r = store.prepend(b);
      else r = patchAt(store, b);
      s.ring.sync(store, r);
      for (const h of s.candle.hosts) inst.graph.markData(h.id);
      if (sid !== inst.main) return;
      inst.objects.onMutation(r);
      inst.viewportDirty = true; // the map's length moved: the time range may have too
      moved(inst, inst.viewport.setPriceInfo(0, store.priceOrigin, store.tickSize));
    } catch (e) {
      if (!(e instanceof DecodeError) && !(e instanceof ModelRejection)) throw e;
      const reason = e instanceof ModelRejection ? e.reason : "decode";
      inst.dataRejected[reason] = (inst.dataRejected[reason] ?? 0) + 1;
      fail(inst.id, e.message);
    }
  }

  function command(inst: Instance, cmd: Command): void {
    switch (cmd.k) {
      case "setViewport": {
        inst.gestures.stop();
        const changed = inst.viewport.setTimeRange(cmd.timeStart, cmd.timeEnd);
        if (changed) inst.localMoved = true; // a command is local: it publishes (BQ-13)
        moved(inst, changed);
        return;
      }
      case "setSync": {
        const was = inst.group;
        if (!joinGroup(inst, cmd.groupId)) return;
        inst.modes = { ...cmd.modes, scale: false };
        inst.relay = cmd.relay;
        // A peer's crosshair leaves with its group and the crosshair mode (not yet drawn: S07).
        if (inst.group !== was || !cmd.modes.crosshair) inst.remoteCrosshair = null;
        return;
      }
      case "setTheme":
        inst.theme = cmd.theme;
        inst.hostTheme = hostTheme(cmd.theme);
        for (const c of inst.candles) themeCandle(inst, c); // STYLE: uniforms, never an upload
        inst.graph.markTheme();
        touch(inst);
        return;
      case "setLod":
        inst.lod = { candles: cmd.candles, footprint: cmd.footprint };
        inst.scheduler.lod = Math.min(cmd.candles, inst.scheduler.maxLod);
        touch(inst);
        return;
      case "setMotion":
        inst.gestures.setMotion(cmd.reduce); // the engine never reads the media query (BQ-104)
        return;
      case "setPriceScale": {
        // BQ-1: `pane` is the facade's key; its slot is the transform's index.
        const p = inst.layout.byKey(cmd.pane);
        const i = p === undefined ? -1 : inst.layout.panes.indexOf(p);
        moved(inst, inst.viewport.setScale(i, cmd)); // TRANSFORM only: no data refetch
        return;
      }
      case "addPane":
        addPane(inst, cmd.pane, cmd.share);
        return;
      case "removePane":
        // R58: the re-key is announced on the `layout` that acks the removal (an unknown key
        // removes nothing, so nothing acks it).
        if (removePane(inst, cmd.pane) && cmd.seq !== undefined) inst.ack = cmd.seq;
        return;
      case "setPaneShares":
        if (setShares(inst, cmd.shares) && cmd.seq !== undefined) {
          inst.ack = cmd.seq; // keyed: a `layout` follows even when nothing moved
          inst.graph.markResize();
        }
        return;
      case "moveSplitter": {
        const p = inst.layout.byKey(cmd.pane);
        if (p === undefined) return;
        inst.layout.moveBoundary(inst.layout.panes.indexOf(p), cmd.by, false);
        if (cmd.seq !== undefined) inst.ack = cmd.seq;
        inst.graph.markResize(); // a `layout` follows even at a limit: the key's announcement
        touch(inst);
        return;
      }
      case "setPaneCollapsed": {
        const p = inst.layout.byKey(cmd.pane);
        if (p === undefined) return fail(inst.id, `no pane ${cmd.pane} on chart ${inst.id}`);
        if (inst.layout.setCollapsed(p.id, cmd.collapsed)) touch(inst);
        else if (cmd.collapsed && !p.collapsed) fail(inst.id, `pane ${cmd.pane} is the last open`);
        return;
      }
      case "pickAt":
        // BQ-135: an explicit pick always replies and leaves the hover edge state alone.
        locate(inst, cmd.x, cmd.y, cmd.pointer ?? "mouse");
        postPick(inst, cmd.reqId);
        return;
      case "export":
        exportPng(inst, cmd.reqId);
        return;
      case "addSeries":
        addSeries(inst, cmd.series, cmd.kind, cmd.pane ?? 0);
        return;
      case "removeSeries":
        removeSeries(inst, cmd.series);
        return;
      case "setSeriesOptions": {
        // BQ-12: `isTimeAligned` (default true) only switches the gap seam (and E11-S06's labels).
        const s = inst.series.get(cmd.series);
        const opts = cmd.options as { isTimeAligned?: unknown; heikinAshi?: unknown };
        const aligned = opts.isTimeAligned;
        if (s !== undefined && typeof aligned === "boolean") s.candle.timeAligned = aligned;
        // E12-S07 (BQ-5): `CandleOptions.heikinAshi` is the same switch as `setSeriesKind`.
        const ha = opts.heikinAshi;
        if (s !== undefined && typeof ha === "boolean" && ha !== s.candle.heikinAshi) {
          setSeriesKind(inst, cmd.series, s.kind, ha);
        }
        touch(inst);
        return;
      }
      case "setSeriesKind":
        setSeriesKind(inst, cmd.series, cmd.kind, cmd.heikinAshi === true);
        return;
      case "release":
        retire(inst);
        groups.leave(inst);
        charts.delete(inst.id);
        if (charts.size === 0) {
          atlas?.dispose(); // the faces leave the font set; a build in flight stops
          atlas = null;
        }
        return;
      default:
        // addDrawing: the scene graph that consumes it is E14's.
        touch(inst);
    }
  }

  function dispatch(msg: ToWorker): void {
    if (msg.t === "sync") {
      receive(msg);
      return;
    }
    if (msg.t === "init") {
      // A second init for a known chart is the degraded-2d handoff (BQ-53): a fresh canvas and
      // scene, the DataModel kept.
      const old = charts.get(msg.id);
      if (old !== undefined) retire(old);
      const slot: Instance["slot"] = { frame: null };
      // `profile` validates as the one forced value (BQ-53; the BQ-94 test hook rides it too).
      const gpu: Instance["gpu"] = { backend: undefined, forced: msg.profile !== undefined };
      const c = msg.canvas as CanvasLike;
      const viewport = new ChartViewport(deps.timeMap);
      const axes = new AxisModel(msg.config.timeZone);
      const uniforms = createPaneUniforms();
      const [w, h] = [c.width / msg.dpr, c.height / msg.dpr];
      viewport.setSize(plotWidthOf(w), h, msg.dpr); // the plot rect, not the canvas (RULED (5))
      const scene = createScene(
        slot,
        gpu,
        () => inst.canvas,
        () => render(inst),
        (backend) => opened(inst, backend),
        viewport,
        () => dataState(inst),
        axes,
        () => prepare(inst),
      );
      scene.layout.setSize(w, h);
      const inst: Instance = {
        ...scene,
        slot,
        gpu,
        id: msg.id,
        canvas: c,
        theme: msg.theme,
        config: msg.config,
        viewport,
        axes,
        axesDirty: false,
        uniforms,
        paneBlocks: [uniforms],
        layoutPosted: -1,
        placedAt: -1,
        blocksAt: -1,
        ack: -1,
        autoscale: new AutoScaler(viewport, (pane) =>
          pane === 0 ? (deps.priceSources ?? NO_SOURCES) : NO_SOURCES,
        ),
        ready: false,
        viewportDirty: false,
        summary: "",
        a11yDirty: false,
        lod: { candles: 0, footprint: 0 },
        lastFrameAt: Number.NEGATIVE_INFINITY,
        gestures: new Gestures(viewport, scene.layout, {
          moved(changed): void {
            if (changed) inst.localMoved = true; // a gesture is local: it publishes (BQ-13)
            moved(inst, changed);
          },
          hover: (x) => crosshairAt(inst, screenToTime(viewport, x)),
          animate: (m) => inst.scheduler.animate(m),
          say: (code) => (inst.axes.say = code),
          split(row, dy): void {
            // A drag folds a pane pushed under the minimum (D02 §8); LAYOUT only, no upload.
            const l = scene.layout;
            let avail = 0; // the open rows' px: share units of this drag (no allocation per row)
            for (const p of l.panes) avail += p.collapsed ? 0 : p.rect[3];
            if (avail > 0 && l.moveBoundary(row, dy / avail, true)) touch(inst);
          },
        }),
        // G-28: the degraded-2d re-init keeps the registrations, re-placed under the new view.
        objects: old ? old.objects.rebind(viewport) : new ObjectIndex(viewport, 0, "main"),
        structural: old
          ? old.structural.rebind(viewport, scene.layout)
          : new StructuralIndex(viewport, scene.layout),
        hit: createPickHit(),
        where: createStructuralHit(),
        hover: { id: null, part: "body", handle: -1 },
        parked: false,
        suspended: false,
        dpr: msg.dpr,
        exact: { width: c.width, height: c.height },
        dprListeners: old?.dprListeners ?? new Set(),
        resizes: old?.resizes ?? { reallocations: 0, dprChanges: 0, lastDpr: msg.dpr },
        loss: null,
        detach: null,
        elements: old ? { ...old.elements } : { bars: 0, footprint: 0, heatmap: 0, profile: 0 },
        fonts: msg.fonts === undefined ? undefined : fontsOk(msg.fonts) ? msg.fonts : "invalid",
        series: old?.series ?? new Map(),
        seriesList: old?.seriesList ?? [],
        main: old?.main ?? -1,
        dataRejected: old?.dataRejected ?? {},
        candles: [],
        blocks: new Map(),
        hostTheme: hostTheme(msg.theme),
        mounts: old?.mounts ?? 0,
        dataState: null,
        barHit: createBarHit(),
        kinds: old?.kinds ?? {
          switchDurationMs: {},
          incompatible: {},
          pending: null,
          pendingAt: 0,
        },
        localMoved: false,
        crosshair: null,
        crosshairMoved: false,
        remoteCrosshair: null,
        group: undefined,
        modes: old?.modes ?? DEFAULT_SYNC_MODES,
        relay: old?.relay ?? false,
        syncSeq: old?.syncSeq ?? 0,
        applied: old?.applied ?? 0,
        syncFrom: { worker: "", chart: -1, seq: 0 },
        syncFromPending: false,
        synced: false,
        applySync: (p) => applySync(inst, p),
      };
      // BQ-7/BQ-9: the host's worker id; the degraded-2d handoff keeps a `setSync` group.
      if (msg.config.workerId !== undefined) workerId = msg.config.workerId;
      // The handoff's join cannot be refused: `old` leaving frees the very slot `inst` takes.
      const keep = old === undefined ? (msg.config.syncGroup ?? null) : (old.group?.id ?? null);
      if (old !== undefined) groups.leave(old);
      joinGroup(inst, keep);
      // BQ-53: the DataModel is kept; its rings now patch the fresh scene's batches.
      for (const [sid, s] of inst.series) {
        s.ring.sink = inst.builder;
        mountCandle(inst, sid, s.candle); // the fresh scene's hosts; the backend attaches them
        themeCandle(inst, s.candle);
      }
      const main = inst.series.get(inst.main);
      if (main !== undefined) viewport.setMap(main.store);
      // BQ-10: the degraded-2d handoff keeps the panes, their keys, shares, collapse and scales.
      if (old !== undefined) {
        const rows = old.layout.panes;
        for (let i = 1; i < rows.length; i += 1) {
          appendPane(inst, (rows[i] as scene.PaneLayout).key, undefined);
        }
        inst.layout.copyFrom(rows);
        old.viewport.panes.forEach((t, i) => Object.assign(viewport.panes[i] ?? {}, t));
      }
      inst.gestures.reduce = msg.reducedMotion === true;
      // 06 §4.3's marks run in bench mode only; a production chart's scheduler keeps `null`.
      if (msg.config.bench && deps.timeline !== undefined) {
        inst.scheduler.marks = performanceStageMarker(deps.timeline);
      }
      charts.set(msg.id, inst);
      touch(inst);
      return;
    }
    const inst = charts.get(msg.id);
    if (inst === undefined) {
      fail(msg.id, `no chart ${msg.id} on this worker`);
      return;
    }
    switch (msg.t) {
      case "resize":
        resize(inst, msg);
        return;
      case "input":
        inst.gestures.apply(msg.kind === "touch", msg.events);
        if (msg.kind === "pointer" || msg.kind === "touch") {
          hover(inst, msg.kind === "touch", msg.events);
        }
        return;
      case "data": {
        if (msg.series !== undefined) {
          storeBars(inst, msg.series, msg.op, msg.layout, msg.buffer);
          deps.post({ t: "ack", id: inst.id, store: msg.store, series: msg.series });
          touch(inst);
          return;
        }
        // E12-S07: footprint data against a Heikin-Ashi series is refused (counted, acked); the
        // series keeps drawing and the footprint count does not move.
        if (msg.store === "footprint" && haSeries(inst) >= 0) {
          refuse(inst, "heikin-ashi+footprint", "a footprint batch cannot draw with Heikin-Ashi");
          deps.post({ t: "ack", id: inst.id, store: msg.store });
          return;
        }
        // Without a series id a batch only moves the element count (pre-E12-S06 callers).
        const n = msg.layout.count;
        if (msg.op === "replace") inst.elements[msg.store] = n;
        else if (msg.op !== "patch") inst.elements[msg.store] += n;
        // BQ-115: a bars batch's params are [priceOrigin, tickSize], the main series' (pane 0).
        const [origin, tick] = msg.layout.params;
        if (msg.store === "bars" && origin !== undefined && tick !== undefined) {
          moved(inst, inst.viewport.setPriceInfo(0, origin, tick));
        }
        deps.post({ t: "ack", id: inst.id, store: msg.store });
        touch(inst);
        return;
      }
      default:
        command(inst, msg.cmd);
    }
  }

  function render(inst: Instance): void {
    const start = deps.now();
    const capabilities = (report ??= deps.probe());
    const backend = inst.gpu.backend ?? null;
    // A 2D backend, or a failed compile, is degraded-2d whatever the probe said (BQ-50, BQ-85).
    const in2d = backend === null || backend.drawsIn2d || backend.failure !== null;
    let renderProfile = in2d ? "degraded-2d" : capabilities.profile;
    if (!inst.ready) {
      inst.ready = true;
      deps.post({ t: "ready", id: inst.id, runMode: deps.runMode, renderProfile, capabilities });
    }
    const { width, height } = inst.exact;
    const backing = inst.canvas;
    // At most one refit per pane per frame, and only when a key changed (BQ-116).
    if (inst.autoscale.update()) inst.viewportDirty = true;
    if (backend !== null && backend.failure === null) {
      // The clip space spans the exact store on both axes (BQ-101, BQ-142, BQ-149); the plot is
      // its left part, so x maps unchanged, and y never mixes vp.height * dpr with the rounded
      // size. A padded store is drawn in its exact top-left sub-rect.
      // Block 0 (drawn) every frame (§3.5); blocks 1.. only on a moved transform or relayout (M1).
      const blocks = inst.paneBlocks;
      if (inst.viewportDirty) inst.blocksAt = -1;
      const n = inst.blocksAt === inst.layout.computes ? 1 : blocks.length;
      inst.blocksAt = inst.layout.computes;
      for (let i = 0; i < n; i += 1) {
        const b = blocks[i] as PaneUniforms;
        writePaneUniforms(inst.viewport, i, b);
        b.floats[4] = width;
        b.floats[5] = height;
      }
      backend.setBackground(inst.theme[BACKGROUND_TOKEN]);
      const cs = inst.candles;
      const vp = inst.viewport;
      const first = Math.floor(vp.leftIndex);
      const last = Math.floor(vp.leftIndex + vp.plotWidth / vp.barSpacing);
      const plot = vp.panes[0] ?? { plotTop: 0, plotHeight: 0 };
      for (let c = 0; c < cs.length; c += 1) {
        // u_geom, u_batch; the seam spans the plot rect: top to top + height, CSS px
        (cs[c] as CandleSeries).frame(
          vp.barSpacing,
          inst.dpr,
          first,
          last,
          plot.plotTop,
          plot.plotTop + plot.plotHeight,
        );
      }
      const { drawList, drawCount } = inst.builder;
      const f = backend.submit(drawList, drawCount, width, height, backing.width, backing.height);
      // The R1 budget closes on the first complete frame after a restore (BQ-49).
      if (
        f === null &&
        inst.loss?.phase === "restoring" &&
        backend.loss?.isContextLost() === false
      ) {
        inst.loss.framed();
      }
      if (f !== null) {
        renderProfile = "degraded-2d";
        deps.post({ t: "error", id: inst.id, code: f.code, message: f.message, recoverable: true });
      }
    }
    if (inst.viewportDirty) {
      inst.viewportDirty = false;
      postViewport(inst);
    }
    inst.syncFromPending = false; // BQ-26: the origin rides this frame's message only
    if (inst.layoutPosted !== inst.layout.computes) {
      inst.layoutPosted = inst.layout.computes;
      const l = inst.layout;
      const msg: { -readonly [K in keyof LayoutMsg]: LayoutMsg[K] } = {
        t: "layout",
        id: inst.id,
        panes: l.panes.map((p) => ({
          pane: p.key,
          top: p.rect[1],
          height: p.rect[3],
          share: p.share,
          collapsed: p.collapsed,
        })),
        timeAxis: [l.timeAxis[1], l.timeAxis[3]],
        plotWidth: l.timeAxis[2],
      };
      if (inst.ack >= 0) msg.ack = inst.ack; // set in place: no spread object per layout
      deps.post(msg);
      inst.ack = -1;
    }
    if (inst.axesDirty || inst.axes.say !== SAY.none) {
      inst.axesDirty = false;
      const ax = inst.axes;
      const say = ax.takeSay(inst.viewport);
      deps.post({
        t: "axes",
        id: inst.id,
        price: [...ax.priceLabels],
        time: [...ax.timeLabels],
        priceName: ax.priceName,
        timeName: ax.timeName,
        priceGutter: inst.layout.priceGutter,
        timeZone: ax.timeZone,
        ...(say !== null && { say }),
      });
    }
    if (inst.a11yDirty) {
      inst.a11yDirty = false;
      deps.post({ t: "a11y", id: inst.id, cursorSummary: inst.summary });
    }
    const end = deps.now();
    const kinds = inst.kinds;
    if (kinds.pending !== null) {
      // `series_type_switch_duration_ms{target}`: the switch to the end of its first frame.
      const ms = end - kinds.pendingAt;
      const counts = (kinds.switchDurationMs[kinds.pending] ??= new Uint32Array(
        SWITCH_BUCKETS_MS.length,
      ));
      let b = 0;
      while (ms > (SWITCH_BUCKETS_MS[b] as number)) b += 1;
      counts[b] = (counts[b] as number) + 1;
      kinds.pending = null;
    }
    if (inst.config.bench || end - inst.lastFrameAt >= FRAME_SAMPLE_MS) {
      inst.lastFrameAt = end;
      deps.post({
        t: "frame",
        id: inst.id,
        runMode: deps.runMode,
        renderProfile,
        frameTimeMs: end - start,
        drawCalls: backend?.trace.draws ?? 0,
        triangles: backend?.trace.triangles ?? 0,
        uploadedBytes: backend?.takeUploadedBytes() ?? 0,
        gpuMemoryMbEstimate: backend?.gpuMemoryMbEstimate ?? 0,
        lod: inst.lod,
        dpr: inst.dpr,
        backingStorePx: [backing.width, backing.height],
      });
    }
  }

  /** BQ-5 (M1): ONE `viewport` a frame; time is the chart's, slot 0's row on top, then 1.. */
  function postViewport(inst: Instance): void {
    const { viewport: vp, layout } = inst;
    const n = layout.panes.length;
    const panes = n > 1 ? Array.from({ length: n - 1 }, (_, i) => scaleRow(inst, i + 1)) : null;
    deps.post({
      t: "viewport",
      id: inst.id,
      timeStart: vp.timeStart,
      timeEnd: vp.timeEnd,
      barSpacing: vp.barSpacing,
      ...scaleRow(inst, 0),
      ...(panes !== null && { panes }),
      frameId: inst.scheduler.frames, // BQ-26: one message, so one `viewportChanged`, a frame
      // A copy: an inline bus hands the message over by reference, and `syncFrom` is reused.
      ...(inst.syncFromPending && { origin: { ...inst.syncFrom } }),
    });
  }

  function scaleRow(inst: Instance, i: number): PaneScaleRow {
    const pane = inst.viewport.panes[i];
    return {
      priceLow: pane?.priceLow ?? 0,
      priceHigh: pane?.priceHigh ?? 0,
      pane: inst.layout.panes[i]?.key ?? 0,
      mode: pane?.scaleMode ?? "linear",
      requestedMode: pane?.requestedMode ?? "linear",
      inverted: pane?.inverted ?? false,
      autoScale: pane?.autoScale ?? true,
      logAvailable: pane?.logReason === null,
      logReason: pane?.logReason ?? null,
      anchorTick: Number.isFinite(pane?.anchorTick) ? (pane?.anchorTick ?? null) : null,
    };
  }

  /** A frame is requested and may run (a parked or suspended chart keeps its request). */
  const due = (inst: Instance): boolean =>
    inst.slot.frame !== null && !inst.parked && !inst.suspended;

  /** The frame's first half (BQ-12); false when it threw, which fails only this chart. */
  function prepareChart(inst: Instance): boolean {
    inst.slot.frame = null;
    inst.synced = false;
    // A throwing canvas or context fails its own chart's frame, recoverably; it never escapes
    // the frame callback, where a worker would turn it into an uncaught error (E11-T02).
    try {
      inst.scheduler.prepare(deps.now());
      if (!prepared.includes(inst)) prepared.push(inst);
      return true;
    } catch (e) {
      fail(inst.id, e instanceof Error ? e.message : "render failed");
      notices(inst);
      return false;
    }
  }

  /**
   * One frame for every chart (BQ-12, 26 §3.5): prepare each chart with a frame pending and
   * publish its local moves → flush every group once → prepare the members that woke (again, if
   * pass 1 prepared one before a later peer published), with publication suppressed → finish (collect, build, submit) every chart. So a
   * peer's move lands on the same frame whichever chart was created first.
   */
  function tick(): void {
    scheduled = true; // a request made inside the tick is re-issued once, at its end
    prepared.length = 0;
    try {
      for (const inst of charts.values()) {
        if (due(inst) && prepareChart(inst)) publish(inst);
      }
      if (groups.flush() > 0) {
        // A woken member is due again, whether or not pass 1 prepared it: a chart prepared before
        // a later peer published laid out the old range, so it is prepared again (no publish).
        for (const inst of charts.values()) if (due(inst) && inst.synced) prepareChart(inst);
      }
      for (let i = 0; i < prepared.length; i += 1) {
        const inst = prepared[i] as Instance;
        try {
          inst.scheduler.finish();
        } catch (e) {
          fail(inst.id, e instanceof Error ? e.message : "render failed");
        }
        notices(inst);
      }
    } finally {
      prepared.length = 0;
      scheduled = false;
      for (const inst of charts.values()) {
        if (!due(inst)) continue;
        scheduled = true;
        deps.requestFrame(tick);
        break;
      }
    }
  }

  function notices(inst: Instance): void {
    notify(inst, inst.scheduler.takeNotice(inst.scheduler.budgetNotice));
    notify(inst, inst.scheduler.takeNotice());
  }

  /** Forwards the scheduler's notices as recoverable, informational `error`s (BQ-S3, BQ-44). */
  function notify(inst: Instance, n: scene.FrameNotice | null): void {
    if (n === null) return;
    if (n.from !== n.to) inst.lod = { ...inst.lod, candles: n.to as LodLevels["candles"] };
    deps.post({ t: "error", id: inst.id, code: n.code, message: describe(n), recoverable: true });
  }

  return {
    handle(msg: unknown): void {
      try {
        const reason = rejectReason(msg);
        if (reason === null) {
          dispatch(msg as ToWorker);
          return;
        }
        const m = msg as { t?: unknown; id?: unknown; store?: unknown; series?: unknown };
        const id = Number.isSafeInteger(m?.id) ? (m.id as ChartId) : null;
        fail(id, reason);
        // A rejected batch still releases its backpressure slot on the host.
        const store = m?.store as StoreId;
        if (m?.t === "data" && id !== null && charts.has(id) && STORE_IDS.includes(store)) {
          const sid = m.series;
          const tag =
            Number.isSafeInteger(sid) && (sid as number) >= 0 ? { series: sid as number } : {};
          deps.post({ t: "ack", id, store, ...tag });
        }
      } catch (e) {
        fail(null, e instanceof Error ? e.message : "unexpected failure");
      }
    },
    get size(): number {
      return charts.size;
    },
    pickIndex(id: ChartId) {
      const inst = charts.get(id);
      return inst && { objects: inst.objects, structural: inst.structural };
    },
    onDprChange(id, cb) {
      const set = charts.get(id)?.dprListeners;
      set?.add(cb);
      return set && (() => void set.delete(cb));
    },
    resizeCounters: (id) => charts.get(id)?.resizes,
    atlasCounters: () => atlas?.counters ?? null,
    series: (id, sid) => charts.get(id)?.series.get(sid),
    dataRejected: (id) => charts.get(id)?.dataRejected,
    seriesMetrics: (id) => charts.get(id)?.kinds,
    graph: (id) => charts.get(id)?.graph,
    syncCounters(id) {
      const inst = charts.get(id);
      if (inst === undefined) return undefined;
      const g = inst.group;
      let collapsed = 0;
      for (const p of inst.layout.panes) if (p.collapsed) collapsed += 1;
      return {
        propagationsPerFrame: g?.propagations ?? 0,
        propagationsPerFrameMax: g?.propagationsMax ?? 0,
        groupMembers: g?.members.length ?? 0,
        echoes,
        applied: inst.applied,
        remoteCrosshair: inst.remoteCrosshair,
        crosshair: inst.crosshair,
        panesCollapsed: collapsed,
      };
    },
    paneStats(id) {
      const inst = charts.get(id);
      return inst?.paneBlocks.map((b, i) => ({
        key: inst.layout.panes[i]?.key ?? -1,
        timeStart: inst.viewport.timeStart,
        timeEnd: inst.viewport.timeEnd,
        xWords: [b.ints[0] ?? 0, b.floats[0] ?? 0, b.floats[3] ?? 0],
      }));
    },
  };
}

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
// (G-23). A refused batch (F-01 decode, F-02 store) leaves the store byte-identical.
import type { RenderBackend } from "../gl/backend.js";
import { ContextLoss, type LossDetails } from "../gl/context-loss.js";
import { type OpenedBackend, openBackend } from "../gl/open-backend.js";
import {
  createPickHit,
  createStructuralHit,
  ObjectIndex,
  StructuralIndex,
  type PickHit,
  type StructuralHit,
} from "../hit/index.js";
import { Gestures } from "../interaction/gestures.js";
import { CandleRing } from "../layers/candle/ring.js";
import { CANDLE_ATTRIBUTES, CandleSeries } from "../layers/candle/series.js";
import type { HostDeps, HostTheme } from "../layers/host.js";
import type { BatchUniforms } from "../gl/submit.js";
import { type BarBatch, BarStore } from "../model/BarStore.js";
import { ModelRejection, type MutationRange, RangeSlot } from "../model/counters.js";
import { plotWidthOf } from "../interaction/wheel.js";
import * as scene from "../scene/index.js";
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
  ENGINE_NO_WEBGL2,
  ENGINE_ATLAS_GENERATION_FAILED,
  fontsOk,
  INPUT,
  INPUT_STRIDE,
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
  type PickPointer,
  type RunMode,
  type StoreId,
  type ThemeLut,
  type ToWorker,
} from "./protocol.js";

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
  series(id: ChartId, series: number): BarSeries | undefined;
  /** Internal (E12-S06): `engine.data.rejected{reason}`, per chart. */
  dataRejected(id: ChartId): Readonly<Record<string, number>> | undefined;
}

/** One runtime-owned series (E12-S06): its store is the CPU truth, the ring its GPU mirror. */
export interface BarSeries {
  readonly kind: BarSeriesKind;
  readonly pane: number;
  readonly store: BarStore;
  readonly ring: CandleRing;
  /** E12-S06: the candle plugin drawing it; null for OHLC `bars` until PR 2. */
  readonly candle: CandleSeries | null;
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
  /** Pane 0's GPU block, rewritten once per frame before submission. */
  readonly uniforms: PaneUniforms;
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
  readonly series: Map<number, BarSeries>;
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

  /** One chart's scene, laid out as one pane until the multi-pane wiring (E11-S09, BQ-45). */
  function createScene(
    slot: Instance["slot"],
    gpu: Instance["gpu"],
    canvas: () => CanvasLike,
    render: () => void,
    opened: (o: OpenedBackend) => void,
    viewport: ChartViewport,
  ) {
    const graph = new scene.SceneGraph();
    graph.addPane("main");
    const layout = new scene.LayoutEngine(graph);
    layout.addPane("main");
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
      layout: () => layout.run(),
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
    const summary = timeUs === null ? "" : summarise(timeUs);
    if (summary === inst.summary) return;
    inst.summary = summary;
    inst.a11yDirty = true;
    touch(inst);
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
  function resize(inst: Instance, w: number, h: number, dpr: number): void {
    const bw = backingPx(w, dpr);
    const bh = backingPx(h, dpr);
    inst.gestures.stop();
    inst.suspended = bw === 0 || bh === 0;
    if (inst.suspended) return; // the requested frame is kept, as a parked chart's is
    const c = inst.canvas;
    if (c.width !== bw || c.height !== bh) {
      c.width = bw;
      c.height = bh;
      inst.resizes.reallocations += 1;
    }
    inst.viewport.setPanePlot(0, 0, h);
    moved(inst, inst.viewport.setSize(plotWidthOf(w), h, dpr));
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
    inst.objects.pick(x, y, pointer, hit);
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
    const candle = kind === "candles" ? new CandleSeries(ring) : null;
    inst.series.set(sid, { kind, pane, store, ring, candle });
    if (candle !== null) {
      mountCandle(inst, sid, candle);
      themeCandle(inst, candle);
    }
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
    const hosts = c.mount(inst.graph, "main", `series.candle.${sid}.${inst.mounts++}`, deps);
    for (let p = 0; p < hosts.length; p += 1) {
      inst.blocks.set((hosts[p] as { id: string }).id, c.blocks[p] as BatchUniforms);
    }
    inst.candles.push(c);
    const backend = inst.gpu.backend;
    if (backend !== undefined) attachCandle(backend, c);
  }

  function attachCandle(backend: RenderBackend, c: CandleSeries): void {
    for (const h of c.hosts) backend.attach(h.id, c.ring, CANDLE_ATTRIBUTES);
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

  function removeSeries(inst: Instance, sid: number): void {
    const gone = inst.series.get(sid);
    if (!inst.series.delete(sid)) {
      fail(inst.id, `no series ${sid} on chart ${inst.id}`);
      return;
    }
    const c = gone?.candle ?? null;
    if (c !== null) {
      // No node removal yet (BQ-46): the hosts stay hidden, their batches unpatched and undrawn.
      for (const h of c.hosts) {
        h.visible = false;
        inst.blocks.delete(h.id);
      }
      c.ring.nodes.length = 0;
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
      for (const h of s.candle?.hosts ?? []) inst.graph.markData(h.id);
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
      case "setViewport":
        inst.gestures.stop();
        moved(inst, inst.viewport.setTimeRange(cmd.timeStart, cmd.timeEnd));
        return;
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
      case "setPriceScale":
        moved(inst, inst.viewport.setScale(cmd.pane, cmd)); // TRANSFORM only: no data refetch
        return;
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
      case "release":
        retire(inst);
        charts.delete(inst.id);
        if (charts.size === 0) {
          atlas?.dispose(); // the faces leave the font set; a build in flight stops
          atlas = null;
        }
        return;
      default:
        // setSeriesOptions / addDrawing: the scene graph that consumes them is E11-S01 / E14.
        touch(inst);
    }
  }

  function dispatch(msg: ToWorker): void {
    if (msg.t === "sync") {
      for (const inst of charts.values()) {
        if (inst.config.syncGroup !== msg.groupId) continue;
        inst.gestures.stop();
        moved(inst, inst.viewport.setTimeRange(msg.timeRange[0], msg.timeRange[1]));
        crosshairAt(inst, msg.crosshair);
      }
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
      const [w, h] = [c.width / msg.dpr, c.height / msg.dpr];
      viewport.setSize(plotWidthOf(w), h, msg.dpr); // the plot rect, not the canvas (RULED (5))
      viewport.setPanePlot(0, 0, h);
      const scene = createScene(
        slot,
        gpu,
        () => inst.canvas,
        () => render(inst),
        (backend) => opened(inst, backend),
        viewport,
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
        uniforms: createPaneUniforms(),
        autoscale: new AutoScaler(viewport, (pane) =>
          pane === 0 ? (deps.priceSources ?? []) : [],
        ),
        ready: false,
        viewportDirty: false,
        summary: "",
        a11yDirty: false,
        lod: { candles: 0, footprint: 0 },
        lastFrameAt: Number.NEGATIVE_INFINITY,
        gestures: new Gestures(viewport, scene.layout, {
          moved: (changed) => moved(inst, changed),
          hover: (x) => crosshairAt(inst, screenToTime(viewport, x)),
          animate: (m) => inst.scheduler.animate(m),
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
        dprListeners: old?.dprListeners ?? new Set(),
        resizes: old?.resizes ?? { reallocations: 0, dprChanges: 0, lastDpr: msg.dpr },
        loss: null,
        detach: null,
        elements: old ? { ...old.elements } : { bars: 0, footprint: 0, heatmap: 0, profile: 0 },
        fonts: msg.fonts === undefined ? undefined : fontsOk(msg.fonts) ? msg.fonts : "invalid",
        series: old?.series ?? new Map(),
        main: old?.main ?? -1,
        dataRejected: old?.dataRejected ?? {},
        candles: [],
        blocks: new Map(),
        hostTheme: hostTheme(msg.theme),
        mounts: old?.mounts ?? 0,
      };
      // BQ-53: the DataModel is kept; its rings now patch the fresh scene's batches.
      for (const [sid, s] of inst.series) {
        s.ring.sink = inst.builder;
        if (s.candle === null) continue;
        mountCandle(inst, sid, s.candle); // the fresh scene's hosts; the backend attaches them
        themeCandle(inst, s.candle);
      }
      const main = inst.series.get(inst.main);
      if (main !== undefined) viewport.setMap(main.store);
      inst.gestures.reduce = msg.reducedMotion === true;
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
        resize(inst, msg.width, msg.height, msg.dpr);
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
    const { width, height } = inst.canvas;
    // At most one refit per pane per frame, and only when a key changed (BQ-116).
    if (inst.autoscale.update()) inst.viewportDirty = true;
    if (backend !== null && backend.failure === null) {
      writePaneUniforms(inst.viewport, 0, inst.uniforms); // once per pane per frame (§3.5)
      // The clip space spans the backing store on both axes (BQ-101, BQ-142); the plot is its
      // left part, so x maps unchanged, and y never mixes vp.height * dpr with the rounded size.
      inst.uniforms.floats[4] = width;
      inst.uniforms.floats[5] = height;
      backend.setBackground(inst.theme[BACKGROUND_TOKEN]);
      const cs = inst.candles;
      for (let c = 0; c < cs.length; c += 1) {
        (cs[c] as CandleSeries).frame(inst.viewport.barSpacing, inst.dpr); // u_geom and u_batch
      }
      const f = backend.submit(inst.builder.drawList, inst.builder.drawCount, width, height);
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
      const vp = inst.viewport;
      const pane = vp.panes[0];
      deps.post({
        t: "viewport",
        id: inst.id,
        timeStart: vp.timeStart,
        timeEnd: vp.timeEnd,
        priceLow: pane?.priceLow ?? 0,
        priceHigh: pane?.priceHigh ?? 0,
        barSpacing: vp.barSpacing,
        pane: 0,
        mode: pane?.scaleMode ?? "linear",
        requestedMode: pane?.requestedMode ?? "linear",
        inverted: pane?.inverted ?? false,
        autoScale: pane?.autoScale ?? true,
        logAvailable: pane?.logReason === null,
        logReason: pane?.logReason ?? null,
        anchorTick: Number.isFinite(pane?.anchorTick) ? (pane?.anchorTick ?? null) : null,
      });
    }
    if (inst.a11yDirty) {
      inst.a11yDirty = false;
      deps.post({ t: "a11y", id: inst.id, cursorSummary: inst.summary });
    }
    const end = deps.now();
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
        backingStorePx: [width, height],
      });
    }
  }

  function tick(): void {
    scheduled = false;
    for (const inst of charts.values()) {
      const frame = inst.slot.frame;
      if (frame === null || inst.parked || inst.suspended) continue; // its request is kept
      inst.slot.frame = null;
      // A throwing canvas or context fails its own chart's frame, recoverably; it never escapes
      // the frame callback, where a worker would turn it into an uncaught error (E11-T02).
      try {
        frame(deps.now());
      } catch (e) {
        fail(inst.id, e instanceof Error ? e.message : "render failed");
      }
      notify(inst, inst.scheduler.takeNotice(inst.scheduler.budgetNotice));
      notify(inst, inst.scheduler.takeNotice());
    }
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
  };
}

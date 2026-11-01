// The render runtime (E11-T02): the one implementation of the worker side of §6. The worker entry
// (`render-worker.ts`) runs it behind `postMessage`; `RunMode.inline` runs the SAME module on the
// main thread behind a synchronous bus (26 §2), so only throughput differs between the modes.
// One runtime drives every chart registered with it from one frame callback, in registration
// order (§3.2 rule 1), each through its own `FrameScheduler` (E11-S01), and parks when nothing
// is dirty (§3.2 rule 5). No DOM types here (C-2.16): the canvas is reached structurally, as an
// OffscreenCanvas and an HTMLCanvasElement both fit. The runtime holds only the `RenderBackend`
// seam (E11-T05, README BQ-85): `openBackend` picks WebGL2 or Canvas 2D, and the loss wiring asks
// for the optional `LossCapable` hooks, so no line here branches on which backend draws (S3).
import { AxisModel, SAY, UPDATE } from "../axes/axis-model.js";
import {
  clockText,
  createZoned,
  dateText,
  decimalsOf,
  formatNumber,
  ZoneClock,
} from "../axes/format.js";
import { GRID_NODE_ID } from "../axes/grid.js";
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
import { plotWidthOf } from "../interaction/wheel.js";
import { RangeSlot } from "../model/counters.js";
import {
  createCrosshair,
  hideCrosshair,
  resolvePointer,
  takeBarEdge,
  type CrosshairState,
  type MagnetMode,
} from "../overlays/crosshair.js";
import { CROSSHAIR_NODE_ID, CrosshairNode } from "../overlays/crosshair-node.js";
import { Readout, type BarSource, type ReadoutProvider } from "../overlays/readout.js";
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
  backingPx,
  indexAt,
  indexToScreen,
  timeAt,
  writePaneUniforms,
} from "../viewport/index.js";
import {
  BACKGROUND_TOKEN,
  ENGINE_DECODE_ERROR,
  ENGINE_NO_WEBGL2,
  ENGINE_ATLAS_GENERATION_FAILED,
  fontsOk,
  INPUT,
  INPUT_STRIDE,
  rejectReason,
  RESTART_BACKOFF_MS,
  STORE_IDS,
  type ChartConfig,
  type CapabilityReport,
  type ChartId,
  type Command,
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
  /**
   * Internal (E11-S07, BQ-14): the main series' bars for the readout and the magnet until the
   * runtime owns a `BarStore` per series (#5307); its `BarView` fits structurally.
   */
  readonly readoutSources?: readonly BarSource[];
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
  /**
   * Internal (E11-S07, BQ-6): E13's seam. A visible series' value joins the readout after Δ, in
   * registration order (a provider with a known key replaces it). Returns the unregister function;
   * undefined for an unknown chart.
   */
  registerReadoutProvider(id: ChartId, provider: ReadoutProvider): (() => void) | undefined;
  /** Internal (BQ-20): `engine.crosshair.*`; `FrameStats` is unchanged. */
  crosshairCounters(id: ChartId): Readonly<CrosshairCounters> | undefined;
}

/** `engine.crosshair.events_emitted` (BQ-20): the public event's bar edges (BQ-10). */
export interface CrosshairCounters {
  eventsEmitted: number;
}

/** E11-D06 §5.2: the lines come back after this long without a drag, a glide or a wheel. */
export const CROSSHAIR_REST_MS = 150;

/** `engine.resize.*` (BQ-153): backing-store reallocations and DPR changes, per chart. */
export interface ResizeCounters {
  reallocations: number;
  dprChanges: number;
  lastDpr: number;
}

/** The crosshair as last posted (BQ-1): a field differs, the message goes out once. */
interface PostedCrosshair {
  bar: number;
  tick: number;
  x: number;
  y: number;
  snap: CrosshairState["snap"];
  driver: CrosshairState["driver"];
  visible: boolean;
  origin: number;
  tickSize: number;
  time: number;
}

/** One chart's crosshair (E11-S07): local state, the pointer, the remote line and the readout. */
interface CrossSlot {
  readonly state: CrosshairState;
  readonly node: CrosshairNode;
  readonly readout: Readout;
  readonly providers: Map<string, ReadoutProvider>;
  readonly counters: CrosshairCounters;
  readonly posted: PostedCrosshair;
  magnet: MagnetMode;
  /** The pointer over the canvas in CSS px; NaN once it left. */
  px: number;
  py: number;
  /** The lines stay hidden until then (a drag, glide or wheel burst, then 150 ms of rest). */
  restUntil: number;
  /** The rest timer is pending; `rest` is its one prebuilt callback. */
  armed: boolean;
  rest: () => void;
  /** The synced crosshair's bar time in µs (BQ-5); drawn only, never announced. */
  remote: number | null;
  /** The time last published to the sync group; NaN when none. */
  published: number;
  readonly clock: ZoneClock;
  readonly zoned: ReturnType<typeof createZoned>;
}

const createPosted = (): PostedCrosshair => ({
  bar: -1,
  tick: Number.NaN,
  x: Number.NaN,
  y: Number.NaN,
  snap: null,
  driver: "none",
  visible: false,
  origin: Number.NaN,
  tickSize: Number.NaN,
  time: Number.NaN,
});

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
  /** E11-S07: the crosshair, its lines and the readout. */
  readonly cross: CrossSlot;
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
}

/** The batch's last move or leave row is a leave (G-29): the pointer left the canvas. */
function leftCanvas(ev: Float32Array): boolean {
  for (let i = ev.length - INPUT_STRIDE; i >= 0; i -= INPUT_STRIDE) {
    if (ev[i] === INPUT.leave) return true;
    if (ev[i] === INPUT.move) return false;
  }
  return false;
}

/** The batch ends a drag or touch (`up` or `cancel`): with no glide, the lines show at once. */
function endsGesture(ev: Float32Array): boolean {
  for (let i = 0; i < ev.length; i += INPUT_STRIDE) {
    if (ev[i] === INPUT.up || ev[i] === INPUT.cancel) return true;
  }
  return false;
}

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
  const crossRange = new RangeSlot();
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
    axes: AxisModel,
    prepare: () => void,
  ) {
    const graph = new scene.SceneGraph();
    graph.addPane("main");
    graph.addNode("main", "background", axes.grid);
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
      layout: () => {
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
    backend.attach(GRID_NODE_ID, inst.axes.grid); // the grid is its own instance ring
    backend.attach(CROSSHAIR_NODE_ID, inst.cross.node); // and so is the crosshair (E11-S07)
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
        inst.cross.node.invalidate(); // and the crosshair's (E11-S07)
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

  function createCross(timeZone: string | undefined, old: CrossSlot | undefined): CrossSlot {
    const c: CrossSlot = {
      state: createCrosshair(),
      node: new CrosshairNode(CROSSHAIR_NODE_ID),
      readout: new Readout(timeZone),
      // The degraded-2d re-init keeps the providers, the magnet and the counters (G-28).
      providers: old?.providers ?? new Map(),
      counters: old?.counters ?? { eventsEmitted: 0 },
      posted: createPosted(),
      magnet: old?.magnet ?? "off",
      px: Number.NaN,
      py: Number.NaN,
      restUntil: Number.NEGATIVE_INFINITY,
      armed: false,
      rest: () => undefined,
      remote: old?.remote ?? null,
      published: Number.NaN,
      clock: new ZoneClock(timeZone ?? "UTC"),
      zoned: createZoned(),
    };
    c.readout.setProviders([...c.providers.values()]);
    return c;
  }

  /**
   * The pointer moved over the canvas (CSS px), or left it (NaN): the next frame resolves. A move
   * outside a gesture ends a wheel's hold at once (E11-D06 §5.2: the earlier of 150 ms after the
   * last wheel event or the next pointer move).
   */
  function pointerAt(inst: Instance, x: number, y: number): void {
    const c = inst.cross;
    const released = !inst.gestures.active && c.restUntil > deps.now();
    if (released) c.restUntil = Number.NEGATIVE_INFINITY;
    if (!released && Object.is(c.px, x) && Object.is(c.py, y)) return;
    c.px = x;
    c.py = y;
    touch(inst);
  }

  /** A drag, glide or wheel hides the lines until 150 ms after the last of them (D06 §5.2). */
  function holdLines(inst: Instance): void {
    const c = inst.cross;
    c.restUntil = deps.now() + CROSSHAIR_REST_MS;
    if (c.armed) return;
    c.armed = true;
    deps.setTimer(c.rest, CROSSHAIR_REST_MS);
  }

  /** The rest timer: re-armed for what is left (the clock has no cancel), else a frame. */
  function rested(inst: Instance): void {
    const c = inst.cross;
    c.armed = false;
    if (charts.get(inst.id) !== inst) return; // retired or re-initialised
    const left = c.restUntil - deps.now();
    if (left > 0) {
      c.armed = true;
      deps.setTimer(c.rest, left);
      return;
    }
    touch(inst);
  }

  /**
   * BQ-6: once per frame in the layout hook, after autoscale and the axes. The pointer becomes
   * the local crosshair (bar centre, magnet), hidden during a gesture and over the gutters; the
   * lines are rewritten when they moved; the bar time goes to the sync group.
   */
  function resolveCrosshair(inst: Instance): void {
    const c = inst.cross;
    const s = c.state;
    // Idle (no pointer seen, nothing shown, drawn or published, no remote line): O(1), so a
    // frame with no crosshair (a resize drag, a pan from the keys) pays nothing for it.
    if (
      !s.visible &&
      c.remote === null &&
      Number.isNaN(c.px) &&
      c.node.count === 0 &&
      Number.isNaN(c.published)
    ) {
      return;
    }
    const vp = inst.viewport;
    const rect = inst.layout.panes[0]?.rect;
    if (inst.gestures.active) holdLines(inst);
    const inPlot =
      rect !== undefined &&
      c.px >= rect[0] &&
      c.px < rect[0] + rect[2] &&
      c.py >= rect[1] &&
      c.py < rect[1] + rect[3];
    if (inPlot && deps.now() >= c.restUntil) {
      resolvePointer(s, vp, 0, deps.readoutSources?.[0] ?? null, c.px, c.py, c.magnet);
    } else if (s.visible) hideCrosshair(s);
    if (rect !== undefined) {
      let remoteX = Number.NaN;
      if (!s.visible && c.remote !== null) {
        // The bar holding the remote time, at its centre (an open time maps to its own bar).
        remoteX = indexToScreen(vp, Math.floor(indexAt(vp.map, c.remote) + 1e-9));
      }
      const deviceH = Math.round(inst.layout.height * vp.dpr);
      if (c.node.write(inst.theme, vp.dpr, deviceH, rect, s.visible, s.x, s.y, remoteX)) {
        // Joined to the scene on its first lines: a chart never crossed walks no extra node.
        if (inst.graph.get(CROSSHAIR_NODE_ID) === undefined) {
          inst.graph.addNode("main", "foreground", c.node);
        }
        inst.graph.markData(CROSSHAIR_NODE_ID);
        inst.builder.patch(CROSSHAIR_NODE_ID, crossRange.set("replace", 0, c.node.count, 0));
      }
    }
    publishCrosshair(inst);
  }

  /**
   * BQ-6: the local crosshair's bar time to every other chart of the same sync group, once per
   * change (null once hidden). S09 (#446) replaces the loop with `SyncGroup`. No echo: a chart
   * publishes only its own local crosshair, never a remote one it was given (`remote` never
   * touches `state`), so a peer without a local cursor computes NaN, equal to its `published`,
   * and sends nothing back.
   */
  function publishCrosshair(inst: Instance): void {
    const group = inst.config.syncGroup;
    if (group === null) return;
    const c = inst.cross;
    const t = c.state.visible ? timeAt(inst.viewport.map, c.state.bar) : Number.NaN;
    if (Object.is(t, c.published)) return;
    c.published = t;
    for (const peer of charts.values()) {
      if (peer !== inst && peer.config.syncGroup === group) {
        applyRemoteCrosshair(peer, Number.isNaN(t) ? null : t);
      }
    }
  }

  /**
   * BQ-5: a remote crosshair is drawn only. It never sets the summary or posts `a11y`, the
   * readout or a magnet change (E11-D01 D3: never announced, never in the DOM mirror).
   */
  function applyRemoteCrosshair(inst: Instance, timeUs: number | null): void {
    if (inst.cross.remote === timeUs) return;
    inst.cross.remote = timeUs;
    touch(inst);
  }

  /**
   * BQ-1, BQ-2: in `render`, after `axes` and before `a11y`. The crosshair is posted when one
   * of its fields changed (at most once a frame); the readout when its bar or the data at that
   * bar changed. A copy is posted, never the pooled fields (inline mode shares the objects).
   */
  function postCrosshair(inst: Instance): void {
    const c = inst.cross;
    const s = c.state;
    const p = c.posted;
    if (!s.visible && !p.visible) return; // hidden and already posted hidden: nothing to say
    const pane = inst.viewport.panes[0];
    const origin = pane?.priceOrigin ?? Number.NaN;
    const tickSize = pane?.tickSize ?? 0;
    const time = s.bar >= 0 ? timeAt(inst.viewport.map, s.bar) : Number.NaN;
    const same =
      p.bar === s.bar &&
      Object.is(p.tick, s.tick) &&
      Object.is(p.x, s.x) &&
      Object.is(p.y, s.y) &&
      p.snap === s.snap &&
      p.driver === s.driver &&
      p.visible === s.visible &&
      Object.is(p.origin, origin) &&
      p.tickSize === tickSize &&
      Object.is(p.time, time);
    if (!same) {
      // The facade emits its readout event once a frame: when the bar or snap moved while shown,
      // a `readout` always follows this message (BQ-11), so the fields are rebuilt.
      if (s.visible && (p.bar !== s.bar || p.snap !== s.snap)) c.readout.invalidate();
      p.bar = s.bar;
      p.tick = s.tick;
      p.x = s.x;
      p.y = s.y;
      p.snap = s.snap;
      p.driver = s.driver;
      p.visible = s.visible;
      p.origin = origin;
      p.tickSize = tickSize;
      p.time = time;
      if (takeBarEdge(s)) c.counters.eventsEmitted += 1;
      const price = tickSize > 0 && Number.isFinite(s.tick);
      const z = c.clock.fields(time / 1000, c.zoned);
      deps.post({
        t: "crosshair",
        id: inst.id,
        bar: s.bar,
        time,
        price: s.tick,
        priceText: price ? formatNumber(origin + s.tick * tickSize, decimalsOf(tickSize)) : "",
        timeText: Number.isFinite(time) ? `${dateText(z)} ${clockText(z.ms, false)}` : "",
        x: s.x,
        y: s.y,
        snap: s.snap,
        driver: s.driver,
        visible: s.visible,
      });
    }
    if (!s.visible || !c.readout.build(deps.readoutSources?.[0] ?? null, s.bar, s.snap)) return;
    deps.post({
      t: "readout",
      id: inst.id,
      bar: s.bar,
      fields: c.readout.fields.map((f) => ({ ...f })),
    });
  }

  /**
   * The layout hook's second half, before collect (E11-S06): autoscale (at most once per frame,
   * BQ-116), then the axes. A new gutter width lays the chart out again and narrows the plot; a
   * rebuilt grid re-uploads its ring in full.
   */
  function prepare(inst: Instance): void {
    if (inst.autoscale.update()) inst.viewportDirty = true;
    const { axes, layout, viewport: vp } = inst;
    let r = axes.update(vp, layout, inst.theme);
    if ((r & UPDATE.gutter) !== 0) {
      layout.setPriceGutter(axes.gutter.width);
      layout.run();
      // In this frame, before collect: TRANSFORM without a wake, so no second frame follows.
      if (vp.setSize(plotWidthOf(layout.width, layout.priceGutter), vp.height, vp.dpr)) {
        inst.viewportDirty = true;
        inst.graph.markViewport();
      }
      r = axes.update(vp, layout, inst.theme);
    }
    if ((r & UPDATE.grid) !== 0) {
      inst.graph.markData(GRID_NODE_ID);
      inst.builder.patch(GRID_NODE_ID, gridRange.set("replace", 0, axes.grid.count, 0));
    }
    if ((r & UPDATE.labels) !== 0) inst.axesDirty = true;
    resolveCrosshair(inst);
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
    inst.viewport.setPanePlot(0, 0, h);
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

  function command(inst: Instance, cmd: Command): void {
    switch (cmd.k) {
      case "setViewport":
        inst.gestures.stop();
        moved(inst, inst.viewport.setTimeRange(cmd.timeStart, cmd.timeEnd));
        return;
      case "setTheme":
        inst.theme = cmd.theme;
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
      case "setCrosshair":
        inst.cross.magnet = cmd.magnetMode; // re-resolved next frame; never announced here
        touch(inst);
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
        applyRemoteCrosshair(inst, msg.crosshair); // remote-only (BQ-5)
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
      const axes = new AxisModel(msg.config.timeZone);
      const cross = createCross(msg.config.timeZone, old?.cross);
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
        uniforms: createPaneUniforms(),
        autoscale: new AutoScaler(viewport, (pane) =>
          pane === 0 ? (deps.priceSources ?? []) : [],
        ),
        ready: false,
        viewportDirty: false,
        cross,
        lod: { candles: 0, footprint: 0 },
        lastFrameAt: Number.NEGATIVE_INFINITY,
        gestures: new Gestures(viewport, scene.layout, {
          moved: (changed) => moved(inst, changed),
          hover: (x, y) => pointerAt(inst, x, y),
          animate: (m) => inst.scheduler.animate(m),
          say: (code) => (inst.axes.say = code),
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
      };
      inst.gestures.reduce = msg.reducedMotion === true;
      cross.rest = () => rested(inst);
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
        if (msg.kind === "wheel") holdLines(inst); // a wheel burst hides the lines (D06 §5.2)
        inst.gestures.apply(msg.kind === "touch", msg.events);
        if (inst.gestures.active) {
          holdLines(inst); // a drag between frames hides them too
        } else if (endsGesture(msg.events)) {
          // E11-D06 §5.2: an up with no glide shows them at once, not after the rest.
          inst.cross.restUntil = Number.NEGATIVE_INFINITY;
          touch(inst);
        }
        if (msg.kind === "pointer" && leftCanvas(msg.events)) pointerAt(inst, NaN, NaN);
        if (msg.kind === "pointer" || msg.kind === "touch") {
          hover(inst, msg.kind === "touch", msg.events);
        }
        return;
      case "data": {
        // The stores are E11-T03's; until then a batch only moves the element count.
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
      writePaneUniforms(inst.viewport, 0, inst.uniforms); // once per pane per frame (§3.5)
      // The clip space spans the exact store on both axes (BQ-101, BQ-142, BQ-149); the plot is
      // its left part, so x maps unchanged, and y never mixes vp.height * dpr with the rounded
      // size. A padded store is drawn in its exact top-left sub-rect.
      inst.uniforms.floats[4] = width;
      inst.uniforms.floats[5] = height;
      backend.setBackground(inst.theme[BACKGROUND_TOKEN]);
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
    postCrosshair(inst);
    // `a11y` is posted for key-driven cursor moves only (BQ-3); their wiring is BQ-7's.
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
        backingStorePx: [backing.width, backing.height],
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
        const m = msg as { t?: unknown; id?: unknown; store?: unknown };
        const id = Number.isSafeInteger(m?.id) ? (m.id as ChartId) : null;
        fail(id, reason);
        // A rejected batch still releases its backpressure slot on the host.
        const store = m?.store as StoreId;
        if (m?.t === "data" && id !== null && charts.has(id) && STORE_IDS.includes(store)) {
          deps.post({ t: "ack", id, store });
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
    registerReadoutProvider(id, provider) {
      const inst = charts.get(id);
      if (inst === undefined) return undefined;
      const { providers, readout } = inst.cross;
      providers.set(provider.key, provider);
      readout.setProviders([...providers.values()]);
      touch(inst);
      return () => {
        if (providers.get(provider.key) !== provider) return;
        providers.delete(provider.key);
        const live = charts.get(id)?.cross ?? inst.cross;
        live.readout.setProviders([...providers.values()]);
        touch(charts.get(id) ?? inst);
      };
    },
    crosshairCounters: (id) => charts.get(id)?.cross.counters,
  };
}

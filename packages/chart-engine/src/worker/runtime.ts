// The render runtime (E11-T02): the one implementation of the worker side of §6. The worker entry
// (`render-worker.ts`) runs it behind `postMessage`; `RunMode.inline` runs the SAME module on the
// main thread behind a synchronous bus (26 §2), so only throughput differs between the modes.
// One runtime drives every chart registered with it from one frame callback, in registration
// order (§3.2 rule 1), each through its own `FrameScheduler` (E11-S01), and parks when nothing
// is dirty (§3.2 rule 5). No DOM types here (C-2.16): the canvas is reached structurally, as an
// OffscreenCanvas and an HTMLCanvasElement both fit. The runtime holds only the `RenderBackend`
// seam (E11-T05, README BQ-85): `openBackend` picks WebGL2 or Canvas 2D, and the loss wiring asks
// for the optional `LossCapable` hooks, so no line here branches on which backend draws (S3).
import type { RenderBackend } from "../gl/backend.js";
import { ContextLoss, type LossDetails } from "../gl/context-loss.js";
import { type OpenedBackend, openBackend } from "../gl/open-backend.js";
import { Gestures } from "../interaction/gestures.js";
import { plotWidthOf } from "../interaction/wheel.js";
import * as scene from "../scene/index.js";
import {
  ChartViewport,
  createPaneUniforms,
  type IndexTimeMap,
  type PaneUniforms,
  screenToTime,
  writePaneUniforms,
} from "../viewport/index.js";
import {
  BACKGROUND_TOKEN,
  ENGINE_DECODE_ERROR,
  ENGINE_NO_WEBGL2,
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
  /** One-shot timer: the context-restore attempts wait on it (BQ-49). */
  setTimer(cb: () => void, ms: number): void;
  /** The capability probe behind the `ready` report; run once, on the first frame. */
  probe(): CapabilityReport;
  /** Test-only (E11-S04, BQ-111): bars for every chart's viewport until E12 wires the store. */
  readonly timeMap?: IndexTimeMap;
}

export interface RenderRuntime {
  /** Handles one inbound message. Never throws: a bad message becomes an `error` event. */
  handle(msg: unknown): void;
  /** Charts registered (read by tests and the host's restart bookkeeping). */
  readonly size: number;
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
  loss: ContextLoss | null;
  /** Removes the context-loss listeners. */
  detach: (() => void) | null;
  viewportDirty: boolean;
  summary: string;
  a11yDirty: boolean;
  lod: LodLevels;
  lastFrameAt: number;
  /** Pointer, wheel and touch routing plus the glide (E11-S04 PR 1). */
  readonly gestures: Gestures;
  lastPick: string | null;
  readonly elements: Record<StoreId, number>;
}

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
    type Details = LossDetails | DegradeDetails;
    const post = (code: string, message: string, recoverable: boolean, d?: Details): void =>
      deps.post({ t: "error", id: inst.id, code, message, recoverable, ...(d && { details: d }) });
    backend.setPaneUniforms(() => inst.uniforms); // one pane until E11-S09 (BQ-45)
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
    return phase !== "live" || inst.parked ? "context-lost" : null; // parked: mid-loss
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
      case "pickAt": {
        // No HitIndex yet (E11-S08): every pick is a miss, reported once (edge-triggered).
        const key = "none";
        if (inst.lastPick === key) return;
        inst.lastPick = key;
        deps.post({
          t: "pick",
          id: inst.id,
          objectId: null,
          kind: key,
          bar: -1,
          price: Number.NaN,
        });
        return;
      }
      case "export":
        exportPng(inst, cmd.reqId);
        return;
      case "release":
        retire(inst);
        charts.delete(inst.id);
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
        lastPick: null,
        parked: false,
        loss: null,
        detach: null,
        elements: old ? { ...old.elements } : { bars: 0, footprint: 0, heatmap: 0, profile: 0 },
      };
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
        inst.canvas.width = Math.max(1, Math.round(msg.width * msg.dpr));
        inst.canvas.height = Math.max(1, Math.round(msg.height * msg.dpr));
        inst.gestures.stop();
        inst.viewport.setPanePlot(0, 0, msg.height);
        moved(inst, inst.viewport.setSize(plotWidthOf(msg.width), msg.height, msg.dpr));
        inst.layout.setSize(msg.width, msg.height); // LAYOUT: recomputed on the next frame only
        touch(inst);
        return;
      case "input":
        inst.gestures.apply(msg.kind === "touch", msg.events);
        return;
      case "data": {
        // The stores are E11-T03's; until then a batch only moves the element count.
        const n = msg.layout.count;
        if (msg.op === "replace") inst.elements[msg.store] = n;
        else if (msg.op !== "patch") inst.elements[msg.store] += n;
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
    if (backend !== null && backend.failure === null) {
      writePaneUniforms(inst.viewport, 0, inst.uniforms); // once per pane per frame (§3.5)
      // The clip space spans the canvas; the plot is its left part, so x maps unchanged (BQ-101).
      inst.uniforms.floats[4] = width;
      backend.setBackground(inst.theme[BACKGROUND_TOKEN]);
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
      });
    }
  }

  function tick(): void {
    scheduled = false;
    for (const inst of charts.values()) {
      const frame = inst.slot.frame;
      if (frame === null || inst.parked) continue; // a parked chart keeps its request
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
  };
}

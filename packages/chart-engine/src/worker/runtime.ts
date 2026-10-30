// The render runtime (E11-T02): the one implementation of the worker side of §6. The worker entry
// (`render-worker.ts`) runs it behind `postMessage`; `RunMode.inline` runs the SAME module on the
// main thread behind a synchronous bus (26 §2), so only throughput differs between the modes.
// One runtime drives every chart registered with it from one frame callback, in registration
// order (§3.2 rule 1), each through its own `FrameScheduler` (E11-S01), and parks when nothing
// is dirty (§3.2 rule 5). No DOM types here (C-2.16): the canvas is reached structurally, as an
// OffscreenCanvas and an HTMLCanvasElement both fit.
import * as scene from "../scene/index.js";
import {
  BACKGROUND_TOKEN,
  ENGINE_DECODE_ERROR,
  INPUT,
  INPUT_STRIDE,
  KEY,
  rejectReason,
  STORE_IDS,
  type ChartConfig,
  type ChartId,
  type Command,
  type FromWorker,
  type LodLevels,
  type RenderProfile,
  type RunMode,
  type StoreId,
  type ThemeLut,
  type ToWorker,
} from "./protocol.js";

/** The 2D context calls the stub renderer makes (GL replaces it in E11-S02). */
interface Context2DLike {
  fillStyle: unknown;
  clearRect(x: number, y: number, w: number, h: number): void;
  fillRect(x: number, y: number, w: number, h: number): void;
}

/** The canvas members the runtime touches, common to OffscreenCanvas and HTMLCanvasElement. */
interface CanvasLike {
  width: number;
  height: number;
  getContext(id: "2d"): unknown;
  convertToBlob?: (opts: { type: string }) => Promise<unknown>;
  toBlob?: (cb: (blob: unknown) => void, type: string) => void;
}

export interface RuntimeDeps {
  readonly runMode: RunMode;
  post(msg: FromWorker): void;
  /** Schedules one frame callback (the worker's or the page's rAF). */
  requestFrame(cb: () => void): void;
  now(): number;
  /** The capability probe behind the `ready` report; run once, on the first frame. */
  probe(): RenderProfile;
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
  widthCss: number;
  dpr: number;
  ready: boolean;
  /** The scheduler's requested frame, run by the shared callback; null while parked. */
  readonly slot: { frame: scene.FrameCallback | null };
  readonly graph: scene.SceneGraph;
  readonly layout: scene.LayoutEngine;
  readonly scheduler: scene.FrameScheduler;
  timeStart: number;
  timeEnd: number;
  viewportDirty: boolean;
  summary: string;
  a11yDirty: boolean;
  lod: LodLevels;
  lastFrameAt: number;
  dragX: number | null;
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
  let profile: RenderProfile | null = null;

  const fail = (id: ChartId | null, message: string): void => {
    deps.post({ t: "error", id, code: ENGINE_DECODE_ERROR, message, recoverable: true });
  };

  const touch = (inst: Instance): void => {
    inst.scheduler.wake();
  };

  /** One chart's scene, laid out as one pane until the multi-pane wiring (E11-S09, BQ-45). */
  function createScene(slot: Instance["slot"], render: () => void) {
    const graph = new scene.SceneGraph();
    graph.addPane("main");
    const layout = new scene.LayoutEngine(graph);
    layout.addPane("main");
    const builder = new scene.BatchBuilder(graph, { uploadSubRange: () => undefined }); // E11-S02
    const clock = { now: () => deps.now(), requestFrame, cancel: () => (slot.frame = null) };
    function requestFrame(cb: scene.FrameCallback): number {
      slot.frame = cb;
      if (!scheduled) deps.requestFrame(tick);
      scheduled = true;
      return 1;
    }
    const scheduler = new scene.FrameScheduler(graph, clock, {
      layout: () => layout.run(),
      build: (sink) => builder.build(sink),
      submit: render,
    });
    return { graph, layout, scheduler };
  }

  function setRange(inst: Instance, start: number, end: number): void {
    if (!(end > start) || !Number.isFinite(start) || !Number.isFinite(end)) return;
    inst.timeStart = start;
    inst.timeEnd = end;
    inst.viewportDirty = true;
    inst.graph.markViewport(); // TRANSFORM, never DATA: buffers are reused
    touch(inst);
  }

  function zoomAt(inst: Instance, x: number, factor: number): void {
    const span = inst.timeEnd - inst.timeStart;
    const at = inst.widthCss > 0 ? x / inst.widthCss : 0.5;
    const anchor = inst.timeStart + at * span;
    setRange(inst, anchor - at * span * factor, anchor + (1 - at) * span * factor);
  }

  function crosshairAt(inst: Instance, timeUs: number | null): void {
    const summary = timeUs === null ? "" : summarise(timeUs);
    if (summary === inst.summary) return;
    inst.summary = summary;
    inst.a11yDirty = true;
    touch(inst);
  }

  function applyInput(inst: Instance, ev: Float32Array): void {
    for (let i = 0; i < ev.length; i += INPUT_STRIDE) {
      const type = ev[i] as number;
      const x = ev[i + 1] as number;
      const buttons = ev[i + 3] as number;
      const span = inst.timeEnd - inst.timeStart;
      if (type === INPUT.down) inst.dragX = x;
      else if (type === INPUT.up) inst.dragX = null;
      else if (type === INPUT.wheel) zoomAt(inst, x, Math.exp(buttons * 0.002));
      else if (type === INPUT.key) {
        if (x === KEY.zoomIn || x === KEY.zoomOut) {
          zoomAt(inst, inst.widthCss / 2, x === KEY.zoomIn ? 0.8 : 1.25);
        }
      } else if (type === INPUT.move) {
        if (inst.dragX !== null && (buttons & 1) === 1 && inst.widthCss > 0) {
          const dt = ((x - inst.dragX) / inst.widthCss) * span;
          inst.dragX = x;
          setRange(inst, inst.timeStart - dt, inst.timeEnd - dt);
        }
        const w = inst.widthCss > 0 ? inst.widthCss : 1;
        crosshairAt(inst, inst.timeStart + (x / w) * (inst.timeEnd - inst.timeStart));
      }
    }
  }

  function exportPng(inst: Instance, reqId: number): void {
    const c = inst.canvas;
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
        setRange(inst, cmd.timeStart, cmd.timeEnd);
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
        inst.scheduler.dispose();
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
        setRange(inst, msg.timeRange[0], msg.timeRange[1]);
        crosshairAt(inst, msg.crosshair);
      }
      return;
    }
    if (msg.t === "init") {
      const slot: Instance["slot"] = { frame: null };
      const scene = createScene(slot, () => render(inst));
      const inst: Instance = {
        ...scene,
        slot,
        id: msg.id,
        canvas: msg.canvas as CanvasLike,
        theme: msg.theme,
        config: msg.config,
        widthCss: (msg.canvas as CanvasLike).width / msg.dpr,
        dpr: msg.dpr,
        ready: false,
        timeStart: 0,
        timeEnd: 1,
        viewportDirty: false,
        summary: "",
        a11yDirty: false,
        lod: { candles: 0, footprint: 0 },
        lastFrameAt: Number.NEGATIVE_INFINITY,
        dragX: null,
        lastPick: null,
        elements: { bars: 0, footprint: 0, heatmap: 0, profile: 0 },
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
        inst.widthCss = msg.width;
        inst.dpr = msg.dpr;
        inst.layout.setSize(msg.width, msg.height); // LAYOUT: recomputed on the next frame only
        touch(inst);
        return;
      case "input":
        applyInput(inst, msg.events);
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
    const renderProfile = (profile ??= deps.probe());
    if (!inst.ready) {
      inst.ready = true;
      deps.post({ t: "ready", id: inst.id, runMode: deps.runMode, renderProfile });
    }
    const ctx = inst.canvas.getContext("2d") as Context2DLike | null;
    if (ctx !== null) {
      ctx.clearRect(0, 0, inst.canvas.width, inst.canvas.height);
      const color = inst.theme[BACKGROUND_TOKEN];
      if (color !== undefined && color !== "") {
        ctx.fillStyle = color;
        ctx.fillRect(0, 0, inst.canvas.width, inst.canvas.height);
      }
    }
    if (inst.viewportDirty) {
      inst.viewportDirty = false;
      deps.post({
        t: "viewport",
        id: inst.id,
        timeStart: inst.timeStart,
        timeEnd: inst.timeEnd,
        priceLow: 0,
        priceHigh: 0,
        barSpacing: 0,
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
        drawCalls: 0,
        triangles: 0,
        uploadedBytes: 0,
        lod: inst.lod,
      });
    }
  }

  function tick(): void {
    scheduled = false;
    for (const inst of charts.values()) {
      const frame = inst.slot.frame;
      if (frame === null) continue;
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

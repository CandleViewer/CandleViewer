// Chart facade (E11-T01, E11-T02). `createChart` returns synchronously; capability detection
// runs lazily on the first frame, so the React binding needs no Suspense. Rendering runs in the
// shared render runtime, in a worker or inline (`ChartOptions.runMode`, src/worker/host.ts); the
// scene graph and GL backend land in E11-S01 / E11-S02 behind this same surface.
import { mountSurface, probeRenderProfile } from "../host/mount.js";
import {
  captureInput,
  createChartHost,
  defaultHostEnv,
  selectRunMode,
  type HostEnv,
} from "../worker/host.js";
import { ENGINE_WORKER_LOST, type FromWorker, type RunMode } from "../worker/protocol.js";
import { createPane, type PaneInternal } from "./pane.js";
import { createTimeScale } from "./scales.js";
import type {
  Chart,
  ChartEvents,
  ChartOptions,
  Density,
  FocusedUnit,
  FrameStats,
  Pane,
  PaneId,
  PaneOptions,
  ThemeTokens,
  Unsubscribe,
  VisibleWindow,
} from "./types.js";

/** §8 defaults for the options `createChart` resolves. */
export const CHART_DEFAULTS = {
  locale: "en-GB",
  timeZone: "UTC",
  density: "comfortable",
  maxBars: 200_000,
  memoryBudgetMb: 600,
} as const;

/** The chart plus the resolved state the stub keeps (read by tests). */
export interface ChartInternal extends Chart {
  readonly theme: ThemeTokens;
  readonly density: Density;
  readonly disposed: boolean;
  readonly runMode: RunMode;
}

let envOverride: ((doc: Document) => HostEnv) | null = null;

/** Test seam: the realm services charts are created with (null restores the page defaults). */
export function setHostEnvFactory(factory: ((doc: Document) => HostEnv) | null): void {
  envOverride = factory;
}

type Listener<E extends keyof ChartEvents> = (p: ChartEvents[E]) => void;

function positiveInt(value: number | undefined, fallback: number, name: string): number {
  if (value === undefined) return fallback;
  if (!Number.isSafeInteger(value) || value <= 0) {
    throw new RangeError(`chart-engine: ${name} must be a positive integer`);
  }
  return value;
}

/**
 * Mounts a chart into `opts.container` and returns its facade synchronously (§8). Capability
 * detection is lazy (first frame or `getStats`), so no caller needs to await anything.
 */
export function createChart(opts: ChartOptions): Chart {
  // The hard ceilings are checked up front (E11-T01 security notes: no unbounded allocation).
  positiveInt(opts.maxBars, CHART_DEFAULTS.maxBars, "maxBars");
  positiveInt(opts.memoryBudgetMb, CHART_DEFAULTS.memoryBudgetMb, "memoryBudgetMb");

  const surface = mountSurface(opts.container);
  const doc = opts.container.ownerDocument;
  const listeners = new Map<keyof ChartEvents, Set<Listener<keyof ChartEvents>>>();
  const panes: PaneInternal[] = [];
  let theme = opts.theme;
  let density: Density = opts.density ?? CHART_DEFAULTS.density;
  let disposed = false;
  let paneSeq = 0;
  let renderProfile: FrameStats["renderProfile"] | null = null;
  let lastStats: FrameStats | null = null;
  let lastRange = { from: 0, to: 1 };

  function emit<E extends keyof ChartEvents>(e: E, payload: ChartEvents[E]): void {
    const set = listeners.get(e);
    if (set === undefined) return;
    for (const cb of [...set]) (cb as Listener<E>)(payload);
  }

  function assertLive(): void {
    if (disposed) throw new Error("chart-engine: the chart was disposed");
  }

  function stats(): FrameStats {
    if (lastStats !== null) return lastStats;
    renderProfile ??= probeRenderProfile(doc).profile;
    return {
      fps: 0,
      frameTimeMsP50: 0,
      frameTimeMsP95: 0,
      drawCalls: 0,
      triangles: 0,
      uploadedBytesPerSec: 0,
      lodCandles: 0,
      lodFootprint: 0,
      gpuMemoryMbEstimate: 0,
      renderProfile,
    };
  }

  function onWorker(msg: FromWorker): void {
    switch (msg.t) {
      case "ready":
        renderProfile = msg.renderProfile;
        return;
      case "frame":
        lastStats = {
          ...stats(),
          frameTimeMsP50: msg.frameTimeMs,
          frameTimeMsP95: msg.frameTimeMs,
          drawCalls: msg.drawCalls,
          triangles: msg.triangles,
          uploadedBytesPerSec: msg.uploadedBytes,
          lodCandles: msg.lod.candles,
          lodFootprint: msg.lod.footprint,
        };
        emit("frameStats", lastStats);
        return;
      case "viewport":
        lastRange = { from: msg.timeStart, to: msg.timeEnd };
        emit("viewportChanged", {
          timeStart: msg.timeStart,
          timeEnd: msg.timeEnd,
          barSpacing: msg.barSpacing,
        });
        return;
      case "error":
        emit("error", { code: msg.code, message: msg.message, recoverable: msg.recoverable });
        return;
      default:
      // pick and a11y are the hit-test and live-region layers' (E11-S08 / E11-S13).
    }
  }

  const env = (envOverride ?? defaultHostEnv)(doc);
  const host = createChartHost({
    realm: doc,
    runMode: selectRunMode(opts.runMode, surface.canvas, doc.defaultView),
    env,
    canvas: () => surface.canvas,
    replaceCanvas: () => surface.replaceCanvas(),
    dpr: doc.defaultView?.devicePixelRatio ?? 1,
    theme: opts.theme.colors,
    syncGroup: opts.syncGroup ?? null,
    // Bench mode (every-frame `frame`, the C-Q02-1 LOD trace) has no §8 option: README BQ-18.
    bench: false,
    listener: {
      deliver: onWorker,
      lost(final: boolean, correlationId: string): void {
        // SCR-048 reads the correlation id from the message (§8's error event has no field).
        emit("error", {
          code: ENGINE_WORKER_LOST,
          message: final
            ? `The render worker could not be restarted (correlation id ${correlationId}).`
            : `The render worker stopped; restarting (correlation id ${correlationId}).`,
          recoverable: !final,
        });
      },
      restored(): void {
        // The snapshot request: the data layer re-sends the stores for the restored viewport.
        emit("visibleRangeNeedsData", { fromTime: lastRange.from, toTime: lastRange.to });
      },
      resync(): void {
        // Backpressure dropped a batch: the same request makes the data layer re-send (BQ-16).
        emit("visibleRangeNeedsData", { fromTime: lastRange.from, toTime: lastRange.to });
      },
    },
  });
  const detachInput = captureInput(opts.container, host);
  const timeScale = createTimeScale((r) => {
    host.command({ k: "setViewport", timeStart: r.from, timeEnd: r.to });
  });

  const chart: ChartInternal = {
    get panes(): readonly Pane[] {
      return [...panes];
    },
    timeScale,
    get theme(): ThemeTokens {
      return theme;
    },
    get density(): Density {
      return density;
    },
    get disposed(): boolean {
      return disposed;
    },
    runMode: host.runMode,
    addPane(paneOpts: PaneOptions): Pane {
      assertLive();
      paneSeq += 1;
      const pane = createPane(`pane-${paneSeq}` as PaneId, paneOpts, {
        assertLive,
        data: (store, op, layout, buffer) => host.data(store, op, layout, buffer),
        onRemoved(id: PaneId): void {
          const i = panes.findIndex((p) => p.id === id);
          if (i >= 0) panes.splice(i, 1);
        },
      });
      panes.push(pane);
      return pane;
    },
    removePane(id: PaneId): void {
      panes.find((p) => p.id === id)?.remove();
    },
    setTheme(next: ThemeTokens): void {
      if (disposed) return;
      theme = next;
      host.command({ k: "setTheme", theme: next.colors });
    },
    setDensity(d: Density): void {
      if (disposed) return;
      density = d;
    },
    subscribe<E extends keyof ChartEvents>(e: E, cb: (p: ChartEvents[E]) => void): Unsubscribe {
      if (disposed) return () => undefined;
      let set = listeners.get(e);
      if (set === undefined) {
        set = new Set();
        listeners.set(e, set);
      }
      const entry = cb as Listener<keyof ChartEvents>;
      set.add(entry);
      return () => {
        listeners.get(e)?.delete(entry);
      };
    },
    async takeScreenshot(): Promise<Blob> {
      if (disposed) throw new Error("chart-engine: the chart was disposed");
      const blob = await host.exportPng();
      if (blob === null) throw new Error("chart-engine: the canvas could not be encoded");
      return blob as Blob;
    },
    getStats: stats,
    getDomMirrorRoot: () => surface.mirrorRoot,
    // No data plane yet (E11-T03): nothing is visible or focused until series hold bars.
    getVisibleWindow: (): VisibleWindow | null => null,
    getFocusedUnit: (): FocusedUnit | null => null,
    dispose(): void {
      if (disposed) return;
      disposed = true;
      for (const pane of [...panes]) pane.remove();
      listeners.clear();
      detachInput();
      host.dispose();
      surface.unmount();
    },
  };
  return chart;
}

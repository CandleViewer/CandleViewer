// Chart facade (E11-T01, E11-T02). `createChart` returns synchronously; capability detection
// runs lazily on the first frame, so the React binding needs no Suspense. Rendering runs in the
// shared render runtime, in a worker or inline (`ChartOptions.runMode`, src/worker/host.ts); the
// scene graph and GL backend land in E11-S01 / E11-S02 behind this same surface.
import { mountSurface, probeRenderProfile } from "../host/mount.js";
import { type AxisStops, createAxisStops } from "../host/axis-stop.js";
import { createScaleBadge } from "../host/scale-badge.js";
import { readReducedMotion, watchMotion } from "../host/motion.js";
import { watchSize } from "../host/resize.js";
import { PRICE_GUTTER_PX } from "../scene/layout-engine.js";
import { ingestMetrics } from "../theme/ThemeIngest.js";
import {
  captureInput,
  createChartHost,
  defaultHostEnv,
  selectRunMode,
  type HostEnv,
} from "../worker/host.js";
import {
  type DegradeDetails,
  ENGINE_WORKER_LOST,
  type FromWorker,
  type RunMode,
} from "../worker/protocol.js";
import { createPane, type PaneInternal } from "./pane.js";
import { checkScaleOptions, createTimeScale } from "./scales.js";
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
  DrawingAnchor,
  DrawingBounds,
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

type ErrorDetails = NonNullable<ChartEvents["error"]["details"]>;

/** A copy per event, so a listener cannot mutate the engine's own lists (BQ-64, BQ-90). */
const copyDetails = (d: ErrorDetails | DegradeDetails): ErrorDetails =>
  "reducedCapabilities" in d
    ? { reducedCapabilities: [...d.reducedCapabilities], reason: d.reason }
    : { ...d };

type Listener<E extends keyof ChartEvents> = (p: ChartEvents[E]) => void;

/** E14-T04: flat `[time, tick, …]` pairs as §8 anchors. */
const anchorsOf = (flat: readonly number[]): DrawingAnchor[] => {
  const out: DrawingAnchor[] = [];
  for (let i = 0; i + 1 < flat.length; i += 2) {
    out.push({ time: flat[i] as number, price: flat[i + 1] as number });
  }
  return out;
};

/** E14-T04: a `[x0, y0, x1, y1]` box as a §8 `Rect`. */
const rectOf = (b: readonly number[]) => {
  const [x0 = 0, y0 = 0, x1 = 0, y1 = 0] = b;
  return { x: x0, y: y0, w: x1 - x0, h: y1 - y0 };
};

/** E14-T04: `[cx, cy, …]` handle centres as `size` px squares (the 24 px target, 2.5.8). */
const squares = (centres: readonly number[], size: number) => {
  const out = [];
  for (let i = 0; i + 1 < centres.length; i += 2) {
    const [x, y] = [centres[i] as number, centres[i + 1] as number];
    out.push({ x: x - size / 2, y: y - size / 2, w: size, h: size });
  }
  return out;
};

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
  return openChart(opts, false);
}

/**
 * Internal: `createChart` with the bench switch (README BQ-18). Only `src/api/bench.ts`, a
 * separate build entry the app never imports, passes `true` (E11-T06).
 */
export function openChart(opts: ChartOptions, bench: boolean): Chart {
  // The hard ceilings are checked up front (E11-T01 security notes: no unbounded allocation).
  positiveInt(opts.maxBars, CHART_DEFAULTS.maxBars, "maxBars");
  positiveInt(opts.memoryBudgetMb, CHART_DEFAULTS.memoryBudgetMb, "memoryBudgetMb");

  const surface = mountSurface(opts.container);
  const doc = opts.container.ownerDocument;
  const listeners = new Map<keyof ChartEvents, Set<Listener<keyof ChartEvents>>>();
  const panes: PaneInternal[] = [];
  let theme = opts.theme;
  // E14-T04 (BQ-02): resolved and range-checked first; ENGINE_THEME_INVALID names a bad field.
  let metrics = ingestMetrics(opts.theme.metrics);
  let density: Density = opts.density ?? CHART_DEFAULTS.density;
  let disposed = false;
  let paneSeq = 0;
  let renderProfile: FrameStats["renderProfile"] | null = null;
  let lastStats: FrameStats | null = null;
  let lastRange = { from: 0, to: 1 };
  let stops: AxisStops | null = null; // the axis stops (E11-S06), from the first `axes` message
  /** E14-T04: pending `getDrawingBounds` replies by reqId; resolved empty on dispose. */
  const boundsReplies = new Map<number, (items: DrawingBounds[]) => void>();
  let boundsSeq = 0;

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
        // A `ready` after a frame (a handoff, a restart) also moves the stats off the stale profile.
        if (lastStats !== null) lastStats = { ...lastStats, renderProfile: msg.renderProfile };
        return;
      case "frame":
        // The engine's own profile: a degraded-2d handoff must reach getStats() / frameStats.
        renderProfile = msg.renderProfile;
        lastStats = {
          ...stats(),
          renderProfile: msg.renderProfile,
          frameTimeMsP50: msg.frameTimeMs,
          frameTimeMsP95: msg.frameTimeMs,
          drawCalls: msg.drawCalls,
          triangles: msg.triangles,
          uploadedBytesPerSec: msg.uploadedBytes,
          lodCandles: msg.lod.candles,
          lodFootprint: msg.lod.footprint,
          gpuMemoryMbEstimate: msg.gpuMemoryMbEstimate,
        };
        emit("frameStats", lastStats);
        return;
      case "viewport":
        lastRange = { from: msg.timeStart, to: msg.timeEnd };
        timeScale.observe(lastRange);
        // The runtime lays out one pane (BQ-45): its window is the first pane's, in ticks.
        panes[0]?.priceScale.observe(
          msg.priceHigh > msg.priceLow ? { low: msg.priceLow, high: msg.priceHigh } : null,
        );
        // E11-S05 (BQ-124): the scale state; `viewportChanged` also tells of a lock (C-35).
        panes[msg.pane]?.priceScale.observeState({
          mode: msg.mode,
          requestedMode: msg.requestedMode,
          inverted: msg.inverted,
          autoScale: msg.autoScale,
          logAvailable: msg.logAvailable,
          logReason: msg.logReason,
          anchorTick: msg.anchorTick,
        });
        if (msg.pane === 0) badge.set(!msg.autoScale);
        emit("viewportChanged", {
          timeStart: msg.timeStart,
          timeEnd: msg.timeEnd,
          barSpacing: msg.barSpacing,
        });
        return;
      case "dataState":
        emit("dataState", { state: msg.state }); // BQ-9: SCR-047 is the app's
        return;
      case "error":
        emit("error", {
          code: msg.code,
          message: msg.message,
          recoverable: msg.recoverable,
          ...(msg.details && { details: copyDetails(msg.details) }),
        });
        return;
      case "axes":
        gutter.price = msg.priceGutter; // the router's regions follow the measured gutter
        // E11-S06: made with the first axes; stop names, the mirror's lists, the announcement.
        stops ??= createAxisStops(opts.container, surface.mirrorRoot, host, theme.colors, {
          now: () => env.now(),
          setTimer: (cb, ms) => env.setTimer(cb, ms),
        });
        stops.update(msg);
        return;
      case "selection":
        emit("selection", {
          ids: [...msg.ids],
          focused: msg.focused === null ? null : { id: msg.focused, handle: msg.handle },
          mode: msg.mode,
        });
        return;
      case "drawingsChanged":
        emit("drawingsChanged", {
          phase: msg.phase,
          intent: msg.intent,
          changes: msg.changes.map((c) => ({ id: c.id, anchors: anchorsOf(c.anchors) })),
        });
        return;
      case "refused":
        emit("refused", { ids: [...msg.ids], reason: msg.reason, intent: msg.intent });
        return;
      case "bounds":
        boundsReplies.get(msg.reqId)?.(
          msg.items.map((it) => ({
            id: it.id,
            rect: rectOf(it.rect),
            handles: squares(it.handles, metrics.handleTargetPx),
          })),
        );
        boundsReplies.delete(msg.reqId);
        return;
      default:
      // pick and a11y are the hit-test and live-region layers' (E11-S08 / E11-S13).
    }
  }

  const badge = createScaleBadge(
    opts.container,
    opts.theme.colors,
    () => host.command({ k: "setPriceScale", pane: 0, auto: true }),
    () => stops?.price ?? opts.container,
  );
  const env = (envOverride ?? defaultHostEnv)(doc);
  const reducedMotion = readReducedMotion(doc); // the app's resolved mode (E11-S04 BQ-104)
  const host = createChartHost({
    realm: doc,
    runMode: selectRunMode(opts.runMode, surface.canvas, doc.defaultView),
    env,
    canvas: () => surface.canvas,
    replaceCanvas: () => surface.replaceCanvas(),
    dpr: doc.defaultView?.devicePixelRatio ?? 1,
    theme: opts.theme.colors,
    syncGroup: opts.syncGroup ?? null,
    timeZone: opts.timeZone ?? CHART_DEFAULTS.timeZone,
    reducedMotion,
    ...(opts.fonts !== undefined && { fonts: opts.fonts }),
    // Bench mode (every-frame `frame`, the LOD trace, the stage marks) has no §8 option: BQ-18.
    bench,
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
  // `init` carries the colours only: `init.theme.metrics` reaches the worker as one setTheme.
  if (opts.theme.metrics !== undefined) {
    host.command({ k: "setTheme", theme: opts.theme.colors, metrics: opts.theme.metrics });
  }
  const gutter = { price: PRICE_GUTTER_PX };
  const detachInput = captureInput(opts.container, host, gutter);
  const detachSize = watchSize(opts.container, host); // BQ-146
  const detachMotion = watchMotion(doc, surface.mirrorRoot, reducedMotion, (reduce) =>
    host.command({ k: "setMotion", reduce }),
  );
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
      const scale = paneOpts.priceScale;
      if (scale !== undefined) checkScaleOptions(scale);
      paneSeq += 1;
      const pane = createPane(`pane-${paneSeq}` as PaneId, paneOpts, {
        assertLive,
        data: (store, op, layout, buffer) => host.data(store, op, layout, buffer),
        scale(id, fields): void {
          const i = panes.findIndex((p) => p.id === id);
          if (i >= 0) host.command({ k: "setPriceScale", pane: i, ...fields });
        },
        onRemoved(id: PaneId): void {
          const i = panes.findIndex((p) => p.id === id);
          if (i >= 0) panes.splice(i, 1);
        },
      });
      panes.push(pane);
      if (scale !== undefined) {
        // BQ-121: the persisted scale (mode and invert survive; the lock never does).
        const { mode, inverted, ...rest } = scale;
        if (mode !== undefined) pane.priceScale.setMode(mode);
        if (inverted !== undefined) pane.priceScale.setInverted(inverted);
        pane.priceScale.setOptions(rest);
      }
      return pane;
    },
    removePane(id: PaneId): void {
      panes.find((p) => p.id === id)?.remove();
    },
    setTheme(next: ThemeTokens): void {
      if (disposed) return;
      metrics = ingestMetrics(next.metrics); // throws before anything changes
      theme = next;
      host.command({
        k: "setTheme",
        theme: next.colors,
        ...(next.metrics !== undefined && { metrics: next.metrics }),
      });
      badge.setTheme(next.colors);
      stops?.setTheme(next.colors);
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
      // Parked, suspended (0×0, BQ-147), mid-loss or failed: `ExportUnavailableError` (code
      // ENGINE_EXPORT_UNAVAILABLE and a reason), never a blank or stale image (F-13, BQ-92).
      const blob = await host.exportPng();
      if (blob === null) throw new Error("chart-engine: the canvas could not be encoded");
      return blob as Blob;
    },
    getStats: stats,
    getDomMirrorRoot: () => surface.mirrorRoot,
    // No data plane yet (E11-T03): nothing is visible or focused until series hold bars.
    getVisibleWindow: (): VisibleWindow | null => null,
    getFocusedUnit: (): FocusedUnit | null => null,
    // E14-T04 (#359): the selection lives in the worker; each call is one command.
    setSelection(ids, op): void {
      if (!disposed) host.command({ k: "setSelection", ids: [...ids], op });
    },
    selectAll(pane?: PaneId): void {
      const i = pane === undefined ? 0 : panes.findIndex((p) => p.id === pane);
      if (!disposed && i >= 0) host.command({ k: "selectAll", pane: i });
    },
    setInteractionMode(mode, o): void {
      if (disposed) return;
      host.command({
        k: "setInteractionMode",
        mode,
        ...(o?.readOnly !== undefined && { readOnly: o.readOnly }),
      });
    },
    focusObject(id, handle): void {
      if (disposed) return;
      host.command({ k: "focusObject", drawingId: id, ...(handle !== undefined && { handle }) });
    },
    nudgeSelection(bars, ticks): void {
      if (!Number.isSafeInteger(bars) || !Number.isSafeInteger(ticks)) {
        throw new RangeError("chart-engine: a nudge is whole bars and ticks");
      }
      if (!disposed) host.command({ k: "nudgeSelection", bars, ticks });
    },
    deleteSelection(): void {
      if (!disposed) host.command({ k: "deleteSelection" });
    },
    cancelDrag(): void {
      if (!disposed) host.command({ k: "cancelDrag" });
    },
    getDrawingBounds(ids): Promise<DrawingBounds[]> {
      if (disposed) return Promise.resolve([]);
      boundsSeq += 1;
      const reqId = boundsSeq;
      return new Promise((resolve) => {
        boundsReplies.set(reqId, resolve);
        host.command({ k: "boundsOf", ids: [...ids], reqId });
      });
    },
    dispose(): void {
      if (disposed) return;
      disposed = true;
      for (const done of boundsReplies.values()) done([]);
      boundsReplies.clear();
      for (const pane of [...panes]) pane.remove();
      listeners.clear();
      detachInput();
      detachSize();
      detachMotion();
      badge.dispose();
      stops?.dispose();
      host.dispose();
      surface.unmount();
    },
  };
  return chart;
}

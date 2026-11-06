// Chart facade (E11-T01, E11-T02). `createChart` returns synchronously; capability detection
// runs lazily on the first frame, so the React binding needs no Suspense. Rendering runs in the
// shared render runtime, in a worker or inline (`ChartOptions.runMode`, src/worker/host.ts); the
// scene graph and GL backend land in E11-S01 / E11-S02 behind this same surface.
import {
  EMPTY_A11Y_WINDOW,
  readA11yUpdate,
  sameCursorWindow,
  sameView,
  type A11yUpdate,
} from "../a11y/window.js";
import { mountSurface, probeRenderProfile } from "../host/mount.js";
import { type AxisStops, createAxisStops } from "../host/axis-stop.js";
import { createScaleBadge } from "../host/scale-badge.js";
import { readReducedMotion, watchMotion } from "../host/motion.js";
import { watchSize } from "../host/resize.js";
import { PRICE_GUTTER_PX } from "../scene/layout-engine.js";
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
  A11yWindow,
  A11yWindowListener,
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

type ErrorDetails = NonNullable<ChartEvents["error"]["details"]>;

/** A copy per event, so a listener cannot mutate the engine's own lists (BQ-64, BQ-90). */
const copyDetails = (d: ErrorDetails | DegradeDetails): ErrorDetails =>
  "reducedCapabilities" in d
    ? { reducedCapabilities: [...d.reducedCapabilities], reason: d.reason }
    : { ...d };

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
  let density: Density = opts.density ?? CHART_DEFAULTS.density;
  let disposed = false;
  let paneSeq = 0;
  /** E11-S09 (BQ-1): each pane's stable wire key, minted here (0 the first, never reused). */
  const keys = new Map<PaneId, number>();
  const byKey = (key: number): PaneInternal | undefined =>
    panes.find((p) => keys.get(p.id) === key);
  const firstKey = (): number => keys.get(panes[0]?.id as PaneId) ?? 0;
  let renderProfile: FrameStats["renderProfile"] | null = null;
  let lastStats: FrameStats | null = null;
  let lastRange = { from: 0, to: 1 };
  let stops: AxisStops | null = null; // the axis stops (E11-S06), from the first `axes` message
  // E11-S13: the cache of the last `a11y` message the synchronous getters read (E06-D03 D9).
  let a11y: A11yUpdate | null = null;
  const a11yListeners = new Set<A11yWindowListener>();

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
      case "viewport": {
        lastRange = { from: msg.timeStart, to: msg.timeEnd };
        timeScale.observe(lastRange);
        // E11-S09 (BQ-5, M1): one message a frame; slot 0's row on top, slots 1.. in `panes`.
        const head = msg.panes?.find((r) => r.pane === firstKey()) ?? msg;
        for (const row of [msg, ...(msg.panes ?? [])]) {
          const pane = byKey(row.pane);
          pane?.priceScale.observe(
            row.priceHigh > row.priceLow ? { low: row.priceLow, high: row.priceHigh } : null,
          );
          // E11-S05 (BQ-124): the scale state; `viewportChanged` also tells of a lock (C-35).
          pane?.priceScale.observeState({
            mode: row.mode,
            requestedMode: row.requestedMode,
            inverted: row.inverted,
            autoScale: row.autoScale,
            logAvailable: row.logAvailable,
            logReason: row.logReason,
            anchorTick: row.anchorTick,
          });
        }
        badge.set(!head.autoScale); // the facade's first pane's row speaks for the chart
        emit("viewportChanged", {
          timeStart: msg.timeStart,
          timeEnd: msg.timeEnd,
          barSpacing: msg.barSpacing,
        });
        return;
      }
      case "layout":
        // BQ-11a rider (R58): the slots are re-mapped from this layout alone. A removal's re-key
        // (slot 0 taking the next pane's key) arrives on the layout that follows it, so no
        // handle keeps a slot the worker no longer has; a handle it does not list holds none.
        for (const p of panes) p.observeSlot(-1);
        for (let i = 0; i < msg.panes.length; i += 1) {
          const row = msg.panes[i] as (typeof msg.panes)[number];
          const pane = byKey(row.pane);
          pane?.observeShare(row.share, row.collapsed);
          pane?.observeSlot(i);
        }
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
      case "a11y": {
        const update = readA11yUpdate(msg);
        if (update === null) return; // an older worker's summary-only message: keep the cache
        const prev = a11y?.window;
        a11y = update;
        // A hover-only summary change never reaches the window's listeners (E06-D03 D6).
        const same = prev !== undefined && sameCursorWindow(prev, update.window);
        if (same && sameView(prev, update.window)) return;
        for (const cb of [...a11yListeners]) cb(update.window, null, update.origin);
        return;
      }
      default:
      // pick is the hit-test layer's (E11-S08); the cursor summary's region is E11-S13 PR-3's.
    }
  }

  const badge = createScaleBadge(
    opts.container,
    opts.theme.colors,
    () => host.command({ k: "setPriceScale", pane: firstKey(), auto: true }),
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
      const key = paneSeq - 1;
      const pane = createPane(`pane-${paneSeq}` as PaneId, paneOpts, {
        key,
        assertLive,
        data: (store, op, layout, buffer) => host.data(store, op, layout, buffer),
        scale: (_id, fields) => host.command({ k: "setPriceScale", pane: key, ...fields }),
        ratio: (_id, share) => host.command({ k: "setPaneShares", shares: [[key, share]] }),
        onRemoved(id: PaneId): void {
          const i = panes.findIndex((p) => p.id === id);
          if (i >= 0) panes.splice(i, 1);
          keys.delete(id);
          if (!disposed) host.command({ k: "removePane", pane: key });
        },
      });
      panes.push(pane);
      keys.set(pane.id, key);
      const share = paneOpts.heightRatio;
      host.command({ k: "addPane", pane: key, ...(share !== undefined && { share }) });
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
      theme = next;
      host.command({ k: "setTheme", theme: next.colors });
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
    // E11-S13: engine truth, from the worker's last `a11y` message (null while no bar is loaded).
    getA11yWindow: (): A11yWindow => a11y?.window ?? EMPTY_A11Y_WINDOW,
    onA11yWindowChange(cb: A11yWindowListener): Unsubscribe {
      if (disposed) return () => undefined;
      a11yListeners.add(cb);
      return () => {
        a11yListeners.delete(cb);
      };
    },
    getVisibleWindow(): VisibleWindow | null {
      if (a11y === null || a11y.window.viewLastBar < a11y.window.viewFirstBar) return null;
      const w = a11y.window;
      return {
        timeStart: a11y.viewTimeStart,
        timeEnd: a11y.viewTimeEnd,
        firstBarIndex: w.viewFirstBar,
        lastBarIndex: w.viewLastBar,
      };
    },
    getFocusedUnit(): FocusedUnit | null {
      const bar = a11y?.window.cursorBar ?? -1;
      const pane = panes[0];
      return bar < 0 || pane === undefined ? null : { kind: "bar", paneId: pane.id, barIndex: bar };
    },
    dispose(): void {
      if (disposed) return;
      disposed = true;
      for (const pane of [...panes]) pane.remove();
      listeners.clear();
      a11yListeners.clear();
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

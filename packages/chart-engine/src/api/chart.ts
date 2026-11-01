// Chart facade (E11-T01, E11-T02). `createChart` returns synchronously; capability detection
// runs lazily on the first frame, so the React binding needs no Suspense. Rendering runs in the
// shared render runtime, in a worker or inline (`ChartOptions.runMode`, src/worker/host.ts); the
// scene graph and GL backend land in E11-S01 / E11-S02 behind this same surface.
import { mountSurface, probeRenderProfile } from "../host/mount.js";
import {
  type AxisStops,
  createAnnouncer,
  createAxisStops,
  MAGNET_ANNOUNCE_KEY,
} from "../host/axis-stop.js";
import { createScaleBadge } from "../host/scale-badge.js";
import { readReducedMotion, watchMotion } from "../host/motion.js";
import { watchSize } from "../host/resize.js";
import { PRICE_GUTTER_PX } from "../scene/layout-engine.js";
import { DEFAULT_SYNC_MODES } from "../sync/SyncGroup.js";
import { SYNC_ANNOUNCE_KEY, syncRegistryFor, type SyncMember } from "../sync/registry.js";
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
  PANE_LABEL_MAX,
  type RunMode,
  SYNC_GROUP_MAX,
} from "../worker/protocol.js";
import { createPane, type PaneHost, type PaneInternal } from "./pane.js";
import { checkScaleOptions, createTimeScale } from "./scales.js";
import type {
  Chart,
  ChartEvents,
  ChartOptions,
  Density,
  FocusedUnit,
  FrameStats,
  MagnetMode,
  Pane,
  PaneId,
  PaneOptions,
  ReadoutEvent,
  ReadoutFieldValue,
  SyncModes,
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

const MAGNET_MODES: ReadonlySet<unknown> = new Set(["off", "weak", "strong"]);

/** E11-D02 §7.3's copy (BQ-9): what the polite announcement says. */
export const magnetText = (m: MagnetMode): string => `Crosshair magnet: ${m}`;

function magnetMode(m: unknown): MagnetMode {
  if (!MAGNET_MODES.has(m))
    throw new RangeError("chart-engine: magnetMode must be off, weak or strong");
  return m as MagnetMode;
}

type CrosshairMessage = Extract<FromWorker, { t: "crosshair" }>;

/** BQ-15: the first pane is the price pane; a later one is "Pane N" (its key + 1). */
export const paneLabelFor = (key: number): string => (key === 0 ? "Price pane" : `Pane ${key + 1}`);

function paneLabel(label: unknown, key: number): string {
  if (label === undefined) return paneLabelFor(key);
  if (typeof label !== "string" || label.length > PANE_LABEL_MAX) {
    throw new RangeError(
      `chart-engine: a pane label must be a string of at most ${PANE_LABEL_MAX}`,
    );
  }
  return label;
}

/** BQ-17: a group id the app names: a non-empty string of at most 120 characters, or null. */
function syncGroupId(g: unknown): string | null {
  if (g === null) return null;
  if (typeof g !== "string" || g.length === 0 || g.length > SYNC_GROUP_MAX) {
    throw new RangeError(
      `chart-engine: a sync group id must be a non-empty string of at most ${SYNC_GROUP_MAX}`,
    );
  }
  return g;
}

/** BQ-17: `base` with the given flags; each must be a boolean. */
function syncModes(base: SyncModes, modes: Partial<SyncModes> | undefined): SyncModes {
  const next = { ...base, ...modes };
  if (![next.time, next.crosshair, next.levels].every((v) => typeof v === "boolean")) {
    throw new RangeError("chart-engine: sync modes are booleans (time, crosshair, levels)");
  }
  return { time: next.time, crosshair: next.crosshair, levels: next.levels };
}

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
  let magnet = magnetMode(opts.magnetMode ?? "off");
  let modes = syncModes(DEFAULT_SYNC_MODES, opts.syncModes);
  const initialGroup = syncGroupId(opts.syncGroup ?? null);

  const surface = mountSurface(opts.container);
  const doc = opts.container.ownerDocument;
  const listeners = new Map<keyof ChartEvents, Set<Listener<keyof ChartEvents>>>();
  const panes: PaneInternal[] = [];
  let theme = opts.theme;
  let density: Density = opts.density ?? CHART_DEFAULTS.density;
  let disposed = false;
  let paneSeq = 0;
  let paneKeys = 0; // BQ-1: the next stable key; 0 is the first pane's, never reused
  const byKey = (key: number): PaneInternal | undefined => panes.find((p) => p.key === key);
  let renderProfile: FrameStats["renderProfile"] | null = null;
  let lastStats: FrameStats | null = null;
  let lastRange = { from: 0, to: 1 };
  let stops: AxisStops | null = null; // the axis stops (E11-S06), from the first `axes` message
  // E11-S07: the last crosshair and readout fields the worker posted, and the event's bar edge.
  let cursor: CrosshairMessage | null = null;
  let fields: readonly ReadoutFieldValue[] = [];
  let emittedBar = -1;
  let sayMagnet: ((text: string) => void) | null = null;

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
          gpuMemoryMbEstimate: msg.gpuMemoryMbEstimate,
        };
        emit("frameStats", lastStats);
        return;
      case "viewport": {
        lastRange = { from: msg.timeStart, to: msg.timeEnd };
        timeScale.observe(lastRange);
        // E11-S09 (BQ-1, BQ-5): one message per pane, addressed by its stable key.
        const target = byKey(msg.pane);
        target?.priceScale.observe(
          msg.priceHigh > msg.priceLow ? { low: msg.priceLow, high: msg.priceHigh } : null,
        );
        // E11-S05 (BQ-124): the scale state; `viewportChanged` also tells of a lock (C-35).
        target?.priceScale.observeState({
          mode: msg.mode,
          requestedMode: msg.requestedMode,
          inverted: msg.inverted,
          autoScale: msg.autoScale,
          logAvailable: msg.logAvailable,
          logReason: msg.logReason,
          anchorTick: msg.anchorTick,
        });
        if (msg.pane === (panes[0]?.key ?? 0)) badge.set(!msg.autoScale);
        emit("viewportChanged", {
          timeStart: msg.timeStart,
          timeEnd: msg.timeEnd,
          barSpacing: msg.barSpacing,
        });
        return;
      }
      case "layout":
        // BQ-4: the worker owns the shares; the facade mirrors them (BQ-11's API is pending).
        for (const box of msg.panes) {
          const pane = byKey(box.pane);
          if (pane !== undefined) pane.share = box.share;
        }
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
      case "crosshair": {
        const prev = cursor;
        cursor = msg;
        // BQ-10: the bar's edge only; a price-only move and the pointer leaving never fire.
        if (msg.visible && msg.bar !== emittedBar) {
          emittedBar = msg.bar;
          const pane = msg.pane === undefined ? undefined : byKey(msg.pane);
          emit("crosshair", {
            time: msg.time,
            price: msg.price,
            barIndex: msg.bar,
            ...(pane !== undefined && { paneId: pane.id }),
          });
        }
        // A moved bar or snap brings its `readout` next (the worker's rule): one event a frame.
        const follows = msg.visible && (prev?.bar !== msg.bar || prev?.snap !== msg.snap);
        if (!follows) emitReadout();
        return;
      }
      case "readout":
        fields = msg.fields;
        emitReadout();
        return;
      case "sync":
        registry.relay(member, msg); // BQ-21: to the group's other workers, origin kept
        return;
      default:
      // pick and a11y are the hit-test and live-region layers' (E11-S08 / E11-S13).
    }
  }

  /** BQ-11: the crosshair and the fields at its bar, on each change of either. */
  function emitReadout(): void {
    if (cursor === null) return;
    const c = cursor;
    const e: ReadoutEvent = {
      visible: c.visible,
      x: c.x,
      y: c.y,
      bar: c.bar,
      time: c.time,
      priceText: c.priceText,
      timeText: c.timeText,
      snap: c.snap,
      fields: c.visible ? fields : [], // a hidden crosshair carries no values
    };
    emit("readout", e);
  }

  const badge = createScaleBadge(
    opts.container,
    opts.theme.colors,
    () => host.command({ k: "setPriceScale", pane: panes[0]?.key ?? 0, auto: true }),
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
    syncGroup: initialGroup,
    timeZone: opts.timeZone ?? CHART_DEFAULTS.timeZone,
    reducedMotion,
    ...(opts.fonts !== undefined && { fonts: opts.fonts }),
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
  const gutter = { price: PRICE_GUTTER_PX };
  const detachInput = captureInput(opts.container, host, gutter);
  const detachSize = watchSize(opts.container, host); // BQ-146
  const detachMotion = watchMotion(doc, surface.mirrorRoot, reducedMotion, (reduce) =>
    host.command({ k: "setMotion", reduce }),
  );
  if (magnet !== "off") host.command({ k: "setCrosshair", magnetMode: magnet });
  // E11-S09 PR 2 (BQ-21): the page's registry; the chart's announcer under `chart:sync`.
  const registry = syncRegistryFor(doc);
  let saySync: ((text: string) => void) | null = null;
  const member: SyncMember = {
    get link(): object {
      return host.link;
    },
    command: (cmd) => host.command(cmd),
    sync: (groupId, payload) => host.sync(groupId, payload),
    say(text: string): void {
      saySync ??= createAnnouncer(
        opts.container,
        { now: () => env.now(), setTimer: (cb, ms) => env.setTimer(cb, ms) },
        SYNC_ANNOUNCE_KEY,
      );
      saySync(text);
    },
  };
  if (initialGroup !== null) registry.set(member, initialGroup, modes);
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
      const key = paneKeys;
      const label = paneLabel(paneOpts.label, key);
      paneKeys += 1;
      paneSeq += 1;
      const paneHost = {
        assertLive,
        data: (store, op, layout, buffer) => host.data(store, op, layout, buffer),
        scale(_id, fields): void {
          host.command({ k: "setPriceScale", pane: key, ...fields }); // BQ-1: the key
        },
        // Lens M1: the stack never drops to zero panes; dispose still removes them all.
        canRemove: (): boolean => disposed || panes.length > 1,
        resized(): void {
          // BQ-3: the whole weight vector, so the wire never carries a partial state.
          host.command({ k: "setPaneShares", shares: panes.map((p) => [p.key, p.heightRatio]) });
        },
        onRemoved(id: PaneId): void {
          const i = panes.findIndex((p) => p.id === id);
          if (i >= 0) panes.splice(i, 1);
          if (!disposed) host.command({ k: "removePane", pane: key });
        },
      } satisfies PaneHost;
      const pane = createPane(`pane-${paneSeq}` as PaneId, paneOpts, paneHost, key, label);
      panes.push(pane);
      host.command({ k: "addPane", pane: key, share: pane.heightRatio, label });
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
    setMagnetMode(m: MagnetMode): void {
      if (disposed) return;
      const next = magnetMode(m);
      if (next === magnet) return;
      magnet = next;
      host.command({ k: "setCrosshair", magnetMode: next });
      // BQ-9: through the #5322 announcer, under its own key (never the axes').
      sayMagnet ??= createAnnouncer(
        opts.container,
        { now: () => env.now(), setTimer: (cb, ms) => env.setTimer(cb, ms) },
        MAGNET_ANNOUNCE_KEY,
      );
      sayMagnet(magnetText(next));
    },
    setSyncGroup(groupId: string | null, next?: Partial<SyncModes>): void {
      if (disposed) return;
      const g = syncGroupId(groupId);
      modes = syncModes(modes, next);
      registry.set(member, g, modes);
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
    // BQ-23: a bar while a key-driven cursor is placed (key wiring is BQ-7's); null otherwise.
    getFocusedUnit(): FocusedUnit | null {
      const pane = (cursor?.pane === undefined ? undefined : byKey(cursor.pane)) ?? panes[0];
      if (cursor === null || !cursor.visible || cursor.driver !== "key" || pane === undefined) {
        return null;
      }
      const unit = { kind: "bar" as const, paneId: pane.id, barIndex: cursor.bar };
      return Number.isFinite(cursor.price) ? { ...unit, priceLevel: cursor.price } : unit;
    },
    dispose(): void {
      if (disposed) return;
      disposed = true;
      for (const pane of [...panes]) pane.remove();
      listeners.clear();
      detachInput();
      detachSize();
      detachMotion();
      badge.dispose();
      stops?.dispose();
      registry.remove(member);
      host.dispose();
      surface.unmount();
    },
  };
  return chart;
}

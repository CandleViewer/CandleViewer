// The main-thread host of the render runtime (E11-T02, 26 §2 and §6). It picks the `RunMode`,
// owns the link to the one runtime every chart on the page shares (a dedicated module worker, or
// the same runtime inline behind a synchronous bus), coalesces input / resize / sync to one
// message per frame, keeps at most two unacknowledged `data` batches per store, transfers every
// buffer, and restarts a lost worker. DOM side: this file is in tsconfig.dom.json's program.
import { probeRenderProfile } from "../host/mount.js";
import { createRenderRuntime, type RenderRuntime } from "./runtime.js";
import { createTextPlatform, type TextScope } from "./text-platform.js";
import {
  conflate,
  INPUT,
  INPUT_MAX_ROWS,
  INPUT_STRIDE,
  ENGINE_CONTEXT_RESTORE_FAILED,
  ENGINE_SHADER_COMPILE_FAILED,
  ExportUnavailableError,
  RESTART_BACKOFF_MS,
  type BufferLayout,
  type CapabilityReport,
  type ChartFont,
  type ChartId,
  type Command,
  type DataOp,
  type ExportRejectReason,
  type FromWorker,
  type InputKind,
  type PendingData,
  type RunMode,
  type StoreId,
  type ThemeLut,
  type ToWorker,
} from "./protocol.js";

/** The `Worker` members the host uses (a real one, or a test double). */
export interface WorkerLike {
  onmessage: ((ev: { data: unknown }) => void) | null;
  onerror: ((ev: unknown) => void) | null;
  onmessageerror: ((ev: unknown) => void) | null;
  postMessage(msg: unknown, transfer: Transferable[]): void;
  terminate(): void;
}

/** Everything the host takes from its realm; tests replace it (fake worker, fake clock). */
export interface HostEnv {
  createWorker(): WorkerLike;
  requestFrame(cb: () => void): void;
  /** One-shot timer; it may return its cancel (the atlas's bounded store calls use it). */
  setTimer(cb: () => void, ms: number): void | (() => void);
  now(): number;
  probe(): CapabilityReport;
  correlationId(): string;
  /**
   * Test-only (E11-T05, README BQ-94): start every chart forced to 2D over the existing
   * `init.profile`, the switch E11-Q07's GPU matrix uses. Not a §8 option, not a user setting.
   */
  readonly forceProfile?: "degraded-2d";
}

export { RESTART_BACKOFF_MS };
/** Wheel fold keys: 2 classes (zoom, pan) × 3 regions (plot, time axis, price axis), BQ-99. */
export const FOLD_KEYS = 6;
/** Unacknowledged `data` batches allowed in flight per store before conflation starts. */
export const MAX_UNACKED = 2;
/** Batches held back per store; beyond it the oldest is dropped (`messages_dropped`). */
export const MAX_QUEUED = 4;
/** A worker `ready` this long before it dies resets the restart budget (README BQ-15). */
export const HEALTHY_RESET_MS = 10_000;

export interface HostCounters {
  /** `engine.worker.messages_dropped` */ messagesDropped: number;
  /** `engine.worker.conflated` */ conflated: number;
  /** `engine.worker.restarts` */ restarts: number;
}

/** What a chart hears from its host. */
export interface HostListener {
  deliver(msg: FromWorker): void;
  /** The worker died: `final` once the restarts are spent (SCR-048 path). */
  lost(final: boolean, correlationId: string): void;
  /** A restarted worker has re-initialised this chart (scene restored, data to be re-sent). */
  restored(): void;
  /** Backpressure dropped a batch of `store`: the data layer must re-send it (one per episode). */
  resync(store: StoreId): void;
}

interface Client {
  deliver(msg: FromWorker): void;
  lost(final: boolean, correlationId: string): void;
  /** Posts `init` again (fresh canvas, current theme, viewport) on a restarted worker. */
  reinit(): void;
  /** Forgets every batch in flight or held back (counted as dropped on a restart). */
  resetFlow(restart: boolean): void;
}

interface Link {
  readonly runMode: RunMode;
  readonly counters: HostCounters;
  add(client: Client): ChartId;
  remove(id: ChartId): void;
  post(msg: ToWorker, transfer: Transferable[]): void;
}

/** Moves `buffer` into a new ArrayBuffer and detaches the original (no copy, like a transfer). */
const move = (buffer: ArrayBuffer): ArrayBuffer => structuredClone(buffer, { transfer: [buffer] });

function inlineLink(env: HostEnv, unlink: () => void): Link {
  const clients = new Map<ChartId, Client>();
  const counters: HostCounters = { messagesDropped: 0, conflated: 0, restarts: 0 };
  let seq = 0;
  const runtime: RenderRuntime = createRenderRuntime({
    runMode: "inline",
    post: (msg) => {
      if (msg.id === null) for (const c of clients.values()) c.deliver(msg);
      else clients.get(msg.id)?.deliver(msg);
    },
    requestFrame: (cb) => env.requestFrame(cb),
    now: () => env.now(),
    setTimer: (cb, ms) => env.setTimer(cb, ms),
    probe: () => env.probe(),
    text: createTextPlatform(globalThis as unknown as TextScope),
  });
  return {
    runMode: "inline",
    counters,
    add(client): ChartId {
      seq += 1;
      clients.set(seq, client);
      return seq;
    },
    remove(id): void {
      clients.delete(id);
      if (clients.size === 0) unlink();
    },
    post(msg): void {
      // Same ownership rule as a worker transfer: the sender's buffer is detached on send.
      if (msg.t === "data") msg = { ...msg, buffer: move(msg.buffer) };
      runtime.handle(msg);
    },
  };
}

function workerLink(env: HostEnv, unlink: () => void): Link {
  const clients = new Map<ChartId, Client>();
  const counters: HostCounters = { messagesDropped: 0, conflated: 0, restarts: 0 };
  let seq = 0;
  let worker: WorkerLike | null = null;
  let failures = 0;
  let restarting = false;
  let dead = false;
  let readyAt: number | null = null;

  const onMessage = (ev: { data: unknown }): void => {
    const msg = ev.data as FromWorker;
    if (msg.t === "ready") readyAt ??= env.now();
    if (msg.id === null) for (const c of clients.values()) c.deliver(msg);
    else clients.get(msg.id)?.deliver(msg);
  };

  function spawn(): void {
    const w = env.createWorker();
    w.onmessage = onMessage;
    w.onerror = onLost;
    w.onmessageerror = onLost;
    worker = w;
  }

  function onLost(): void {
    if (restarting || dead) return;
    worker?.terminate();
    worker = null;
    // Only a worker that stayed up a while earns a fresh budget: one that reaches `ready` and
    // then dies every time still runs out of restarts.
    if (readyAt !== null && env.now() - readyAt >= HEALTHY_RESET_MS) failures = 0;
    readyAt = null;
    failures += 1;
    const id = env.correlationId();
    if (failures > RESTART_BACKOFF_MS.length) {
      dead = true;
      unlink();
      for (const c of clients.values()) c.lost(true, id);
      return;
    }
    for (const c of clients.values()) c.lost(false, id);
    restarting = true;
    env.setTimer(restart, RESTART_BACKOFF_MS[failures - 1] as number);
  }

  function restart(): void {
    restarting = false;
    if (clients.size === 0) return;
    counters.restarts += 1;
    try {
      spawn();
    } catch {
      onLost();
      return;
    }
    for (const c of clients.values()) {
      c.resetFlow(true);
      c.reinit();
    }
  }

  spawn();
  return {
    runMode: "worker",
    counters,
    add(client): ChartId {
      seq += 1;
      clients.set(seq, client);
      return seq;
    },
    remove(id): void {
      clients.delete(id);
      if (clients.size > 0) return;
      worker?.terminate();
      worker = null;
      dead = true;
      unlink();
    },
    post(msg, transfer): void {
      worker?.postMessage(msg, transfer);
    },
  };
}

const links = new WeakMap<object, Map<RunMode, Link>>();

/** The one link per realm and mode: every chart in a document shares one runtime (§3.2 rule 1). */
function linkFor(realm: object, mode: RunMode, env: HostEnv): Link {
  let byMode = links.get(realm);
  if (byMode === undefined) {
    byMode = new Map();
    links.set(realm, byMode);
  }
  const known = byMode.get(mode);
  if (known !== undefined) return known;
  // A dead link unlinks itself once; its late last `remove` must not evict its successor.
  const unlink = (): void => {
    if (byMode.get(mode) === link) byMode.delete(mode);
  };
  const link = mode === "worker" ? workerLink(env, unlink) : inlineLink(env, unlink);
  byMode.set(mode, link);
  return link;
}

/**
 * `RunMode` selection (26 §2, E11-T02): `worker` when the realm has `OffscreenCanvas` and the
 * canvas can transfer its control, otherwise `inline`. `ChartOptions.runMode` overrides it;
 * asking for `worker` where it cannot run falls back to `inline` (README BQ-11).
 */
export function selectRunMode(
  requested: RunMode | undefined,
  canvas: HTMLCanvasElement,
  view: object | null,
): RunMode {
  if (requested === "inline") return "inline";
  const offscreen =
    view !== null && typeof (view as { OffscreenCanvas?: unknown }).OffscreenCanvas === "function";
  return offscreen && typeof canvas.transferControlToOffscreen === "function" ? "worker" : "inline";
}

let correlationSeq = 0;

/** The page's defaults: a same-origin bundled module worker (no `blob:` URL; E10 CSP). */
export function defaultHostEnv(doc: Document): HostEnv {
  const view = doc.defaultView;
  return {
    createWorker: () =>
      new Worker(new URL("./render-worker.js", import.meta.url), {
        type: "module",
      }) as unknown as WorkerLike,
    requestFrame: (cb) => {
      if (typeof view?.requestAnimationFrame === "function") view.requestAnimationFrame(cb);
      else setTimeout(cb, 16);
    },
    setTimer: (cb, ms) => {
      const t = setTimeout(cb, ms);
      return () => clearTimeout(t);
    },
    now: () => performance.now(),
    probe: () => probeRenderProfile(doc),
    correlationId: () => {
      correlationSeq += 1;
      const bytes = crypto.getRandomValues(new Uint8Array(6));
      const hex = Array.from(bytes, (b) => b.toString(16).padStart(2, "0")).join("");
      return `cv-${hex}-${correlationSeq}`;
    },
  };
}

export interface ChartHostOptions {
  readonly realm: object;
  readonly runMode: RunMode;
  readonly env: HostEnv;
  /** The surface's current canvas, and a fresh one after a worker loss. */
  canvas(): HTMLCanvasElement;
  replaceCanvas(): HTMLCanvasElement;
  readonly dpr: number;
  readonly theme: ThemeLut;
  readonly syncGroup: string | null;
  readonly bench: boolean;
  /** The app's resolved motion mode at mount (E11-S04 BQ-104); `setMotion` updates it. */
  readonly reducedMotion?: boolean;
  /** The design fonts (E11-S11 BQ-258); every `init` carries them, a restart's included. */
  readonly fonts?: readonly ChartFont[];
  readonly listener: HostListener;
}

export interface ChartHost {
  readonly runMode: RunMode;
  readonly counters: HostCounters;
  /**
   * Queues one packed input row; rows of a kind go out as one `input` message per frame. A row
   * with a `fold` key (0 to `FOLD_KEYS - 1`; wheel only, E11-S04 BQ-99) is summed into the
   * batch's trailing row when that row has the same key: its delta and `dt` add (in float64), its
   * x, y and modifiers are the newest. Any other key opens a row, so the order is kept.
   */
  input(
    kind: InputKind,
    row: readonly [number, number, number, number, number, number],
    fold?: number,
  ): void;
  /** Debounced to one `resize` per frame. */
  resize(width: number, height: number, dpr: number): void;
  /** Coalesced to one `sync` per frame (last wins). */
  sync(groupId: string, timeRange: readonly [number, number], crosshair: number | null): void;
  /** Hands `buffer` over (it is detached on return) under the two-in-flight rule. */
  data(
    store: StoreId,
    op: DataOp,
    layout: BufferLayout,
    buffer: ArrayBuffer,
    series?: number,
  ): void;
  command(cmd: Command): void;
  /** Resolves the PNG, or null when it cannot encode; rejects `ExportUnavailableError` (BQ-92). */
  exportPng(): Promise<unknown>;
  dispose(): void;
}

const KINDS: readonly InputKind[] = ["pointer", "wheel", "key", "touch"];
/** Codes after which a canvas that held WebGL2 must be swapped to draw in 2D (BQ-53, BQ-54). */
const HANDOFF: ReadonlySet<string> = new Set([
  ENGINE_SHADER_COMPILE_FAILED,
  ENGINE_CONTEXT_RESTORE_FAILED,
]);

/** The link for `mode`, or the inline one when a worker cannot even be created (CSP, quota). */
function linkOrInline(realm: object, mode: RunMode, env: HostEnv): Link {
  try {
    return linkFor(realm, mode, env);
  } catch (e) {
    if (mode !== "worker") throw e;
    return linkFor(realm, "inline", env);
  }
}

/** The key a retained command is replayed under after a restart (the last one per key wins). */
function retainKey(cmd: Command): string | null {
  switch (cmd.k) {
    case "setViewport":
      return "viewport";
    case "setLod":
      return "lod";
    case "setSeriesOptions":
      return `series:${cmd.series}`;
    case "addDrawing":
      return `drawing:${cmd.drawingId}`;
    default:
      return null;
  }
}

type ResizeMsg = Extract<ToWorker, { t: "resize" }>;

/** The canvas's CSS box follows the container on the main thread, in both run modes. */
function styleCanvas(canvas: HTMLCanvasElement, size: ResizeMsg): void {
  canvas.style.width = `${size.width}px`;
  canvas.style.height = `${size.height}px`;
}

export function createChartHost(o: ChartHostOptions): ChartHost {
  let link = linkOrInline(o.realm, o.runMode, o.env);
  let theme = o.theme;
  const retained = new Map<string, Command>();
  let disposed = false;
  let restoring = false;
  let flushQueued = false;
  let pendingResize: ResizeMsg | null = null;
  /** The last size sent: replayed after a restart so the restored chart keeps it. */
  let size: ResizeMsg | null = null;
  let pendingSync: ToWorker | null = null;
  const rows = new Map<InputKind, { buf: Float32Array; n: number }>();
  // The open wheel row per fold key in the pending batch (-1: none) and its float64 sums.
  const folded = new Int32Array(FOLD_KEYS).fill(-1);
  const sums = new Float64Array(FOLD_KEYS * 2);
  // E12-S06: in-flight counts, held batches and resync asks per lane, a store or one series of
  // it, so two series' batches never conflate into each other (the per-store merge gap).
  const unacked = new Map<string, number>();
  const queues = new Map<string, PendingData[]>();
  const resyncAsked = new Set<string>();
  const laneOf = (store: StoreId, series: number | undefined): string =>
    series === undefined ? store : `${store}#${series}`;
  const exports = new Map<number, (msg: { blob: unknown; reason?: ExportRejectReason }) => void>();
  let exportSeq = 0;
  /** Set once by the degraded-2d handoff and kept across worker restarts (BQ-53). */
  let forced = o.env.forceProfile !== undefined;
  /** The motion mode every `init` carries, a restart's included (not a retained command). */
  let reduce = o.reducedMotion === true;

  const init = (): void => {
    const canvas = o.canvas();
    const dpr = size?.dpr ?? o.dpr;
    const config = { bench: o.bench, syncGroup: o.syncGroup };
    const extra = {
      ...(forced && { profile: "degraded-2d" as const }),
      ...(reduce && { reducedMotion: true }),
      ...(o.fonts !== undefined && { fonts: o.fonts }),
    };
    if (link.runMode === "worker") {
      const off = canvas.transferControlToOffscreen();
      link.post({ t: "init", id, canvas: off, dpr, theme, config, ...extra }, [
        off as unknown as Transferable,
      ]);
    } else {
      link.post({ t: "init", id, canvas, dpr, theme, config, ...extra }, []);
    }
    if (size !== null) {
      styleCanvas(canvas, size);
      link.post(size, []);
    }
    for (const cmd of retained.values()) link.post({ t: "command", id, cmd }, []);
  };

  function send(store: StoreId, series: number | undefined, batch: PendingData): void {
    const lane = laneOf(store, series);
    unacked.set(lane, (unacked.get(lane) ?? 0) + 1);
    const tag = series === undefined ? {} : { series };
    link.post({ t: "data", id, store, ...batch, ...tag }, [batch.buffer]);
  }

  const settleExports = (): void => {
    for (const done of exports.values()) done({ blob: null });
    exports.clear();
  };

  const client: Client = {
    deliver(msg): void {
      if (disposed) return;
      if (msg.t === "ack") {
        const lane = laneOf(msg.store, msg.series);
        unacked.set(lane, Math.max(0, (unacked.get(lane) ?? 0) - 1));
        const queue = queues.get(lane);
        const next = queue?.shift();
        if (next !== undefined) send(msg.store, msg.series, next);
        if ((queue?.length ?? 0) === 0) resyncAsked.delete(lane);
        return;
      }
      if (msg.t === "exported") {
        exports.get(msg.reqId)?.(msg);
        exports.delete(msg.reqId);
        return;
      }
      o.listener.deliver(msg);
      if (msg.t === "error" && !forced && HANDOFF.has(msg.code)) {
        // A canvas that held WebGL2 never yields 2D: a fresh one, re-inited 2D (BQ-53, BQ-58).
        forced = true;
        o.replaceCanvas();
        init();
        return;
      }
      if (msg.t === "ready" && restoring) {
        restoring = false;
        o.listener.restored();
      }
    },
    lost: (final, cid) => {
      // No worker will answer an export again: a pending screenshot resolves null.
      if (final) settleExports();
      if (!disposed) o.listener.lost(final, cid);
    },
    reinit(): void {
      restoring = true;
      o.replaceCanvas();
      init();
    },
    resetFlow(restart): void {
      if (restart) {
        for (const q of queues.values()) link.counters.messagesDropped += q.length;
      }
      unacked.clear();
      queues.clear();
      resyncAsked.clear();
      settleExports();
    },
  };
  let id = link.add(client);
  try {
    init();
  } catch (e) {
    // The canvas would not transfer (or the worker refused it): run this chart inline instead.
    if (link.runMode !== "worker") throw e;
    link.remove(id);
    link = linkFor(o.realm, "inline", o.env);
    id = link.add(client);
    o.replaceCanvas();
    init();
  }

  /** Posts the rows held for `kind` as one `input` message and empties the batch. */
  function postRows(kind: InputKind, r: { buf: Float32Array; n: number }): void {
    const events = r.buf.slice(0, r.n * INPUT_STRIDE);
    r.n = 0;
    if (kind === "wheel") folded.fill(-1);
    link.post({ t: "input", id, kind, events }, [events.buffer]);
  }

  function flush(): void {
    flushQueued = false;
    if (disposed) return;
    if (pendingResize !== null) {
      size = pendingResize;
      styleCanvas(o.canvas(), size);
      link.post(size, []);
    }
    if (pendingSync !== null) link.post(pendingSync, []);
    pendingResize = null;
    pendingSync = null;
    for (const kind of KINDS) {
      const r = rows.get(kind);
      if (r !== undefined && r.n > 0) postRows(kind, r);
    }
  }

  const schedule = (): void => {
    if (flushQueued) return;
    flushQueued = true;
    o.env.requestFrame(flush);
  };

  return {
    runMode: link.runMode,
    counters: link.counters,
    input(kind, row, fold): void {
      if (disposed) return;
      let r = rows.get(kind);
      if (r === undefined) {
        r = { buf: new Float32Array(INPUT_STRIDE * INPUT_MAX_ROWS), n: 0 };
        rows.set(kind, r);
      }
      const key = fold !== undefined && fold >= 0 && fold < FOLD_KEYS ? fold : -1;
      const at = key < 0 ? -1 : (folded[key] as number);
      // Only the trailing row folds: a class or region change opens a row, so order is kept.
      if (at >= 0 && at === r.n - 1) {
        // Σ posted == Σ raw: summed in float64, rounded to the row's float32 once per event.
        const o = at * INPUT_STRIDE;
        sums[key * 2] = (sums[key * 2] as number) + row[3];
        sums[key * 2 + 1] = (sums[key * 2 + 1] as number) + row[5];
        r.buf.set(row, o);
        r.buf[o + 3] = sums[key * 2] as number;
        r.buf[o + 5] = sums[key * 2 + 1] as number;
        link.counters.conflated += 1;
        schedule();
        return;
      }
      if (r.n === INPUT_MAX_ROWS) {
        // A full batch folds a move into a trailing move (the newest position wins); any other
        // row (down, up, key, wheel) is never overwritten: the batch goes out early instead.
        const last = r.buf[(r.n - 1) * INPUT_STRIDE];
        if (row[0] === INPUT.move && last === INPUT.move) {
          r.n -= 1;
          link.counters.conflated += 1;
        } else postRows(kind, r);
      }
      r.buf.set(row, r.n * INPUT_STRIDE);
      if (key >= 0) {
        folded[key] = r.n;
        sums[key * 2] = row[3];
        sums[key * 2 + 1] = row[5];
      }
      r.n += 1;
      schedule();
    },
    resize(width, height, dpr): void {
      if (disposed) return;
      pendingResize = { t: "resize", id, width, height, dpr };
      schedule();
    },
    sync(groupId, timeRange, crosshair): void {
      if (disposed) return;
      pendingSync = { t: "sync", groupId, timeRange, crosshair };
      schedule();
    },
    data(store, op, layout, buffer, series): void {
      if (disposed) return;
      const batch: PendingData = { op, layout, buffer: move(buffer) };
      const lane = laneOf(store, series);
      if ((unacked.get(lane) ?? 0) < MAX_UNACKED) {
        send(store, series, batch);
        return;
      }
      let queue = queues.get(lane);
      if (queue === undefined) {
        queue = [];
        queues.set(lane, queue);
      }
      if (conflate(queue, batch)) link.counters.conflated += 1;
      if (queue.length > MAX_QUEUED) {
        queue.shift();
        link.counters.messagesDropped += 1;
        // The store now has a hole: ask the data layer to re-send it, once per overload episode.
        if (!resyncAsked.has(lane)) {
          resyncAsked.add(lane);
          o.listener.resync(store);
        }
      }
    },
    command(cmd): void {
      if (disposed) return;
      if (cmd.k === "setTheme") theme = cmd.theme;
      if (cmd.k === "setMotion") reduce = cmd.reduce;
      const key = retainKey(cmd);
      if (key !== null) {
        retained.delete(key);
        retained.set(key, cmd);
      }
      link.post({ t: "command", id, cmd }, []);
    },
    exportPng(): Promise<unknown> {
      if (disposed) return Promise.resolve(null);
      exportSeq += 1;
      const reqId = exportSeq;
      return new Promise((resolve, reject) => {
        // A refusal (F-13, BQ-92) rejects with its reason; any other miss resolves null.
        exports.set(reqId, (m) =>
          m.reason === undefined ? resolve(m.blob) : reject(new ExportUnavailableError(m.reason)),
        );
        link.post({ t: "command", id, cmd: { k: "export", reqId } }, []);
      });
    },
    dispose(): void {
      if (disposed) return;
      link.post({ t: "command", id, cmd: { k: "release" } }, []);
      disposed = true;
      client.resetFlow(false);
      link.remove(id);
    },
  };
}

// E11-S04 PR 1 (README BQ-98): the DOM half of the InputRouter moved to src/host/input-router.ts.
export { routeInput as captureInput } from "../host/input-router.js";

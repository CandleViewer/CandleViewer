// The render-worker protocol (26-chart-engine-design.md §6, E11-T02): the message envelope in
// both directions, the worker-boundary validation and the pure helpers both sides share. No DOM,
// no I/O, no exchange knowledge (C-2.16): this file compiles under tsconfig.core.json, so the
// canvas is typed structurally (an OffscreenCanvas in worker mode, the HTMLCanvasElement inline).
import type {
  CapabilityReport,
  DegradeReason,
  ReducedCapability,
  RenderProfile,
} from "../gl/capability.js";
import type { LossDetails } from "../gl/context-loss.js";
import type { AtlasDetails } from "../text/atlas.js";
import type { ChartFont } from "../text/platform.js";
import { INT32_TICKS } from "../viewport/transform.js";

export type { CapabilityReport, DegradeReason, ReducedCapability, RenderProfile };

/** `ENGINE_NO_WEBGL2`'s optional details (E11-T05, README BQ-90): codes, never prose. */
export interface DegradeDetails {
  readonly reducedCapabilities: readonly ReducedCapability[];
  readonly reason: DegradeReason;
}

/**
 * Why an export was refused (README BQ-92, F-13): no pixels can be trusted, so none are sent;
 * `suspended` while the container is 0×0 or hidden (E11-S10, BQ-148).
 */
export type ExportRejectReason = "context-lost" | "backend-failed" | "suspended";
export const ENGINE_EXPORT_UNAVAILABLE = "ENGINE_EXPORT_UNAVAILABLE";

/** `takeScreenshot`'s distinct rejection while the chart is parked (mid-loss) or failed (BQ-92). */
export class ExportUnavailableError extends Error {
  readonly code = ENGINE_EXPORT_UNAVAILABLE;
  constructor(readonly reason: ExportRejectReason) {
    super(`chart-engine: the chart cannot be exported now (${reason})`);
    this.name = "ExportUnavailableError";
  }
}

/** The token the renderer clears the canvas with (§5 rule 1: colour comes from tokens only). */
export const BACKGROUND_TOKEN = "color.chart.background";

export const ENGINE_DECODE_ERROR = "ENGINE_DECODE_ERROR";
export const ENGINE_WORKER_LOST = "ENGINE_WORKER_LOST";
// E11-S02's codes (ticket Observability), each posted with `recoverable` (README BQ-48).
// ENGINE_CONTEXT_RESTORED is informational (BQ-55): SCR-048's strip clears on it.
export const ENGINE_NO_WEBGL2 = "ENGINE_NO_WEBGL2";
export {
  ENGINE_CONTEXT_LOST,
  ENGINE_CONTEXT_RESTORE_FAILED,
  ENGINE_CONTEXT_RESTORED,
} from "../gl/context-loss.js";
export { ENGINE_SHADER_COMPILE_FAILED } from "../gl/program-cache.js";
// E11-S11's codes (BQ-272): the cache one is informational, the generation one is not.
export { ENGINE_ATLAS_CACHE_INVALID, ENGINE_ATLAS_GENERATION_FAILED } from "../text/codes.js";
export type { AtlasDetails, ChartFont };
/** Bounds on `init.fonts` (BQ-258): a few faces, each at most 8 MiB. */
export const MAX_FONTS = 4;
export const MAX_FONT_BYTES = 8 * 2 ** 20;
/** Backoff before each worker restart and each context-restore attempt: 1 / 2 / 4 s (BQ-49). */
export const RESTART_BACKOFF_MS = [1000, 2000, 4000] as const;

export type RunMode = "worker" | "inline";
/** One chart instance on the shared worker, minted by the host. */
export type ChartId = number;
/** The `DataModel` stores a `data` message can mutate (§3.3; the stores themselves are E11-T03). */
export const STORE_IDS = ["bars", "footprint", "heatmap", "profile"] as const;
export type StoreId = (typeof STORE_IDS)[number];
export type DataOp = "append" | "patch" | "prepend" | "replace";
export type InputKind = "pointer" | "wheel" | "key" | "touch";
/** Resolved colour tokens (token name to CSS colour), the theme as the renderer reads it. */
export type ThemeLut = Readonly<Record<string, string>>;

export interface ChartConfig {
  /** Bench mode posts `frame` every frame instead of sampling it at 1 Hz (§6). */
  readonly bench: boolean;
  readonly syncGroup: string | null;
}

/** One column of a columnar buffer: `count` elements of `bytes` each from `offset`. */
export interface ColumnLayout {
  readonly offset: number;
  readonly bytes: 1 | 2 | 4 | 8;
}

/**
 * How a `data` buffer is laid out: `count` elements, one column per field, plus the scalar
 * parameters of the batch (e.g. `priceOrigin`, `tickSize`). The columns must tile the buffer
 * exactly: `count × Σ bytes === buffer.byteLength`.
 */
export interface BufferLayout {
  readonly count: number;
  readonly columns: readonly ColumnLayout[];
  readonly params: readonly number[];
}

/** E11-S05's price-scale modes (BQ-118); percent and indexed draw as linear and relabel. */
export type ScaleModeName = "linear" | "log" | "percent" | "indexed";
const SCALE_MODES: ReadonlySet<unknown> = new Set(["linear", "log", "percent", "indexed"]);

/** E12-S06: the series kinds a runtime-owned `BarStore` backs (candles and OHLC bars). */
export type BarSeriesKind = "candles" | "bars";
const BAR_SERIES: ReadonlySet<unknown> = new Set(["candles", "bars"]);

/** The pointer a pick's tolerance comes from (E11-S08, BQ-130): 10 px, 16 px for touch. */
export type PickPointer = "mouse" | "pen" | "touch";
const PICK_POINTERS: ReadonlySet<unknown> = new Set(["mouse", "pen", "touch"]);

export type Command =
  | { readonly k: "setViewport"; readonly timeStart: number; readonly timeEnd: number }
  | { readonly k: "setSeriesOptions"; readonly series: number; readonly options: object }
  | { readonly k: "addDrawing"; readonly drawingId: string; readonly kind: string }
  | { readonly k: "setTheme"; readonly theme: ThemeLut }
  | { readonly k: "setLod"; readonly candles: 0 | 1 | 2; readonly footprint: 0 | 1 | 2 | 3 }
  /** The app's resolved motion mode changed (E11-S04 BQ-104): `reduce` stops a glide. */
  | { readonly k: "setMotion"; readonly reduce: boolean }
  /** E11-S08 (BQ-135, additive): `pointer` sets the tolerance (mouse by default); `reqId` echoes. */
  | {
      readonly k: "pickAt";
      readonly x: number;
      readonly y: number;
      readonly pointer?: PickPointer;
      readonly reqId?: number;
    }
  /** E11-S05 (BQ-124, additive): one pane's scale; `auto: false` is the lock. */
  | {
      readonly k: "setPriceScale";
      readonly pane: number;
      readonly mode?: ScaleModeName;
      readonly inverted?: boolean;
      readonly auto?: boolean;
      readonly includeDrawings?: boolean;
      readonly priceOnly?: boolean;
      /** Fractions of the window, each in [0, 0.45] (BQ-117). */
      readonly marginTop?: number;
      readonly marginBottom?: number;
    }
  | { readonly k: "export"; readonly reqId: number }
  /** E12-S06 (additive): a series the runtime backs with its own `BarStore`, on `pane` (0). */
  | {
      readonly k: "addSeries";
      readonly series: number;
      readonly kind: BarSeriesKind;
      readonly pane?: number;
    }
  | { readonly k: "removeSeries"; readonly series: number }
  | { readonly k: "release" };

export type ToWorker =
  | {
      readonly t: "init";
      readonly id: ChartId;
      readonly canvas: unknown;
      readonly dpr: number;
      readonly theme: ThemeLut;
      readonly config: ChartConfig;
      /** The host's handoff after a compile failure or a failed restore (BQ-53): no WebGL2. */
      readonly profile?: "degraded-2d";
      /** The app's resolved motion mode at mount (BQ-104); absent means full motion. */
      readonly reducedMotion?: boolean;
      /** The design fonts' bytes (E11-S11 BQ-258, additive): copied, never transferred. */
      readonly fonts?: readonly ChartFont[];
    }
  | {
      /** CSS px (backing / dpr, BQ-145); 0 on either axis suspends the chart (BQ-147). */
      readonly t: "resize";
      readonly id: ChartId;
      readonly width: number;
      readonly height: number;
      readonly dpr: number;
    }
  | {
      readonly t: "input";
      readonly id: ChartId;
      readonly kind: InputKind;
      readonly events: Float32Array;
    }
  | {
      readonly t: "data";
      readonly id: ChartId;
      readonly store: StoreId;
      readonly op: DataOp;
      readonly layout: BufferLayout;
      readonly buffer: ArrayBuffer;
      /** E12-S06 (additive): the `addSeries` id a `bars` batch is for; absent, nothing is stored. */
      readonly series?: number;
    }
  | { readonly t: "command"; readonly id: ChartId; readonly cmd: Command }
  | {
      readonly t: "sync";
      readonly groupId: string;
      readonly timeRange: readonly [number, number];
      readonly crosshair: number | null;
    };

export interface LodLevels {
  readonly candles: 0 | 1 | 2;
  readonly footprint: 0 | 1 | 2 | 3;
}

export type FromWorker =
  | {
      readonly t: "ready";
      readonly id: ChartId;
      readonly runMode: RunMode;
      readonly renderProfile: RenderProfile;
      /** The probe's limits and the plain-language reasons for a reduced profile (BQ-50). */
      readonly capabilities: CapabilityReport;
    }
  | {
      readonly t: "frame";
      readonly id: ChartId;
      readonly runMode: RunMode;
      readonly renderProfile: RenderProfile;
      readonly frameTimeMs: number;
      readonly drawCalls: number;
      readonly triangles: number;
      readonly uploadedBytes: number;
      /** GL buffers and textures held (BQ-59); 0 under `degraded-2d`. */
      readonly gpuMemoryMbEstimate: number;
      readonly lod: LodLevels;
      /** The ratio drawn at and the backing store `[width, height]` in device px (BQ-153). */
      readonly dpr: number;
      readonly backingStorePx: readonly [number, number];
    }
  | {
      readonly t: "pick";
      readonly id: ChartId;
      readonly objectId: string | null;
      /** The object's kind; `none` on a miss, `axis` in a gutter (BQ-136). */
      readonly kind: string;
      /** `screenToIndex` and the integer tick level under the point, on every reply. */
      readonly bar: number;
      readonly price: number;
      /** E11-S08 (BQ-136, additive): on a hit, the body or one of the object's handles. */
      readonly part?: "body" | "handle";
      readonly handle?: number;
      /** A `pickAt`'s own `reqId`; hover picks carry none. */
      readonly reqId?: number;
    }
  | {
      readonly t: "viewport";
      readonly id: ChartId;
      readonly timeStart: number;
      readonly timeEnd: number;
      readonly priceLow: number;
      readonly priceHigh: number;
      readonly barSpacing: number;
      /** E11-S05 (BQ-124, additive): the reported pane's scale state (pane 0 until E11-S09). */
      readonly pane: number;
      readonly mode: ScaleModeName;
      readonly requestedMode: ScaleModeName;
      readonly inverted: boolean;
      readonly autoScale: boolean;
      readonly logAvailable: boolean;
      /** BQ-120: why log is unavailable, a code (the UI owns the copy, C-32). */
      readonly logReason: "non-positive" | "no-price-origin" | null;
      /** Percent / indexed: the anchor bar's close in ticks; null when none. */
      readonly anchorTick: number | null;
    }
  | { readonly t: "a11y"; readonly id: ChartId; readonly cursorSummary: string }
  | {
      readonly t: "error";
      readonly id: ChartId | null;
      readonly code: string;
      readonly message: string;
      readonly recoverable: boolean;
      /** On `ENGINE_CONTEXT_LOST` (BQ-64), `ENGINE_NO_WEBGL2` (BQ-90) and
       * `ENGINE_ATLAS_GENERATION_FAILED` (BQ-272) only. */
      readonly details?: LossDetails | DegradeDetails | AtlasDetails;
    }
  // README BQ-10: §6 has no acknowledgement, which the host's backpressure needs, and no reply to
  // the `export` command; both are added in their narrowest form.
  | { readonly t: "ack"; readonly id: ChartId; readonly store: StoreId }
  | {
      readonly t: "exported";
      readonly id: ChartId;
      readonly reqId: number;
      readonly blob: unknown;
      /** Set, with a null `blob`, when the export was refused (BQ-92). */
      readonly reason?: ExportRejectReason;
    };

// ---- input packing ---------------------------------------------------------------------------

/** One packed input row: `[type, x, y, buttons, modifiers, dt]` (the ticket's layout). */
export const INPUT_STRIDE = 6;
/** Rows one `input` message may carry (a 240 Hz trackpad over a 1 s stall, rounded up). */
export const INPUT_MAX_ROWS = 256;
/**
 * Row `type` codes. A wheel row carries its folded px delta in the `buttons` slot, and its class
 * as `MOD.pan` in `modifiers` (E11-S04, BQ-99); a `touch` row carries the `pointerId` there
 * instead of buttons (BQ-102). `cancel` (pointercancel or a lost capture) ends a drag with no
 * coast; `dblclick` resets the axis it lands on; `leave` (E11-S08 G-29, a mouse or pen only)
 * clears the hover pick. Additive §6 rows: the stride stays 6.
 */
export const INPUT = {
  move: 0,
  down: 1,
  up: 2,
  wheel: 3,
  key: 4,
  cancel: 5,
  dblclick: 6,
  leave: 7,
} as const;
/**
 * Key codes a `key` row carries in its `x` slot, Shift and Ctrl in its modifiers (E11-S04 PR 2,
 * BQ-106 to BQ-109: additive; `zoomIn` and `zoomOut` are E11-T02's).
 */
export const KEY = {
  zoomIn: 1,
  zoomOut: 2,
  left: 3,
  right: 4,
  home: 5,
  end: 6,
  spaceDown: 7,
  spaceUp: 8,
} as const;

// ---- validation ------------------------------------------------------------------------------

const MAX_COUNT = 1 << 26;
const OPS: ReadonlySet<string> = new Set(["append", "patch", "prepend", "replace"]);
const KINDS: ReadonlySet<string> = new Set(["pointer", "wheel", "key", "touch"]);
const STORES: ReadonlySet<string> = new Set(STORE_IDS);
const BYTES: ReadonlySet<number> = new Set([1, 2, 4, 8]);

const isObj = (v: unknown): v is Record<string, unknown> => typeof v === "object" && v !== null;
const finite = (v: unknown): v is number => typeof v === "number" && Number.isFinite(v);
const chartId = (v: unknown): v is ChartId => Number.isSafeInteger(v) && (v as number) >= 0;
/** An OffscreenCanvas (worker) or an HTMLCanvasElement (inline), reached structurally. */
const canvasLike = (v: unknown): boolean =>
  isObj(v) && finite(v["width"]) && finite(v["height"]) && typeof v["getContext"] === "function";

/**
 * Bytes the layout's columns cover, or -1 if any column is malformed, out of range or overlaps
 * another, or if a non-empty batch has no columns. With the total equal to the buffer's length,
 * the columns tile it exactly.
 */
export function layoutBytes(layout: unknown, byteLength: number): number {
  if (!isObj(layout) || !Array.isArray(layout["columns"]) || !Array.isArray(layout["params"])) {
    return -1;
  }
  const count = layout["count"];
  if (!Number.isSafeInteger(count) || (count as number) < 0 || (count as number) > MAX_COUNT) {
    return -1;
  }
  if (!layout["params"].every(finite)) return -1;
  const cols = layout["columns"] as unknown[];
  if ((count as number) > 0 && cols.length === 0) return -1;
  const spans: [number, number][] = [];
  let total = 0;
  for (const col of cols) {
    if (!isObj(col) || !BYTES.has(col["bytes"] as number)) return -1;
    const bytes = col["bytes"] as number;
    const offset = col["offset"];
    if (!Number.isSafeInteger(offset) || (offset as number) < 0) return -1;
    const end = (offset as number) + (count as number) * bytes;
    if ((offset as number) % bytes !== 0 || end > byteLength) return -1;
    spans.push([offset as number, end]);
    total += (count as number) * bytes;
  }
  spans.sort((a, b) => a[0] - b[0]);
  for (let i = 1; i < spans.length; i += 1) {
    if ((spans[i] as [number, number])[0] < (spans[i - 1] as [number, number])[1]) return -1;
  }
  return total;
}

const optional = (v: unknown, ok: (v: unknown) => boolean): boolean => v === undefined || ok(v);
const isBool = (v: unknown): boolean => typeof v === "boolean";
const isMargin = (v: unknown): boolean => finite(v) && v >= 0 && v <= 0.45;
const seriesId = (v: unknown): boolean => Number.isSafeInteger(v) && (v as number) >= 0;

/** BQ-124: a pane index, a known mode, booleans and margins in [0, 0.45], nothing else. */
function validScale(cmd: Record<string, unknown>): boolean {
  return (
    Number.isSafeInteger(cmd["pane"]) &&
    (cmd["pane"] as number) >= 0 &&
    optional(cmd["mode"], (v) => SCALE_MODES.has(v)) &&
    ["inverted", "auto", "includeDrawings", "priceOnly"].every((f) => optional(cmd[f], isBool)) &&
    optional(cmd["marginTop"], isMargin) &&
    optional(cmd["marginBottom"], isMargin)
  );
}

function validCommand(cmd: unknown): boolean {
  if (!isObj(cmd)) return false;
  switch (cmd["k"]) {
    case "setViewport":
      return (
        finite(cmd["timeStart"]) && finite(cmd["timeEnd"]) && cmd["timeEnd"] > cmd["timeStart"]
      );
    case "setSeriesOptions":
      return Number.isSafeInteger(cmd["series"]) && isObj(cmd["options"]);
    case "addDrawing":
      return typeof cmd["drawingId"] === "string" && typeof cmd["kind"] === "string";
    case "setTheme":
      return isObj(cmd["theme"]);
    case "setLod":
      return (
        [0, 1, 2].includes(cmd["candles"] as number) &&
        [0, 1, 2, 3].includes(cmd["footprint"] as number)
      );
    case "setMotion":
      return typeof cmd["reduce"] === "boolean";
    case "pickAt":
      return (
        finite(cmd["x"]) &&
        finite(cmd["y"]) &&
        optional(cmd["pointer"], (v) => PICK_POINTERS.has(v)) &&
        optional(cmd["reqId"], Number.isSafeInteger)
      );
    case "export":
      return Number.isSafeInteger(cmd["reqId"]);
    case "setPriceScale":
      return validScale(cmd);
    case "addSeries":
      return (
        seriesId(cmd["series"]) && BAR_SERIES.has(cmd["kind"]) && optional(cmd["pane"], seriesId)
      );
    case "removeSeries":
      return seriesId(cmd["series"]);
    case "release":
      return true;
    default:
      return false;
  }
}

/**
 * `init.fonts`: at most `MAX_FONTS` faces, each a named weight over bounded bytes. Checked by the
 * runtime on its own: a bad `fonts` never rejects the init, it is ENGINE_ATLAS_GENERATION_FAILED
 * ("font-load") for that chart, which keeps rendering without text.
 */
export function fontsOk(fonts: unknown): fonts is readonly ChartFont[] {
  if (!Array.isArray(fonts) || fonts.length > MAX_FONTS) return false;
  return fonts.every(
    (f: unknown) =>
      isObj(f) &&
      typeof f["family"] === "string" &&
      f["family"].length <= 64 &&
      Number.isInteger(f["weight"]) &&
      (f["weight"] as number) >= 1 &&
      (f["weight"] as number) <= 1000 &&
      f["bytes"] instanceof ArrayBuffer &&
      f["bytes"].byteLength <= MAX_FONT_BYTES &&
      (f["version"] === undefined || typeof f["version"] === "string"),
  );
}

/**
 * Checks a message at the worker boundary before any typed-array view is made. Returns the reason
 * it is rejected, or null when it is a well-formed `ToWorker`. Never throws (E11-T02 security).
 */
export function rejectReason(msg: unknown): string | null {
  if (!isObj(msg)) return "not an object";
  const t = msg["t"];
  if (t === "sync") {
    const r = msg["timeRange"];
    const c = msg["crosshair"];
    const range = Array.isArray(r) && r.length === 2 && finite(r[0]) && finite(r[1]);
    return typeof msg["groupId"] === "string" && range && (c === null || finite(c))
      ? null
      : "malformed sync";
  }
  if (!chartId(msg["id"])) return `bad chart id in ${String(t)}`;
  switch (t) {
    case "init":
      return finite(msg["dpr"]) &&
        (msg["dpr"] as number) > 0 &&
        canvasLike(msg["canvas"]) &&
        isObj(msg["theme"]) &&
        isObj(msg["config"]) &&
        (msg["profile"] === undefined || msg["profile"] === "degraded-2d") &&
        (msg["reducedMotion"] === undefined || typeof msg["reducedMotion"] === "boolean")
        ? null
        : "malformed init";
    case "resize":
      // A 0 size is a hidden container (BQ-147, C-45); NaN, a negative size or dpr <= 0 is not.
      return [msg["width"], msg["height"]].every((v) => finite(v) && v >= 0) &&
        finite(msg["dpr"]) &&
        (msg["dpr"] as number) > 0
        ? null
        : "malformed resize";
    case "input": {
      const ev = msg["events"];
      if (!KINDS.has(msg["kind"] as string) || !(ev instanceof Float32Array))
        return "malformed input";
      if (ev.length % INPUT_STRIDE !== 0 || ev.length > INPUT_STRIDE * INPUT_MAX_ROWS) {
        return "input length is not a whole number of rows";
      }
      for (let i = 0; i < ev.length; i += 1) if (!Number.isFinite(ev[i])) return "non-finite input";
      if (msg["kind"] === "pointer") return null;
      for (let i = 0; i < ev.length; i += INPUT_STRIDE) {
        if (ev[i] === INPUT.leave) return "a leave row outside pointer input";
      }
      return null;
    }
    case "data": {
      if (!STORES.has(msg["store"] as string)) return `unknown store ${String(msg["store"])}`;
      if (!OPS.has(msg["op"] as string)) return `unknown op ${String(msg["op"])}`;
      if (!optional(msg["series"], seriesId)) return "bad series id";
      if (msg["series"] !== undefined && msg["store"] !== "bars") return "a series batch is bars";
      const buf = msg["buffer"];
      if (!(buf instanceof ArrayBuffer)) return "data without an ArrayBuffer";
      const covered = layoutBytes(msg["layout"], buf.byteLength);
      return covered === buf.byteLength ? null : "buffer length does not match its layout";
    }
    case "command":
      return validCommand(msg["cmd"]) ? null : "malformed command";
    default:
      return `unknown message kind ${String(t)}`;
  }
}

// ---- conflation (host side, pure) -------------------------------------------------------------

export interface PendingData {
  readonly op: DataOp;
  readonly layout: BufferLayout;
  readonly buffer: ArrayBuffer;
}

const sameShape = (a: BufferLayout, b: BufferLayout): boolean =>
  a.columns.length === b.columns.length &&
  a.columns.every((c, i) => c.bytes === b.columns[i]?.bytes) &&
  a.params.length === b.params.length &&
  a.params.every((p, i) => p === b.params[i]);

/** Concatenates two batches column by column (`first` then `second`) into one fresh buffer. */
export function concatBatches(first: PendingData, second: PendingData): PendingData {
  const count = first.layout.count + second.layout.count;
  const columns: ColumnLayout[] = [];
  let offset = 0;
  for (const col of first.layout.columns) {
    columns.push({ offset, bytes: col.bytes });
    offset += count * col.bytes;
  }
  const out = new Uint8Array(offset);
  first.layout.columns.forEach((col, i) => {
    const other = second.layout.columns[i] as ColumnLayout;
    const at = (columns[i] as ColumnLayout).offset;
    const a = first.layout.count * col.bytes;
    out.set(new Uint8Array(first.buffer, col.offset, a), at);
    out.set(new Uint8Array(second.buffer, other.offset, second.layout.count * col.bytes), at + a);
  });
  return {
    op: first.op,
    layout: { count, columns, params: first.layout.params },
    buffer: out.buffer,
  };
}

/**
 * Folds `next` into the queue of batches held back by backpressure (E11-T02): `replace` supersedes
 * everything queued; `patch` replaces a queued tail `patch` (last wins); `append` concatenates onto
 * a queued tail `append` and `prepend` onto a queued tail `prepend` (older history first). Returns
 * true when `next` was merged rather than queued.
 */
export function conflate(queue: PendingData[], next: PendingData): boolean {
  const tail = queue[queue.length - 1];
  if (next.op === "replace") {
    const merged = queue.length > 0;
    queue.length = 0;
    queue.push(next);
    return merged;
  }
  if (tail === undefined || tail.op !== next.op || !sameShape(tail.layout, next.layout)) {
    queue.push(next);
    return false;
  }
  if (next.op === "patch") queue[queue.length - 1] = next;
  else if (next.op === "append") queue[queue.length - 1] = concatBatches(tail, next);
  else queue[queue.length - 1] = concatBatches(next, tail);
  return true;
}

// ---- F-01: checked tick narrowing (E12-S06, threat model F-01 / CE-T04) ---------------------

/** A batch refused at the data boundary; the runtime reports it as `ENGINE_DECODE_ERROR`. */
export class DecodeError extends RangeError {
  readonly code = ENGINE_DECODE_ERROR;
  constructor(message: string) {
    super(`chart-engine: ${message}`);
    this.name = "DecodeError";
  }
}

/** Ticks live in ±2^30 so the int32 uniform bases never wrap (`INT32_TICKS`, BQ-75). */
export const TICK_WINDOW = INT32_TICKS;
/** How far from a whole tick a decimal price may land after the division (float rounding). */
const TICK_EPSILON = 1e-6;

/** The frame's own origin and tick size: finite, tickSize > 0, the whole window representable. */
export function checkTickFrame(priceOrigin: number, tickSize: number): void {
  const edge = Math.abs(priceOrigin) + TICK_WINDOW * tickSize;
  if (!Number.isFinite(priceOrigin) || !(tickSize > 0) || !Number.isFinite(edge)) {
    throw new DecodeError("priceOrigin / tickSize must be finite, tickSize > 0");
  }
}

/**
 * F-01 (BQ-10): a decimal price as whole ticks from `priceOrigin`, checked, never truncated: a
 * non-finite price, one that is not a whole tick, or one outside ±`TICK_WINDOW` throws a
 * `DecodeError`. The app's binding narrows with it; `encodeCandles` and the worker re-check.
 */
export function toTicks(price: number, priceOrigin: number, tickSize: number): number {
  checkTickFrame(priceOrigin, tickSize);
  const t = (price - priceOrigin) / tickSize;
  const r = Math.round(t);
  if (!Number.isFinite(t) || Math.abs(t - r) > TICK_EPSILON) {
    throw new DecodeError(`price ${price} is not a whole tick of ${tickSize} from ${priceOrigin}`);
  }
  if (r < -TICK_WINDOW || r > TICK_WINDOW) {
    throw new DecodeError(`price ${price} is outside the int32 tick window`);
  }
  return r === 0 ? 0 : r; // no -0
}

/** Re-check (F-01): every tick of an int32 column inside ±`TICK_WINDOW`. O(n), allocates nothing. */
function checkTickColumn(c: unknown, name: string): void {
  if (!(c instanceof Int32Array)) throw new DecodeError(`${name} must be an Int32Array of ticks`);
  for (let i = 0; i < c.length; i += 1) {
    const v = c[i] as number;
    if (v < -TICK_WINDOW || v > TICK_WINDOW) {
      throw new DecodeError(`${name}[${i}] is outside the int32 tick window`);
    }
  }
}

// ---- encoding (host side, pure) ---------------------------------------------------------------

/** The columnar arrays of a candle batch (the `CandleData` of §8, structurally). */
export interface CandleColumns {
  readonly time: Float64Array;
  readonly open: Int32Array;
  readonly high: Int32Array;
  readonly low: Int32Array;
  readonly close: Int32Array;
  readonly volume: Float32Array;
  /** E12-S06 (BQ-3): `BAR_FLAG` bits per bar, sent as a seventh, 1-byte column. */
  readonly flags?: Uint8Array | undefined;
  readonly priceOrigin: number;
  readonly tickSize: number;
}

const OHLC = ["open", "high", "low", "close"] as const;
/** The `bars` columns' widths: time, open, high, low, close, volume, then the optional flags. */
const BAR_COLUMN_BYTES = [8, 4, 4, 4, 4, 4, 1] as const;

/**
 * The `bars` buffer for a candle batch: `time, open, high, low, close, volume` columns (plus
 * `flags`, BQ-3) and the params `[priceOrigin, tickSize]`. The frame and every tick are
 * re-checked first (F-01). When the arrays are views that tile one ArrayBuffer (the decoder's
 * layout), that buffer is sent as is: zero-copy. Otherwise they are packed into a new buffer, one
 * copy (README BQ-13).
 */
export function encodeCandles(d: CandleColumns): { layout: BufferLayout; buffer: ArrayBuffer } {
  const cols: ArrayBufferView[] = [d.time, d.open, d.high, d.low, d.close, d.volume];
  if (d.flags !== undefined) cols.push(d.flags);
  const count = d.time.length;
  if (cols.some((c) => (c as Uint8Array).length !== count)) {
    throw new RangeError("chart-engine: candle columns must all have the same length");
  }
  checkTickFrame(d.priceOrigin, d.tickSize);
  for (const name of OHLC) checkTickColumn(d[name], name);
  if (d.flags !== undefined && !(d.flags instanceof Uint8Array)) {
    throw new DecodeError("flags must be a Uint8Array");
  }
  const params = [d.priceOrigin, d.tickSize];
  const shared = d.time.buffer;
  const layout = (offsets: number[]): BufferLayout => ({
    count,
    columns: cols.map((c, i) => ({
      offset: offsets[i] as number,
      bytes: BAR_COLUMN_BYTES[i] as 1 | 4 | 8,
    })),
    params,
  });
  if (shared instanceof ArrayBuffer && cols.every((c) => c.buffer === shared)) {
    const zeroCopy = layout(cols.map((c) => c.byteOffset));
    if (layoutBytes(zeroCopy, shared.byteLength) === shared.byteLength) {
      return { layout: zeroCopy, buffer: shared };
    }
  }
  const offsets: number[] = [];
  let at = 0;
  for (const c of cols) {
    offsets.push(at);
    at += c.byteLength;
  }
  const out = new Uint8Array(at);
  cols.forEach((c, i) => out.set(new Uint8Array(c.buffer, c.byteOffset, c.byteLength), offsets[i]));
  return { layout: layout(offsets), buffer: out.buffer };
}

/**
 * The worker's half (E12-S06): a `bars` buffer as typed views over it, the layout already
 * validated by `rejectReason` (aligned, in bounds, tiling the buffer). The column widths must be
 * `BAR_COLUMN_BYTES`, the params `[priceOrigin, tickSize]`, and F-01 is checked again; the bar
 * relations (F-02) are the store's. Throws `DecodeError`; one set of views per message.
 */
export function decodeBars(layout: BufferLayout, buffer: ArrayBuffer): CandleColumns {
  const { count, columns: c, params } = layout;
  const n = c.length;
  const widths = (n === 6 || n === 7) && c.every((col, i) => col.bytes === BAR_COLUMN_BYTES[i]);
  if (!widths || params.length !== 2) {
    throw new DecodeError(
      "a bars batch is time f64, open/high/low/close i32, volume f32, flags u8",
    );
  }
  const [origin, tick] = params as [number, number];
  checkTickFrame(origin, tick);
  const at = (i: number): number => (c[i] as ColumnLayout).offset;
  const d: CandleColumns = {
    time: new Float64Array(buffer, at(0), count),
    open: new Int32Array(buffer, at(1), count),
    high: new Int32Array(buffer, at(2), count),
    low: new Int32Array(buffer, at(3), count),
    close: new Int32Array(buffer, at(4), count),
    volume: new Float32Array(buffer, at(5), count),
    flags: n === 7 ? new Uint8Array(buffer, at(6), count) : undefined,
    priceOrigin: origin,
    tickSize: tick,
  };
  for (const name of OHLC) checkTickColumn(d[name], name);
  return d;
}

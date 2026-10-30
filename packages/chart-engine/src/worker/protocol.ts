// The render-worker protocol (26-chart-engine-design.md §6, E11-T02): the message envelope in
// both directions, the worker-boundary validation and the pure helpers both sides share. No DOM,
// no I/O, no exchange knowledge (C-2.16): this file compiles under tsconfig.core.json, so the
// canvas is typed structurally (an OffscreenCanvas in worker mode, the HTMLCanvasElement inline).
import type { CapabilityReport, RenderProfile } from "../gl/capability.js";

export type { CapabilityReport, RenderProfile };

/** The token the renderer clears the canvas with (§5 rule 1: colour comes from tokens only). */
export const BACKGROUND_TOKEN = "color.chart.background";

export const ENGINE_DECODE_ERROR = "ENGINE_DECODE_ERROR";
export const ENGINE_WORKER_LOST = "ENGINE_WORKER_LOST";
// E11-S02's codes (ticket Observability), each posted with `recoverable` (README BQ-48).
export const ENGINE_CONTEXT_LOST = "ENGINE_CONTEXT_LOST";
export const ENGINE_CONTEXT_RESTORE_FAILED = "ENGINE_CONTEXT_RESTORE_FAILED";
export const ENGINE_NO_WEBGL2 = "ENGINE_NO_WEBGL2";
export const ENGINE_SHADER_COMPILE_FAILED = "ENGINE_SHADER_COMPILE_FAILED";

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

export type Command =
  | { readonly k: "setViewport"; readonly timeStart: number; readonly timeEnd: number }
  | { readonly k: "setSeriesOptions"; readonly series: number; readonly options: object }
  | { readonly k: "addDrawing"; readonly drawingId: string; readonly kind: string }
  | { readonly k: "setTheme"; readonly theme: ThemeLut }
  | { readonly k: "setLod"; readonly candles: 0 | 1 | 2; readonly footprint: 0 | 1 | 2 | 3 }
  | { readonly k: "pickAt"; readonly x: number; readonly y: number }
  | { readonly k: "export"; readonly reqId: number }
  | { readonly k: "release" };

export type ToWorker =
  | {
      readonly t: "init";
      readonly id: ChartId;
      readonly canvas: unknown;
      readonly dpr: number;
      readonly theme: ThemeLut;
      readonly config: ChartConfig;
    }
  | {
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
      readonly lod: LodLevels;
    }
  | {
      readonly t: "pick";
      readonly id: ChartId;
      readonly objectId: string | null;
      readonly kind: string;
      readonly bar: number;
      readonly price: number;
    }
  | {
      readonly t: "viewport";
      readonly id: ChartId;
      readonly timeStart: number;
      readonly timeEnd: number;
      readonly priceLow: number;
      readonly priceHigh: number;
      readonly barSpacing: number;
    }
  | { readonly t: "a11y"; readonly id: ChartId; readonly cursorSummary: string }
  | {
      readonly t: "error";
      readonly id: ChartId | null;
      readonly code: string;
      readonly message: string;
      readonly recoverable: boolean;
    }
  // README BQ-10: §6 has no acknowledgement, which the host's backpressure needs, and no reply to
  // the `export` command; both are added in their narrowest form.
  | { readonly t: "ack"; readonly id: ChartId; readonly store: StoreId }
  | {
      readonly t: "exported";
      readonly id: ChartId;
      readonly reqId: number;
      readonly blob: unknown;
    };

// ---- input packing ---------------------------------------------------------------------------

/** One packed input row: `[type, x, y, buttons, modifiers, dt]` (the ticket's layout). */
export const INPUT_STRIDE = 6;
/** Rows one `input` message may carry (a 240 Hz trackpad over a 1 s stall, rounded up). */
export const INPUT_MAX_ROWS = 256;
/** Row `type` codes. A wheel row carries the pixel `deltaY` in the `buttons` slot. */
export const INPUT = { move: 0, down: 1, up: 2, wheel: 3, key: 4 } as const;
/** Key codes a `key` row carries in its `x` slot. */
export const KEY = { zoomIn: 1, zoomOut: 2 } as const;

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
    case "pickAt":
      return finite(cmd["x"]) && finite(cmd["y"]);
    case "export":
      return Number.isSafeInteger(cmd["reqId"]);
    case "release":
      return true;
    default:
      return false;
  }
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
        isObj(msg["config"])
        ? null
        : "malformed init";
    case "resize":
      return [msg["width"], msg["height"], msg["dpr"]].every((v) => finite(v) && v > 0)
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
      return null;
    }
    case "data": {
      if (!STORES.has(msg["store"] as string)) return `unknown store ${String(msg["store"])}`;
      if (!OPS.has(msg["op"] as string)) return `unknown op ${String(msg["op"])}`;
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

// ---- encoding (host side, pure) ---------------------------------------------------------------

/** The columnar arrays of a candle batch (the `CandleData` of §8, structurally). */
export interface CandleColumns {
  readonly time: Float64Array;
  readonly open: Int32Array;
  readonly high: Int32Array;
  readonly low: Int32Array;
  readonly close: Int32Array;
  readonly volume: Float32Array;
  readonly priceOrigin: number;
  readonly tickSize: number;
}

/**
 * The `bars` buffer for a candle batch: `time, open, high, low, close, volume` columns and the
 * params `[priceOrigin, tickSize]`. When the six arrays are views that tile one ArrayBuffer (the
 * decoder's layout), that buffer is sent as is: zero-copy. Otherwise they are packed into a new
 * buffer, one copy (README BQ-13).
 */
export function encodeCandles(d: CandleColumns): { layout: BufferLayout; buffer: ArrayBuffer } {
  const cols = [d.time, d.open, d.high, d.low, d.close, d.volume];
  const count = d.time.length;
  if (cols.some((c) => c.length !== count)) {
    throw new RangeError("chart-engine: candle columns must all have the same length");
  }
  const params = [d.priceOrigin, d.tickSize];
  const shared = d.time.buffer;
  const layout = (offsets: number[]): BufferLayout => ({
    count,
    columns: cols.map((c, i) => ({
      offset: offsets[i] as number,
      bytes: c.BYTES_PER_ELEMENT as 4 | 8,
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

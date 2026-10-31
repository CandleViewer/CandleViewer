// The §6 protocol at the worker boundary (E11-T02): codec round-trips, validation, conflation,
// candle encoding and the RunMode selection matrix.
import { describe, expect, it } from "vitest";
import { selectRunMode } from "../../src/worker/host.js";
import {
  concatBatches,
  conflate,
  encodeCandles,
  INPUT_MAX_ROWS,
  INPUT_STRIDE,
  layoutBytes,
  rejectReason,
  type BufferLayout,
  type PendingData,
  type ToWorker,
} from "../../src/worker/protocol.js";

const f64 = (n: number): BufferLayout => ({
  count: n,
  columns: [{ offset: 0, bytes: 8 }],
  params: [],
});

/** An OffscreenCanvas stand-in: it is transferred, never cloned, so the round trip skips it. */
const offscreen = { width: 2, height: 2, getContext: (): null => null };

const valid: ToWorker[] = [
  {
    t: "init",
    id: 1,
    canvas: offscreen,
    dpr: 2,
    theme: {},
    config: { bench: false, syncGroup: null },
  },
  { t: "resize", id: 1, width: 10, height: 10, dpr: 1 },
  { t: "input", id: 1, kind: "pointer", events: new Float32Array(INPUT_STRIDE) },
  { t: "data", id: 1, store: "bars", op: "append", layout: f64(2), buffer: new ArrayBuffer(16) },
  { t: "sync", groupId: "g", timeRange: [1, 2], crosshair: null },
  { t: "command", id: 1, cmd: { k: "setViewport", timeStart: 1, timeEnd: 2 } },
  { t: "command", id: 1, cmd: { k: "setSeriesOptions", series: 0, options: {} } },
  { t: "command", id: 1, cmd: { k: "addDrawing", drawingId: "d", kind: "trend" } },
  { t: "command", id: 1, cmd: { k: "setTheme", theme: {} } },
  { t: "command", id: 1, cmd: { k: "setLod", candles: 2, footprint: 3 } },
  { t: "command", id: 1, cmd: { k: "pickAt", x: 1, y: 2 } },
  // E11-S05 (BQ-124): every field optional but the pane.
  {
    t: "command",
    id: 1,
    cmd: { k: "setPriceScale", pane: 0, mode: "log", auto: false, marginTop: 0.45 },
  },
  { t: "command", id: 1, cmd: { k: "export", reqId: 1 } },
  { t: "command", id: 1, cmd: { k: "release" } },
];

describe("the §6 messages survive the structured-clone boundary", () => {
  it.each(valid.map((m) => [m.t === "command" ? `command ${m.cmd.k}` : m.t, m] as const))(
    "%s round-trips and validates",
    (_name, msg) => {
      const cloned: unknown =
        msg.t === "init"
          ? { ...structuredClone({ ...msg, canvas: null }), canvas: msg.canvas }
          : structuredClone(msg);
      expect(cloned).toEqual(msg);
      expect(rejectReason(cloned)).toBeNull();
    },
  );
});

describe("Scenario: A malformed message cannot kill the worker (validation)", () => {
  it("rejects a bars buffer 3 bytes shorter than its declared element count", () => {
    const msg = { ...valid[3], buffer: new ArrayBuffer(13) };
    expect(rejectReason(msg)).toBe("buffer length does not match its layout");
  });

  it.each([
    ["a non-object", 5, "not an object"],
    ["an unknown kind", { t: "explode", id: 1 }, "unknown message kind explode"],
    ["a bad chart id", { t: "resize", id: -1 }, "bad chart id in resize"],
    ["an unknown store", { ...valid[3], store: "orders" }, "unknown store orders"],
    ["an unknown op", { ...valid[3], op: "upsert" }, "unknown op upsert"],
    [
      "data without a buffer",
      { ...valid[3], buffer: new Uint8Array(16) },
      "data without an ArrayBuffer",
    ],
    [
      "a NaN coordinate",
      { ...valid[2], events: new Float32Array([0, Number.NaN, 0, 0, 0, 0]) },
      "non-finite input",
    ],
    [
      "a partial input row",
      { ...valid[2], events: new Float32Array(5) },
      "input length is not a whole number of rows",
    ],
    [
      "an oversized input batch",
      { ...valid[2], events: new Float32Array(INPUT_STRIDE * (INPUT_MAX_ROWS + 1)) },
      "input length is not a whole number of rows",
    ],
    ["an unknown input kind", { ...valid[2], kind: "gamepad" }, "malformed input"],
    ["a zero dpr", { ...valid[0], dpr: 0 }, "malformed init"],
    ["an init without a canvas", { ...valid[0], canvas: undefined }, "malformed init"],
    ["an init with a plain object", { ...valid[0], canvas: {} }, "malformed init"],
    [
      "an init canvas without getContext",
      { ...valid[0], canvas: { width: 1, height: 1, getContext: 1 } },
      "malformed init",
    ],
    [
      "an init canvas with a NaN width",
      { ...valid[0], canvas: { ...offscreen, width: Number.NaN } },
      "malformed init",
    ],
    ["a zero-width resize", { ...valid[1], width: 0 }, "malformed resize"],
    ["a bad sync", { t: "sync", groupId: "g", timeRange: [1], crosshair: null }, "malformed sync"],
    ["an unknown command", { t: "command", id: 1, cmd: { k: "eval" } }, "malformed command"],
    [
      "an inverted viewport",
      { t: "command", id: 1, cmd: { k: "setViewport", timeStart: 2, timeEnd: 1 } },
      "malformed command",
    ],
    [
      "a bad LOD",
      { t: "command", id: 1, cmd: { k: "setLod", candles: 3, footprint: 0 } },
      "malformed command",
    ],
    ...(
      [
        ["an unknown scale mode", { mode: "symlog" }],
        ["a negative pane", { pane: -1 }],
        ["a margin over 0.45", { marginBottom: 0.5 }],
        ["a NaN margin", { marginTop: Number.NaN }],
        ["a non-boolean lock", { auto: 1 }],
        ["no pane", { pane: undefined }],
      ] as const
    ).map(([name, f]): [string, object, string] => [
      `a setPriceScale with ${name}`,
      { t: "command", id: 1, cmd: { k: "setPriceScale", pane: 0, ...f } },
      "malformed command",
    ]),
  ])("rejects %s", (_name, msg, reason) => {
    expect(rejectReason(msg)).toBe(reason);
  });

  it.each([
    ["missing columns", { count: 1, params: [] }],
    ["a negative count", { count: -1, columns: [], params: [] }],
    ["a NaN param", { count: 0, columns: [], params: [Number.NaN] }],
    ["an odd column width", { count: 1, columns: [{ offset: 0, bytes: 3 }], params: [] }],
    ["a misaligned column", { count: 1, columns: [{ offset: 4, bytes: 8 }], params: [] }],
    ["a column past the end", { count: 3, columns: [{ offset: 0, bytes: 8 }], params: [] }],
    ["a negative offset", { count: 1, columns: [{ offset: -8, bytes: 8 }], params: [] }],
    ["elements but no columns", { count: 1, columns: [], params: [] }],
    [
      "overlapping columns",
      {
        count: 1,
        columns: [
          { offset: 8, bytes: 8 },
          { offset: 4, bytes: 4 },
          { offset: 8, bytes: 4 },
        ],
        params: [],
      },
    ],
  ])("a layout with %s covers nothing", (_name, layout) => {
    expect(layoutBytes(layout, 16)).toBe(-1);
  });
});

const batch = (op: PendingData["op"], values: number[]): PendingData => ({
  op,
  layout: f64(values.length),
  buffer: new Float64Array(values).buffer,
});
const values = (b: PendingData | undefined): number[] => [
  ...new Float64Array(b?.buffer ?? new ArrayBuffer(0)),
];

describe("conflation under a 3x overrun", () => {
  it("concatenates appends, keeps the last patch and lets replace supersede", () => {
    const q: PendingData[] = [];
    expect(conflate(q, batch("append", [1]))).toBe(false);
    expect(conflate(q, batch("append", [2]))).toBe(true);
    expect(conflate(q, batch("append", [3, 4]))).toBe(true);
    expect(q.map(values)).toEqual([[1, 2, 3, 4]]);
    expect(conflate(q, batch("patch", [5]))).toBe(false);
    expect(conflate(q, batch("patch", [6]))).toBe(true);
    expect(q.map(values)).toEqual([[1, 2, 3, 4], [6]]);
    expect(conflate(q, batch("replace", [7]))).toBe(true);
    expect(q.map(values)).toEqual([[7]]);
    expect(conflate([], batch("replace", [8]))).toBe(false);
  });

  it("puts older history first when prepends conflate", () => {
    const q = [batch("prepend", [3, 4])];
    expect(conflate(q, batch("prepend", [1, 2]))).toBe(true);
    expect(q.map(values)).toEqual([[1, 2, 3, 4]]);
  });

  it("never merges batches of different shapes", () => {
    const q = [batch("append", [1])];
    const other: PendingData = { ...batch("append", [2]), layout: { ...f64(1), params: [1] } };
    expect(conflate(q, other)).toBe(false);
    expect(q).toHaveLength(2);
  });

  it("concatenates column by column", () => {
    const layout = (n: number): BufferLayout => ({
      count: n,
      columns: [
        { offset: 0, bytes: 8 },
        { offset: n * 8, bytes: 4 },
      ],
      params: [],
    });
    const make = (t: number[], v: number[]): PendingData => {
      const buf = new ArrayBuffer(t.length * 12);
      new Float64Array(buf, 0, t.length).set(t);
      new Int32Array(buf, t.length * 8, v.length).set(v);
      return { op: "append", layout: layout(t.length), buffer: buf };
    };
    const out = concatBatches(make([1], [10]), make([2, 3], [20, 30]));
    expect(out.layout).toEqual(layout(3));
    expect([...new Float64Array(out.buffer, 0, 3)]).toEqual([1, 2, 3]);
    expect([...new Int32Array(out.buffer, 24, 3)]).toEqual([10, 20, 30]);
  });
});

describe("candle encoding", () => {
  it("sends one shared buffer as is (zero-copy) and packs separate columns", () => {
    const n = 4;
    const buf = new ArrayBuffer(n * 28);
    const shared = {
      time: new Float64Array(buf, 0, n),
      open: new Int32Array(buf, n * 8, n),
      high: new Int32Array(buf, n * 12, n),
      low: new Int32Array(buf, n * 16, n),
      close: new Int32Array(buf, n * 20, n),
      volume: new Float32Array(buf, n * 24, n),
      priceOrigin: 100,
      tickSize: 0.5,
    };
    const zero = encodeCandles(shared);
    expect(zero.buffer).toBe(buf);
    expect(zero.layout.params).toEqual([100, 0.5]);

    const separate = { ...shared, time: new Float64Array([1, 2, 3, 4]) };
    const packed = encodeCandles(separate);
    expect(packed.buffer).not.toBe(buf);
    expect(packed.buffer.byteLength).toBe(n * 28);
    expect([...new Float64Array(packed.buffer, 0, n)]).toEqual([1, 2, 3, 4]);
    expect(layoutBytes(packed.layout, packed.buffer.byteLength)).toBe(n * 28);
    expect(() => encodeCandles({ ...shared, open: new Int32Array(1) })).toThrow(RangeError);
  });
});

describe("RunMode selection matrix", () => {
  const canvas = (transfer: boolean): HTMLCanvasElement =>
    (transfer ? { transferControlToOffscreen: () => ({}) } : {}) as unknown as HTMLCanvasElement;
  const view = (offscreen: boolean): object => (offscreen ? { OffscreenCanvas: class {} } : {});

  it.each([
    [undefined, true, true, "worker"],
    [undefined, true, false, "inline"],
    [undefined, false, true, "inline"],
    ["worker", true, true, "worker"],
    ["worker", false, true, "inline"],
    ["inline", true, true, "inline"],
    ["inline", false, false, "inline"],
  ] as const)("requested %s, OffscreenCanvas %s, transferable %s: %s", (req, off, tr, mode) => {
    expect(selectRunMode(req, canvas(tr), view(off))).toBe(mode);
  });

  it("chooses inline without a view", () => {
    expect(selectRunMode(undefined, canvas(true), null)).toBe("inline");
  });
});

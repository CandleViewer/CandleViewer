// E11-S15 AC6 (F-08): the maxBars and memoryBudgetMb ceilings are checked on every `data` batch
// before it is applied (26 §7 "When"). A breaching batch is refused with a recoverable
// ENGINE_DECODE_ERROR, releases its backpressure slot, moves nothing and the scene keeps
// rendering. The bars cap is per batch: the store front-evicts at maxBars (26 §3.2). Plus a seeded fuzz of hostile counts and lengths over the runtime's ingest path.
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { mulberry32 } from "../../bench/fixtures/rng.mjs";
import { MAX_BARS_CEILING, MEMORY_BUDGET_CEILING_MB } from "../../src/memory/config.js";
import {
  ceilingBreach,
  createRenderRuntime,
  type RenderRuntime,
} from "../../src/worker/runtime.js";
import {
  BACKGROUND_TOKEN,
  ENGINE_DECODE_ERROR,
  ENGINE_NO_WEBGL2,
  encodeCandles,
  type CandleColumns,
  type ChartConfig,
  type FromWorker,
  type ToWorker,
} from "../../src/worker/protocol.js";
import { FakeCtx2D } from "../canvas2d/fake-ctx2d.js";
import { FULL } from "../gl/fake-gl.js";
import { THEME } from "../layers/fixtures.js";

const MIB = 2 ** 20;
let out: FromWorker[];
let rt: RenderRuntime;
const frame = (): void => {
  vi.advanceTimersByTime(16);
};
const errors = (): Extract<FromWorker, { t: "error" }>[] =>
  out.filter(
    (m): m is Extract<FromWorker, { t: "error" }> => m.t === "error" && m.code !== ENGINE_NO_WEBGL2,
  );
const acks = (): number => out.filter((m) => m.t === "ack").length;

function make(
  config: Partial<ChartConfig> = {},
  theme: Record<string, string> = { [BACKGROUND_TOKEN]: "#000000" },
): FakeCtx2D {
  const ctx = new FakeCtx2D();
  rt.handle({
    t: "init",
    id: 1,
    canvas: { width: 200, height: 100, getContext: () => ctx },
    dpr: 1,
    theme,
    config: { bench: false, syncGroup: null, ...config },
  } satisfies ToWorker);
  return ctx;
}

const T0 = 1_700_000_000_000_000;
/** `n` candles from minute 0 (time, OHLC and volume columns). */
const candles = (n: number, from = 0): CandleColumns => ({
  time: Float64Array.from({ length: n }, (_, i) => T0 + (from + i) * 60e6),
  open: Int32Array.from({ length: n }, (_, i) => from + i),
  high: Int32Array.from({ length: n }, (_, i) => from + i + 3),
  low: Int32Array.from({ length: n }, (_, i) => from + i - 2),
  close: Int32Array.from({ length: n }, (_, i) => from + i + 1),
  volume: new Float32Array(n).fill(1),
  priceOrigin: 50_000,
  tickSize: 0.1,
});

/** A bars batch of `count` 1-byte elements (the smallest buffer a count can declare). */
const bars = (op: "append" | "patch" | "prepend" | "replace", count: number): ToWorker => ({
  t: "data",
  id: 1,
  store: "bars",
  op,
  layout: { count, columns: count > 0 ? [{ offset: 0, bytes: 1 }] : [], params: [] },
  buffer: new ArrayBuffer(count),
});

beforeEach(() => {
  vi.useFakeTimers();
  out = [];
  rt = createRenderRuntime({
    runMode: "inline",
    post: (m) => out.push(m),
    requestFrame: (cb) => {
      setTimeout(cb, 16);
    },
    now: () => Date.now(),
    setTimer: (cb, ms) => {
      setTimeout(cb, ms);
    },
    probe: () => FULL,
  });
});

afterEach(() => {
  vi.useRealTimers();
});

describe("Scenario: A malformed length field cannot exhaust memory (E11-S15 AC6, F-08)", () => {
  it("refuses a bars batch above maxBars with ENGINE_DECODE_ERROR and keeps the scene rendering", () => {
    const ctx = make({ maxBars: 10 });
    rt.handle(bars("replace", 8));
    frame();
    const fills = ctx.fills.length;
    expect(errors()).toEqual([]);
    rt.handle(bars("append", 11));
    expect(errors()).toEqual([
      {
        t: "error",
        id: 1,
        code: ENGINE_DECODE_ERROR,
        message: "bars batch of 11 exceeds maxBars 10",
        recoverable: true,
      },
    ]);
    expect(acks()).toBe(2); // the backpressure slot is released
    // The cap is per batch, for every op: a batch of 11 is refused whatever it does.
    for (const op of ["prepend", "patch", "replace"] as const) rt.handle(bars(op, 11));
    expect(errors()).toHaveLength(4);
    expect(acks()).toBe(5);
    rt.handle({
      t: "command",
      id: 1,
      cmd: { k: "setTheme", theme: { [BACKGROUND_TOKEN]: "#000" } },
    });
    frame();
    expect(ctx.fills.length).toBeGreaterThan(fills); // the existing scene still renders
  });

  it("a chart at maxBars keeps taking live appends; a prepend past the cap is refused (26 §3.2)", () => {
    make({ maxBars: 10 });
    rt.handle(bars("replace", 10));
    for (let i = 0; i < 50; i += 1) rt.handle(bars("append", 1)); // the store front-evicts
    rt.handle(bars("patch", 10));
    expect(errors()).toEqual([]);
    expect(acks()).toBe(52);
    // BarStore.prepend refuses a prepend that would pass maxBars (reason "ceiling"); the count mirrors it.
    rt.handle(bars("prepend", 1));
    expect(errors().map((e) => e.message)).toEqual(["prepend would pass maxBars"]);
    expect(rt.dataRejected(1)).toEqual({ ceiling: 1 });
    expect(acks()).toBe(53);
  });

  it("the series path is checked at ingest too: a breaching batch is refused and changes nothing", () => {
    make({ maxBars: 10, memoryBudgetMb: 64 }, THEME);
    rt.handle({ t: "command", id: 1, cmd: { k: "addSeries", series: 0, kind: "candles" } });
    const send = (n: number, op: "append" | "replace", from = 0): void => {
      const { layout, buffer } = encodeCandles(candles(n, from));
      rt.handle({ t: "data", id: 1, store: "bars", op, layout, buffer, series: 0 });
    };
    send(8, "replace");
    const held = (): number | undefined => rt.series(1, 0)?.store.length;
    expect([held(), errors(), acks()]).toEqual([8, [], 1]);
    send(11, "append"); // over maxBars
    expect(errors().map((e) => e.message)).toEqual(["bars batch of 11 exceeds maxBars 10"]);
    expect(errors()[0]?.code).toBe(ENGINE_DECODE_ERROR);
    expect([held(), acks(), rt.dataRejected(1)]).toEqual([8, 2, {}]);
    send(2, "append", 8); // a compliant batch is accepted
    expect(errors()).toHaveLength(1);
    expect(acks()).toBe(3);
  });

  it("a series batch whose buffer alone exceeds memoryBudgetMb is refused and acked with its series", () => {
    make({ memoryBudgetMb: 64 }, THEME);
    rt.handle({ t: "command", id: 1, cmd: { k: "addSeries", series: 0, kind: "candles" } });
    const total = 2 ** 21 * 4 * 9; // 2^21 bars in nine 4-byte columns: within maxBars, over 64 MiB
    rt.handle({
      t: "data",
      id: 1,
      store: "bars",
      op: "append",
      layout: {
        count: 2 ** 21,
        columns: Array.from({ length: 9 }, (_, i) => ({ offset: i * 2 ** 23, bytes: 4 })),
        params: [],
      },
      buffer: new ArrayBuffer(total),
      series: 0,
    });
    expect(errors().map((e) => e.message)).toEqual([
      `data batch of ${total} bytes exceeds memoryBudgetMb 64`,
    ]);
    expect(out.filter((m) => m.t === "ack")).toEqual([
      { t: "ack", id: 1, store: "bars", series: 0 },
    ]);
    expect(rt.series(1, 0)?.store.length).toBe(0);
  });

  it("refuses any batch whose buffer alone exceeds memoryBudgetMb, for every store", () => {
    make({ memoryBudgetMb: 64 });
    for (const store of ["bars", "footprint", "heatmap", "profile"] as const) {
      rt.handle({
        t: "data",
        id: 1,
        store,
        op: "append",
        layout: { count: 32 * MIB + 1, columns: [{ offset: 0, bytes: 2 }], params: [] },
        buffer: new ArrayBuffer(64 * MIB + 2),
      });
    }
    expect(errors().map((e) => e.message)).toEqual(
      Array(4).fill(`data batch of ${64 * MIB + 2} bytes exceeds memoryBudgetMb 64`),
    );
    expect(acks()).toBe(4);
  });

  it("without the chart's values the hard ceilings hold (2^21 bars, 4096 MiB)", () => {
    make();
    rt.handle(bars("replace", MAX_BARS_CEILING));
    rt.handle(bars("append", 1));
    expect(errors()).toEqual([]);
    const cfg = { bench: false, syncGroup: null };
    expect(ceilingBreach(cfg, "bars", MAX_BARS_CEILING + 1, 8)).toBe(
      `bars batch of ${MAX_BARS_CEILING + 1} exceeds maxBars ${MAX_BARS_CEILING}`,
    );
    expect(ceilingBreach(cfg, "heatmap", 1, MEMORY_BUDGET_CEILING_MB * MIB)).toBeNull();
    expect(ceilingBreach(cfg, "heatmap", 1, MEMORY_BUDGET_CEILING_MB * MIB + 1)).toBe(
      `data batch of ${MEMORY_BUDGET_CEILING_MB * MIB + 1} bytes exceeds memoryBudgetMb 4096`,
    );
  });

  it("an init whose maxBars or memoryBudgetMb is outside its range is refused", () => {
    for (const config of [
      { maxBars: 0 },
      { maxBars: MAX_BARS_CEILING + 1 },
      { maxBars: 1.5 },
      { memoryBudgetMb: 63 },
      { memoryBudgetMb: 4097 },
      { memoryBudgetMb: Number.NaN },
    ]) {
      make(config as Partial<ChartConfig>);
      expect(errors().at(-1)).toMatchObject({ id: 1, message: "malformed init" });
    }
    expect(rt.size).toBe(0);
  });
});

describe("Scenario: fuzz over the ingest path (E11-S15 test plan, F-08)", () => {
  it("ceilingBreach fails closed on NaN, negative, fractional and huge counts and lengths", () => {
    const cfg: ChartConfig = { bench: false, syncGroup: null, maxBars: 100, memoryBudgetMb: 64 };
    const hostile = [Number.NaN, -1, -0.5, 0.5, Infinity, -Infinity, 2 ** 53, 1e300];
    for (const v of hostile) {
      expect(ceilingBreach(cfg, "bars", v, 8)).not.toBeNull();
      expect(ceilingBreach(cfg, "footprint", 1, v)).not.toBeNull();
    }
    expect(ceilingBreach(cfg, "bars", 100, 100)).toBeNull();
    expect(ceilingBreach(cfg, "footprint", 10_000, 64 * MIB)).toBeNull();
  });

  it("500 seeded hostile batches: each is refused with ENGINE_DECODE_ERROR or fits, never throws", () => {
    const ctx = make({ maxBars: 1000, memoryBudgetMb: 64 });
    const rng = mulberry32(20261102);
    const counts = [
      Number.NaN,
      -1,
      -(2 ** 31),
      0.5,
      Infinity,
      2 ** 26 + 1,
      2 ** 21,
      1001,
      999,
      0,
      1,
    ];
    const ops = ["append", "patch", "prepend", "replace"] as const;
    let expectedErrors = 0;
    let held = 0; // the bars count the runtime holds
    for (let i = 0; i < 500; i += 1) {
      const count = counts[Math.floor(rng() * counts.length)] as number;
      const op = ops[Math.floor(rng() * ops.length)] as (typeof ops)[number];
      const sane = Number.isSafeInteger(count) && count >= 0 && count <= 2 ** 22;
      const len = sane ? count : 8;
      rt.handle({
        t: "data",
        id: 1,
        store: "bars",
        op,
        layout: { count, columns: [{ offset: 0, bytes: 1 }], params: [] },
        buffer: new ArrayBuffer(len),
      });
      if (!sane || count > 1000) expectedErrors += 1;
      else if (op === "replace") held = count;
      else if (op === "append") held = Math.min(held + count, 1000);
      else if (op === "prepend") {
        // The legacy count path mirrors BarStore.prepend: past maxBars is refused.
        if (held + count > 1000) expectedErrors += 1;
        else held += count;
      }
    }
    const errs = errors();
    expect(errs.every((e) => e.code === ENGINE_DECODE_ERROR && e.recoverable)).toBe(true);
    expect(errs.length).toBe(expectedErrors);
    expect(acks()).toBe(500);
    frame();
    expect(ctx.fills.length).toBeGreaterThan(0);
  });
});

// E11-S11 PR B + E11-S06 PR 3 through the runtime: the axis labels drawn as one SDF batch, one
// draw call, measured with the atlas metrics (BQ-271); text held until the atlas is ready; a
// WebGL2 chart with no fonts at all skipped and disclosed once (`no-font`, BQ-259); the text
// uniforms set from the theme; `degraded-2d` axis labels painted with fillText (C-104).
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { proceduralPlatform, TEST_FONTS } from "../../bench/fixtures/text-platform.js";
import { AXIS_TEXT_ID } from "../../src/axes/axis-model.js";
import { columnSource } from "../../src/viewport/index.js";
import { ENGINE_ATLAS_GENERATION_FAILED, type FromWorker } from "../../src/worker/protocol.js";
import { createRenderRuntime, type RenderRuntime } from "../../src/worker/runtime.js";
import { FakeCtx2D } from "../canvas2d/fake-ctx2d.js";
import { FakeGl, FULL, ROOMY } from "../gl/fake-gl.js";
import { minuteMap } from "../interaction/fixtures.js";

type Axes = Extract<FromWorker, { t: "axes" }>;
const cols = {
  low: new Int32Array(2000).map((_, i) => 127_800 + (i % 50)),
  high: new Int32Array(2000).map((_, i) => 128_500 + (i % 50)),
  close: new Int32Array(2000).map((_, i) => 128_100 + (i % 50)),
  length: 2000,
};
const THEME = { "color.chart.background": "#0b0e11", "color.text.secondary": "#848e9c" };
let out: FromWorker[];

beforeEach(() => {
  vi.useFakeTimers();
  out = [];
});
afterEach(() => void vi.useRealTimers());

function chart(ctx: unknown, extra: object = {}): RenderRuntime {
  const rt = createRenderRuntime({
    runMode: "inline",
    post: (m) => out.push(m),
    requestFrame: (cb) => void setTimeout(cb, 16),
    now: () => Number(vi.getMockedSystemTime()),
    setTimer: (cb, ms) => void setTimeout(cb, ms),
    probe: () => FULL,
    timeMap: minuteMap(),
    priceSources: [columnSource(() => cols)],
    text: proceduralPlatform(),
  });
  const canvas = { width: 1264, height: 624, getContext: () => ctx };
  const config = { bench: true, syncGroup: null };
  rt.handle({ ...extra, t: "init", id: 1, canvas, dpr: 1, theme: THEME, config });
  const layout = { count: 0, columns: [], params: [0, 0.5] };
  const buffer = new ArrayBuffer(0);
  rt.handle({ t: "data", id: 1, store: "bars", op: "replace", layout, buffer });
  return rt;
}
const frames = (n: number): void => {
  for (let i = 0; i < n; i += 1) vi.advanceTimersByTime(16);
};
type Frame = Extract<FromWorker, { t: "frame" }>;
const lastFrame = (): Frame | undefined => out.filter((m): m is Frame => m.t === "frame").at(-1);
const lastAxes = (): Axes | undefined => out.filter((m): m is Axes => m.t === "axes").at(-1);
const noFont = (): unknown[] =>
  out.filter((m) => m.t === "error" && m.code === ENGINE_ATLAS_GENERATION_FAILED);

describe("Scenario: axis labels render as one SDF batch (E11-S06 PR 3, G-47)", () => {
  it("held until the atlas is ready, then both axes' labels in one instanced draw call", async () => {
    const gl = new FakeGl({ params: ROOMY });
    const rt = chart(gl, { fonts: TEST_FONTS });
    frames(2);
    expect([rt.textCounters(1)?.glyphs, lastFrame()?.drawCalls]).toEqual([0, 1]); // grid only
    await vi.advanceTimersByTimeAsync(300);
    frames(2);
    const ax = lastAxes();
    const chars = [...(ax?.price ?? []), ...(ax?.time ?? [])].join("").replaceAll(" ", "");
    expect(rt.textCounters(1)).toEqual({ glyphs: chars.length, replacedGlyphs: 0 });
    // The grid, then every label of both axes: one more draw (the cell and drawing batches are
    // empty, so they draw nothing).
    expect(lastFrame()?.drawCalls).toBe(2);
    const text = gl.uniforms.find(([name]) => name === "u_text");
    expect(text).toEqual(["u_text", 1, 4, 1024, 1024]); // outline px, spread, atlas size
    expect(noFont()).toEqual([]);
  });

  it("a DPR change rewrites the outline width (1 px x DPR) with no theme change", async () => {
    const gl = new FakeGl({ params: ROOMY });
    const rt = chart(gl, { fonts: TEST_FONTS });
    await vi.advanceTimersByTimeAsync(300);
    frames(2);
    rt.handle({ t: "resize", id: 1, width: 1264, height: 624, dpr: 2 });
    frames(2);
    const text = gl.uniforms.filter(([name]) => name === "u_text").at(-1);
    expect(text).toEqual(["u_text", 2, 4, 1024, 1024]);
  });

  it("the gutter is measured with the atlas metrics once ready (one metrics source, BQ-271)", async () => {
    const rt = chart(new FakeGl({ params: ROOMY }), { fonts: TEST_FONTS });
    frames(2);
    const before = lastAxes()?.priceGutter;
    await vi.advanceTimersByTimeAsync(300);
    frames(3);
    expect(rt.textCounters(1)?.glyphs).toBeGreaterThan(0);
    expect(lastAxes()?.priceGutter).toBeGreaterThanOrEqual(48);
    expect(before).toBeGreaterThanOrEqual(48);
  });

  it("no fonts at all: no text drawn, `no-font` once with the chart's id at its first text", () => {
    const rt = chart(new FakeGl({ params: ROOMY }));
    frames(10);
    expect(rt.textCounters(1)?.glyphs).toBe(0);
    expect(noFont()).toEqual([
      expect.objectContaining({ id: 1, recoverable: false, details: { atlasReason: "no-font" } }),
    ]);
  });

  it("no fonts, but the runtime's atlas came from another chart: drawn, no `no-font`", async () => {
    const rt = chart(new FakeGl({ params: ROOMY }), { fonts: TEST_FONTS });
    const canvas = { width: 1264, height: 624, getContext: () => new FakeGl({ params: ROOMY }) };
    const config = { bench: true, syncGroup: null };
    await vi.advanceTimersByTimeAsync(300);
    rt.handle({ t: "init", id: 2, canvas, dpr: 1, theme: THEME, config });
    const layout = { count: 0, columns: [], params: [0, 0.5] };
    const buffer = new ArrayBuffer(0);
    rt.handle({ t: "data", id: 2, store: "bars", op: "replace", layout, buffer });
    frames(4);
    expect(rt.textCounters(2)?.glyphs).toBeGreaterThan(0);
    expect(noFont()).toEqual([]);
  });

  it("degraded-2d: the axis labels paint with fillText from their strings", () => {
    const ctx = new FakeCtx2D();
    const rt = chart(ctx, { profile: "degraded-2d" });
    frames(4);
    const ax = lastAxes();
    const n = (ax?.price.length ?? 0) + (ax?.time.length ?? 0);
    expect(n).toBeGreaterThan(0);
    ctx.texts.length = 0;
    rt.handle({ t: "command", id: 1, cmd: { k: "setTheme", theme: { ...THEME } } });
    frames(1);
    expect(ctx.texts.length).toBeGreaterThan(0);
    expect(ctx.texts.every((t) => t.endsWith("#848e9c"))).toBe(true);
    expect(noFont()).toEqual([]);
    expect(AXIS_TEXT_ID).toBe("main/axis-text");
  });
});

// E11-S03: the zoom-at-cursor and BTC-magnitude precision scenarios. The precision half is a CPU
// stand-in (BQ-78): the bar-cell vertex shader's arithmetic is emulated with Math.fround on the
// real uniform block; the SwiftShader golden is E11-T08's (#391, README C-11).
import { describe, expect, it } from "vitest";
import { bars } from "../../bench/scenes/pan-zero-upload.js";
import { PROGRAM, ProgramCache } from "../../src/gl/program-cache.js";
import { GlRegistry } from "../../src/gl/registry.js";
import { BarStore } from "../../src/model/BarStore.js";
import {
  BAR_SPACING_MAX,
  ChartViewport,
  createPaneUniforms,
  indexToScreen,
  type PaneUniforms,
  priceToScreen,
  timeToScreen,
  writePaneUniforms,
} from "../../src/viewport/index.js";
import { FakeGl } from "../gl/fake-gl.js";

const MIN = 60e6;
const T0 = Date.UTC(2026, 10, 24) * 1000; // µs
const NOON = Date.UTC(2026, 10, 24, 12) * 1000;

describe("Scenario: Zoom keeps the point under the cursor fixed", () => {
  it("the 2026-11-24T12:00:00Z bar stays at x = 640 px through zoomAt(640, 1.25)", () => {
    const store = new BarStore();
    store.append(bars(2000, T0));
    const vp = new ChartViewport(store);
    vp.setSize(1280, 720, 1);
    vp.setTimeRange(NOON - 80 * MIN, NOON + 80 * MIN);
    expect(timeToScreen(vp, NOON)).toBe(640);
    vp.zoomAt(640, 1.25);
    expect(Math.abs(timeToScreen(vp, NOON) - 640)).toBeLessThanOrEqual(0.5);
    expect(vp.barSpacing).toBe(10);
    for (const f of [1e3, 1e-6]) {
      vp.zoomAt(640, f); // clamped into [0.05, 200]; the anchor still holds
      expect(vp.barSpacing).toBe(f > 1 ? BAR_SPACING_MAX : 0.05);
      expect(Math.abs(timeToScreen(vp, NOON) - 640)).toBeLessThanOrEqual(0.5);
    }
  });
});

const fr = Math.fround;
/** The bar-cell vertex shader at the bar's centre, in float32, back to CSS px. */
const shaderY = (tick: number, b: PaneUniforms, dpr: number): number =>
  fr(fr(fr(tick - (b.ints[1] ?? 0)) * (b.floats[1] ?? 0)) + (b.floats[2] ?? 0)) / dpr;
const shaderX = (i: number, b: PaneUniforms, dpr: number): number =>
  fr(fr(fr(fr(i - (b.ints[0] ?? 0)) + 0.5) - (b.floats[3] ?? 0)) * (b.floats[0] ?? 0)) / dpr;

describe("Scenario: Prices keep sub-tick precision at BTC magnitudes", () => {
  // tickSize 0.5 around 64 000 with priceOrigin 0: 128 001 ticks is 64 000.5.
  const HIGH = 128_001;
  const BAR = 150_000; // deep into a 100 000+ bar history
  const vp = new ChartViewport();
  vp.setSize(1280, 800, 2);
  vp.setPanePlot(0, 0, 800);
  vp.setPriceRange(0, 127_900.3, 128_100.3);
  vp.pan(-(BAR - 100) * vp.barSpacing);
  const block = createPaneUniforms();
  writePaneUniforms(vp, 0, block);

  it("a bar's high, a drawing anchored to it and an axis tick agree within 0.5 px", () => {
    const candle = shaderY(HIGH, block, vp.dpr); // the GPU path
    const drawing = priceToScreen(vp, 0, HIGH); // drawings, hit-testing, the axis (E11-S06)
    const axisTick = priceToScreen(vp, 0, 64_000.5 / 0.5);
    expect(Math.abs(candle - drawing)).toBeLessThan(0.5);
    expect(Math.abs(candle - axisTick)).toBeLessThan(0.5);
    expect(Math.abs(shaderX(BAR, block, vp.dpr) - indexToScreen(vp, BAR))).toBeLessThan(0.5);
    // The DOM mirror's surrogate (E11-S13) is placed by the same calls: its box tops the candle.
    const mirror = { top: priceToScreen(vp, 0, HIGH), left: indexToScreen(vp, BAR) - 3 };
    expect(Math.abs(mirror.top - candle)).toBeLessThan(0.5);
    expect(mirror.left + 3).toBe(indexToScreen(vp, BAR));
  });

  it("no float32 the GPU receives holds the absolute price or bar index", () => {
    const gl = new FakeGl();
    const programs = new ProgramCache(gl, new GlRegistry(gl));
    programs.bind(PROGRAM.barCell);
    programs.setUniforms(PROGRAM.barCell, block);
    expect(gl.uniforms.map((u) => u[0])).toEqual([
      "u_indexBase",
      "u_tickBase",
      "u_k",
      "u_viewport",
      "u_log", // E11-S05: [0, 0] under linear (BQ-113)
    ]);
    const floats = gl.uniforms.slice(2).flatMap((u) => u.slice(1));
    expect(floats.every((v) => Math.abs(v as number) < 4096)).toBe(true);
    expect(gl.uniforms.slice(0, 2)).toEqual([
      ["u_indexBase", Math.floor(vp.leftIndex)],
      ["u_tickBase", 127_900], // exact ints
    ]);
  });

  it("tick indices above 2^24 stay within 0.5 px where the old float path is off by >= 1 px", () => {
    // tickSize 0.001: 64 000.501 is 64 000 501 ticks, past float32's exact integers.
    const HI = 64_000_501;
    const LOW = 64_000_400.3;
    const DEEP = 2 ** 24 + 1;
    expect(fr(HI)).not.toBe(HI);
    const v = new ChartViewport();
    v.setSize(1280, 800, 1);
    v.setPanePlot(0, 0, 800);
    v.setPriceRange(0, LOW, 64_000_600.3); // 200 ticks over 800 px: 4 px a tick
    v.pan(-(DEEP - 100) * v.barSpacing);
    const b = createPaneUniforms();
    writePaneUniforms(v, 0, b);
    const y = priceToScreen(v, 0, HI);
    expect(Math.abs(shaderY(HI, b, 1) - y)).toBeLessThan(0.5);
    expect(Math.abs(shaderX(DEEP, b, 1) - indexToScreen(v, DEEP))).toBeLessThan(0.5);
    const oldFloatPath = fr(fr(fr(HI) - fr(LOW)) * -4) + 800; // the former u_priceOrigin maths
    expect(Math.abs(oldFloatPath - y)).toBeGreaterThanOrEqual(1);
  });

  it.todo(
    "Integration: a candle, a drawing on its high and an axis tick render within 0.5 px " +
      "in a golden image, with the mirror node's box (E11-T08, #391; README C-11)",
  );
});

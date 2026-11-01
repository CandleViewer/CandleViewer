// E11-S11 PR A: the runtime's atlas wiring — one CPU atlas per runtime uploaded into each chart's
// context (BQ-277), a DPR change never regenerates (K01 BQ-175), the codes broadcast once and
// repeated to a chart that opens later, no build for a 2D chart, `init.fonts` validated on its own
// (a bad option never rejects the init, BQ-258), and the faces released with the last chart.
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { proceduralPlatform, TEST_FONTS } from "../../bench/fixtures/text-platform.js";
import { GL } from "../../src/gl/gl-types.js";
import {
  ENGINE_ATLAS_GENERATION_FAILED,
  fontsOk,
  MAX_FONT_BYTES,
  MAX_FONTS,
  rejectReason,
} from "../../src/worker/protocol.js";
import { codes, frames, lossCanvas, roomyGl, runtimeOnFakeClock } from "../chaos/harness.js";

beforeEach(() => {
  vi.useFakeTimers();
  vi.setSystemTime(0);
});
afterEach(() => void vi.useRealTimers());

const images = (gl: ReturnType<typeof roomyGl>) =>
  gl.textures.filter((t) => t === `image ${GL.R8} 1024x1024`).length;

describe("the runtime's SDF atlas (E11-S11 PR A)", () => {
  it("two charts: the atlas is built once and uploaded into each context once", async () => {
    const text = proceduralPlatform();
    const { rt, out, init } = runtimeOnFakeClock("inline", text);
    const [a, b] = [roomyGl(), roomyGl()];
    init(lossCanvas(a), 1, { fonts: TEST_FONTS });
    frames(16); // chart 1's backend opens before the atlas is ready
    await vi.advanceTimersByTimeAsync(200);
    init(lossCanvas(b), 2, { fonts: TEST_FONTS }); // chart 2's opens after: uploaded on open
    await vi.advanceTimersByTimeAsync(200);
    expect([images(a), images(b), text.rasters, codes(out)]).toEqual([1, 1, 194, []]);
    expect(rt.atlasCounters()).toMatchObject({ cacheHit: false });
    expect(rt.atlasCounters()?.occupancyPct).toBeGreaterThan(0);
  });

  it("a DPR change re-scales and never regenerates or re-uploads the atlas", async () => {
    const text = proceduralPlatform();
    const { rt, init } = runtimeOnFakeClock("inline", text);
    const gl = roomyGl();
    init(lossCanvas(gl), 1, { fonts: TEST_FONTS });
    await vi.advanceTimersByTimeAsync(200);
    rt.handle({ t: "resize", id: 1, width: 200, height: 100, dpr: 2 });
    await vi.advanceTimersByTimeAsync(200);
    expect([text.rasters, images(gl), rt.resizeCounters(1)?.dprChanges]).toEqual([194, 1, 1]);
  });

  it("no fonts passed: no atlas; a missing family: GENERATION_FAILED once, to every chart", async () => {
    const { rt, out, init } = runtimeOnFakeClock("inline", proceduralPlatform());
    init(lossCanvas(roomyGl()), 1);
    await vi.advanceTimersByTimeAsync(100);
    expect(rt.atlasCounters()).toBeNull();
    init(lossCanvas(roomyGl()), 2, { fonts: TEST_FONTS.slice(1) });
    init(lossCanvas(roomyGl()), 3, { fonts: TEST_FONTS.slice(1) });
    await vi.advanceTimersByTimeAsync(100);
    const errors = out.filter((m) => m.t === "error");
    expect(errors).toEqual([
      expect.objectContaining({
        id: null,
        code: ENGINE_ATLAS_GENERATION_FAILED,
        recoverable: false,
        details: { atlasReason: "no-font" },
      }),
    ]);
  });

  it("a chart that opens after the atlas failed is told too, with its own id", async () => {
    const { out, init } = runtimeOnFakeClock("inline", proceduralPlatform());
    init(lossCanvas(roomyGl()), 1, { fonts: TEST_FONTS.slice(1) });
    await vi.advanceTimersByTimeAsync(100);
    init(lossCanvas(roomyGl()), 2);
    await vi.advanceTimersByTimeAsync(100);
    const failed = out.flatMap((m) =>
      m.t === "error" && m.code === ENGINE_ATLAS_GENERATION_FAILED ? [[m.id, m.details]] : [],
    );
    const details = { atlasReason: "no-font" };
    expect(failed).toEqual([
      [null, details],
      [2, details],
    ]);
  });

  it("a degraded-2d chart never builds the atlas", async () => {
    const text = proceduralPlatform();
    const { rt, out, init } = runtimeOnFakeClock("inline", text);
    init(lossCanvas(null), 1, { fonts: TEST_FONTS });
    await vi.advanceTimersByTimeAsync(200);
    expect([text.loads, text.rasters, rt.atlasCounters()]).toEqual([0, 0, null]);
    expect(out.some((m) => m.t === "frame")).toBe(true);
  });

  it("a malformed fonts option: the chart still renders, GENERATION_FAILED for it alone", async () => {
    const text = proceduralPlatform();
    const { out, init } = runtimeOnFakeClock("inline", text);
    const fonts = [{ ...TEST_FONTS[0], bytes: new ArrayBuffer(MAX_FONT_BYTES + 1) }];
    init(lossCanvas(roomyGl()), 1, { fonts });
    await vi.advanceTimersByTimeAsync(200);
    expect(out.filter((m) => m.t === "error")).toEqual([
      expect.objectContaining({
        id: 1,
        code: ENGINE_ATLAS_GENERATION_FAILED,
        recoverable: false,
        details: { atlasReason: "font-load" },
      }),
    ]);
    expect([out.some((m) => m.t === "frame"), text.loads]).toEqual([true, 0]);
  });

  it("releasing the last chart disposes the atlas: its faces leave the font set", async () => {
    const text = proceduralPlatform();
    const { rt, out, init } = runtimeOnFakeClock("inline", text);
    const gl = roomyGl();
    const raster = text.rasterize.bind(text);
    text.rasterize = (...a) => {
      // The app releases the chart while the mono task runs (the faces are loaded by then).
      if (text.rasters === 0) rt.handle({ t: "command", id: 1, cmd: { k: "release" } });
      return raster(...a);
    };
    init(lossCanvas(gl), 1, { fonts: TEST_FONTS });
    await vi.advanceTimersByTimeAsync(400);
    expect([text.loads, text.releases, rt.atlasCounters()]).toEqual([2, 2, null]);
    expect(text.rasters).toBeLessThan(194); // the ui task never ran
    expect([images(gl), codes(out)]).toEqual([0, []]);
  });

  it("init.fonts is checked on its own: never a reason to reject the init", () => {
    const base = { t: "init", id: 1, canvas: lossCanvas(null), dpr: 1, theme: {}, config: {} };
    const font = TEST_FONTS[0];
    expect(fontsOk(TEST_FONTS)).toBe(true);
    const bad = [
      "x",
      Array.from({ length: MAX_FONTS + 1 }, () => font),
      [{ ...font, family: 3 }],
      [{ ...font, family: "x".repeat(65) }],
      [{ ...font, weight: 0 }],
      [{ ...font, weight: 1.5 }],
      [{ ...font, bytes: new Uint8Array(4) }],
      [{ ...font, bytes: new ArrayBuffer(MAX_FONT_BYTES + 1) }],
      [{ ...font, version: 2 }],
      [null],
    ];
    for (const fonts of bad) {
      expect(fontsOk(fonts)).toBe(false);
      expect(rejectReason({ ...base, fonts })).toBeNull();
    }
  });
});

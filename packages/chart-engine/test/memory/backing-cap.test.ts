// E11-S15 PR-2a, F-12: the pure backing-store cap (26 §6, §11; BQ-P2-06/07). The GL axis limit is
// min(MAX_TEXTURE_SIZE, MAX_RENDERBUFFER_SIZE, MAX_VIEWPORT_DIMS); Canvas2D uses the browser caps.
import { describe, expect, it } from "vitest";
import { mulberry32 } from "../../bench/fixtures/rng.mjs";
import {
  CANVAS2D_MAX_AREA_PX,
  CANVAS2D_MAX_SIDE_PX,
  capBackingStore,
  type GlBackingLimits,
} from "../../src/memory/backing-cap.js";

const gl = (tex: number, rb: number, vw: number, vh: number): GlBackingLimits => ({
  maxTextureSize: tex,
  maxRenderbufferSize: rb,
  maxViewportDims: [vw, vh],
});

describe("Scenario: the backing store is capped to the probed limits (F-12)", () => {
  it("passes a size within every limit through unclamped", () => {
    expect(capBackingStore(3840, 2160, gl(16384, 16384, 16384, 16384))).toEqual({
      width: 3840,
      height: 2160,
      clamped: false,
    });
  });

  it("caps each axis at the smallest of texture, renderbuffer and viewport limits", () => {
    expect(capBackingStore(20_000, 9000, gl(16384, 8192, 32767, 32767))).toEqual({
      width: 8192,
      height: 8192,
      clamped: true,
    });
    expect(capBackingStore(5000, 5000, gl(16384, 16384, 4096, 2048))).toEqual({
      width: 4096,
      height: 2048,
      clamped: true,
    });
    expect(capBackingStore(4096, 2048, gl(4096, 4096, 4096, 2048)).clamped).toBe(false);
  });

  it("treats a missing or hostile probe value as a 1 px limit, never as no limit", () => {
    for (const bad of [Number.NaN, 0, -5, -Infinity]) {
      expect(capBackingStore(800, 600, gl(bad, 4096, 4096, 4096))).toEqual({
        width: 1,
        height: 1,
        clamped: true,
      });
    }
    expect(capBackingStore(800, 600, gl(Infinity, 4096, 4096, 4096)).width).toBe(1);
  });

  it("keeps a hidden container's 0 side and floors fractional or hostile requests", () => {
    expect(capBackingStore(0, 0, gl(4096, 4096, 4096, 4096))).toEqual({
      width: 0,
      height: 0,
      clamped: false,
    });
    expect(capBackingStore(10.9, Number.NaN, null)).toEqual({
      width: 10,
      height: 0,
      clamped: false,
    });
    expect(capBackingStore(-1, Infinity, null)).toEqual({ width: 0, height: 0, clamped: false });
  });
});

describe("Scenario: the Canvas2D backend has its own cap (BQ-P2-06)", () => {
  it("the caps are 32,767 px per axis and 16,384^2 px of area", () => {
    expect([CANVAS2D_MAX_SIDE_PX, CANVAS2D_MAX_AREA_PX]).toEqual([32_767, 16_384 ** 2]);
  });

  it("caps each axis, then the area, keeping the aspect ratio", () => {
    expect(capBackingStore(40_000, 100, null)).toEqual({
      width: 32_767,
      height: 100,
      clamped: true,
    });
    const sq = capBackingStore(30_000, 30_000, null);
    expect(sq).toEqual({ width: 16_384, height: 16_384, clamped: true });
    const wide = capBackingStore(32_000, 16_000, null);
    expect(wide.width * wide.height).toBeLessThanOrEqual(CANVAS2D_MAX_AREA_PX);
    expect(Math.abs(wide.width / wide.height - 2)).toBeLessThan(1e-3);
  });

  it("property: 500 seeded requests never exceed a limit and never grow a side", () => {
    const rng = mulberry32(20261102);
    for (let i = 0; i < 500; i += 1) {
      const w = Math.floor(rng() * 70_000);
      const h = Math.floor(rng() * 70_000);
      const c = capBackingStore(w, h, null);
      expect(c.width <= w && c.height <= h, `case ${i}`).toBe(true);
      expect(c.width <= CANVAS2D_MAX_SIDE_PX && c.height <= CANVAS2D_MAX_SIDE_PX).toBe(true);
      expect(c.width * c.height).toBeLessThanOrEqual(CANVAS2D_MAX_AREA_PX);
      expect(c.clamped).toBe(c.width < w || c.height < h);
    }
  });
});

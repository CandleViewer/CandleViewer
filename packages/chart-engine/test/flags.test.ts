import { describe, expect, it } from "vitest";
import {
  createEngine,
  stepFrame,
  animationWorkUnits,
  DEFAULT_RENDER_FLAGS,
} from "../src/compat.js";

const calm = { animate: false, heatmapFade: false, inertia: false, flashOnTick: false };

describe("accessibility render flags", () => {
  it("setFlags is read on the next frame without rebuilding", () => {
    const e = createEngine();
    expect(e.getFlags()).toEqual(DEFAULT_RENDER_FLAGS);
    e.setFlags(calm);
    expect(e.getFlags()).toBe(calm);
    e.dispose();
  });
  it("calm flags remove all animation work and finish in one frame", () => {
    expect(animationWorkUnits(calm)).toBe(0);
    const s = { velocity: 500, fadeAlpha: 1, flash: 1 };
    expect(stepFrame(s, calm, 16)).toBe(false);
    expect(s).toEqual({ velocity: 0, fadeAlpha: 0, flash: 0 });
  });
  it("animated flags keep requesting frames until decayed (frames needed: calm 1 vs animated many)", () => {
    const s = { velocity: 500, fadeAlpha: 1, flash: 1 };
    let frames = 0;
    while (stepFrame(s, DEFAULT_RENDER_FLAGS, 16) && frames < 5000) frames++;
    expect(frames).toBeGreaterThan(20);
    expect(frames).toBeLessThan(5000);
  });
});

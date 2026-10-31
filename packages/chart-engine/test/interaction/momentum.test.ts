// E11-S04 PR 1 (BQ-103): the glide is integrated on the scheduler's elapsed time, so it rests at
// x₀ + v₀τ at any frame rate and through dropped frames; the release velocity is a 50 ms EWMA.
import { describe, expect, it } from "vitest";
import { mulberry32 } from "../../bench/fixtures/rng.mjs";
import { Momentum, MOMENTUM } from "../../src/interaction/momentum.js";
import { VelocityEstimator } from "../../src/interaction/velocity.js";
import { FrameScheduler } from "../../src/scene/frame-scheduler.js";
import { SceneGraph } from "../../src/scene/graph.js";
import { TestClock } from "../scene/test-clock.js";

/** Glides from `v0` px/ms at `fps`, dropping every `drop`-th frame (0: none); the rest x. */
function glide(v0: number, fps: number, drop = 0): { x: number; frames: number } {
  const clock = new TestClock();
  const scheduler = new FrameScheduler(new SceneGraph(), clock);
  let x = 0;
  const m = new Momentum((dx) => ((x += dx), true));
  expect(m.start(v0, 1e6)).toBe(true);
  scheduler.animate(m);
  const period = 1000 / fps;
  let frames = 0;
  for (; !scheduler.parked && frames < 10_000; frames += 1) {
    if (drop > 0 && frames % drop === drop - 1) clock.advance(period); // a frame never ran
    clock.tick(period);
  }
  expect(m.active).toBe(false);
  return { x, frames };
}

describe("Scenario: momentum is frame-rate independent (TestClock)", () => {
  it("rests at x₀ + v₀τ at 30, 60 and 144 fps and with dropped frames", () => {
    const v0 = 2.5;
    const want = v0 * MOMENTUM.tauMs;
    for (const fps of [30, 60, 144]) {
      for (const drop of [0, 3, 2]) {
        expect(Math.abs(glide(v0, fps, drop).x - want)).toBeLessThan(1e-6);
      }
    }
    expect(glide(v0, 144).frames).toBeGreaterThan(glide(v0, 30).frames);
  });

  it("holds for 300 seeded releases, frame rates and drop patterns", () => {
    const rng = mulberry32(20261030);
    for (let c = 0; c < 300; c += 1) {
      const v0 = (rng() < 0.5 ? -1 : 1) * (MOMENTUM.minPxPerMs + rng() * 6);
      const fps = 24 + rng() * 216;
      const drop = Math.floor(rng() * 5);
      expect(Math.abs(glide(v0, fps, drop).x - v0 * MOMENTUM.tauMs), `case ${c}`).toBeLessThan(
        1e-6,
      );
    }
  });
});

describe("momentum bounds (E11-D06 D2 to D5)", () => {
  it("does not start below 0.3 px/ms, and caps |v₀| at 1.5 plot widths per τ", () => {
    const m = new Momentum(() => true);
    expect([m.start(0.29, 800), m.start(Number.NaN, 800), m.start(1, 0)]).toEqual([
      false,
      false,
      false,
    ]);
    expect(m.start(-1e3, 800)).toBe(true);
    expect(m.v).toBe((-1.5 * 800) / MOMENTUM.tauMs);
  });

  it("stops at the clamp with no bounce, and a cancel counts once", () => {
    let budget = 100; // px the view can still move
    const m = new Momentum((dx) => {
      const moved = Math.min(budget, dx);
      budget -= moved;
      return moved > 0;
    });
    m.start(5, 1000);
    let steps = 0;
    while (m.step(16)) steps += 1;
    expect([budget, m.active, m.v, m.registered]).toEqual([0, false, 0, false]);
    expect(steps).toBeLessThan(10);
    m.start(5, 1000);
    m.cancel();
    m.cancel();
    expect([m.cancelled, m.active, m.step(16)]).toEqual([1, false, false]);
  });

  it("ignores a frame with no elapsed time (the first after a park)", () => {
    const m = new Momentum(() => true);
    m.start(1, 1000);
    expect([m.step(0), m.v]).toEqual([true, 1]);
  });
});

describe("the release velocity (a 50 ms EWMA over coalesced samples)", () => {
  it("converges on a steady 2 px/ms train, sampled at 240 Hz or 60 Hz alike", () => {
    for (const hz of [240, 60]) {
      const v = new VelocityEstimator();
      const dt = 1000 / hz;
      for (let t = 0; t < 400; t += dt) v.sample(2 * dt, dt);
      expect(v.release(0)).toBeCloseTo(2, 2);
    }
  });

  it("smooths a noisy two-point outlier instead of following it", () => {
    const v = new VelocityEstimator();
    for (let i = 0; i < 60; i += 1) v.sample(4, 4); // 1 px/ms
    v.sample(40, 4); // a 10 px/ms spike
    expect(v.release(0)).toBeLessThan(2.5);
  });

  it("is 0 after the pointer rested over 100 ms (D06 D3), and carries same-timestamp samples", () => {
    const v = new VelocityEstimator();
    for (let i = 0; i < 30; i += 1) v.sample(8, 4);
    expect(v.release(100)).toBeGreaterThan(1);
    expect(v.release(100.5)).toBe(0);
    v.sample(0, 60);
    v.sample(0, 41);
    expect(v.release(0)).toBe(0); // still for 101 ms before the up
    v.reset();
    v.sample(10, 0); // coalesced at one timestamp: carried to the next interval
    v.sample(10, 10);
    expect(v.v).toBeCloseTo(2 * (1 - Math.exp(-10 / MOMENTUM.ewmaMs)), 12);
  });
});

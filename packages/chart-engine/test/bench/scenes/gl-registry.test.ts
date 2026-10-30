// The clock-free half of the `gl-registry` scene (E11-S02 PR1); timing is in the .perf.test.ts.
import { describe, expect, it } from "vitest";
import { GlRegistryBench } from "../../../bench/scenes/gl-registry.js";
import { FakeGl } from "../../gl/fake-gl.js";

describe("gl-registry scene", () => {
  it("invalidates and recreates 1 000 resources per step, leaking none", () => {
    const gl = new FakeGl();
    const bench = new GlRegistryBench(gl);
    for (let i = 0; i < 3; i += 1) expect(bench.step()).toBe(0);
    const counts = bench.registry.counts();
    expect(counts).toEqual({
      program: 250,
      texture: 250,
      buffer: 250,
      vertexArray: 250,
      live: 1000,
    });
    expect([gl.alive.size, bench.registry.generation, bench.registry.stats.recreated]).toEqual([
      1000, 3, 3000,
    ]);
  });
});

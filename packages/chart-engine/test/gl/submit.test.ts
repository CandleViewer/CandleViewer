// E11-S02 PR2: draw submission over the batch builder's draw list, on the fake GL's trace.
import { describe, expect, it } from "vitest";
import { DrawSubmitBench } from "../../bench/scenes/draw-submit.js";
import { PROGRAM, PROGRAMS } from "../../src/gl/program-cache.js";
import { NullSeries } from "../../src/scene/null-series.js";
import { FakeGl } from "./fake-gl.js";

const calls = (gl: FakeGl, name: string): number => gl.log.filter((c) => c === name).length;

describe("Scenario: Draw calls stay within the architectural budget", () => {
  it("a 3-pane frame makes <= 18 draws per pane, <= 40 per chart, with minimal program switches", () => {
    const bench = new DrawSubmitBench(new FakeGl());
    const { trace } = bench.backend;
    trace.enabled = true;
    bench.step();
    const perPane = [0, 1, 2].map((p) => trace.nodes.filter((n) => n.startsWith(`p${p}/`)).length);
    expect(perPane).toEqual([6, 6, 6]);
    expect(Math.max(...perPane)).toBeLessThanOrEqual(18);
    expect(trace.draws).toBe(18);
    expect(trace.draws).toBeLessThanOrEqual(40);
    // Layer order fixes the sequence; inside a layer batches group by program (BQ-42), so a
    // switch happens only where the program differs from the last draw's: 4 per pane, 12 in all.
    const { drawList, drawCount } = bench.builder;
    const runs = drawList.slice(0, drawCount).filter((b, i, l) => b.program !== l[i - 1]?.program);
    expect(trace.programSwitches).toBe(runs.length);
    expect(trace.programSwitches).toBe(12);
    expect(trace.nodes.slice(0, 6)).toEqual(
      ["grid", "candles", "ema", "vwap", "crosshair", "labels"].map((n) => `p0/${n}`),
    );
    expect(trace.triangles).toBe(3 * 2 * (40 + 500 + 499 + 499 + 2 + 64));
  });
});

describe("draw submission: steady state", () => {
  it("allocates nothing across 600 frames and resolves uniform locations once", () => {
    const gl = new FakeGl();
    const bench = new DrawSubmitBench(gl);
    bench.step(); // warm-up: compiles, first full uploads
    const { registry, programs } = bench.backend;
    const uniforms = PROGRAMS.reduce((n, p) => n + p.uniforms.length, 0) - 1; // quad unused
    const before = [registry.stats.created, programs.stats.compiles, bench.builder.pool.created];
    expect(calls(gl, "getUniformLocation")).toBe(uniforms);
    const list = bench.builder.drawList;
    for (let f = 0; f < 600; f += 1) bench.step();
    expect([registry.stats.created, programs.stats.compiles, bench.builder.pool.created]).toEqual(
      before,
    );
    expect(bench.builder.drawList).toBe(list);
    expect(bench.backend.trace.nodes).toEqual([]); // the trace records only when enabled
    expect(calls(gl, "getUniformLocation")).toBe(uniforms);
    expect(calls(gl, "drawArraysInstanced")).toBe(601 * 18);
    expect(bench.backend.takeUploadedBytes()).toBe(18 * 1024 * 4 * 4); // the first frame only
  });
});

describe("draw submission: teardown and unattached nodes", () => {
  it("skips a batch without a VAO and dispose() deletes every GL object", () => {
    const gl = new FakeGl();
    const bench = new DrawSubmitBench(gl);
    const orphan = Object.assign(new NullSeries("p0/orphan"), { program: PROGRAM.quad, count: 9 });
    bench.graph.addNode("p0", "series", orphan); // never attached: no VAO
    bench.step();
    expect(bench.backend.trace.draws).toBe(18);
    // E11-T05 BQ-85: the seam's attach and loss hooks reach the same buffers and context.
    bench.backend.attach(orphan.id, { data: new Float32Array(72), head: 0, stride: 8 });
    bench.step();
    expect(bench.backend.trace.draws).toBe(19);
    expect([bench.backend.loss === bench.backend, bench.backend.loss.isContextLost()]).toEqual([
      true,
      false,
    ]);
    expect(bench.backend.registry.counts().live).toBeGreaterThan(0);
    bench.backend.dispose();
    expect(bench.backend.registry.counts().live).toBe(0);
  });
});

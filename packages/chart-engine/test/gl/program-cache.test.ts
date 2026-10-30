// E11-S02 PR2: lazy program compilation and the compile-failure path (BQ-52).
import { describe, expect, it } from "vitest";
import { DrawSubmitBench } from "../../bench/scenes/draw-submit.js";
import { GLBackend } from "../../src/gl/backend.js";
import {
  ContextLostError,
  INFO_LOG_MAX,
  PROGRAM,
  ProgramCache,
  ProgramCompileError,
} from "../../src/gl/program-cache.js";
import { GlRegistry } from "../../src/gl/registry.js";
import { ENGINE_SHADER_COMPILE_FAILED } from "../../src/worker/protocol.js";
import { FakeGl } from "./fake-gl.js";

const live = (gl: FakeGl, kind: string): number =>
  [...gl.alive].filter((o) => (o as { kind: string }).kind === kind).length;

describe("Scenario: A shader that fails to compile is a handled error", () => {
  it("reports ENGINE_SHADER_COMPILE_FAILED with the program, the renderer and the log", () => {
    const gl = new FakeGl({ failCompile: "a_segment", infoLog: `ERROR: 0:3 ${"x".repeat(600)}` });
    const bench = new DrawSubmitBench(gl);
    bench.step();
    const failure = bench.backend.failure;
    expect(failure).toMatchObject({
      code: ENGINE_SHADER_COMPILE_FAILED,
      recoverable: true,
      fallback: "degraded-2d",
    });
    expect(failure?.message).toMatch(/^program "line" failed to compile on fake renderer: ERROR/);
    expect(failure?.message).toContain("x".repeat(INFO_LOG_MAX - 11));
    expect(failure?.message).not.toContain("x".repeat(INFO_LOG_MAX - 10)); // log trimmed to 512
    expect([live(gl, "Program"), live(gl, "Shader")]).toEqual([0, 0]); // nothing leaked
    const draws = gl.log.length;
    bench.step(); // failed: no more GL drawing until the host swaps the canvas (PR3)
    expect(gl.log.slice(draws)).not.toContain("drawArraysInstanced");
    expect(bench.backend.submit([], 0, 1, 1)).toBe(failure);
  });

  it("names the renderer as masked without WEBGL_debug_renderer_info", () => {
    const gl = new FakeGl({ failCompile: "#version", infoLog: "bad" });
    const backend = new GLBackend(gl, null);
    backend.buffers.attach("n", { data: new Float32Array(4), head: 0, stride: 4 });
    const batch = { nodeId: "n", program: PROGRAM.quad, texture: 0, first: 0, count: 1 };
    const f = backend.submit([{ ...batch, layer: 0, seq: 0, lo: 0, hi: 0 }], 1, 1, 1);
    expect(f?.message).toBe('program "quad" failed to compile on renderer masked: bad');
  });
});

describe("ProgramCache", () => {
  it("compiles lazily, once per program, and times it", () => {
    const gl = new FakeGl();
    let t = 0;
    const cache = new ProgramCache(gl, new GlRegistry(gl), () => (t += 2));
    expect(cache.stats.compiles).toBe(0);
    const a = cache.use(PROGRAM.sdfText);
    expect(cache.use(PROGRAM.sdfText)).toBe(a);
    expect(Object.keys(a.uniforms)).toEqual(["u_viewport", "u_atlas", "u_color"]);
    expect(cache.stats).toEqual({ compiles: 1, compileMs: 2 });
    expect(live(gl, "Shader")).toBe(0); // shaders are deleted once linked
    expect(() => cache.use(99)).toThrow(ProgramCompileError);
  });

  it("fails a link, and a lost context, without leaking", () => {
    const gl = new FakeGl();
    gl.getProgramParameter = (): unknown => false;
    const cache = new ProgramCache(gl, new GlRegistry(gl));
    expect(() => cache.use(PROGRAM.line)).toThrow(ProgramCompileError);
    // m2: on a lost context a null object or a false status is the loss path, not a compile error
    gl.loseContext();
    expect(() => cache.use(PROGRAM.line)).toThrow(ContextLostError);
    expect(() => new ProgramCache(gl, new GlRegistry(gl)).use(PROGRAM.line)).toThrow(
      ContextLostError,
    );
    expect(gl.alive.size).toBe(0);
  });
});

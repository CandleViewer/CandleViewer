// E11-S15 PR-1, BQ-S15-12: the sampler reads the account every memory.sampleIntervalMs on the 1 s
// tick and at once on a resize, never per frame, and a sample allocates nothing. Timing is in
// test/bench/scenes/memory-sample.perf.test.ts.
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { MemorySampleBench, probeAllocations } from "../../bench/scenes/memory-sample.js";
import { MEMORY_SAMPLE_INTERVAL_MS, MemoryAccount, MemorySampler } from "../../src/memory/index.js";
import { BAR_BYTES } from "../../src/model/BarStore.js";
import { createRenderRuntime, type RenderRuntime } from "../../src/worker/runtime.js";
import { FakeGl, FULL, ROOMY } from "../gl/fake-gl.js";
import { minuteMap } from "../interaction/fixtures.js";

describe("MemorySampler", () => {
  it("samples on the first tick, then only once memory.sampleIntervalMs (5000) has passed", () => {
    const account = new MemoryAccount();
    let held = 1024;
    account.register({ id: "gl", bytes: () => held });
    const s = new MemorySampler(account);
    expect(s.intervalMs).toBe(MEMORY_SAMPLE_INTERVAL_MS);
    expect(MEMORY_SAMPLE_INTERVAL_MS).toBe(5000);
    const fired = [0, 1000, 2000, 3000, 4000, 4999, 5000, 6000, 10_000].map((t) => s.tick(t));
    expect(fired).toEqual([true, false, false, false, false, false, true, false, true]);
    held = 2 ** 21;
    expect([s.samples, s.usedBytes]).toEqual([3, 1024]); // a source change waits for a sample
    expect(s.sample(10_500)).toBe(2 ** 21); // a resize samples at once and restarts the interval
    expect([s.tick(15_000), s.tick(15_500), s.usedMb]).toEqual([false, true, 2]);
  });

  it("honours a configured interval and refuses a non-positive or fractional one", () => {
    const s = new MemorySampler(new MemoryAccount(), 1000);
    expect([s.tick(0), s.tick(999), s.tick(1000)]).toEqual([true, false, true]);
    for (const bad of [0, -1, 0.5, Number.NaN, Infinity]) {
      expect(() => new MemorySampler(new MemoryAccount(), bad)).toThrow(RangeError);
    }
  });
});

describe("Scenario: a sample allocates nothing (memory-sample bench scene)", () => {
  it("walks the fixed source array, reads each source once a sample and never reads ids", () => {
    const bench = new MemorySampleBench();
    const ids = vi.spyOn(bench.account, "ids", "get");
    const bars = vi.spyOn(bench.bars, "bytes", "get");
    const first = bench.step(0);
    const out = new Float64Array(10_000);
    const calls = probeAllocations(() => {
      for (let i = 1; i < 10_000; i += 1) out[i] = bench.step(i);
    });
    expect(calls).toBe(0);
    expect(out.subarray(1).every((v) => v === first)).toBe(true);
    expect(first).toBeGreaterThan(200_000 * BAR_BYTES);
    expect([ids.mock.calls.length, bars.mock.calls.length]).toEqual([0, 10_000]);
    expect(bench.sampler.samples).toBe(10_000);
  });

  it("the probe trips on an allocating sum and restores every built-in it wrapped", () => {
    const account = new MemoryAccount();
    for (const id of ["a", "b", "c"]) account.register({ id, bytes: () => 8 });
    const sources = (account as unknown as { sources: { bytes(): number }[] }).sources;
    const map = Array.prototype.map;
    const bind = Function.prototype.bind;
    let sum = 0;
    // The regression D1 names: `totalBytes` as `this.sources.map(...).reduce(...)`.
    expect(
      probeAllocations(() => {
        sum = sources.map((s) => s.bytes()).reduce((a, b) => a + b, 0);
      }),
    ).toBe(2);
    expect(probeAllocations(() => void (() => sum).bind(null))).toBe(1);
    expect(sum).toBe(24);
    expect([Array.prototype.map, Function.prototype.bind]).toEqual([map, bind]);
    expect(() =>
      probeAllocations(() => {
        throw new Error("boom");
      }),
    ).toThrow("boom");
    expect(Array.prototype.map).toBe(map);
  });
});

describe("Scenario: the runtime samples on the 1 s tick and on resize, never per frame", () => {
  let rt: RenderRuntime;

  beforeEach(() => {
    vi.useFakeTimers();
    const gl = new FakeGl({ params: ROOMY });
    rt = createRenderRuntime({
      runMode: "inline",
      post: () => undefined,
      requestFrame: (cb) => void setTimeout(cb, 16),
      now: () => Number(vi.getMockedSystemTime()),
      setTimer: (cb, ms) => void setTimeout(cb, ms),
      probe: () => FULL,
      timeMap: minuteMap(),
    });
    const canvas = { width: 400, height: 200, getContext: () => gl };
    rt.handle({
      t: "init",
      id: 1,
      canvas,
      dpr: 1,
      theme: {},
      config: { bench: true, syncGroup: null },
    });
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("samples the first frame, each backing-store change at once, and nothing on a no-op resize", () => {
    const s = rt.memorySampler(1)!;
    expect(s.samples).toBe(0);
    vi.advanceTimersByTime(16);
    expect(s.samples).toBe(1);
    const first = s.usedBytes;
    rt.handle({ t: "resize", id: 1, width: 800, height: 400, dpr: 1 });
    expect([s.samples, s.usedBytes - first]).toEqual([2, (800 * 400 - 400 * 200) * 4]);
    rt.handle({ t: "resize", id: 1, width: 800, height: 400, dpr: 1 });
    vi.advanceTimersByTime(16 * 10); // frames inside the interval do not sample
    expect(s.samples).toBe(2);
    expect(rt.memorySampler(2)).toBeUndefined();
  });

  it("builds the sampler with the init's configured interval (memory.sampleIntervalMs)", () => {
    const canvas = { width: 400, height: 200, getContext: () => new FakeGl({ params: ROOMY }) };
    const config = { bench: true, syncGroup: null, sampleIntervalMs: 1000 };
    rt.handle({ t: "init", id: 2, canvas, dpr: 1, theme: {}, config });
    expect([rt.memorySampler(2)?.intervalMs, rt.memorySampler(1)?.intervalMs]).toEqual([
      1000, 5000,
    ]);
  });
});

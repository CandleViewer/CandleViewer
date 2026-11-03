// The clock-free half of the `forming-tick` scene (E12-S10): a live tick on the forming bar uploads
// one 20-byte instance (the ring's slot; the marks entry is unchanged), never a full buffer, and
// allocates nothing; the series draws three batches while the ring is in view (wick, body,
// marks), and a confirm settles the bar in one slot and posts one event per state change.
import { describe, expect, it } from "vitest";
import { FormingTickBench } from "../../../bench/scenes/forming-tick.js";
import { FakeGl } from "../../gl/fake-gl.js";

describe("forming-tick bench: 5k and 100k bars, a live forming bar", () => {
  it.each([5_000, 100_000])("%i bars: 20 bytes per tick, 0 full uploads, 0 alloc", (n) => {
    const gl = new FakeGl();
    gl.trackDraws = true;
    const bench = new FormingTickBench(n, gl);
    const { backend } = bench.scene;
    backend.takeUploadedBytes();
    const writes = gl.writes.length;
    const draws = gl.draws.length;
    const events = bench.events;
    for (let f = 1; f <= 1_000; f += 1) {
      bench.tick(64 + f * 16);
      expect(backend.takeUploadedBytes()).toBe(20);
    }
    const tickWrites = gl.writes.slice(writes);
    expect(tickWrites.filter((w) => w.startsWith("full"))).toEqual([]);
    expect(tickWrites).toHaveLength(1_000); // one bufferSubData per tick
    expect(new Set(tickWrites.map((w) => w.split(" ")[3]))).toEqual(new Set(["5"])); // 5 words
    expect(gl.draws.length - draws).toBe(3 * 1_000); // wick, body, the forming ring
    expect(gl.draws.at(-1)).toBe("4 1"); // the marks batch: one ring instance
    expect(bench.events - events).toBe(0); // never an event per tick
    expect(bench.allocationsSinceWarm).toBe(0);
  });

  it("a confirm settles the bar in one slot; the next bar's ring takes its place", () => {
    const gl = new FakeGl();
    const bench = new FormingTickBench(5_000, gl);
    const { backend, series, ring } = bench.scene;
    const rewrites = ring.rewrites;
    const before = bench.events;
    backend.takeUploadedBytes();
    bench.confirm(2_000);
    // The confirmed slot, the appended bar, and the marks entry moved to the new slot.
    expect(backend.takeUploadedBytes()).toBe(20 + 20 + 20);
    expect(series.marks.count).toBe(1);
    expect(bench.events - before).toBe(2); // closed, then the next one forming
    expect(ring.rewrites).toBe(rewrites);
    expect(bench.allocationsSinceWarm).toBe(0);
  });
});

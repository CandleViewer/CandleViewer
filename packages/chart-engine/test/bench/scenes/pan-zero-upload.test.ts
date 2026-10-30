// The counted half of the `pan-zero-upload` scene (E11-S01 PR3, B1-like); timing is in the
// .perf.test.ts. The upload count is on a fake sink until E11-S02's GL backend (BQ-S12).
import { describe, expect, it } from "vitest";
import { PanZeroUploadBench } from "../../../bench/scenes/pan-zero-upload.js";

describe("Scenario: Panning reuses GPU buffers", () => {
  it("5 s of pan over 100 000 bars marks TRANSFORM, never DATA, and uploads nothing", () => {
    const bench = new PanZeroUploadBench(100_000);
    const batch = bench.builder.drawList[0];
    expect([bench.builder.uploads, batch?.count]).toEqual([1, 100_000]); // the first build: all

    for (let f = 1; f <= 300; f += 1) bench.step(f * (5000 / 300)); // 60 Hz for 5 s
    expect([bench.transformCollects, bench.dataDirtyCollects]).toEqual([300, 0]);
    // The AC's bufferSubData count over the pan: still the one upload of the first build.
    expect([bench.builder.uploads, bench.allocationsInFramePath]).toEqual([1, 0]);
    expect([bench.builder.drawCount, bench.builder.drawList[0]]).toEqual([1, batch]);
    expect([bench.requests, bench.scheduler.parked]).toEqual([301, true]); // parks between pans
  });
});

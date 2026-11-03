// Counting half of the `dom-mirror` scene (E11-S13 PR-2): the steady feed keeps the window at 60
// rows with the pool's identity (no rewindow, no desync) and never grows the node count.
import { describe, expect, it } from "vitest";
import { DomMirrorBench } from "../../../bench/scenes/dom-mirror.js";

describe("the dom-mirror scene", () => {
  it("test_dom_mirror_scene_steady_feed_keeps_60_rows_without_rewindow", () => {
    let t = 0;
    const bench = new DomMirrorBench(120, () => (t += 0.01));
    bench.run();
    const c = bench.mirror.counters;
    expect(c.mirrorNodes).toBe(11 + 60 * 8);
    expect([c.mirrorRewindows, c.desyncDetected]).toEqual([0, 0]);
    expect(Array.from(bench.times).every((ms) => ms > 0)).toBe(true);
  });
});

// E11-S08 PR 2, G-27: under log y a segment is drawn straight on screen, so its ticks bend. A
// seeded property (C-38) over 200 log scenes: the grid answers as the brute-force scan at points
// on each drawn line and around it, after pans and autoscales; a mode, origin or tick switch is one
// counted rebuild, a pan none. A failure prints its seed.
import { describe, expect, it } from "vitest";
import { mulberry32 } from "../../bench/fixtures/rng.mjs";
import { hitViewport } from "../../bench/scenes/hit-pick.js";
import { ObjectIndex, createPickHit } from "../../src/hit/index.js";
import { priceToScreen, timeToScreen } from "../../src/viewport/index.js";

const SCENES = 200;
const BAR_US = 60e6;

function logScene(seed: number) {
  const rng = mulberry32(seed);
  const { viewport: vp } = hitViewport(2_000);
  const pane = vp.panes[0];
  if (pane === undefined) throw new Error("no pane");
  vp.setPriceInfo(0, 1 + rng() * 50, 0.01 + rng() * 2); // every tick in [0, 100 000] is positive
  vp.setPriceRange(0, rng() * 100, 1_000 + rng() * 99_000);
  pane.scaleMode = "log";
  const index = new ObjectIndex(vp);
  return { rng, vp, index };
}

describe("Scenario: picks under a log scale (G-27)", () => {
  it("the grid answers as the brute-force scan on and around every drawn segment", () => {
    const hit = createPickHit();
    const ref = createPickHit();
    for (let seed = 1; seed <= SCENES; seed += 1) {
      const { rng, vp, index } = logScene(389_200 + seed);
      const lines: [number, number, number, number][] = [];
      const n = 1 + Math.floor(rng() * 12);
      for (let i = 0; i < n; i += 1) {
        const t0 = (vp.leftIndex + rng() * vp.visibleBars) * BAR_US;
        const t1 = t0 + (rng() - 0.5) * 120 * BAR_US;
        const [p0, p1] = [rng() * 100_000, rng() * 100_000];
        lines.push([t0, p0, t1, p1]);
        const geometry = { type: "segment", t0, p0, t1, p1 } as const;
        const widthPx = rng() * 4;
        index.registerPickable({
          id: `s${i}`,
          kind: "drawing",
          paneId: "main",
          zIndex: 0,
          geometry,
          widthPx,
        });
      }
      for (let round = 0; round < 3; round += 1) {
        for (const [t0, p0, t1, p1] of lines) {
          const [ax, ay] = [timeToScreen(vp, t0), priceToScreen(vp, 0, p0)];
          const [bx, by] = [timeToScreen(vp, t1), priceToScreen(vp, 0, p1)];
          const u = rng();
          const [dx, dy] = [(rng() - 0.5) * 30, (rng() - 0.5) * 30];
          for (const [x, y, on] of [
            [ax + (bx - ax) * u, ay + (by - ay) * u, true],
            [ax + (bx - ax) * u + dx, ay + (by - ay) * u + dy, false],
          ] as const) {
            index.pick(x, y, "mouse", hit);
            index.pickLinear(x, y, "mouse", ref);
            expect(hit, `seed ${389_200 + seed}`).toEqual(ref);
            if (on) expect(ref.id, `seed ${389_200 + seed}: on a drawn line`).not.toBeNull();
          }
        }
        vp.pan((rng() - 0.5) * 400);
        vp.setPriceRange(0, rng() * 50, 2_000 + rng() * 98_000); // an autoscale: log-affine
      }
    }
  });

  it("a mode, origin or tick change is one rebuild; a pan is none", () => {
    const { vp, index } = logScene(389_001);
    const pane = vp.panes[0];
    if (pane === undefined) throw new Error("no pane");
    const t0 = (vp.leftIndex + 10) * BAR_US;
    const geometry = { type: "segment", t0, p0: 50, t1: t0 + 100 * BAR_US, p1: 90_000 } as const;
    index.registerPickable({
      id: "s",
      kind: "drawing",
      paneId: "main",
      zIndex: 0,
      geometry,
      widthPx: 1,
    });
    const hit = createPickHit();
    const rebuilds = (): number => index.counters.indexRebuilds;
    index.pick(100, 100, "mouse", hit);
    const start = rebuilds();
    for (let i = 0; i < 50; i += 1) {
      vp.pan(3);
      index.pick(100, 100, "mouse", hit);
    }
    expect(rebuilds()).toBe(start);
    pane.scaleMode = "linear";
    index.pick(100, 100, "mouse", hit);
    index.pick(120, 100, "mouse", hit);
    expect(rebuilds()).toBe(start + 1);
    pane.scaleMode = "log";
    vp.setPriceInfo(0, pane.priceOrigin + 1, pane.tickSize);
    index.pick(100, 100, "mouse", hit);
    expect(rebuilds()).toBe(start + 2);
  });

  it("a segment through a non-positive price is tested on every query", () => {
    const { vp, index } = logScene(389_002);
    vp.setPriceInfo(0, -10, 1); // ticks up to 10 are non-positive prices
    vp.setPriceRange(0, 20, 6_000); // the window's base is positive: log is drawn
    const t0 = (vp.leftIndex + 10) * BAR_US;
    const geometry = { type: "segment", t0, p0: 0, t1: t0 + 50 * BAR_US, p1: 5_000 } as const;
    index.registerPickable({
      id: "s",
      kind: "drawing",
      paneId: "main",
      zIndex: 0,
      geometry,
      widthPx: 1,
    });
    const hit = createPickHit();
    index.pick(0, 0, "mouse", hit); // places it under log
    index.pick(-1e6, -1e6, "mouse", hit);
    expect(index.counters.lastCandidates).toBe(1); // the unbounded list, wherever the pointer is
  });
});

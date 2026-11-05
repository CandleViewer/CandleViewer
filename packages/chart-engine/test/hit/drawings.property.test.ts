// E14-T04 properties (C-38: seeded mulberry32 loops, no fast-check, README BQ-30): over 400 random
// scenes of drawings in every tool family plus trading lines, the grid answers exactly as the
// brute-force scan after moves, hides, re-shows, pans and zooms (10 000 picks with an id, part,
// handle and distance each). The ellipse rim distance is never under the sampled true distance.
// A failure prints its seed.
import { describe, expect, it } from "vitest";
import { mulberry32 } from "../../bench/fixtures/rng.mjs";
import { hitViewport } from "../../bench/scenes/hit-pick.js";
import {
  DrawingAdapter,
  ObjectIndex,
  createPickHit,
  distToEllipse,
  type DrawingRecord,
} from "../../src/hit/index.js";

const SCENES = 400;
const PICKS = 25;
const BASE = 359_000;
const TOOLS = [
  ["trendline", 2],
  ["ray", 2],
  ["extended_line", 2],
  ["horizontal_line", 1],
  ["vertical_line", 1],
  ["rectangle", 2],
  ["ellipse", 2],
  ["fib_retracement", 2],
  ["fib_extension", 3],
  ["parallel_channel", 3],
  ["brush", 5],
  ["text", 1],
] as const;
const POINTERS = ["mouse", "pen", "touch"] as const;

function scene(rng: () => number): void {
  const { viewport: vp } = hitViewport();
  const index = new ObjectIndex(vp);
  const drawings = new DrawingAdapter(index);
  const anchors = (n: number): number[] => {
    const out: number[] = [];
    const t = vp.leftIndex + rng() * vp.visibleBars;
    const p = rng() * 2_000;
    for (let i = 0; i < n; i += 1) {
      out.push((t + (rng() - 0.5) * 60) * 60e6, Math.round(p + (rng() - 0.5) * 800));
    }
    return out;
  };
  const recs: DrawingRecord[] = [];
  const count = 1 + Math.floor(rng() * 40);
  for (let i = 0; i < count; i += 1) {
    const [tool, n] = TOOLS[Math.floor(rng() * TOOLS.length)] as (typeof TOOLS)[number];
    recs.push(
      drawings.upsert({
        id: `d${i}`,
        tool,
        anchors: anchors(n),
        widthPx: rng() * 4,
        zIndex: Math.floor(rng() * 3),
        locked: rng() < 0.2,
        visible: rng() < 0.9,
        ...(rng() < 0.5 && { levels: [0, 0.5, 1, 1.618] }),
      }),
    );
  }
  for (let i = 0; i < 4; i += 1) {
    index.registerPickable({
      id: `l${i}`,
      kind: i % 2 === 0 ? "order-line" : "alert-line",
      paneId: "main",
      zIndex: 0,
      widthPx: 1,
      geometry: { type: "hline", p: rng() * 2_000 },
    });
  }
  for (let k = Math.floor(rng() * 6); k > 0; k -= 1) {
    const r = recs[Math.floor(rng() * recs.length)] as DrawingRecord;
    if (rng() < 0.3) drawings.setVisible(r, !r.visible);
    else drawings.setAnchors(r, anchors(r.anchors.length / 2));
  }
  index.gesture = rng() < 0.5;
  if (rng() < 0.5) vp.pan((rng() - 0.5) * 1_500);
  else vp.zoomAt(rng() * vp.plotWidth, 0.2 + rng() * 5);
  const grid = createPickHit();
  const brute = createPickHit();
  for (let i = 0; i < PICKS; i += 1) {
    const x = rng() * vp.plotWidth;
    const y = rng() * 720;
    const pointer = POINTERS[Math.floor(rng() * 3)] as (typeof POINTERS)[number];
    index.pickLinear(x, y, pointer, brute);
    index.pick(x, y, pointer, grid);
    expect(grid).toEqual(brute);
  }
  expect(index.counters.capped).toBe(0); // exact: no scene reaches PICK_BUDGET
}

describe("property: drawings pick through the grid exactly as through a linear scan", () => {
  it("10 000 seeded picks over 400 scenes of every family agree", { timeout: 60_000 }, () => {
    for (let c = 0; c < SCENES; c += 1) {
      try {
        scene(mulberry32(BASE + c));
      } catch (e) {
        throw new Error(`seed ${BASE + c}: ${(e as Error).message}`);
      }
    }
  });
});

describe("property: the ellipse distance is conservative", () => {
  it("10 000 points: 0 exactly inside, never under the rim's sampled distance", () => {
    const rng = mulberry32(BASE);
    for (let c = 0; c < 10_000; c += 1) {
      const [x0, y0] = [rng() * 200, rng() * 200];
      const [x1, y1] = [x0 + 1 + rng() * 300, y0 + 1 + rng() * 300];
      const [px, py] = [rng() * 700 - 100, rng() * 700 - 100];
      const [cx, cy, rx, ry] = [(x0 + x1) / 2, (y0 + y1) / 2, (x1 - x0) / 2, (y1 - y0) / 2];
      const d = distToEllipse(px, py, x0, y0, x1, y1);
      const inside = ((px - cx) / rx) ** 2 + ((py - cy) / ry) ** 2 <= 1;
      if (inside) {
        expect(d).toBe(0);
        continue;
      }
      let rim = Infinity;
      for (let k = 0; k < 720; k += 1) {
        const a = (k / 720) * 2 * Math.PI;
        rim = Math.min(rim, Math.hypot(px - cx - rx * Math.cos(a), py - cy - ry * Math.sin(a)));
      }
      expect(d, `seed ${BASE} case ${c}`).toBeGreaterThanOrEqual(rim - 0.5);
    }
  });
});

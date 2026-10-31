// E11-S08 property (C-38: seeded mulberry32 loops, no fast-check): over 500 random scenes and
// viewports, 20 picks each (10 000 cases), the grid answers exactly as the brute-force scan, after
// moves (across types and the 64 px unbounded pad), unregisters, pans, zooms (with and without a
// gesture), autoscales and prepends. A failure prints its seed.
// The oracle `pickLinear` shares the precise `test()`, so this proves the grid finds the same
// candidates; the distances and the order are proven by the unit tests (geometry, object-index).
import { describe, expect, it } from "vitest";
import { mulberry32 } from "../../bench/fixtures/rng.mjs";
import { randomShape } from "../../bench/scenes/hit-pick.js";
import { bars } from "../../bench/scenes/pan-zero-upload.js";
import { ObjectIndex, createPickHit } from "../../src/hit/index.js";
import { BarStore } from "../../src/model/BarStore.js";
import { ChartViewport } from "../../src/viewport/index.js";

const SCENES = 500;
const PICKS = 20;
const BASE = 389_000;
const POINTERS = ["mouse", "pen", "touch"] as const;

function scene(rng: () => number): void {
  const store = new BarStore();
  store.append(bars(2_000, 1e15));
  const vp = new ChartViewport(store);
  const w = 200 + rng() * 1_800;
  const h = 100 + rng() * 900;
  vp.setSize(w, h, 1);
  vp.setPanePlot(0, rng() * 40, h);
  vp.zoomAt(0, 0.2 + rng() * 6);
  vp.scrollTo(rng() * 2_000);
  vp.setPriceRange(0, rng() * 1_000, 1_100 + rng() * 5_000);
  const index = new ObjectIndex(vp);
  const objects = 1 + Math.floor(rng() * 60);
  const shift = (g: ReturnType<typeof randomShape>) =>
    "t" in g ? { ...g, t: g.t + 1e15 } : "t0" in g ? { ...g, t0: g.t0 + 1e15, t1: g.t1 + 1e15 } : g;
  /** Any shape; a bubble's pad (width / 2 + radius) straddles CELL_PX, the unbounded threshold. */
  const shape = () => {
    const u = rng();
    const t = 1e15 + (vp.leftIndex + rng() * vp.visibleBars) * 60e6;
    if (u < 0.1) return { type: "hline", p: rng() * 6_000 } as const;
    if (u < 0.2) return { type: "vline", t } as const;
    if (u < 0.3) return { type: "point", t, p: rng() * 2_000, radiusPx: 55 + rng() * 20 } as const;
    return shift(randomShape(rng, vp));
  };
  const handlesOf = (g: ReturnType<typeof shape>) => ("t0" in g ? [{ t: g.t1, p: g.p1 }] : []);
  const live: string[] = [];
  for (let i = 0; i < objects; i += 1) {
    const geometry = shape();
    const zIndex = Math.floor(rng() * 3);
    const widthPx = rng() * 6;
    const handles = handlesOf(geometry);
    index.registerPickable({
      id: `o${i}`,
      kind: "drawing",
      paneId: "main",
      zIndex,
      geometry,
      widthPx,
      handles,
    });
    live.push(`o${i}`);
  }
  /** Moves (type and radius changes included) and unregisters; the picks below check them. */
  const churn = () => {
    for (let k = Math.floor(rng() * 8); k > 0 && live.length > 0; k -= 1) {
      const j = Math.floor(rng() * live.length);
      const id = live[j] as string;
      if (rng() < 0.25) {
        index.unregister(id);
        live.splice(j, 1);
      } else {
        const geometry = shape();
        index.move(id, geometry, handlesOf(geometry));
      }
    }
  };
  churn();
  const step = rng();
  index.gesture = rng() < 0.5;
  if (step < 0.3) vp.pan((rng() - 0.5) * 2_000);
  else if (step < 0.6) vp.zoomAt(rng() * w, 0.1 + rng() * 10);
  else if (step < 0.8) vp.setPriceRange(0, rng() * 3_000, 3_500 + rng() * 50_000);
  else {
    const k = 1 + Math.floor(rng() * 3_000);
    index.onMutation(store.prepend(bars(k, 1e15 - k * 60e6)));
    vp.scrollTo(vp.leftIndex + k);
  }
  churn();
  const grid = createPickHit();
  const brute = createPickHit();
  for (let i = 0; i < PICKS; i += 1) {
    const x = rng() * w;
    const y = rng() * (h + 40);
    const pointer = POINTERS[Math.floor(rng() * 3)] as (typeof POINTERS)[number];
    index.pickLinear(x, y, pointer, brute);
    index.pick(x, y, pointer, grid);
    expect(grid).toEqual(brute);
  }
  expect(index.staleEntries()).toBe(0);
}

describe("property: the grid picks exactly what a linear scan picks", () => {
  it(
    "10 000 seeded picks over 500 scenes agree in id, part, handle and distance",
    { timeout: 60_000 },
    () => {
      for (let c = 0; c < SCENES; c += 1) {
        try {
          scene(mulberry32(BASE + c));
        } catch (e) {
          throw new Error(`seed ${BASE + c}: ${(e as Error).message}`);
        }
      }
    },
  );
});

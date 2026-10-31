// `hit-pick` scene (E11-S08, BQ-141; R5, B8, 06 §4.3): one 1216 × 720 pane over 10 000 bars with
// seeded drawings (segments, rects, bubbles, a few rays) plus horizontal order and position lines,
// and 1 000 seeded picks. The unit test counts (no pick reads more than a fraction of the objects,
// no rebuild); the .perf.test.ts times the p95 pick (≤ 1 ms) at 250 and at 1 000 objects.
import { mulberry32 } from "../fixtures/rng.mjs";
import { BarStore } from "../../src/model/BarStore.js";
import { ObjectIndex, createPickHit, type PickGeometry } from "../../src/hit/index.js";
import { ChartViewport } from "../../src/viewport/index.js";
import { bars } from "./pan-zero-upload.js";

export const PLOT = { width: 1216, height: 720 };
const BAR_US = 60e6;
const PICKS = 1_000;

/** 10 000 one-minute bars, the latest ~200 in view at 6 px a bar, ticks 0..2 000 on 720 px. */
export function hitViewport(n = 10_000): { store: BarStore; viewport: ChartViewport } {
  const store = new BarStore();
  store.append(bars(n));
  const viewport = new ChartViewport(store);
  viewport.setSize(PLOT.width, PLOT.height, 1);
  viewport.setPanePlot(0, 0, PLOT.height);
  viewport.setPriceRange(0, 0, 2_000);
  viewport.scrollTo(n - 190);
  return { store, viewport };
}

/** A seeded shape around the view: segments, rects, bubbles and rays (5 % each of the last two). */
export function randomShape(rng: () => number, vp: ChartViewport): PickGeometry {
  const t0 = (vp.leftIndex + rng() * vp.visibleBars) * BAR_US;
  const p0 = rng() * 2_000;
  const t1 = t0 + (rng() - 0.5) * 50 * BAR_US;
  const p1 = p0 + (rng() - 0.5) * 400;
  const u = rng();
  if (u < 0.05) return { type: "ray", t0, p0, t1, p1 };
  if (u < 0.1) return { type: "point", t: t0, p: p0, radiusPx: 4 + rng() * 8 };
  if (u < 0.3) return { type: "rect", t0, p0, t1: t0 + (t1 - t0) / 2, p1: p0 + (p1 - p0) / 4 };
  return { type: "segment", t0, p0, t1, p1 };
}

/** `drawings` seeded shapes and `lines` horizontal lines, registered in that order. */
export function seedPickables(
  index: ObjectIndex,
  vp: ChartViewport,
  rng: () => number,
  drawings: number,
  lines: number,
): void {
  for (let i = 0; i < drawings; i += 1) {
    const geometry = randomShape(rng, vp);
    const handles = geometry.type === "segment" ? [{ t: geometry.t0, p: geometry.p0 }] : [];
    const zIndex = Math.floor(rng() * 4);
    index.registerPickable({
      id: `d${i}`,
      kind: "drawing",
      paneId: "main",
      zIndex,
      geometry,
      widthPx: 2,
      handles,
    });
  }
  for (let i = 0; i < lines; i += 1) {
    const kind = i % 2 === 0 ? "order-line" : "position-line";
    const geometry = { type: "hline", p: rng() * 2_000 } as const;
    index.registerPickable({ id: `l${i}`, kind, paneId: "main", zIndex: 10, geometry, widthPx: 1 });
  }
}

export class HitPickBench {
  readonly viewport: ChartViewport;
  readonly index: ObjectIndex;
  /** Per-pick ms of the last `run` (zero without a clock), and the most candidates one pick read. */
  readonly times = new Float64Array(PICKS);
  maxCandidates = 0;
  hits = 0;
  private readonly points = new Float64Array(PICKS * 2);
  private readonly hit = createPickHit();

  /** 200 drawings + 50 lines (R5), or the 1 000-object margin variant at the same mix. */
  constructor(
    objects = 250,
    private readonly now: () => number = () => 0,
    seed = 389,
  ) {
    this.viewport = hitViewport().viewport;
    this.index = new ObjectIndex(this.viewport);
    const rng = mulberry32(seed);
    seedPickables(this.index, this.viewport, rng, (objects * 4) / 5, objects / 5);
    for (let i = 0; i < PICKS; i += 1) {
      this.points[2 * i] = rng() * PLOT.width;
      this.points[2 * i + 1] = rng() * PLOT.height;
    }
  }

  run(): void {
    this.maxCandidates = 0;
    this.hits = 0;
    for (let i = 0; i < PICKS; i += 1) {
      const t = this.now();
      const x = this.points[2 * i] as number;
      if (this.index.pick(x, this.points[2 * i + 1] as number, "mouse", this.hit)) this.hits += 1;
      this.times[i] = this.now() - t;
      this.maxCandidates = Math.max(this.maxCandidates, this.index.counters.lastCandidates);
    }
  }

  /** Pick i through the grid and through the brute-force reference: equal ids, parts, handles. */
  agrees(i: number): boolean {
    const [x, y] = [this.points[2 * i] as number, this.points[2 * i + 1] as number];
    const ref = createPickHit();
    this.index.pickLinear(x, y, "mouse", ref);
    this.index.pick(x, y, "mouse", this.hit);
    return ref.id === this.hit.id && ref.part === this.hit.part && ref.handle === this.hit.handle;
  }
}

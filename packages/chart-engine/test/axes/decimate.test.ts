// E11-S06 decimation (README BQ-189 to BQ-191; E11-D02 §5): the AC scenarios on the time axis
// (400 bars over 1200 px), a seeded pan / zoom property (no label blinks, monotone retention),
// the last-price pin and the P0 shift-instead-of-drop at an area edge.
import { describe, expect, it } from "vitest";
import { mulberry32 } from "../../bench/fixtures/rng.mjs";
import { TickSet } from "../../src/axes/decimate.js";
import { ZoneClock } from "../../src/axes/format.js";
import { RANK, TIME_LADDER, TimeTicks } from "../../src/axes/time-ticks.js";
import { ChartViewport } from "../../src/viewport/index.js";
import { minuteMap } from "../interaction/fixtures.js";

const W = 1200;
const LABEL_H = 13;
const GAP = 1.5 * LABEL_H;

/** The time axis's kept set at the viewport's current state, labels `width` px wide. */
function retained(vp: ChartViewport, width = 34) {
  const set = new TickSet();
  const ticks = new TimeTicks(new ZoneClock());
  ticks.update(vp, W, 80, () => width, set);
  set.decimate(GAP, 0, W, Infinity); // no zones yet: nothing shifts (BQ-190)
  const kept = new Map<number, number>();
  for (let i = 0; i < set.n; i += 1) if (set.kept[i] === 1) kept.set(set.value[i] as number, i);
  return { set, kept, step: TIME_LADDER[ticks.step] as number };
}

function view(spacing = 3): ChartViewport {
  const vp = new ChartViewport(minuteMap(20_000));
  vp.setSize(W, 600, 1);
  vp.scrollTo(10_000, spacing);
  return vp;
}

/** Inside the area with its whole box: a label that could be shown in this frame. */
const fits = (s: TickSet, i: number): boolean =>
  (s.at[i] as number) - (s.size[i] as number) / 2 >= 0 &&
  (s.at[i] as number) + (s.size[i] as number) / 2 <= W;

describe("Scenario: Labels decimate instead of colliding", () => {
  it("400 bars over 1200 px: no two kept labels within 1.5 label heights", () => {
    for (const width of [34, 75, 120]) {
      const vp = view(W / 400);
      const { set, kept } = retained(vp, width);
      expect(kept.size).toBeGreaterThan(0);
      const boxes = [...kept.values()]
        .map((i) => [(set.pos[i] as number) - width / 2, (set.pos[i] as number) + width / 2])
        .sort((a, b) => (a[0] as number) - (b[0] as number));
      for (let k = 1; k < boxes.length; k += 1) {
        expect((boxes[k]?.[0] as number) - (boxes[k - 1]?.[1] as number)).toBeGreaterThanOrEqual(
          GAP,
        );
      }
      expect(boxes.every((b) => (b[0] as number) >= 0 && (b[1] as number) <= W)).toBe(true);
    }
  });

  it("the retained set is a stable subset as the user pans: no label blinks (seeded)", () => {
    const rng = mulberry32(387_001);
    for (let run = 0; run < 40; run += 1) {
      const width = 30 + rng() * 90;
      const vp = view(0.5 + rng() * 20);
      const sign = rng() < 0.5 ? -1 : 1;
      const seen = new Map<number, boolean[]>(); // per label: kept, in each frame it fits
      // Its kept state never changes while it is in view: nothing blinks.
      for (let f = 0; f < 30; f += 1) {
        vp.pan(sign * rng() * 40);
        const { set, kept } = retained(vp, width);
        for (let i = 0; i < set.n; i += 1) {
          if (!fits(set, i)) continue;
          const t = set.value[i] as number;
          seen.set(t, [...(seen.get(t) ?? []), kept.has(t)]);
        }
      }
      for (const [t, states] of seen) {
        const flips = states.filter((k, i) => i > 0 && k !== states[i - 1]).length;
        expect(flips, `run ${run}, label at ${t}: ${states.join()}`).toBe(0);
      }
    }
  });

  it("a label kept at zoom z is kept at every zoom ≥ z while in view (nested steps)", () => {
    const rng = mulberry32(387_002);
    for (let run = 0; run < 20; run += 1) {
      const width = 30 + rng() * 60;
      const vp = view(0.3 + rng() * 4);
      let prev = retained(vp, width);
      for (let z = 0; z < 25; z += 1) {
        vp.zoomAt(W / 2, 1.05);
        const next = retained(vp, width);
        // 3 h → 2 h, 15 m → 10 m and 15 s → 10 s drop marks the finer step lacks (C-62).
        const nested = prev.step % next.step === 0;
        for (const t of nested ? prev.kept.keys() : []) {
          const i = [...Array(next.set.n).keys()].find((k) => next.set.value[k] === t);
          if (i !== undefined && fits(next.set, i))
            expect(next.kept.has(t), `run ${run}`).toBe(true);
        }
        prev = next;
      }
    }
  });
});

describe("Scenario: The last-price label never hides behind a tick", () => {
  it("a tick within one label height of the pin is suppressed; the pin keeps its place", () => {
    const set = new TickSet();
    for (const y of [100, 160, 220, 280]) set.push(y, LABEL_H, 0, y, 0, `${y}`);
    const dropped = set.decimate(GAP, 0, 600, Infinity, 168, LABEL_H);
    expect(dropped).toBe(1);
    expect([...set.kept.slice(0, 4)]).toEqual([1, 0, 1, 1]);
  });
});

describe("exclusion zones (BQ-190)", () => {
  it("a P0 date crossing the area edge shifts in; an ordinary label drops", () => {
    const set = new TickSet();
    set.push(4, 40, RANK.day, 1, 2, "14 Oct");
    set.push(1196, 40, 3, 2, 0, "13:30");
    set.decimate(GAP, 0, W, RANK.day);
    expect([set.kept[0], set.kept[1]]).toEqual([1, 0]);
    expect([set.pos[0], set.at[0]]).toEqual([20, 4]); // the label moves, its line does not
  });

  it("stops adding at the cap", () => {
    const set = new TickSet();
    let n = 0;
    while (set.push(n, 1, 0, n, 0, "")) n += 1;
    expect(n).toBe(256);
  });
});

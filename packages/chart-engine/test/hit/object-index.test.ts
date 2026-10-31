// E11-S08: the object index against the ticket's scenarios (S2, S3, S5, S6 at index level) and
// its contract (BQ-127 to BQ-139). Times are bar i's open, i minutes; ticks 0..2 000 on 720 px.
import { describe, expect, it } from "vitest";
import { hitViewport, seedPickables } from "../../bench/scenes/hit-pick.js";
import { mulberry32 } from "../../bench/fixtures/rng.mjs";
import { bars } from "../../bench/scenes/pan-zero-upload.js";
import {
  MAX_OBJECTS,
  ObjectIndex,
  createPickHit,
  type Pickable,
  type PickGeometry,
} from "../../src/hit/index.js";
import { BarStore } from "../../src/model/BarStore.js";
import { ChartViewport, priceToScreen, timeToScreen } from "../../src/viewport/index.js";

const T = (i: number): number => i * 60e6;
const seg = (i0: number, p0: number, i1: number, p1: number): PickGeometry => ({
  type: "segment",
  t0: T(i0),
  p0,
  t1: T(i1),
  p1,
});

function setup(n = 10_000, now?: () => number) {
  const { store, viewport } = hitViewport(n);
  const index = new ObjectIndex(viewport, 0, "main", now);
  const hit = createPickHit();
  const add = (id: string, geometry: PickGeometry, more: Partial<Pickable> = {}): void =>
    index.registerPickable({
      id,
      kind: "drawing",
      paneId: "main",
      zIndex: 0,
      geometry,
      widthPx: 1,
      ...more,
    });
  const at = (i: number, p: number): [number, number] => [
    timeToScreen(viewport, T(i)),
    priceToScreen(viewport, 0, p),
  ];
  /** The grid's answer, checked against the brute-force reference. */
  const pick = (x: number, y: number, pointer: "mouse" | "touch" = "mouse") => {
    const ref = createPickHit();
    index.pickLinear(x, y, pointer, ref);
    index.pick(x, y, pointer, hit);
    expect(hit).toEqual(ref);
    return hit;
  };
  return { store, viewport, index, add, at, pick };
}

describe("Scenario: The front-most object wins", () => {
  it("three overlapping drawings at z 1, 5 and 3: the z 5 one", () => {
    const { add, at, pick } = setup();
    add("z1", seg(9_890, 1_000, 9_910, 1_000), { zIndex: 1 });
    add("z5", seg(9_900, 900, 9_900, 1_100), { zIndex: 5 });
    add("z3", seg(9_890, 900, 9_910, 1_100), { zIndex: 3 });
    expect(pick(...at(9_900, 1_000)).id).toBe("z5");
  });

  it("at one zIndex the closer wins; at one distance too, the later registration", () => {
    const { add, at, pick } = setup();
    add("far", { type: "hline", p: 1_010 }, { zIndex: 2 });
    add("near", { type: "hline", p: 1_000 }, { zIndex: 2 });
    expect(pick(...at(9_900, 1_002)).id).toBe("near");
    add("twin", { type: "hline", p: 1_000 }, { zIndex: 2 });
    expect(pick(...at(9_900, 1_002))).toMatchObject({ id: "twin", kind: "drawing" });
  });

  it("within one object a handle beats the body, even where the body is closer (BQ-131)", () => {
    const { add, at, pick } = setup();
    const handles = [
      { t: T(9_880), p: 1_000 },
      { t: T(9_920), p: 1_000 },
    ];
    add("s", seg(9_880, 1_000, 9_920, 1_000), { handles });
    const [x, y] = at(9_920, 1_000);
    expect(pick(x - 4, y)).toMatchObject({ id: "s", part: "handle", handle: 1, distancePx: 4 });
    expect(pick(...at(9_900, 1_000))).toMatchObject({ id: "s", part: "body", handle: -1 });
  });

  it("a matched handle's distance stands for its object; the nearest handle, earlier on a tie", () => {
    const { add, at, pick } = setup();
    const [x, y] = at(9_895, 1_000);
    expect(at(9_905, 1_000)[0] - x).toBeGreaterThan(20); // handle 1 is out of reach below
    const h = (i: number) => ({ t: T(i), p: 1_000 });
    add("s", seg(9_890, 1_000, 9_910, 1_000), { handles: [h(9_895), h(9_905), h(9_895)] });
    expect(pick(x + 1, y)).toMatchObject({ id: "s", part: "handle", handle: 0, distancePx: 1 });
    add("t", seg(9_890, 1_008, 9_910, 1_008)); // its body ~3 px off beats s's handle 8 px off
    expect(pick(x + 8, y)).toMatchObject({ id: "t", part: "body", handle: -1 });
  });
});

describe("Scenario: Touch gets a larger tolerance than mouse", () => {
  it("an order line 13 px away: touch picks it (16 px), mouse does not (10 px)", () => {
    const { index, at, pick } = setup();
    index.registerPickable({
      ...{ id: "o", kind: "order-line", paneId: "main", zIndex: 0, widthPx: 0 },
      geometry: { type: "hline", p: 1_000 },
    });
    const [x, y] = at(9_900, 1_000);
    expect(pick(x, y + 13, "touch")).toMatchObject({ id: "o", kind: "order-line" });
    expect(pick(x, y + 13, "mouse")).toMatchObject({ id: null, kind: "none" });
  });
});

describe("Scenario: A history prepend does not misplace objects", () => {
  it("a drawing at bar 120, then 2 000 bars prepended: found at its time and price", () => {
    const { store, viewport, index, add, at, pick } = setup();
    viewport.scrollTo(100);
    add("d", seg(120, 1_000, 130, 1_000));
    const before = at(125, 1_000);
    expect(pick(...before).id).toBe("d");
    const range = store.prepend(bars(2_000, T(-2_000)));
    viewport.scrollTo(2_100);
    expect(index.staleEntries()).toBe(1); // the probe sees the rebase owed
    index.onMutation(range);
    expect(at(125, 1_000)).toEqual(before);
    expect(pick(...before).id).toBe("d");
    expect([index.staleEntries(), index.counters.indexRebuilds]).toEqual([0, 0]);
  });

  it("an anchor past the last bar is re-placed as the map grows; an evicted one as it shrinks", () => {
    const { viewport, index, add, at, pick } = setup(1_000);
    const evicting = new BarStore({ maxBars: 1_000 });
    evicting.append(bars(1_000));
    viewport.setMap(evicting);
    viewport.scrollTo(900);
    add("future", { type: "vline", t: T(1_030) });
    add("old", seg(10, 500, 30, 600));
    add("mid", seg(950, 500, 960, 600));
    index.onMutation(evicting.append(bars(50, T(1_000))));
    index.onMutation(evicting.patch(0, bars(1, T(50))));
    expect(index.staleEntries()).toBe(0);
    viewport.scrollTo(900 - 50);
    expect(pick(...at(1_030, 1_000)).id).toBe("future");
    expect(pick(...at(955, 550)).id).toBe("mid");
    viewport.scrollTo(-50);
    expect(pick(...at(20, 550)).id).toBe("old");
    expect(evicting.length).toBe(1_000);
  });

  it("a replace is one counted rebuild", () => {
    const { store, index, add } = setup();
    add("d", seg(9_890, 1_000, 9_910, 1_000));
    index.onMutation(store.replace(bars(10_000)));
    expect([index.counters.indexRebuilds, index.staleEntries()]).toEqual([1, 0]);
  });
});

describe("Scenario: Panning does not rebuild the index", () => {
  it("250 objects, 300 pan frames (5 s at 60 Hz): no rebuild, every pick as brute force", () => {
    const { viewport, index, pick } = setup();
    const rng = mulberry32(3_890);
    seedPickables(index, viewport, rng, 200, 50);
    index.gesture = true;
    for (let f = 0; f < 300; f += 1) {
      viewport.pan(f < 150 ? 4 : -4);
      viewport.setPriceRange(0, f, 2_000 + f); // an autoscale following the pan
      pick(rng() * 1_216, rng() * 720);
    }
    expect(index.counters.indexRebuilds).toBe(0);
    expect(index.size).toBe(250);
  });

  it("a zoom past 4× defers its rebuild while the gesture lasts, then rebuilds once", () => {
    const { viewport, index, add, at, pick } = setup();
    add("d", seg(9_890, 1_000, 9_910, 1_100));
    index.gesture = true;
    viewport.zoomAt(600, 8);
    expect(pick(...at(9_900, 1_050)).id).toBe("d");
    expect(index.counters.indexRebuilds).toBe(0);
    index.gesture = false;
    expect(pick(...at(9_900, 1_050)).id).toBe("d");
    expect(index.counters.indexRebuilds).toBe(1);
    index.gesture = true; // a ring over RING_MAX buckets rebuilds even mid-gesture
    viewport.setPriceRange(0, 0, 4_000_000);
    viewport.zoomAt(600, 1 / 64);
    pick(...at(9_900, 1_050));
    expect(index.counters.indexRebuilds).toBe(2);
  });
});

describe("move across tables: each shape lands in its own structure", () => {
  const P = { type: "point", t: T(9_900), p: 1_000, radiusPx: 5 } as const;
  const RAY = { type: "ray", t0: T(9_900), p0: 1_000, t1: T(9_901), p1: 1_000 } as const;
  const cases: [string, PickGeometry, PickGeometry][] = [
    ["a 2 000 px bubble to a 5 px one", { ...P, radiusPx: 2_000 }, P],
    ["a ray to a point", { ...RAY, p0: 500, p1: 500 }, P],
    ["an hline to a point", { type: "hline", p: 500 }, P],
    ["a vline to a point", { type: "vline", t: T(9_800) }, P],
    ["a segment to an hline", seg(9_800, 500, 9_810, 500), { type: "hline", p: 1_000 }],
    ["a point to a ray", { ...P, p: 500 }, RAY],
  ];
  it.each(cases)("%s: no throw, picked as brute force picks it, nothing stale", (_, a, b) => {
    const { index, add, at, pick } = setup();
    add("o", a);
    expect(() => index.move("o", b)).not.toThrow();
    expect(pick(...at(9_900, 1_000)).id).toBe("o");
    expect(index.staleEntries()).toBe(0);
  });

  it("unplacing a slot missing from the unbounded list removes no other object", () => {
    const { index, add, at, pick } = setup();
    add("a", { type: "point", t: T(9_900), p: 1_000, radiusPx: 2_000 });
    add("b", { type: "point", t: T(9_900), p: 1_000, radiusPx: 2_000 });
    (index as unknown as { unbounded: number[] }).unbounded.shift(); // an inconsistent state
    index.unregister("a");
    expect(pick(...at(9_900, 1_000)).id).toBe("b");
  });
});

describe("the object index contract", () => {
  it("move and unregister touch only that object; a long segment joins the unbounded list", () => {
    const { index, add, at, pick } = setup();
    add("d", seg(9_890, 1_000, 9_910, 1_000));
    index.move("d", seg(9_890, 500, 9_910, 500));
    expect(pick(...at(9_900, 1_000)).id).toBeNull();
    expect(pick(...at(9_900, 500)).id).toBe("d");
    add("long", seg(0, 1_000 - 9_900 * 100, 9_900, 1_000)); // > MAX_CELLS cells
    expect(pick(...at(9_900, 1_000)).id).toBe("long");
    expect(index.unregister("d")).toBe(true);
    expect(index.unregister("d")).toBe(false);
    expect(pick(...at(9_900, 500)).id).toBeNull();
    add("e", seg(9_890, 500, 9_910, 500)); // reuses the freed slot
    expect(pick(...at(9_900, 500)).id).toBe("e");
    expect(() => index.move("d", seg(0, 0, 1, 1))).toThrow(/no d/);
    expect(index.counters.registered).toMatchObject({ drawing: 2, "order-line": 0 });
  });

  it("a 4 000 px line or a 2 000 px bubble joins the unbounded list: no rebuild per pick", () => {
    const { viewport, index, add, at, pick } = setup();
    seedPickables(index, viewport, mulberry32(7), 200, 50);
    add("fat", { type: "hline", p: 1_000 }, { widthPx: 4_000 });
    add("big", { type: "point", t: T(9_900), p: 1_000, radiusPx: 2_000 });
    for (let i = 0; i < 50; i += 1) pick(...at(9_850 + i * 2, 500 + i * 20));
    expect(index.counters.indexRebuilds).toBe(0);
    expect(index.counters.lastCandidates).toBeLessThan(252 / 4);
    index.unregister("fat");
    index.unregister("big");
    pick(...at(9_900, 1_000));
    expect(index.counters.indexRebuilds).toBe(0);
  });

  it("rejects structural kinds, other panes, duplicates and non-finite values (BQ-138)", () => {
    const { add } = setup();
    add("d", seg(1, 1, 2, 2));
    const bad: [Partial<Pickable>, RegExp][] = [
      [{ kind: "cell" as never }, /registerStructural/],
      [{ paneId: "other" }, /not ours/],
      [{ id: "d" }, /exists/],
      [{ widthPx: -1 }, /finite/],
      [{ zIndex: Number.NaN }, /finite/],
      [{ geometry: seg(1, Number.NaN, 2, 2) }, /not finite/],
      [{ geometry: { type: "point", t: 0, p: 0, radiusPx: -1 } }, /not finite/],
      [{ handles: [{ t: Infinity, p: 0 }] }, /not finite/],
    ];
    for (const [more, message] of bad)
      expect(() => add("x", seg(1, 1, 2, 2), more)).toThrow(message);
  });

  it("holds at most MAX_OBJECTS per pane", () => {
    const { add } = setup();
    for (let i = 0; i < MAX_OBJECTS; i += 1) add(`h${i}`, { type: "hline", p: i });
    expect(() => add("one-more", { type: "hline", p: 0 })).toThrow(/ceiling/);
  });

  it("projects bounds in CSS px for the DOM mirror (BQ-132, G-22)", () => {
    const { viewport, index, add, at } = setup();
    add("s", seg(9_890, 1_000, 9_910, 900), { widthPx: 4 });
    add("h", { type: "hline", p: 1_000 });
    add("v", { type: "vline", t: T(9_900) });
    add("b", { type: "point", t: T(9_900), p: 1_000, radiusPx: 5 }, { widthPx: 0 });
    add("r", { type: "ray", t0: T(9_900), p0: 1_000, t1: T(9_901), p1: 1_000 }, { widthPx: 0 });
    const out = [0, 0, 0, 0];
    const [x0, y0] = at(9_890, 1_000);
    const [x1, y1] = at(9_910, 900);
    expect(index.boundsOf("s", out) && out).toEqual([x0 - 2, y0 - 2, x1 + 2, y1 + 2]);
    expect(index.boundsOf("h", out) && out).toEqual([-0.5, y0 - 0.5, 1_216.5, y0 + 0.5]);
    const [xm] = at(9_900, 1_000);
    expect(index.boundsOf("v", out) && out).toEqual([xm - 0.5, -0.5, xm + 0.5, 720.5]);
    expect(index.boundsOf("b", out) && out).toEqual([xm - 5, y0 - 5, xm + 5, y0 + 5]);
    expect(index.boundsOf("r", out) && out).toEqual([xm, y0, viewport.plotWidth, y0]);
    expect(index.boundsOf("none", out)).toBe(false);
  });

  it.todo("mirror-node rects match pickable bounds within 1 px (E11-S13 #520, G-22)");

  it("counts candidates, and times picks into the histogram through an injected clock", () => {
    let t = 0;
    const { index, add, at } = setup(10_000, () => (t += 0.3)); // 300 µs a pick
    add("d", seg(9_890, 1_000, 9_910, 1_000));
    index.pick(...at(9_900, 1_000), "mouse", createPickHit());
    expect([index.counters.lastCandidates, index.counters.candidatesTested]).toEqual([1, 1]);
    expect(Array.from(index.counters.pickDurationUs)).toEqual([0, 0, 0, 0, 1, 0, 0, 0]);
    index.counters.observe(1e9);
    expect(index.counters.pickDurationUs[7]).toBe(1);
  });

  it("a zero-height plot or an empty index picks nothing", () => {
    const vp = new ChartViewport();
    const index = new ObjectIndex(vp);
    const hit = createPickHit();
    expect(index.pick(0, 0, "mouse", hit)).toBe(false);
    index.registerPickable({
      ...{ id: "h", kind: "alert-line", paneId: "main", zIndex: 0, widthPx: 1 },
      geometry: { type: "hline", p: 0 },
    });
    expect(index.pick(0, 0, "mouse", hit) || index.pickLinear(0, 0, "mouse", hit)).toBe(false);
  });

  it("a custom hitTest replaces the geometry's body distance", () => {
    const { add, at, pick } = setup();
    add("c", seg(9_890, 1_000, 9_910, 1_000), { hitTest: (x) => (x > 500 ? 0 : Infinity) });
    expect(pick(...at(9_900, 1_000)).id).toBe("c"); // x ≈ 543
    expect(pick(...at(9_880, 1_000)).id).toBeNull();
  });
});

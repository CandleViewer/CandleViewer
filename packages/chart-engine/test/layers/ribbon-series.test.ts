// E12-S07 PR B: RibbonSeries per frame and per pick. The blocks per kind (line 3 draws, area 4,
// baseline 6; the rest skip with `instances` 0), base B (the first visible close, clamped, or
// the user's tick; the disc reads the last close), the BQ-7 refusal (a theme without
// `color.chart.line` hides only these hosts), and the pick: the nearest point of the drawn line,
// never across a gap (R-2).
import { describe, expect, it } from "vitest";
import {
  CandleRing,
  createBarHit,
  FLAG_GAP_BEFORE,
  RIBBON_GEOM,
  RIBBON_PART,
  RibbonSeries,
  ribbonX,
} from "../../src/layers/index.js";
import { BarStore } from "../../src/model/index.js";
import { SceneGraph } from "../../src/scene/graph.js";
import { ChartViewport, createPaneUniforms, writePaneUniforms } from "../../src/viewport/index.js";
import { projectRel } from "../../src/viewport/transform.js";
import { THEME } from "./fixtures.js";

const LINE_THEME = { ...THEME, "color.chart.line": "#8b5cf6" };
const CLOSES = [10, 14, 12, 18, 9, 11];

function setup(flags = new Uint8Array(CLOSES.length), dpr = 1) {
  const store = new BarStore({ initialCapacity: 8 });
  const ring = new CandleRing();
  const close = Int32Array.from(CLOSES);
  ring.sync(
    store,
    store.append({
      time: Float64Array.from(CLOSES, (_, i) => i * 60e6),
      open: close.slice(),
      high: close.map((c) => c + 1),
      low: close.map((c) => c - 1),
      close,
      volume: new Float32Array(CLOSES.length).fill(1),
      flags,
      priceOrigin: 0,
      tickSize: 1,
    }),
  );
  const vp = new ChartViewport(store);
  vp.setSize(200, 100, dpr);
  vp.setPanePlot(0, 0, 100);
  vp.setPriceInfo(0, 0, 1);
  vp.setPriceRange(0, 0, 20);
  vp.setTimeRange(-30e6, 330e6); // ≈ 33 CSS px a bar
  const b = createPaneUniforms();
  writePaneUniforms(vp, 0, b);
  b.floats[4] = 200 * dpr;
  b.floats[5] = 100 * dpr;
  return { store, ring, vp, b };
}

describe("RibbonSeries blocks per kind", () => {
  it.each([
    ["line", [0, 0, 0, -1, -1, 1], [0, 0, 0, 0, 1, 2]],
    ["area", [-1, 0, 0, -1, -1, 1], [3, 0, 0, 0, 1, 2]],
    ["baseline", [-1, -1, 1, -1, -1, 1], [4, 5, 6, 0, 1, 2]],
  ] as const)("%s: instances %j, parts %j", (kind, instances, parts) => {
    const { ring } = setup();
    const r = new RibbonSeries(ring, kind);
    r.frame(33, 1, 0);
    expect(r.blocks.map((b) => b.instances)).toEqual(instances);
    expect(r.blocks.map((b) => b.ints[0])).toEqual(parts);
    for (const blk of r.blocks) {
      expect([blk.ints[1], blk.ints[2], blk.ints[3]]).toEqual([ring.head, ring.capacity - 1, 6]);
    }
    expect(r.blocks.filter((b) => b.instances !== 0)).toHaveLength(
      { line: 3, area: 4, baseline: 6 }[kind],
    );
  });

  it("B is the first visible close (clamped into the bars held), or the user's tick", () => {
    const { ring } = setup();
    const r = new RibbonSeries(ring, "baseline");
    const base = (): number[] => r.blocks.map((b) => b.base ?? NaN);
    r.frame(33, 1, 2);
    expect(base()).toEqual([12, 12, 12, 12, 12, 11]); // the disc: the last close
    r.frame(33, 1, -4);
    expect(base()[2]).toBe(10);
    r.frame(33, 1, 40);
    expect(base()[2]).toBe(11);
    r.baseTick = 15;
    r.frame(33, 1, 2);
    expect(base().slice(0, 3)).toEqual([15, 15, 15]);
  });

  it("an empty ring draws nothing; a kind switch changes the labels, not the blocks' arrays", () => {
    const r = new RibbonSeries(new CandleRing(), "area");
    r.frame(10, 1);
    expect(r.blocks.every((b) => b.instances === 0)).toBe(true);
    const ints = r.blocks.map((b) => b.ints);
    r.setKind("baseline");
    expect(r.blocks.map((b) => b.label)).toEqual(
      ["above", "below", "base", "stroke", "join", "last"].map((p) => `series.baseline.${p}`),
    );
    expect(r.blocks.map((b) => b.ints)).toEqual(ints);
  });
});

describe("RibbonSeries theme (BQ-7)", () => {
  it("a theme without color.chart.line is refused and hides only these hosts", () => {
    const { ring, vp } = setup();
    const graph = new SceneGraph();
    graph.addPane("main");
    const r = new RibbonSeries(ring, "line");
    const deps = {
      viewport: vp,
      pane: 0,
      theme: () => ({
        palette: "default" as const,
        convention: "standard" as const,
        colors: THEME,
      }),
    };
    const hosts = r.mount(graph, "main", "series.line.0.0", deps);
    expect(ring.nodes).toEqual(hosts.map((h) => h.id));
    expect(r.setTheme(THEME)?.token).toBe("color.chart.line");
    expect(hosts.map((h) => h.visible)).toEqual(Array(6).fill(false));
    expect(r.setTheme(LINE_THEME)).toBeNull();
    expect(hosts.map((h) => h.visible)).toEqual(Array(6).fill(true));
    r.setActive(false);
    expect(hosts.some((h) => h.visible)).toBe(false);
  });
});

describe("RibbonSeries hit-testing: the nearest point of the drawn line", () => {
  const pt = (b: ReturnType<typeof setup>["b"], i: number, dpr = 1): [number, number] => [
    ribbonX(i, b.floats, b.ints[0] ?? 0, false) / dpr,
    projectRel(b.floats, (CLOSES[i] ?? 0) - (b.ints[1] ?? 0)) / dpr,
  ];

  it.each([1, 1.5, 2])("dpr %f: on a vertex, near a segment, and a miss", (dpr) => {
    const { ring, b } = setup(undefined, dpr);
    const r = new RibbonSeries(ring, "line");
    r.setTheme(LINE_THEME);
    r.frame(33, dpr, 0);
    const hit = createBarHit();
    const [x2, y2] = pt(b, 2, dpr);
    expect(r.hitTest(x2, y2, 2, b.floats, b.ints[0] ?? 0, b.ints[1] ?? 0, 10, hit)).toBe(true);
    expect([hit.index, hit.part, hit.distancePx]).toEqual([2, RIBBON_PART.stroke, 0]);
    // A point on segment 2 → 3, a quarter of the way: bar 2 is nearer; three quarters: bar 3.
    const [x3, y3] = pt(b, 3, dpr);
    const at = (t: number): [number, number] => [x2 + (x3 - x2) * t, y2 + (y3 - y2) * t];
    expect(r.hitTest(...at(0.25), 2, b.floats, b.ints[0] ?? 0, b.ints[1] ?? 0, 10, hit)).toBe(true);
    expect(hit.index).toBe(2);
    expect(r.hitTest(...at(0.75), 3, b.floats, b.ints[0] ?? 0, b.ints[1] ?? 0, 10, hit)).toBe(true);
    expect(hit.index).toBe(3);
    // 20 CSS px below the vertex (the segments run elsewhere): outside a 10 px tolerance.
    const half = (r.geom[RIBBON_GEOM.stroke] ?? 0) / 2 / dpr;
    expect(r.hitTest(x2, y2 + 20, 2, b.floats, b.ints[0] ?? 0, b.ints[1] ?? 0, 30, hit)).toBe(true);
    expect(hit.distancePx).toBeLessThanOrEqual(20 - half + 1e-9);
    expect(r.hitTest(x2, y2 + 40, 2, b.floats, b.ints[0] ?? 0, b.ints[1] ?? 0, 10, hit)).toBe(
      false,
    );
    expect([hit.index, hit.part]).toEqual([-1, -1]);
  });

  it("R-2: no segment across a gap_before bar is hit; undrawable, inactive or out of range: none", () => {
    const flags = Uint8Array.of(0, 0, 0, FLAG_GAP_BEFORE, 0, 0);
    const { ring, b } = setup(flags);
    const r = new RibbonSeries(ring, "line");
    r.setTheme(LINE_THEME);
    r.frame(33, 1, 0);
    const hit = createBarHit();
    const [x2, y2] = pt(b, 2);
    const [x3, y3] = pt(b, 3);
    const mid: [number, number] = [(x2 + x3) / 2, (y2 + y3) / 2];
    const args = [b.floats, b.ints[0] ?? 0, b.ints[1] ?? 0, 2, hit] as const;
    expect(r.hitTest(...mid, 2, ...args)).toBe(false);
    const whole = setup().ring;
    const joined = new RibbonSeries(whole, "line");
    joined.setTheme(LINE_THEME);
    joined.frame(33, 1, 0);
    expect(joined.hitTest(...mid, 2, ...args)).toBe(true);
    joined.setActive(false);
    expect(joined.hitTest(...mid, 2, ...args)).toBe(false);
    expect(r.hitTest(x2, y2, 9, ...args)).toBe(false);
    expect(new RibbonSeries(ring).hitTest(x2, y2, 2, ...args)).toBe(false); // no theme yet
  });
});

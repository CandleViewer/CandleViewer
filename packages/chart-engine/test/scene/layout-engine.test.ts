// E11-S01 PR3: the layout engine and a 600-frame draw-trace determinism run (26 §3.1, §14).
import { describe, expect, it } from "vitest";
import { mulberry32 } from "../../bench/fixtures/rng.mjs";
import { BatchBuilder } from "../../src/scene/batch-builder.js";
import { LAYER_ORDER } from "../../src/scene/dirty.js";
import { FrameScheduler } from "../../src/scene/frame-scheduler.js";
import { SceneGraph } from "../../src/scene/graph.js";
import { LayoutEngine, type PaneLayout } from "../../src/scene/layout-engine.js";
import { NullSeries } from "../../src/scene/null-series.js";
import { TestClock } from "./test-clock.js";

function chart(panes: number, nodes = 0) {
  const graph = new SceneGraph();
  const layout = new LayoutEngine(graph);
  const trace: string[] = [];
  const builder = new BatchBuilder(graph, {
    uploadSubRange: (b, from, to) => trace.push(`u ${b.nodeId} ${from} ${to}`),
  });
  const clock = new TestClock();
  const hooks = { layout: () => layout.run(), build: builder.build.bind(builder) };
  const scheduler = new FrameScheduler(graph, clock, hooks);
  const all: NullSeries[] = [];
  for (let p = 0; p < panes; p += 1) graph.addPane(`p${p}`);
  for (let k = 0; k < nodes; k += 1) all.push(new NullSeries(`n${k}`));
  const frame = (): void => {
    scheduler.wake();
    clock.tick();
  };
  return { graph, layout, builder, trace, clock, scheduler, all, frame };
}

describe("LayoutEngine: pane rects, gutters and height ratios", () => {
  it("recomputes only on LAYOUT: pans, themes and data never relayout", () => {
    const { graph, layout, frame } = chart(1);
    graph.addNode("p0", "series", new NullSeries("s"));
    layout.addPane("p0");
    layout.setSize(800, 600);
    frame();
    for (const mark of [
      () => graph.markViewport(),
      () => graph.markTheme(),
      () => graph.markData("s"),
    ]) {
      mark();
      frame();
    }
    layout.setSize(800, 600); // unchanged: no mark
    frame();
    expect([layout.computes, graph.rebuilds]).toEqual([1, 1]);
    layout.setSize(1000, 600);
    frame();
    expect([layout.computes, layout.panes[0]?.rect[2]]).toEqual([2, 936]);
  });

  it("an explicit share rescales the others into the rest; the panes tile the plot exactly", () => {
    const { layout, frame } = chart(3);
    for (const [p, r] of [
      [0, 1],
      [1, 0.5],
      [2, 0.25],
    ] as const)
      layout.addPane(`p${p}`, r);
    layout.setSize(864, 724);
    frame();
    expect(layout.panes.map((p) => p.share)).toEqual([0.375, 0.375, 0.25]);
    expect(layout.panes.map((p) => [...p.rect, ...p.priceAxis])).toEqual([
      [0, 0, 800, 263, 800, 0, 64, 263],
      [0, 263, 800, 262, 800, 263, 64, 262],
      [0, 525, 800, 175, 800, 525, 64, 175],
    ]);
    expect(layout.timeAxis).toEqual([0, 700, 800, 24]);
    expect(() => layout.addPane("nope")).toThrow(RangeError);
    expect(() => layout.addPane("p0", 0)).toThrow(RangeError);
    expect(() => layout.setHeightRatio("p0", 1.5)).toThrow(RangeError);
    expect(() => layout.setHeightRatio("p9", 1)).toThrow(RangeError);
  });
});

/** Sums in index order: the order the layout engine and every consumer add them in. */
const sum = (xs: readonly number[]): number => xs.reduce((a, b) => a + b, 0);

describe("LayoutEngine: shares, minimum height and collapse (E11-S09, BQ-11)", () => {
  it("addPane without a share gives equal shares; setHeightRatio rescales the others", () => {
    const { layout, frame } = chart(3);
    for (let p = 0; p < 3; p += 1) layout.addPane(`p${p}`);
    const shares = (): number[] => layout.panes.map((p) => p.share);
    expect(shares()).toEqual([1, 1, 1].map(() => expect.closeTo(1 / 3, 12)));
    layout.setHeightRatio("p0", 0.6);
    expect([shares(), sum(shares())]).toEqual([
      [0.6, 0.2, 0.2].map((x) => expect.closeTo(x, 12)),
      1,
    ]);
    layout.setSize(864, 524);
    frame();
    expect(layout.panes.map((p) => p.rect[3])).toEqual([300, 100, 100]);
  });

  it("a share below the minimum collapses to the stub, whose px come out first", () => {
    const { graph, layout, frame } = chart(3);
    for (let p = 0; p < 3; p += 1) layout.addPane(`p${p}`);
    layout.setSize(864, 424); // plot 400 px
    layout.setHeightRatio("p1", 0.1); // 40 px < 48: folds
    frame();
    expect(layout.panes.map((p) => p.collapsed)).toEqual([false, true, false]);
    expect(layout.panes.map((p) => p.share)).toEqual(
      [0.5, 0, 0.5].map((x) => expect.closeTo(x, 12)),
    );
    expect(layout.panes.map((p) => p.rect[3])).toEqual([184, 32, 184]); // (400 - 32) / 2
    expect(graph.get("p1")?.visible).toBe(false); // no draws; the rings stay attached
    layout.setChrome(24, 13); // compact: a 24 px stub, the minimum still 48 (D02:96)
    frame();
    expect([layout.minPx, layout.panes.map((p) => p.rect[3])]).toEqual([48, [188, 24, 188]]);
  });

  it("restores to max(last share, minimum) and never folds the last open pane", () => {
    const { graph, layout, frame } = chart(2);
    layout.addPane("p0");
    layout.addPane("p1");
    layout.setSize(864, 424);
    frame();
    expect(layout.setCollapsed("p1", true)).toBe(true);
    expect(layout.setCollapsed("p0", true)).toBe(false); // the only open pane
    frame();
    expect(layout.panes.map((p) => p.rect[3])).toEqual([368, 32]);
    expect(layout.setCollapsed("p1", false)).toBe(true);
    frame();
    expect([layout.panes[1]?.share, graph.get("p1")?.visible]).toEqual([0.5, true]);
    layout.setHeightRatio("p1", 0.05); // 20 px: folds, remembering 0.05
    frame();
    expect(layout.panes[1]?.collapsed).toBe(true);
    layout.setCollapsed("p1", false); // back to the minimum, 48 of 400 px, not 0.05
    frame();
    expect([layout.panes[1]?.share, layout.panes[1]?.rect[3]]).toEqual([48 / 400, 48]);
  });

  it("property: shares sum to exactly 1 and pane px plus stub px tile the plot (seeded)", () => {
    const rng = mulberry32(20261104);
    const int = (n: number): number => Math.floor(rng() * n);
    for (let c = 0; c < 500; c += 1) {
      const n = 1 + int(6);
      const { layout, frame } = chart(n);
      for (let p = 0; p < n; p += 1)
        layout.addPane(`p${p}`, int(2) === 0 ? undefined : Math.min(1, 0.01 + rng()));
      for (let op = int(8); op > 0; op -= 1) {
        const id = `p${int(n)}`;
        const ratio = int(3) !== 0;
        if (!ratio) layout.setCollapsed(id, int(2) === 0);
        else layout.setHeightRatio(id, Math.min(1, 0.001 + rng()));
        if (int(2) === 0) layout.setSize(200 + int(1600), int(1200));
        if (int(2) === 0) layout.setChrome(int(2) === 0 ? 24 : 32, int(2) === 0 ? 13 : 16);
        frame();
        // m2: after a share mutation every open pane but a sole one keeps the minimum (± 1 px).
        const open = layout.panes.filter((p) => !p.collapsed);
        if (!ratio || layout.height <= 24 || open.length < 2) continue;
        for (const p of open)
          expect(p.rect[3], `case ${c} ${p.id}`).toBeGreaterThanOrEqual(layout.minPx - 1);
      }
      const ps = layout.panes;
      let y = 0;
      let tiled = true;
      for (const p of ps) {
        tiled &&= p.rect[1] === y && Number.isInteger(p.rect[3]) && p.rect[3] >= 0;
        y += p.rect[3];
      }
      const got = [sum(ps.map((p) => p.share)), y, ps.some((p) => !p.collapsed), tiled];
      expect(got, `case ${c}`).toEqual([1, Math.max(0, layout.height - 24), true, true]);
    }
  });

  it("property: a partial setShares rescales only proportionally; the unlisted fill 1 - listed (BQ-3a)", () => {
    // Ruling R58 (BQ-3a): the listed panes take their shares; each unlisted open pane is scaled by
    // the one factor (1 - listed) / (its old sum), so the unlisted keep their mutual ratios.
    const rng = mulberry32(20261105);
    const int = (n: number): number => Math.floor(rng() * n);
    const near = (x: number): unknown => expect.closeTo(x, 12);
    for (let c = 0; c < 500; c += 1) {
      const n = 2 + int(6);
      const { layout } = chart(n);
      for (let p = 0; p < n; p += 1) layout.addPane(`p${p}`, 0.05 + 0.95 * rng());
      const fold = n > 2 && int(2) === 0 ? `p${int(n)}` : null; // an unlisted stub stays at 0
      if (fold !== null) layout.setCollapsed(fold, true);
      const ids = layout.panes.map((p) => p.id).filter((id) => id !== fold);
      const k = 1 + int(ids.length - 1); // at least one open pane stays unlisted
      const listed = ids.sort(() => rng() - 0.5).slice(0, k);
      const entries = listed.map((id) => [id, 0.001 + (0.95 / k) * rng()] as const);
      const before = new Map(layout.panes.map((p) => [p.id, p.share]));
      layout.setShares(entries);
      const after = new Map(layout.panes.map((p) => [p.id, p.share]));
      const taken = sum(entries.map(([, r]) => r));
      const free = ids.filter((id) => !listed.includes(id));
      const factor = (1 - taken) / sum(free.map((id) => before.get(id) ?? 0));
      const got = {
        listed: entries.map(([id]) => after.get(id)),
        unlisted: free.map((id) => after.get(id)),
        fill: sum(free.map((id) => after.get(id) ?? 0)),
        stub: fold === null ? 0 : after.get(fold),
      };
      expect(got, `case ${c}`).toEqual({
        listed: entries.map(([, r]) => near(r)),
        unlisted: free.map((id) => near((before.get(id) ?? 0) * factor)),
        fill: near(1 - taken),
        stub: 0,
      });
    }
  });
});

/** A scripted 600-frame session: seeded marks, data patches, resizes and frame gaps; its trace. */
function session(seed: number): string[] {
  const rng = mulberry32(seed);
  const int = (n: number): number => Math.floor(rng() * n);
  const { graph, layout, builder, trace, clock, scheduler, all } = chart(3, 12);
  all.forEach((n, k) => {
    [n.program, n.texture, n.count] = [int(3), int(2), 1 + int(500)];
    graph.addNode(`p${k % 3}`, LAYER_ORDER[int(6)] ?? "series", n);
    if (k < 3) layout.addPane(`p${k}`, 1 / (k + 1));
  });
  for (let f = 0; f < 600; f += 1) {
    const [op, n] = [int(10), all[int(12)] as NullSeries];
    if (op < 6) graph.markViewport();
    if (op === 8) layout.setSize(1280, 700 + int(200));
    if (op === 9)
      builder.patch(n.id, { op: "patch", from: int(n.count), to: n.count, indexShift: 0 });
    if (op === 9) graph.markData(n.id);
    scheduler.wake();
    clock.tick(1 + int(20));
    const list = builder.drawList
      .slice(0, builder.drawCount)
      .map((b) => `${b.nodeId}:${b.program}`);
    trace.push(`f ${f} lod ${scheduler.lod} shed ${scheduler.shedLevel} ${list}`);
  }
  return trace;
}

describe("Determinism: TestClock + seeded RNG", () => {
  it("a 600-frame scripted session produces an identical draw trace across runs", () => {
    const a = session(20261030);
    expect(session(20261030)).toEqual(a);
    expect([a.filter((l) => l.startsWith("f ")).length, a.some((l) => l.startsWith("u "))]).toEqual(
      [600, true],
    );
    expect(session(20261031)).not.toEqual(a); // the trace does depend on the script
  });
});

describe("LayoutEngine: removal, absorb and the handoff copy (E11-S09, BQ-11a)", () => {
  const row = (p: PaneLayout): unknown[] => [p.id, p.key, p.share, p.collapsed];
  const near = (x: number): unknown => expect.closeTo(x, 12);

  it("removePane renormalises the rest; leaving only stubs reopens the last", () => {
    const { graph, layout } = chart(3);
    for (let p = 0; p < 3; p += 1) layout.addPane(`p${p}`);
    layout.setHeightRatio("p0", 0.5); // p1 and p2 0.25 each
    layout.removePane("p1");
    expect(layout.panes.map(row)).toEqual([
      ["p0", 0, near(2 / 3), false],
      ["p2", 2, near(1 / 3), false],
    ]);
    expect(layout.setCollapsed("p2", true)).toBe(true);
    layout.removePane("p0"); // only the stub p2 is left: it reopens with the whole plot
    expect([layout.panes.map(row), graph.get("p2")?.visible]).toEqual([
      [["p2", 2, 1, false]],
      true,
    ]);
  });

  it("absorb gives slot 0 the next pane's key, share and collapse; that row goes", () => {
    const { layout } = chart(3);
    for (let p = 0; p < 3; p += 1) layout.addPane(`p${p}`);
    layout.setHeightRatio("p1", 0.5); // p0 and p2 0.25 each
    layout.absorb("p0", "p1");
    expect(layout.panes.map(row)).toEqual([
      ["p0", 1, near(2 / 3), false],
      ["p2", 2, near(1 / 3), false],
    ]);
    const two = chart(2);
    for (let p = 0; p < 2; p += 1) two.layout.addPane(`p${p}`);
    expect(two.layout.setCollapsed("p1", true)).toBe(true);
    two.layout.absorb("p0", "p1"); // p0 takes the stub's collapse: only stubs left, so it reopens
    expect([two.layout.panes.map(row), two.graph.get("p0")?.visible]).toEqual([
      [["p0", 1, 1, false]],
      true,
    ]);
  });

  it("copyFrom gives each slot the old slot's key, share, last share and collapse", () => {
    const old = chart(3);
    for (let p = 0; p < 3; p += 1) old.layout.addPane(`p${p}`, undefined, 10 + p);
    old.layout.setHeightRatio("p0", 0.6);
    expect(old.layout.setCollapsed("p2", true)).toBe(true);
    const { graph, layout } = chart(3);
    for (let p = 0; p < 3; p += 1) layout.addPane(`p${p}`);
    layout.copyFrom(old.layout.panes);
    const full = (p: PaneLayout): unknown[] => [...row(p), p.lastShare];
    expect(layout.panes.map(full)).toEqual(old.layout.panes.map(full));
    expect([10, 11, 12].map((k) => layout.byKey(k)?.id)).toEqual(["p0", "p1", "p2"]);
    expect(graph.get("p2")?.visible).toBe(false);
  });
});

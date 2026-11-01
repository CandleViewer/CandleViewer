// E11-S09 (#446 BQ-11, the proposed default) in the layout engine: the splitter drag moves only the
// two panes beside a boundary, a pane pushed below max(48, 3 x label box) collapses to a stub row
// with its share remembered, and a restore gives back max(that share, the minimum).
import { describe, expect, it } from "vitest";
import { mulberry32 } from "../../bench/fixtures/rng.mjs";
import { LayoutEngine, SceneGraph } from "../../src/scene/index.js";
import {
  MIN_PANE_PX,
  minPaneHeight,
  SPLIT,
  STUB_PX,
  STUB_PX_COMFORTABLE,
} from "../../src/scene/layout-engine.js";

/** Panes a, b, c at 60 / 20 / 20 of a 600 px plot (624 px under the 24 px time strip). */
function stack(): LayoutEngine {
  const g = new SceneGraph();
  const layout = new LayoutEngine(g);
  for (const id of ["a", "b", "c"]) {
    g.addPane(id);
    layout.addPane(id);
  }
  layout.setSize(664, 624);
  layout.setWeights(
    new Map([
      ["a", 0.6],
      ["b", 0.2],
      ["c", 0.2],
    ]),
  );
  layout.run();
  return layout;
}

const heights = (l: LayoutEngine): number[] => l.panes.map((p) => p.rect[3]);
const sum = (xs: number[]): number => xs.reduce((s, x) => s + x, 0);

describe("Scenario: A pane too small to read collapses honestly (layout)", () => {
  it("test_minPaneHeight_labelBox_isTheLargerOf48AndThreeBoxes", () => {
    expect(MIN_PANE_PX).toBe(48);
    expect(minPaneHeight()).toBe(48);
    expect(minPaneHeight(12)).toBe(48);
    expect(minPaneHeight(20)).toBe(60);
    expect([STUB_PX, STUB_PX_COMFORTABLE]).toEqual([24, 32]);
  });

  it("test_dragSplitter_withinBounds_movesOnlyTheTwoPanesBesideIt", () => {
    const l = stack();
    expect(heights(l)).toEqual([360, 120, 120]);
    expect(l.dragSplitter(0, -60)).toBe(SPLIT.moved);
    expect(l.dragSplitter(0, 0)).toBe(SPLIT.none);
    l.run();
    expect(heights(l)).toEqual([300, 180, 120]);
    expect(sum(l.panes.map((p) => p.share))).toBe(1);
  });

  it("test_dragSplitter_belowTheMinimum_collapsesToAStubAndRemembersTheShare", () => {
    const l = stack();
    expect(l.dragSplitter(1, 70)).toBe(SPLIT.moved); // c: 120 -> 50
    const share = l.panes[2]?.share ?? 0;
    expect(l.dragSplitter(1, 5)).toBe(SPLIT.collapsed); // 45 < 48
    l.run();
    expect(l.panes.map((p) => p.collapsed)).toEqual([false, false, true]);
    expect(heights(l)).toEqual([...heights(l).slice(0, 2), STUB_PX]);
    expect(sum(heights(l))).toBe(600);
    expect(l.panes[2]?.share).toBe(share); // remembered, not 0
    expect(l.dragSplitter(1, 10)).toBe(SPLIT.none); // a stub never shrinks
    expect(l.dragSplitter(1, -10)).toBe(SPLIT.restored); // growing it restores it
    l.run();
    expect(l.panes[2]?.collapsed).toBe(false);
    expect(l.panes[2]?.rect[3]).toBeGreaterThanOrEqual(MIN_PANE_PX);
  });

  it("test_dragSplitter_paneAboveBelowTheMinimum_collapsesThePaneAbove", () => {
    const l = stack();
    expect(l.dragSplitter(1, -100)).toBe(SPLIT.collapsed); // b: 120 -> 20
    expect(l.panes[1]?.collapsed).toBe(true);
    expect(l.dragSplitter(0, 10)).toBe(SPLIT.none); // down would shrink the stub
    expect(l.dragSplitter(0, -10)).toBe(SPLIT.restored); // up grows it back
    expect(l.dragSplitter(5, 10)).toBe(SPLIT.none); // no such boundary
  });

  it("test_setCollapsed_restore_givesTheLargerOfTheLastShareAndTheMinimum", () => {
    const l = stack();
    l.setWeights(new Map([["c", 0.01]])); // a share far below 48 px
    expect(l.setCollapsed("c", true)).toBe(true);
    expect(l.setCollapsed("c", true)).toBe(false);
    expect(l.setCollapsed("nope", true)).toBe(false);
    expect(l.setCollapsed("c", false)).toBe(true);
    l.run();
    expect(l.panes[2]?.share).toBeCloseTo(48 / 600, 6);
    expect(l.panes[2]?.rect[3]).toBe(48);
    expect(sum(l.panes.map((p) => p.share))).toBe(1);
  });

  it("test_setCollapsed_lastExpandedPane_isRefused", () => {
    const l = stack();
    expect(l.setCollapsed("a", true)).toBe(true);
    expect(l.setCollapsed("b", true)).toBe(true);
    expect(l.setCollapsed("c", true)).toBe(false);
    l.removePane("c"); // only stubs left: the stack expands again
    expect(l.panes.map((p) => p.collapsed)).toEqual([false, false]);
  });

  it("test_dragSplitter_seededDrags_tileThePlotExactlyAndKeepEveryExpandedPaneReadable", () => {
    const next = mulberry32(446_011); // C-38: a seeded loop, no fast-check
    for (let run = 0; run < 200; run += 1) {
      const l = stack();
      const n = Math.floor(next() * 40);
      for (let m = 0; m < n; m += 1)
        l.dragSplitter(next() < 0.5 ? 0 : 1, Math.round((next() - 0.5) * 180));
      l.run();
      expect(sum(heights(l)), `run ${run}`).toBe(600);
      expect(sum(l.panes.map((p) => p.share)), `run ${run}`).toBe(1);
      for (const p of l.panes) {
        if (p.collapsed) expect(p.rect[3]).toBe(STUB_PX);
        else expect(p.rect[3], `run ${run}`).toBeGreaterThanOrEqual(MIN_PANE_PX - 1); // rounding
        expect(p.ratio).toBeGreaterThan(0);
        expect(p.ratio).toBeLessThanOrEqual(1);
      }
      expect(l.panes.some((p) => !p.collapsed)).toBe(true);
    }
  });

  it("test_setCollapsed_seededRestores_theRestoredPaneIsAlwaysAtLeastTheMinimum", () => {
    const next = mulberry32(446_012); // C-38: 3000 seeded stacks, the lens's fuzz
    for (let run = 0; run < 3000; run += 1) {
      const g = new SceneGraph();
      const l = new LayoutEngine(g);
      const n = 2 + Math.floor(next() * 4);
      const ids = Array.from({ length: n }, (_, i) => `p${i}`);
      for (const id of ids) {
        g.addPane(id);
        l.addPane(id, 0.001 + next() * 0.999);
      }
      l.setSize(664, 160 + Math.floor(next() * 900));
      if (next() < 0.5) l.stubPx = STUB_PX_COMFORTABLE;
      for (const id of ids) if (next() < 0.6) l.setCollapsed(id, true);
      const pick = ids[Math.floor(next() * n)] as string;
      l.setCollapsed(pick, true);
      l.setCollapsed(pick, false);
      l.run();
      const row = l.panes.find((p) => p.id === pick);
      const others = l.panes.filter((p) => !p.collapsed && p !== row).length;
      const room = l.height - 24 - l.panes.filter((p) => p.collapsed).length * l.stubPx;
      if (row?.collapsed === false && others > 0 && room > 2 * MIN_PANE_PX) {
        expect(row.rect[3], `run ${run}`).toBeGreaterThanOrEqual(MIN_PANE_PX);
      }
      expect(sum(l.panes.map((p) => p.share))).toBe(1);
      for (const p of l.panes) expect(p.ratio).toBeLessThanOrEqual(1);
    }
  });
});

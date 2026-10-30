// E11-S01 property test, 10 000 seeded cases (a mulberry32 loop, BQ-21): no node is collected while
// clean; a visible marked node is collected next frame unless deferred; a deferred, hidden or
// failed node keeps exactly its marks; a critical node is never deferred.
import { describe, expect, it } from "vitest";
import { mulberry32 } from "../../bench/fixtures/rng.mjs";
import { DeferClass, Dirty, DIRTY_ALL, LAYER_ORDER } from "../../src/scene/dirty.js";
import { FrameContext } from "../../src/scene/frame-context.js";
import { SceneGraph } from "../../src/scene/graph.js";
import { NullSeries } from "../../src/scene/null-series.js";
import { PooledBatchSink } from "../../src/scene/pool.js";

describe("property: dirty flags survive until a successful collect, never longer", () => {
  it("holds for 10 000 seeded random trees and sequences", { timeout: 60_000 }, () => {
    const rng = mulberry32(20261029);
    const int = (n: number): number => Math.floor(rng() * n);
    const failures: string[] = [];
    const seen = { cleared: 0, deferred: 0 };
    for (let c = 0; c < 10_000; c += 1) {
      const graph = new SceneGraph();
      const want = new Map<NullSeries, number>();
      const panes = 1 + int(3);
      for (let p = 0; p < panes; p += 1) {
        graph.addPane(`p${p}`);
        for (let k = int(5); k > 0; k -= 1) {
          const critical = rng() < 0.15;
          const deferClass = critical ? 0 : (int(5) as DeferClass);
          const node = new NullSeries(`p${p}:${k}`, { critical, deferClass, zIndex: int(3) });
          graph.addNode(`p${p}`, LAYER_ORDER[int(6)] ?? "series", node);
          want.set(node, DIRTY_ALL);
        }
      }
      const nodes = [...want.keys()];
      const mark = (flag: number, prefix = "", only?: NullSeries): void => {
        for (const n of nodes) {
          if (n.id.startsWith(prefix) && (only ?? n) === n) want.set(n, (want.get(n) ?? 0) | flag);
        }
      };
      const ctx = new FrameContext();
      const sink = new PooledBatchSink(4);
      for (let s = 0; s < 12; s += 1) {
        const pick = nodes[int(nodes.length)] ?? new NullSeries("none");
        const op = nodes.length === 0 ? 1 + int(3) : int(8);
        if (op === 0) graph.markData(pick.id);
        if (op === 0) mark(Dirty.DATA, "", pick);
        if (op === 1) graph.markViewport();
        if (op === 1) mark(Dirty.TRANSFORM);
        if (op === 2) graph.markTheme();
        if (op === 2) mark(Dirty.STYLE);
        if (op === 3) {
          const pane = rng() < 0.5 ? undefined : `p${int(panes)}`;
          graph.markResize(pane);
          mark(Dirty.LAYOUT, pane === undefined ? "" : `${pane}:`);
        }
        if (op === 4) {
          const visible = rng() < 0.5;
          if (pick.visible !== visible) mark(Dirty.STYLE, "", pick);
          graph.setVisible(pick.id, visible);
        }
        if (op === 5) pick.failCollect = rng() < 0.3;
        if (op < 6) continue;
        const shed = int(5) as DeferClass;
        const before = nodes.map((n) => n.collects);
        sink.reset();
        ctx.begin(s * 16, 16.7);
        graph.frame(ctx, sink, shed);
        nodes.forEach((n, i) => {
          const marks = want.get(n) ?? 0;
          const deferred = n.deferClass !== DeferClass.NONE && n.deferClass <= shed;
          const due = marks !== Dirty.NONE && n.visible && !deferred;
          const cleared = due && !n.failCollect;
          const at = `case ${c} step ${s} ${n.id}`;
          const collects = n.collects - (before[i] ?? 0);
          if (collects !== (due ? 1 : 0)) failures.push(`${at}: ${collects} collects`);
          if (n.critical && deferred) failures.push(`${at}: critical node deferred`);
          if (n.dirty !== (cleared ? 0 : marks)) failures.push(`${at}: flags ${n.dirty}`);
          if (n.cleanCollects !== 0) failures.push(`${at}: collected while clean`);
          if (cleared) want.set(n, Dirty.NONE);
          seen.cleared += cleared ? 1 : 0;
          seen.deferred += deferred && marks !== Dirty.NONE && n.visible ? 1 : 0;
        });
      }
    }
    expect(failures.slice(0, 5)).toEqual([]);
    expect([seen.cleared > 10_000, seen.deferred > 1000]).toEqual([true, true]); // both paths ran
  });
});

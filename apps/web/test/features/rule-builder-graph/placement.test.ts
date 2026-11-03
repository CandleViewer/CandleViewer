// @vitest-environment node
import type { GraphLayout, GraphModel } from "@candleviewer/rule-graph";
import { describe, expect, it, vi } from "vitest";
import {
  GRID,
  Occupancy,
  placeNodes,
  positionOf,
} from "../../../src/features/rule-builder-graph/model/placement.js";
import { edge, node, randomGraph, rng } from "./fixtures.js";

const BLANK: GraphLayout = { positions: {}, collapsed: [], comments: [], extra: {} };

const layoutWith = (positions: GraphLayout["positions"]): GraphLayout => ({ ...BLANK, positions });

/**
 * The pairs of nodes less than a grid step apart on both axes, a placed node in each: two stored
 * positions may overlap, which placement does not decide.
 */
function overlaps(layout: GraphLayout, stored: GraphLayout["positions"] = {}): string[] {
  const all = Object.entries(layout.positions);
  const found: string[] = [];
  all.forEach(([a, p], i) => {
    for (const [b, q] of all.slice(i + 1)) {
      if (Object.hasOwn(stored, a) && Object.hasOwn(stored, b)) continue;
      if (Math.abs(p.x - q.x) < GRID && Math.abs(p.y - q.y) < GRID) found.push(`${a}/${b}`);
    }
  });
  return found;
}

/** s-graph (hand-off §D): a shared condition feeding two gates, one gate feeding the other. */
const S_GRAPH: GraphModel = {
  envelope: {},
  nodes: [
    node("n1", "trigger"),
    node("n2", "condition", { kind: "comparison", op: "gt" }),
    node("n3", "logicGate", { op: "all_of" }),
    node("n4", "logicGate", { op: "any_of" }),
    node("n5", "action"),
  ],
  edges: [
    edge("e1", "n2", "n3", "in"),
    edge("e2", "n2", "n4", "in"),
    edge("e3", "n4", "n3", "in"),
    edge("e4", "n3", "n5", "when"),
  ],
};

describe("placing the nodes a loaded rule has no position for", () => {
  it("lays s-form out left to right on the 240-unit grid: trigger, condition, action", () => {
    const graph: GraphModel = {
      envelope: {},
      nodes: [
        node("n1", "trigger"),
        node("n2", "condition", { kind: "comparison" }),
        node("n3", "action"),
      ],
      edges: [edge("e1", "n2", "n3", "when")],
    };
    expect(placeNodes(graph, BLANK).positions).toEqual({
      n1: { x: 0, y: 0 },
      n2: { x: 240, y: 0 },
      n3: { x: 480, y: 0 },
    });
  });

  it("puts every node right of each producer that feeds it", () => {
    const { positions } = placeNodes(S_GRAPH, BLANK);
    expect(positions).toEqual({
      n1: { x: 0, y: 0 },
      n2: { x: 240, y: 0 },
      n4: { x: 480, y: 0 },
      n3: { x: 720, y: 0 },
      n5: { x: 960, y: 0 },
    });
  });

  it("stacks the nodes of one column down the grid", () => {
    const graph: GraphModel = {
      envelope: {},
      nodes: [
        node("a", "condition", { kind: "comparison" }),
        node("b", "condition", { kind: "comparison" }),
        node("g", "logicGate", { op: "all_of" }),
      ],
      edges: [edge("e1", "a", "g", "in"), edge("e2", "b", "g", "in")],
    };
    expect(placeNodes(graph, BLANK).positions).toEqual({
      a: { x: 240, y: 0 },
      b: { x: 240, y: 240 },
      g: { x: 480, y: 0 },
    });
  });

  it("keeps the stored positions and places the rest clear of them", () => {
    const stored = layoutWith({ n2: { x: 230, y: 10 } });
    const { positions } = placeNodes(S_GRAPH, stored);
    expect(positions["n2"]).toEqual({ x: 230, y: 10 });
    expect(Object.keys(positions).sort()).toEqual(["n1", "n2", "n3", "n4", "n5"]);
    expect(overlaps(layoutWith(positions), stored.positions)).toEqual([]);
  });

  it("returns the layout itself when every node has a position", () => {
    const full = placeNodes(S_GRAPH, BLANK);
    expect(placeNodes(S_GRAPH, full)).toBe(full);
  });

  it("ends on a loop and places each of its nodes", () => {
    const cycle: GraphModel = {
      ...S_GRAPH,
      edges: [...S_GRAPH.edges, edge("e5", "n3", "n4", "in")],
    };
    const { positions } = placeNodes(cycle, BLANK);
    expect(Object.keys(positions).sort()).toEqual(["n1", "n2", "n3", "n4", "n5"]);
    expect(overlaps(layoutWith(positions))).toEqual([]);
  });

  it(
    "is deterministic, overlap-free and left to right on any acyclic graph (seeded sweep)",
    { timeout: 60_000 },
    () => {
      for (let seed = 1; seed <= 200; seed += 1) {
        const rand = rng(seed);
        const raw = randomGraph(rand, 14);
        // Acyclic: keep the edges that run from a lower node index to a higher one, and none into
        // a trigger, which has no input.
        const index = new Map(raw.nodes.map((n, i) => [n.id, i]));
        const triggers = new Set(raw.nodes.filter((n) => n.type === "trigger").map((n) => n.id));
        const edges = raw.edges.filter(
          (e) =>
            !triggers.has(e.target) &&
            (index.get(e.source) ?? Infinity) < (index.get(e.target) ?? -Infinity),
        );
        const graph: GraphModel = { envelope: {}, nodes: raw.nodes, edges };
        const stored = Object.fromEntries(
          raw.nodes
            .filter(() => rand() < 0.25)
            .map((n) => [n.id, { x: Math.floor(rand() * 2000), y: Math.floor(rand() * 2000) }]),
        );
        const layout = placeNodes(graph, layoutWith(stored));
        expect(placeNodes(graph, layoutWith(stored)), `seed ${seed}`).toEqual(layout);
        expect(overlaps(layout, stored), `seed ${seed}`).toEqual([]);
        for (const n of raw.nodes)
          expect(positionOf(layout, n.id), `seed ${seed} ${n.id}`).toBeDefined();
        for (const e of edges) {
          if (Object.hasOwn(stored, e.source) || Object.hasOwn(stored, e.target)) continue;
          const [from, to] = [positionOf(layout, e.source), positionOf(layout, e.target)];
          expect((from?.x ?? 0) < (to?.x ?? 0), `seed ${seed} ${e.id}`).toBe(true);
        }
      }
    },
  );

  it("places a node whose stored position is no point, read through positionOf", () => {
    const raw = { ...BLANK, positions: { n1: null } } as unknown as GraphLayout;
    expect(placeNodes(S_GRAPH, raw).positions["n1"]).toEqual({ x: 0, y: 0 });
  });

  it("places a node whose id is an object key of the prototype", () => {
    const graph: GraphModel = { envelope: {}, nodes: [node("__proto__", "trigger")], edges: [] };
    const { positions } = placeNodes(graph, BLANK);
    expect(Object.hasOwn(positions, "__proto__")).toBe(true);
    expect(positionOf(layoutWith(positions), "__proto__")).toEqual({ x: 0, y: 0 });
    expect(positionOf(BLANK, "toString")).toBeUndefined();
  });
});

describe("Occupancy", () => {
  it("counts a node within one grid step on both axes as taken, and one a full step away as free", () => {
    const taken = new Occupancy([{ x: 0, y: 0 }]);
    expect(taken.isFree({ x: 239, y: 239 })).toBe(false);
    expect(taken.isFree({ x: -239, y: 0 })).toBe(false);
    expect(taken.isFree({ x: 240, y: 0 })).toBe(true);
    expect(taken.isFree({ x: 0, y: -240 })).toBe(true);
  });

  it.each([1e19, -1e19])(
    "ends its walk down a column even where a step no longer moves %d",
    (y) => {
      const isFree = Occupancy.prototype.isFree;
      let calls = 0;
      const spy = vi.spyOn(Occupancy.prototype, "isFree").mockImplementation(function (
        this: Occupancy,
        at,
      ) {
        calls += 1;
        if (calls > 100) throw new Error("the walk does not end");
        return isFree.call(this, at);
      });
      try {
        expect(new Occupancy([{ x: 0, y }]).takeBelow({ x: 0, y })).toEqual({ x: 0, y });
        expect(calls).toBeLessThanOrEqual(3);
      } finally {
        spy.mockRestore();
      }
    },
  );

  it("takes the first free point below, one grid step at a time", () => {
    const taken = new Occupancy([
      { x: 0, y: 0 },
      { x: 10, y: 250 },
    ]);
    expect(taken.takeBelow({ x: 0, y: 0 })).toEqual({ x: 0, y: 720 });
    expect(taken.isFree({ x: 0, y: 720 })).toBe(false);
  });

  it("walks 2n + 1 steps for n points held: a point off the column's grid blocks two", () => {
    const taken = new Occupancy([
      { x: 0, y: 120 },
      { x: 0, y: 600 },
    ]);
    expect(taken.takeBelow({ x: 0, y: 0 })).toEqual({ x: 0, y: 960 });
  });
});

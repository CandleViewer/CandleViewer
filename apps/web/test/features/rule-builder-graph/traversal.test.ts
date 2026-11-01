import { describe, expect, it } from "vitest";
import {
  GraphNavigator,
  traversalOrder,
} from "../../../src/features/rule-builder-graph/a11y/traversal.js";
import { edge, node, randomGraph, rng, RULE, shuffle } from "./fixtures.js";

describe("traversalOrder (E47-S03 BQ-04)", () => {
  it("lists triggers first, then inputs before what they feed, then edgeless nodes", () => {
    expect(traversalOrder(RULE)).toEqual([
      { id: "trigger", depth: 0 },
      { id: "cmp1", depth: 0 },
      { id: "and", depth: 1 },
      { id: "act1", depth: 2 },
      { id: "act2", depth: 2 },
      { id: "cmp2", depth: 0 },
      { id: "note", depth: 0 },
    ]);
  });

  it("reaches nodes that only sit on a loop", () => {
    const graph = {
      nodes: [node("b", "logicGate"), node("a", "logicGate")],
      edges: [edge("e1", "a", "b", "in"), edge("e2", "b", "a", "in")],
    };
    expect(traversalOrder(graph).map((e) => e.id)).toEqual(["a", "b"]);
  });

  it("is empty for an empty canvas", () => {
    expect(traversalOrder({ nodes: [], edges: [] })).toEqual([]);
  });

  it("property: every node exactly once, whatever the edges, in any array order", () => {
    const rand = rng(1317);
    for (let run = 0; run < 300; run += 1) {
      const graph = randomGraph(rand);
      const order = traversalOrder(graph).map((e) => e.id);
      expect([...order].sort()).toEqual(graph.nodes.map((n) => n.id).sort());
      const shuffled = {
        nodes: shuffle(rand, graph.nodes),
        edges: shuffle(rand, graph.edges),
      };
      expect(traversalOrder(shuffled).map((e) => e.id)).toEqual(order);
    }
  });
});

describe("GraphNavigator", () => {
  const nav = new GraphNavigator(RULE);

  it("Right follows the first outbound edge, Left the first inbound one", () => {
    expect(nav.move("cmp1", "right")).toBe("and");
    expect(nav.move("and", "right")).toBe("act1");
    expect(nav.move("and", "left")).toBe("cmp1");
    expect(nav.move("act2", "left")).toBe("and");
    expect(nav.move("act1", "right")).toBe("act1");
    expect(nav.move("trigger", "left")).toBe("trigger");
  });

  it("Up and Down step between nodes of the same depth and stop at the ends", () => {
    expect(nav.move("act1", "down")).toBe("act2");
    expect(nav.move("act2", "down")).toBe("act2");
    expect(nav.move("act2", "up")).toBe("act1");
    expect(nav.move("trigger", "down")).toBe("cmp1");
    expect(nav.move("trigger", "up")).toBe("trigger");
  });

  it("Home and End go to the ends of the order", () => {
    expect(nav.move("and", "home")).toBe("trigger");
    expect(nav.move("and", "end")).toBe("note");
  });

  it("an unknown id lands on the first node; an empty graph stays put", () => {
    expect(nav.move("gone", "right")).toBe("trigger");
    expect(new GraphNavigator({ nodes: [], edges: [] }).move("x", "down")).toBe("x");
  });

  it("gives the 1-based position and set size", () => {
    expect(nav.positionOf("and")).toEqual({ index: 3, size: 7 });
    expect(nav.positionOf("gone")).toBeUndefined();
  });

  it("lists a node's edges outbound first, then inbound, by order rank", () => {
    expect(nav.edgesOf("and").map((e) => e.id)).toEqual(["e3", "e4", "e1", "e2"]);
    expect(nav.edgesOf("note")).toEqual([]);
  });

  it("property: every move lands on a node of the graph", () => {
    const rand = rng(82);
    const keys = ["right", "left", "up", "down", "home", "end"] as const;
    for (let run = 0; run < 100; run += 1) {
      const graph = randomGraph(rand);
      const ids = new Set(graph.nodes.map((n) => n.id));
      const walker = new GraphNavigator(graph);
      let at = walker.order[0]?.id as string;
      for (let press = 0; press < 30; press += 1) {
        at = walker.move(at, keys[Math.floor(rand() * keys.length)] as (typeof keys)[number]);
        expect(ids.has(at)).toBe(true);
      }
    }
  });
});

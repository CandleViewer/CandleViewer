import { describe, expect, it } from "vitest";
import type { A11yGraph } from "../../../src/features/rule-builder-graph/a11y/graph.js";
import {
  GraphNavigator,
  traversalOrder,
  type NavKey,
} from "../../../src/features/rule-builder-graph/a11y/traversal.js";
import { edge, node, randomGraph, rng, RULE, shuffle } from "./fixtures.js";

/**
 * A rule shaped as rule-graph's toGraph builds one, with branching, a fan-out (cmp2 feeds both
 * `or` and the root `and`), a fragment not yet under an action (g2 <- cmp4), an orphan and a
 * comment. The node array is deliberately not in reading order.
 */
const BRANCHING: A11yGraph = {
  nodes: [
    node("note", "comment", { text: "why" }),
    node("cmp2", "condition", { kind: "comparison" }),
    node("a1", "action"),
    node("orphan", "logicGate"),
    node("and", "logicGate"),
    node("cmp1", "condition", { kind: "comparison" }),
    node("trigger", "trigger"),
    node("g2", "logicGate"),
    node("or", "logicGate"),
    node("a2", "action"),
    node("cmp4", "condition", { kind: "comparison" }),
    node("cmp3", "condition", { kind: "comparison" }),
    node("arith", "condition", { kind: "arithmetic" }),
  ],
  edges: [
    edge("e1", "and", "a1", "when"),
    edge("e2", "and", "a2", "when"),
    edge("e3", "or", "and", "in"),
    edge("e4", "cmp3", "and", "in"),
    edge("e5", "cmp2", "and", "in"),
    edge("e6", "cmp1", "or", "in"),
    edge("e7", "cmp2", "or", "in"),
    edge("e8", "arith", "cmp1", "left"),
    edge("e9", "cmp4", "g2", "in"),
  ],
};

/**
 * a11y lens A-1's counterexample, plus an edgeless comment so W is not last: under the old model
 * (Up / Down within a depth level, Right / Left first edge only) no key reached W.
 */
const STRANDED: A11yGraph = {
  nodes: [
    ...["S1", "V", "S2", "a", "b", "W"].map((id) => node(id, "logicGate")),
    node("Z", "comment"),
  ],
  edges: [
    edge("e1", "S1", "V", "in"),
    edge("e2", "S2", "a", "in"),
    edge("e3", "a", "b", "in"),
    edge("e4", "b", "V", "in"),
    edge("e5", "b", "W", "in"),
  ],
};

const KEYS: readonly NavKey[] = ["up", "down", "home", "end"];

/** Every node one key press (or a run of Right / Left presses from the same node) reaches. */
function nextOf(graph: A11yGraph, from: string): Set<string> {
  const out = new Set<string>();
  for (const key of KEYS) out.add(new GraphNavigator(graph).move(from, key));
  for (const key of ["right", "left"] as const) {
    const nav = new GraphNavigator(graph);
    for (let press = 0; press <= nav.neighbours(from, key).length; press += 1) {
      out.add(nav.move(from, key));
    }
  }
  return out;
}

/** BFS over key transitions: the nodes reachable from `start` by arrow, Home and End keys. */
function reachable(graph: A11yGraph, start: string): Set<string> {
  const seen = new Set([start]);
  const queue = [start];
  for (let head = 0; head < queue.length; head += 1) {
    for (const next of nextOf(graph, queue[head] as string)) {
      if (seen.has(next)) continue;
      seen.add(next);
      queue.push(next);
    }
  }
  return seen;
}

describe("traversalOrder (E37-D02 §13, BQ-15 RULED)", () => {
  it("reads trigger, the root's subtree depth-first in in-edge order, actions, then the rest", () => {
    expect(traversalOrder(BRANCHING)).toEqual([
      { id: "trigger", depth: 0 },
      { id: "and", depth: 0 },
      { id: "or", depth: 1 },
      { id: "cmp1", depth: 2 },
      { id: "arith", depth: 3 },
      { id: "cmp2", depth: 2 },
      { id: "cmp3", depth: 1 },
      { id: "a1", depth: 0 },
      { id: "a2", depth: 0 },
      { id: "g2", depth: 0 },
      { id: "cmp4", depth: 1 },
      { id: "note", depth: 0 },
      { id: "orphan", depth: 0 },
    ]);
  });

  it("puts the root before the conditions it reads, and the actions after them", () => {
    expect(traversalOrder(RULE).map((e) => e.id)).toEqual([
      "trigger",
      "and",
      "cmp1",
      "cmp2",
      "act1",
      "act2",
      "note",
    ]);
  });

  it("reaches nodes that only sit on a loop", () => {
    const graph = {
      nodes: [node("b", "logicGate"), node("a", "logicGate")],
      edges: [edge("e1", "a", "b", "in"), edge("e2", "b", "a", "in")],
    };
    expect(traversalOrder(graph).map((e) => e.id)).toEqual(["b", "a"]);
  });

  it("is empty for an empty canvas", () => {
    expect(traversalOrder({ nodes: [], edges: [] })).toEqual([]);
  });

  it("walks a long chain without recursion", () => {
    const n = 20_000;
    const nodes = Array.from({ length: n }, (_, i) => node(`c${i}`, "logicGate"));
    const edges = Array.from({ length: n - 1 }, (_, i) =>
      edge(`e${i}`, `c${i + 1}`, `c${i}`, "in"),
    );
    const order = traversalOrder({ nodes, edges });
    expect(order).toHaveLength(n);
    expect(order[n - 1]).toEqual({ id: `c${n - 1}`, depth: n - 1 });
  });

  it("property: every node exactly once, whatever the edges", () => {
    const rand = rng(1317);
    for (let run = 0; run < 300; run += 1) {
      const graph = randomGraph(rand);
      const order = traversalOrder(graph).map((e) => e.id);
      expect([...order].sort()).toEqual(graph.nodes.map((n) => n.id).sort());
    }
  });

  it("property: the order follows the arrays, not the spelling of the ids", () => {
    const rand = rng(1318);
    for (let run = 0; run < 200; run += 1) {
      const graph = randomGraph(rand);
      const ids = graph.nodes.map((n) => n.id);
      const spelling = shuffle(rand, ids);
      const renamed = new Map(ids.map((id, i) => [id, `z${spelling[i] as string}`]));
      const rename = (id: string): string => renamed.get(id) ?? id;
      const relabelled: A11yGraph = {
        nodes: graph.nodes.map((n) => ({ ...n, id: rename(n.id) })),
        edges: graph.edges.map((e) => ({
          ...e,
          source: rename(e.source),
          target: rename(e.target),
        })),
      };
      expect(traversalOrder(relabelled).map((e) => e.id)).toEqual(
        traversalOrder(graph).map((e) => rename(e.id)),
      );
    }
  });
});

describe("GraphNavigator", () => {
  it("Right goes to a consumer and Left to a producer, cycling when there are several", () => {
    const nav = new GraphNavigator(RULE);
    expect(nav.move("cmp1", "right")).toBe("and");
    expect(nav.move("and", "right")).toBe("act1");
    expect(nav.move("and", "right")).toBe("act2");
    expect(nav.move("and", "right")).toBe("act1");
    expect(nav.move("and", "left")).toBe("cmp1");
    expect(nav.move("and", "left")).toBe("cmp2");
    expect(nav.move("and", "left")).toBe("cmp1");
    expect(nav.move("act2", "left")).toBe("and");
    expect(nav.move("act1", "right")).toBe("act1");
    expect(nav.move("trigger", "left")).toBe("trigger");
  });

  it("lists a node's neighbours once each, by order rank", () => {
    const nav = new GraphNavigator(BRANCHING);
    expect(nav.neighbours("and", "left")).toEqual(["or", "cmp2", "cmp3"]);
    expect(nav.neighbours("cmp2", "right")).toEqual(["and", "or"]);
    expect(nav.neighbours("note", "right")).toEqual([]);
  });

  it("Up and Down step along the one linear order and stop at the ends", () => {
    const nav = new GraphNavigator(RULE);
    expect(nav.move("trigger", "down")).toBe("and");
    expect(nav.move("cmp2", "down")).toBe("act1");
    expect(nav.move("act2", "down")).toBe("note");
    expect(nav.move("note", "down")).toBe("note");
    expect(nav.move("and", "up")).toBe("trigger");
    expect(nav.move("trigger", "up")).toBe("trigger");
  });

  it("Home and End go to the ends of the order", () => {
    const nav = new GraphNavigator(RULE);
    expect(nav.move("and", "home")).toBe("trigger");
    expect(nav.move("and", "end")).toBe("note");
  });

  it("an unknown id lands on the first node; an empty graph stays put", () => {
    expect(new GraphNavigator(RULE).move("gone", "right")).toBe("trigger");
    expect(new GraphNavigator({ nodes: [], edges: [] }).move("x", "down")).toBe("x");
  });

  it("gives the 1-based position and set size", () => {
    const nav = new GraphNavigator(RULE);
    expect(nav.positionOf("and")).toEqual({ index: 2, size: 7 });
    expect(nav.positionOf("gone")).toBeUndefined();
  });

  it("lists a node's edges outbound first, then inbound, by order rank", () => {
    const nav = new GraphNavigator(RULE);
    expect(nav.edgesOf("and").map((e) => e.id)).toEqual(["e3", "e4", "e1", "e2"]);
    expect(nav.edgesOf("note")).toEqual([]);
  });

  it("reaches the node the old model stranded, from every start (a11y lens A-1)", () => {
    for (const start of STRANDED.nodes) {
      expect([...reachable(STRANDED, start.id)].sort()).toEqual([
        "S1",
        "S2",
        "V",
        "W",
        "Z",
        "a",
        "b",
      ]);
    }
  });

  it("property: Down moves from position i to i + 1, so the announced position is navigable", () => {
    const rand = rng(83);
    for (let run = 0; run < 100; run += 1) {
      const nav = new GraphNavigator(randomGraph(rand));
      nav.order.slice(0, -1).forEach((entry, i) => {
        expect(nav.positionOf(nav.move(entry.id, "down"))?.index).toBe(i + 2);
      });
    }
  });

  it("property: from any start node, every node is reachable by the arrow keys", () => {
    const rand = rng(84);
    for (let run = 0; run < 60; run += 1) {
      const graph = randomGraph(rand, 10);
      const all = graph.nodes.map((n) => n.id).sort();
      for (const start of graph.nodes) {
        expect([...reachable(graph, start.id)].sort()).toEqual(all);
      }
    }
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

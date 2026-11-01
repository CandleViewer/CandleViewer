import { describe, expect, it } from "vitest";
import type { A11yGraph } from "../../../src/features/rule-builder-graph/a11y/graph.js";
import {
  GraphNavigator,
  traversalOrder,
  type GraphFocus,
  type NavKey,
} from "../../../src/features/rule-builder-graph/a11y/traversal.js";
import { edge, node, oracle, randomGraph, rng, RULE, shuffle } from "./fixtures.js";

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

/** A fan-out whose first consumer is not the next node in the order: X feeds G1 and G2. */
const FAN_OUT: A11yGraph = {
  nodes: [
    node("A", "action"),
    node("R", "logicGate"),
    node("G1", "logicGate"),
    node("G2", "logicGate"),
    node("X", "condition", { kind: "comparison" }),
    node("Y", "condition", { kind: "comparison" }),
  ],
  edges: [
    edge("e1", "R", "A", "when"),
    edge("e2", "G1", "R", "in"),
    edge("e3", "G2", "R", "in"),
    edge("e4", "X", "G1", "in"),
    edge("e5", "Y", "G1", "in"),
    edge("e6", "X", "G2", "in"),
  ],
};

const nodeAt = (id: string): GraphFocus => ({ kind: "node", node: id });

/** Presses the keys from `from` and returns where focus ends. */
function press(nav: GraphNavigator, from: GraphFocus, keys: readonly NavKey[]): GraphFocus {
  return keys.reduce((at, key) => nav.next(at, key), from);
}

/** A random graph with no loop: every edge runs from a higher-numbered node to a lower one. */
function randomDag(rand: () => number): A11yGraph {
  const graph = randomGraph(rand);
  const num = (id: string): number => Number(id.slice(1));
  const ids = new Set(graph.nodes.map((n) => n.id));
  return {
    nodes: graph.nodes,
    edges: graph.edges.filter(
      (e) => ids.has(e.source) && ids.has(e.target) && num(e.source) > num(e.target),
    ),
  };
}

describe("traversalOrder (E37-D02 §13 :358, BQ-15 RULED; E47-S03 BQ-04)", () => {
  it("reads trigger, the root's subtree depth-first in in-edge order, actions, then the rest", () => {
    expect(traversalOrder(BRANCHING)).toEqual([
      { id: "trigger", depth: 0 },
      { id: "arith", depth: 3 },
      { id: "cmp1", depth: 2 },
      { id: "cmp2", depth: 2 },
      { id: "or", depth: 1 },
      { id: "cmp3", depth: 1 },
      { id: "and", depth: 0 },
      { id: "a1", depth: 0 },
      { id: "a2", depth: 0 },
      { id: "cmp4", depth: 1 },
      { id: "g2", depth: 0 },
      { id: "note", depth: 0 },
      { id: "orphan", depth: 0 },
    ]);
  });

  it("is topological: the conditions before the root they feed, the actions after it", () => {
    expect(traversalOrder(RULE).map((e) => e.id)).toEqual([
      "trigger",
      "cmp1",
      "cmp2",
      "and",
      "act1",
      "act2",
      "note",
    ]);
  });

  it("puts an unconnected action after the connected walk, in creation order", () => {
    const graph: A11yGraph = {
      nodes: [node("late", "action"), ...RULE.nodes],
      edges: RULE.edges,
    };
    expect(traversalOrder(graph).map((e) => e.id)).toEqual([
      "trigger",
      "cmp1",
      "cmp2",
      "and",
      "act1",
      "act2",
      "late",
      "note",
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

  it("walks a long chain without recursion", () => {
    const n = 20_000;
    const nodes = Array.from({ length: n }, (_, i) => node(`c${i}`, "logicGate"));
    const edges = Array.from({ length: n - 1 }, (_, i) =>
      edge(`e${i}`, `c${i + 1}`, `c${i}`, "in"),
    );
    const order = traversalOrder({ nodes, edges });
    expect(order).toHaveLength(n);
    expect(order[0]).toEqual({ id: `c${n - 1}`, depth: n - 1 });
    expect(order[n - 1]).toEqual({ id: "c0", depth: 0 });
  });

  it("property: every node exactly once, whatever the edges", () => {
    const rand = rng(1317);
    for (let run = 0; run < 300; run += 1) {
      const graph = randomGraph(rand);
      const order = traversalOrder(graph).map((e) => e.id);
      expect([...order].sort()).toEqual(graph.nodes.map((n) => n.id).sort());
    }
  });

  it("property: without a loop, every producer comes before the node it feeds", () => {
    const rand = rng(1319);
    for (let run = 0; run < 300; run += 1) {
      const graph = randomDag(rand);
      const rank = new Map(traversalOrder(graph).map((e, i) => [e.id, i]));
      for (const e of graph.edges) {
        expect(rank.get(e.source) as number).toBeLessThan(rank.get(e.target) as number);
      }
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

describe("GraphNavigator: Up / Down between nodes (D02 §13 :358, :364)", () => {
  it("steps along the order and stops at the ends", () => {
    const nav = new GraphNavigator(RULE);
    expect(nav.next(nodeAt("trigger"), "down")).toEqual(nodeAt("cmp1"));
    expect(nav.next(nodeAt("cmp2"), "down")).toEqual(nodeAt("and"));
    expect(nav.next(nodeAt("act2"), "down")).toEqual(nodeAt("note"));
    expect(nav.next(nodeAt("note"), "down")).toEqual(nodeAt("note"));
    expect(nav.next(nodeAt("cmp1"), "up")).toEqual(nodeAt("trigger"));
    expect(nav.next(nodeAt("trigger"), "up")).toEqual(nodeAt("trigger"));
  });

  it("at a fan-in, Up from the consumer goes to its first in producer", () => {
    const nav = new GraphNavigator(RULE);
    expect(nav.producersOf("and")).toEqual(["cmp1", "cmp2"]);
    expect(nav.next(nodeAt("and"), "up")).toEqual(nodeAt("cmp1")); // the order's previous is cmp2
    expect(new GraphNavigator(BRANCHING).next(nodeAt("and"), "up")).toEqual(nodeAt("or"));
  });

  it("at a fan-out, Down from the shared producer goes to its first consumer", () => {
    const nav = new GraphNavigator(FAN_OUT);
    expect(nav.order.map((e) => e.id)).toEqual(["X", "Y", "G1", "G2", "R", "A"]);
    expect(nav.consumersOf("X")).toEqual(["G1", "G2"]);
    expect(nav.next(nodeAt("X"), "down")).toEqual(nodeAt("G1")); // the order's next is Y
    expect(nav.next(nodeAt("Y"), "down")).toEqual(nodeAt("G1"));
    expect(nav.next(nodeAt("R"), "down")).toEqual(nodeAt("A"));
  });

  it("Home and End go to the ends of the order", () => {
    const nav = new GraphNavigator(RULE);
    expect(nav.next(nodeAt("and"), "home")).toEqual(nodeAt("trigger"));
    expect(nav.next(nodeAt("and"), "end")).toEqual(nodeAt("note"));
  });

  it("gives the 1-based position and set size", () => {
    const nav = new GraphNavigator(RULE);
    expect(nav.positionOf("and")).toEqual({ index: 4, size: 7 });
    expect(nav.positionOf("gone")).toBeUndefined();
  });

  it("property: with no fan-out, Down from the first node visits the whole order", () => {
    const rand = rng(83);
    for (let run = 0; run < 100; run += 1) {
      const graph = randomGraph(rand);
      const fed = new Set<string>();
      const edges = graph.edges.filter((e) => !fed.has(e.source) && fed.add(e.source));
      const nav = new GraphNavigator({ nodes: graph.nodes, edges });
      const ids = nav.order.map((e) => e.id);
      const walked = ids.slice(1).reduce<string[]>(
        (seen) => {
          const at = nav.next(nodeAt(seen[seen.length - 1] as string), "down");
          return [...seen, at.node];
        },
        [ids[0] as string],
      );
      expect(walked).toEqual(ids);
    }
  });
});

describe("GraphNavigator: Tab, ports and connections (D02 §13 :363–369, §6 E2 :226)", () => {
  it("Tab enters once: on the last focus while it is still in the graph, else the first node", () => {
    const nav = new GraphNavigator(RULE, oracle);
    expect(nav.enter()).toEqual(nodeAt("trigger"));
    const port: GraphFocus = { kind: "port", node: "and", direction: "input", port: "in" };
    expect(nav.enter(port)).toEqual(port);
    expect(nav.enter(nodeAt("gone"))).toEqual(nodeAt("trigger"));
    expect(nav.enter({ ...port, kind: "edge", edge: "gone" })).toEqual(nodeAt("trigger"));
    expect(new GraphNavigator({ nodes: [], edges: [] }).enter()).toBeUndefined();
  });

  it("Left takes the first input and Right the output; along the ports they step and stop", () => {
    const nav = new GraphNavigator(RULE, oracle);
    const cmp = (direction: "input" | "output", port: string): GraphFocus => ({
      kind: "port",
      node: "cmp1",
      direction,
      port,
    });
    expect(nav.portsOf("cmp1").map((p) => p.port)).toEqual(["left", "right", "out"]);
    expect(nav.next(nodeAt("cmp1"), "left")).toEqual(cmp("input", "left"));
    expect(nav.next(nodeAt("cmp1"), "right")).toEqual(cmp("output", "out"));
    expect(press(nav, nodeAt("cmp1"), ["left", "right"])).toEqual(cmp("input", "right"));
    expect(press(nav, nodeAt("cmp1"), ["left", "right", "right", "right"])).toEqual(
      cmp("output", "out"),
    );
    expect(press(nav, nodeAt("cmp1"), ["left", "left"])).toEqual(cmp("input", "left"));
    expect(press(nav, nodeAt("cmp1"), ["right", "left"])).toEqual(cmp("input", "right"));
  });

  it("a node with no port on that side keeps focus", () => {
    const nav = new GraphNavigator(RULE, oracle);
    expect(nav.next(nodeAt("note"), "left")).toEqual(nodeAt("note"));
    expect(nav.next(nodeAt("act1"), "right")).toEqual(nodeAt("act1"));
    expect(nav.next(nodeAt("trigger"), "left")).toEqual(nodeAt("trigger"));
  });

  it("Down on a port walks its connections; Up returns to the port, then to the node", () => {
    const nav = new GraphNavigator(RULE, oracle);
    const port: GraphFocus = { kind: "port", node: "and", direction: "input", port: "in" };
    const on = (id: string): GraphFocus => ({ ...port, kind: "edge", edge: id });
    expect(nav.next(nodeAt("and"), "left")).toEqual(port);
    expect(press(nav, port, ["down"])).toEqual(on("e1"));
    expect(press(nav, port, ["down", "down"])).toEqual(on("e2"));
    expect(press(nav, port, ["down", "down", "down"])).toEqual(on("e2"));
    expect(press(nav, port, ["down", "down", "up"])).toEqual(on("e1"));
    expect(press(nav, port, ["down", "up"])).toEqual(port);
    expect(press(nav, port, ["up"])).toEqual(nodeAt("and"));
    expect(press(nav, port, ["down", "right"])).toMatchObject({ kind: "port", port: "out" });
    const out = nav.next(nodeAt("and"), "right");
    expect(press(nav, out, ["down"])).toMatchObject({ kind: "edge", edge: "e3" });
    expect(press(nav, out, ["down", "down"])).toMatchObject({ kind: "edge", edge: "e4" });
  });

  it("an unconnected port keeps focus on Down; Home and End leave the ports", () => {
    const nav = new GraphNavigator(RULE, oracle);
    const left = nav.next(nodeAt("cmp1"), "left");
    expect(nav.next(left, "down")).toEqual(left);
    expect(nav.next(left, "home")).toEqual(nodeAt("trigger"));
    expect(nav.next(left, "end")).toEqual(nodeAt("note"));
  });

  it("without an oracle, a node's ports are the ones its edges name", () => {
    const nav = new GraphNavigator(RULE);
    expect(nav.portsOf("cmp1").map((p) => p.port)).toEqual(["out"]);
    expect(nav.portsOf("act1").map((p) => p.port)).toEqual(["when"]);
    expect(nav.portsOf("gone")).toEqual([]);
  });

  it("a focus no longer in the graph lands on the first node; an empty graph stays put", () => {
    expect(new GraphNavigator(RULE).next(nodeAt("gone"), "down")).toEqual(nodeAt("trigger"));
    expect(new GraphNavigator({ nodes: [], edges: [] }).next(nodeAt("x"), "down")).toEqual(
      nodeAt("x"),
    );
  });

  it("after a node delete, focus goes to the previous node in the order (D02 §13 :370)", () => {
    const nav = new GraphNavigator(RULE);
    expect(nav.afterDelete("and")).toBe("cmp2");
    expect(nav.afterDelete("trigger")).toBe("cmp1");
    expect(nav.afterDelete("gone")).toBeUndefined();
    expect(new GraphNavigator({ nodes: [node("a", "comment")], edges: [] }).afterDelete("a")).toBe(
      undefined,
    );
  });

  it("lists a node's edges outbound first, then inbound, by order rank", () => {
    const nav = new GraphNavigator(RULE);
    expect(nav.edgesOf("and").map((e) => e.id)).toEqual(["e3", "e4", "e1", "e2"]);
    expect(nav.edgesOf("note")).toEqual([]);
  });

  it("property: every key lands on a node, port or connection of the graph", () => {
    const rand = rng(82);
    const keys = ["right", "left", "up", "down", "home", "end"] as const;
    for (let run = 0; run < 100; run += 1) {
      const graph = randomGraph(rand);
      const nav = new GraphNavigator(graph, oracle);
      let at = nav.enter() as GraphFocus;
      for (let step = 0; step < 40; step += 1) {
        at = nav.next(at, keys[Math.floor(rand() * keys.length)] as NavKey);
        expect(nav.enter(at)).toEqual(at); // enter() keeps a focus only while it is valid
      }
    }
  });
});

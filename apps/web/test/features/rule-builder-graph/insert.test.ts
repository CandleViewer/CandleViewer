// @vitest-environment node
import type { GraphLayout, GraphModel, GraphNode } from "@candleviewer/rule-graph";
import { describe, expect, it, vi } from "vitest";
import { planInsert } from "../../../src/features/rule-builder-graph/model/insert.js";
import { CANVAS_LIMIT } from "../../../src/features/rule-builder-graph/model/layout.js";
import {
  GRID,
  Occupancy,
  placeNodes,
} from "../../../src/features/rule-builder-graph/model/placement.js";
import { portOracle } from "../../../src/features/rule-builder-graph/model/portOracle.js";
import { edge, node } from "./fixtures.js";

const BLANK: GraphLayout = { positions: {}, collapsed: [], comments: [], extra: {} };
const COMPARISON = node("n9", "condition", { kind: "comparison", op: "gt" });
const ARITHMETIC = node("n9", "condition", { kind: "arithmetic", op: "add" });
const ACTION = node("n9", "action", { type: "flatten_position" });
const GATE = node("n9", "logicGate", { op: "any_of" });

/** `Enter` on a palette entry with `selected` selected: where `added` goes, and what it joins. */
function insert(
  nodes: GraphNode[],
  edges: GraphModel["edges"],
  selected: string[],
  added: GraphNode,
) {
  const graph: GraphModel = { envelope: {}, nodes, edges };
  return planInsert(graph, placeNodes(graph, BLANK), selected, added, portOracle);
}
const to = (source: string, target: string, targetPort: string) => ({
  source,
  sourcePort: "out",
  target,
  targetPort,
});

describe("Non-drag insertion works (AC 3, the insertion rule)", () => {
  it("connects the node to the selection where types allow, at its first free compatible port", () => {
    const plan = insert([node("g", "logicGate", { op: "all_of" })], [], ["g"], COMPARISON);
    expect(plan.edge).toEqual(to("n9", "g", "in"));
  });

  it("takes the selection's first free compatible port, not the first compatible one", () => {
    const nodes = [
      node("a", "condition", { kind: "arithmetic", op: "add" }),
      node("c", "condition", { kind: "comparison", op: "gt" }),
    ];
    const plan = insert(nodes, [edge("e1", "a", "c", "left")], ["c"], ARITHMETIC);
    expect(plan.edge).toEqual(to("n9", "c", "right"));
  });

  it("reads the selection's inputs before its output", () => {
    // A gate after a gate fits both ways round; the selection's input comes first.
    const plan = insert([node("g", "logicGate", { op: "all_of" })], [], ["g"], GATE);
    expect(plan.edge).toEqual(to("n9", "g", "in"));
  });

  it("connects the selection's output to the new node's first input when no input takes it", () => {
    const comparison = node("c", "condition", { kind: "comparison", op: "gt" });
    expect(insert([comparison], [], ["c"], ACTION).edge).toEqual(to("c", "n9", "when"));
  });

  it("inserts unconnected, right of the selection, when no port allows it", () => {
    expect(insert([node("t", "trigger")], [], ["t"], COMPARISON)).toEqual({
      position: { x: 240, y: 0 },
      edge: undefined,
    });
  });

  it("refuses what a drag refuses: an occupied single input takes no second edge", () => {
    const nodes = [node("c", "condition", { kind: "comparison", op: "gt" }), node("act", "action")];
    const plan = insert(nodes, [edge("e1", "c", "act", "when")], ["act"], COMPARISON);
    expect(plan.edge).toBeUndefined();
  });

  it("anchors on the selection's most recent node", () => {
    const nodes = [node("t", "trigger"), node("g", "logicGate", { op: "all_of" })];
    expect(insert(nodes, [], ["g", "t"], COMPARISON).edge).toBeUndefined();
    expect(insert(nodes, [], ["t", "g"], COMPARISON).edge).toEqual(to("n9", "g", "in"));
  });

  it("places the node lower down when the cell right of the selection is taken", () => {
    const nodes = [node("t", "trigger"), node("c", "condition", { kind: "comparison" })];
    // Placement put t at (0, 0) and c at (240, 0).
    expect(insert(nodes, [], ["t"], ACTION).position).toEqual({ x: 240, y: 240 });
  });

  it("with nothing selected, takes the first free cell of the leftmost column", () => {
    expect(insert([], [], [], ACTION).position).toEqual({ x: 0, y: 0 });
    expect(insert([node("t", "trigger")], [], [], ACTION).position).toEqual({ x: 0, y: 240 });
  });

  it("ignores selected ids no longer in the graph", () => {
    expect(insert([node("t", "trigger")], [], ["gone"], ACTION)).toEqual({
      position: { x: 0, y: 240 },
      edge: undefined,
    });
  });

  it("inserts beside an anchor stored far past the canvas bound, read clamped, up inside it", () => {
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
      const nodes = [
        node("a", "logicGate", { op: "all_of" }),
        node("b", "logicGate", { op: "any_of" }),
      ];
      const graph: GraphModel = { envelope: {}, nodes, edges: [] };
      const far = { a: { x: 0, y: 1e19 }, b: { x: 240, y: 1e19 } };
      const plan = planInsert(graph, { ...BLANK, positions: far }, ["a"], ACTION, portOracle);
      expect(plan.position).toEqual({ x: 240, y: CANVAS_LIMIT - GRID });
    } finally {
      spy.mockRestore();
    }
  });

  it("inserts in the anchor's column at the canvas bound's right edge, on a free point", () => {
    const graph: GraphModel = { envelope: {}, nodes: [node("a", "logicGate")], edges: [] };
    const layout = { ...BLANK, positions: { a: { x: CANVAS_LIMIT, y: 0 } } };
    const plan = planInsert(graph, layout, ["a"], ACTION, portOracle);
    expect(plan.position).toEqual({ x: CANVAS_LIMIT, y: GRID });
  });

  it("plans without changing the graph it reads", () => {
    const nodes = [node("g", "logicGate", { op: "all_of" })];
    const graph: GraphModel = { envelope: {}, nodes, edges: [] };
    const plan = planInsert(graph, placeNodes(graph, BLANK), ["g"], ACTION, portOracle);
    expect(plan).toEqual({ position: { x: 480, y: 0 }, edge: to("g", "n9", "when") });
    expect(graph.nodes).toBe(nodes);
    expect(nodes).toHaveLength(1);
  });
});

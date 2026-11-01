import { describe, expect, it } from "vitest";
import {
  buildOutline,
  nodeName,
  parameterSummary,
} from "../../../src/features/rule-builder-graph/a11y/outline.js";
import { validationAnnouncement } from "../../../src/features/rule-builder-graph/a11y/validation.js";
import { edge, node, randomGraph, rng, RULE } from "./fixtures.js";

describe("outline: Gherkin 3, the structure without the canvas", () => {
  const rows = buildOutline(RULE);

  it("lists every node in the documented order with its position", () => {
    expect(rows.map((r) => [r.id, r.index, r.size, r.depth])).toEqual([
      ["trigger", 1, 7, 0],
      ["cmp1", 2, 7, 0],
      ["and", 3, 7, 1],
      ["act1", 4, 7, 2],
      ["act2", 5, 7, 2],
      ["cmp2", 6, 7, 0],
      ["note", 7, 7, 0],
    ]);
  });

  it("describes type, name, parameters and both directions of connection", () => {
    const and = rows.find((r) => r.id === "and");
    expect(and?.description).toBe(
      "Logic gate AND, op and. Inputs: ATR above into input; Condition cmp2 into input. " +
        "Output connects to: Alert run when; Log run when.",
    );
    expect(and?.inbound.map((l) => [l.edgeId, l.nodeId, l.port])).toEqual([
      ["e1", "cmp1", "in"],
      ["e2", "cmp2", "in"],
    ]);
    expect(rows.find((r) => r.id === "cmp1")?.description).toBe(
      "Condition ATR above, op gt, value 14. Inputs: none. Output connects to: AND input.",
    );
    expect(rows.find((r) => r.id === "note")?.description).toBe(
      "Comment why, no parameters. Inputs: none. Output connects to: none.",
    );
  });

  it("names a node from its own text, else its type and id", () => {
    expect(nodeName(node("a", "action", { name: "  Alert " }))).toBe("Alert");
    expect(nodeName(node("a", "action", { name: " ", label: "Log" }))).toBe("Log");
    expect(nodeName(node("g", "logicGate", { name: 3 }))).toBe("Logic gate g");
  });

  it("summarises scalar parameters only", () => {
    const data = { kind: "comparison", node_id: "x", z: true, a: 1, nested: { b: 2 }, n: Infinity };
    expect(parameterSummary(node("x", "condition", data))).toBe("a 1, z true");
    expect(parameterSummary(node("x", "trigger"))).toBe("no parameters");
  });

  it("names a dangling edge end by its id", () => {
    const graph = { nodes: [node("a", "action")], edges: [edge("e", "ghost", "a", "when")] };
    expect(buildOutline(graph)[0]?.inbound[0]?.text).toBe("ghost into run when");
  });

  it("property: one row per node, links matching the edges", () => {
    const rand = rng(81);
    for (let i = 0; i < 200; i += 1) {
      const graph = randomGraph(rand);
      const out = buildOutline(graph);
      expect(out).toHaveLength(graph.nodes.length);
      const links = out.reduce((sum, r) => sum + r.inbound.length + r.outbound.length, 0);
      const ids = new Set(graph.nodes.map((n) => n.id));
      const ends = graph.edges.reduce(
        (sum, e) => sum + (ids.has(e.source) ? 1 : 0) + (ids.has(e.target) ? 1 : 0),
        0,
      );
      expect(links).toBe(ends);
    }
  });
});

describe("validationAnnouncement: Gherkin 6's announce and focus-first", () => {
  it("says so when there is nothing wrong", () => {
    expect(validationAnnouncement(RULE, [])).toEqual({
      text: "No problems found.",
      focusNodeId: undefined,
    });
  });

  it("counts the problems and names the first by the documented order", () => {
    const got = validationAnnouncement(RULE, [
      { message: "Choose a channel.", nodeId: "act2" },
      { message: "Enter a value.", nodeId: "cmp1" },
    ]);
    expect(got).toEqual({
      text: "2 problems. First: ATR above: Enter a value.",
      focusNodeId: "cmp1",
    });
  });

  it("puts a rule-level problem first and handles one problem on a vanished node", () => {
    expect(
      validationAnnouncement(RULE, [
        { message: "Name the rule.", nodeId: "cmp1" },
        { message: "Add an action." },
      ]),
    ).toEqual({ text: "2 problems. First: Add an action.", focusNodeId: undefined });
    expect(validationAnnouncement(RULE, [{ message: "Gone.", nodeId: "x" }])).toEqual({
      text: "1 problem. First: Gone.",
      focusNodeId: undefined,
    });
  });
});

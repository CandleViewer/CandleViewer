import { describe, expect, it } from "vitest";
import type { A11yNode } from "../../../src/features/rule-builder-graph/a11y/graph.js";
import {
  buildOutline,
  nodeName,
  nodeNames,
  parameterSummary,
} from "../../../src/features/rule-builder-graph/a11y/outline.js";
import { validationAnnouncement } from "../../../src/features/rule-builder-graph/a11y/validation.js";
import { edge, node, oracle, randomGraph, rng, RULE } from "./fixtures.js";

describe("outline: Gherkin 3, the structure without the canvas", () => {
  const rows = buildOutline(RULE, oracle);

  it("lists every node in the documented order with its position", () => {
    expect(rows.map((r) => [r.id, r.index, r.size, r.depth])).toEqual([
      ["trigger", 1, 7, 0],
      ["and", 2, 7, 0],
      ["cmp1", 3, 7, 1],
      ["cmp2", 4, 7, 1],
      ["act1", 5, 7, 0],
      ["act2", 6, 7, 0],
      ["note", 7, 7, 0],
    ]);
  });

  it("describes type, name, parameters and every port with its type and connections", () => {
    const and = rows.find((r) => r.id === "and");
    expect(and?.description).toBe(
      "Logic gate AND, op and. Input port, boolean, connected to ATR above and Condition cmp2. " +
        "Output port, boolean, connected to Alert and Log.",
    );
    expect(and?.inbound.map((l) => [l.edgeId, l.nodeId, l.port])).toEqual([
      ["e1", "cmp1", "in"],
      ["e2", "cmp2", "in"],
    ]);
    expect(rows.find((r) => r.id === "trigger")?.description).toBe(
      "Trigger On bar close, no parameters. Output port, trigger, not connected.",
    );
    expect(rows.find((r) => r.id === "note")?.description).toBe(
      "Comment why, no parameters. No ports.",
    );
  });

  it("lists an empty input as not connected (a11y lens A-3)", () => {
    const cmp1 = rows.find((r) => r.id === "cmp1");
    expect(cmp1?.ports.map((p) => [p.direction, p.port, p.type, p.links.length])).toEqual([
      ["input", "left", "number", 0],
      ["input", "right", "number", 0],
      ["output", "out", "boolean", 1],
    ]);
    expect(cmp1?.description).toBe(
      "Condition ATR above, op gt, value 14. Input A port, number, not connected. " +
        "Input B port, number, not connected. Output port, boolean, connected to AND.",
    );
  });

  it("says a node with inputs has no output", () => {
    expect(rows.find((r) => r.id === "act1")?.description).toBe(
      "Action Alert, channel toast. Run when port, action, connected to AND. No output.",
    );
  });

  it("names a node from its own name or label, a comment also from its text, else type and id", () => {
    expect(nodeName(node("a", "action", { name: "  Alert " }))).toBe("Alert");
    expect(nodeName(node("a", "action", { name: " ", label: "Log" }))).toBe("Log");
    expect(nodeName(node("g", "logicGate", { name: 3 }))).toBe("Logic gate g");
    expect(nodeName(node("c", "comment", { text: " why " }))).toBe("why");
    expect(nodeName(node("a", "action", { text: "Buy now" }))).toBe("Action a");
  });

  it("reads an action's text as a parameter, a comment's never (code lens L5)", () => {
    expect(parameterSummary(node("a", "action", { text: "Buy now" }))).toBe("text Buy now");
    expect(parameterSummary(node("c", "comment", { text: "why" }))).toBe("no parameters");
  });

  it("tells two nodes with one name apart by position (a11y lens A-9)", () => {
    const graph = {
      nodes: [node("x", "logicGate", { name: "Check" }), node("y", "logicGate", { name: "Check" })],
      edges: [edge("e1", "x", "y", "in")],
    };
    expect(nodeNames(graph)).toEqual(
      new Map([
        ["y", "Check (node 1)"],
        ["x", "Check (node 2)"],
      ]),
    );
    const [y] = buildOutline(graph, oracle);
    expect(y?.description).toBe(
      "Logic gate Check (node 1), no parameters. Input port, boolean, connected to " +
        "Check (node 2). Output port, boolean, not connected.",
    );
  });

  it("summarises scalar parameters and counts the rest", () => {
    const data = { kind: "comparison", node_id: "x", z: true, a: 1, nested: { b: 2 }, n: Infinity };
    expect(parameterSummary(node("x", "condition", data))).toBe(
      "a 1, z true, plus 2 more settings",
    );
    expect(parameterSummary(node("x", "condition", { window: [1, 2] }))).toBe("parameters set");
    expect(parameterSummary(node("x", "trigger"))).toBe("no parameters");
    expect(parameterSummary(node("g", "logicGate", { op: "and", children: [null, null] }))).toBe(
      "op and",
    );
  });

  it("never reads an account id aloud (security lens r1, Info)", () => {
    const data = { kind: "comparison", op: "gt", account_id: "acct-7" };
    expect(parameterSummary(node("x", "condition", data))).toBe("op gt");
  });

  it("names a dangling edge end by its id, and a port only an edge names", () => {
    const graph = {
      nodes: [node("a", "action")],
      edges: [edge("e", "ghost", "a", "when"), edge("f", "ghost", "a", "in")],
    };
    const [row] = buildOutline(graph, oracle);
    expect(row?.inbound[0]?.text).toBe("ghost into run when");
    expect(row?.description).toBe(
      "Action Action a, no parameters. Run when port, action, connected to ghost. " +
        "Input port, type unknown, connected to ghost. No output.",
    );
  });

  it("property: one row per node, links matching the edges, every declared input listed", () => {
    const rand = rng(81);
    for (let i = 0; i < 200; i += 1) {
      const graph = randomGraph(rand);
      const out = buildOutline(graph, oracle);
      expect(out).toHaveLength(graph.nodes.length);
      const links = out.reduce((sum, r) => sum + r.inbound.length + r.outbound.length, 0);
      const ids = new Set(graph.nodes.map((n) => n.id));
      const ends = graph.edges.reduce(
        (sum, e) => sum + (ids.has(e.source) ? 1 : 0) + (ids.has(e.target) ? 1 : 0),
        0,
      );
      expect(links).toBe(ends);
      for (const row of out) {
        const n = graph.nodes.find((g) => g.id === row.id) as A11yNode;
        const inputs = row.ports.filter((p) => p.direction === "input").map((p) => p.port);
        for (const [port] of oracle.inputsOf(n)) expect(inputs).toContain(port);
      }
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
      text: "2 problems. First: ATR above: Enter a value. 1 more problem in the problems list.",
      focusNodeId: "cmp1",
    });
  });

  it("puts a rule-level problem first and handles one problem on a vanished node", () => {
    expect(
      validationAnnouncement(RULE, [
        { message: "Name the rule.", nodeId: "cmp1" },
        { message: "Add an action." },
      ]),
    ).toEqual({
      text: "2 problems. First: Add an action. 1 more problem in the problems list.",
      focusNodeId: undefined,
    });
    expect(validationAnnouncement(RULE, [{ message: "Gone.", nodeId: "x" }])).toEqual({
      text: "1 problem. First: Gone.",
      focusNodeId: undefined,
    });
  });
});

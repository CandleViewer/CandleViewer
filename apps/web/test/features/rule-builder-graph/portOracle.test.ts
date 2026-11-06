// @vitest-environment node
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import {
  canConnect,
  isRuleGraphError,
  PORT_COMPAT,
  PORT_TYPES,
  type GraphNode,
} from "@candleviewer/rule-graph";
import { describe, expect, it } from "vitest";
import { REFUSAL } from "../../../src/features/rule-builder-graph/a11y/copy.js";
import type { A11yGraph } from "../../../src/features/rule-builder-graph/a11y/graph.js";
import { verdictFor } from "../../../src/features/rule-builder-graph/a11y/portSelection.js";
import {
  LIST_PORT,
  portOracle,
} from "../../../src/features/rule-builder-graph/model/portOracle.js";
import { edge, node } from "./fixtures.js";

/** The E37-D05 copy deck (`docs/design/E37/`): the 36 `rules.graph.connect.*` rows are PORT_COMPAT's. */
const DECK = resolve(import.meta.dirname, "../../../../../docs/design/E37/E37-D05-copy-deck.jsonl");

interface DeckRow {
  readonly key?: string;
  readonly text?: string;
  readonly state?: string;
}

const CONNECT_ROWS = readFileSync(DECK, "utf8")
  .split("\n")
  .filter((line) => line.trim() !== "")
  .map((line) => JSON.parse(line) as DeckRow)
  .filter((row) => row.key?.startsWith("rules.graph.connect.") === true);

/** One node per kind, with the output type each one gives an edge. */
const SOURCES: readonly (readonly [GraphNode, string])[] = [
  [node("src", "trigger"), "trigger"],
  [node("src", "condition", { kind: "comparison", op: "gt" }), "boolean"],
  [node("src", "logicGate", { op: "all_of" }), "boolean"],
  [node("src", "condition", { kind: "temporal", op: "sustained_for" }), "boolean"],
  [node("src", "condition", { kind: "arithmetic", op: "add" }), "number"],
];

/** One input per kind and port, with its type. */
const TARGETS: readonly (readonly [GraphNode, string, string])[] = [
  [node("dst", "action", { type: "flatten_position" }), "when", "action"],
  [node("dst", "logicGate", { op: "any_of" }), "in", "boolean"],
  [node("dst", "condition", { kind: "comparison", op: "gt" }), "left", "number"],
  [node("dst", "condition", { kind: "comparison", op: "gt" }), "right", "number"],
  [node("dst", "condition", { kind: "temporal", op: "sustained_for" }), "child", "boolean"],
  [node("dst", "condition", { kind: "arithmetic", op: "add" }), "in", "number"],
];

describe("Incompatible connection is refused with a reason (AC 2, the verdict)", () => {
  it("refuses a boolean output dropped on a number input with the matrix's own sentence", () => {
    const graph: A11yGraph = {
      nodes: [
        node("c1", "condition", { kind: "comparison", op: "gt" }),
        node("c2", "condition", { kind: "comparison", op: "gt" }),
      ],
      edges: [],
    };
    expect(verdictFor(graph, portOracle, "c1", "c2", "left")).toEqual({
      ok: false,
      reason: PORT_COMPAT.boolean.number,
    });
  });

  it("answers all 36 type pairs as rule-graph's canConnect and PORT_COMPAT do", () => {
    for (const from of PORT_TYPES) {
      for (const to of PORT_TYPES) {
        const cell = PORT_COMPAT[from][to];
        const expected = cell === true ? { ok: true } : { ok: false, reason: cell };
        expect(portOracle.canConnect(from, to), `${from} -> ${to}`).toEqual(expected);
        expect(portOracle.canConnect(from, to)).toEqual(canConnect(from, to));
      }
    }
  });

  it("speaks each of the 29 refusals as its rules.graph.connect deck row, byte for byte", () => {
    expect(CONNECT_ROWS).toHaveLength(36);
    const refused = CONNECT_ROWS.filter((row) => row.state === "incompatible");
    expect(refused).toHaveLength(29);
    for (const row of CONNECT_ROWS) {
      const [from = "", to = ""] = (row.key ?? "").split(".").slice(3);
      const verdict = portOracle.canConnect(from, to);
      if (row.state === "compatible") expect(verdict, row.key).toEqual({ ok: true });
      else expect(verdict, row.key).toEqual({ ok: false, reason: row.text });
    }
  });

  it("gives verdictFor the matrix's answer for every pair two real nodes can make", () => {
    for (const [source, fromType] of SOURCES) {
      for (const [target, port, toType] of TARGETS) {
        const graph: A11yGraph = { nodes: [source, target], edges: [] };
        const label = `${fromType} -> ${target.type}.${port}`;
        expect(verdictFor(graph, portOracle, "src", "dst", port), label).toEqual(
          portOracle.canConnect(fromType, toType),
        );
      }
    }
  });

  it("refuses an unknown port type as rule-graph does, with SCHEMA_VIOLATION", () => {
    let thrown: unknown;
    try {
      portOracle.canConnect("boolean", "colour");
    } catch (error) {
      thrown = error;
    }
    expect(isRuleGraphError(thrown) && thrown.code).toBe("SCHEMA_VIOLATION");
  });
});

describe("the port oracle reads rule-graph's port catalogue", () => {
  it.each([
    ["a trigger", node("n", "trigger"), "trigger", []],
    ["a comment", node("n", "comment", { text: "why" }), null, []],
    ["an action", node("n", "action", { type: "flatten_position" }), null, [["when", "action"]]],
    ["a gate", node("n", "logicGate", { op: "all_of" }), "boolean", [["in", "boolean"]]],
    [
      "a two-operand comparison",
      node("n", "condition", { kind: "comparison", op: "gt" }),
      "boolean",
      [
        ["left", "number"],
        ["right", "number"],
      ],
    ],
    [
      "a one-operand comparison",
      node("n", "condition", { kind: "comparison", op: "is_true" }),
      "boolean",
      [["left", "number"]],
    ],
    [
      "a between comparison",
      node("n", "condition", { kind: "comparison", op: "between" }),
      "boolean",
      [
        ["left", "number"],
        ["right", "number"],
        ["right2", "number"],
      ],
    ],
    [
      "a temporal condition",
      node("n", "condition", { kind: "temporal", op: "sustained_for" }),
      "boolean",
      [["child", "boolean"]],
    ],
    [
      "an arithmetic node",
      node("n", "condition", { kind: "arithmetic", op: "add" }),
      "number",
      [["in", "number"]],
    ],
  ] as const)("gives %s its output and inputs", (_, n, output, inputs) => {
    expect(portOracle.outputOf(n)).toBe(output);
    expect(portOracle.inputsOf(n)).toEqual(inputs);
  });

  it.each([
    ["a condition of no kind", node("n", "condition", {})],
    ["a condition naming another type's kind", node("n", "condition", { kind: "logicGate" })],
    // A stored graph is user data: the oracle meets nodes the type does not promise.
    [
      "a node whose data is not an object",
      { id: "n", type: "action", data: null } as unknown as GraphNode,
    ],
  ])("gives %s no ports, never throwing", (_, n) => {
    expect(portOracle.outputOf(n)).toBeNull();
    expect(portOracle.inputsOf(n)).toEqual([]);
  });

  it("lets only rule-graph's list input take more than one edge", () => {
    expect(LIST_PORT).toBe("in");
    for (const port of ["left", "right", "right2", "child", "when", "out"]) {
      expect(portOracle.acceptsMany(port), port).toBe(false);
    }
    expect(portOracle.acceptsMany("in")).toBe(true);
  });

  it("refuses a second edge into a single input, and takes several into a list", () => {
    const graph: A11yGraph = {
      nodes: [
        node("a", "condition", { kind: "arithmetic", op: "add" }),
        node("b", "condition", { kind: "arithmetic", op: "add" }),
        node("cmp", "condition", { kind: "comparison", op: "gt" }),
        node("sum", "condition", { kind: "arithmetic", op: "add" }),
      ],
      edges: [edge("e1", "a", "cmp", "left"), edge("e2", "a", "sum", "in")],
    };
    expect(verdictFor(graph, portOracle, "b", "cmp", "left")).toEqual({
      ok: false,
      reason: REFUSAL.occupied,
    });
    expect(verdictFor(graph, portOracle, "b", "sum", "in")).toEqual({ ok: true });
  });
});

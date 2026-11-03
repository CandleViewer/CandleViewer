// toCompileModel (E37-S01): the editor's graph as `POST /rules/{ruleId}/compile` reads it with
// `editor: "graph"` (rules/compiler/graph.py:1-14). Unit cases per rule of the shape, a property
// block on the seeded port of the server's generator, and the golden every hash vector's model is
// pinned in: services/api/tests/contract/test_rule_graph_compile_model_contract.py compiles each to
// its vector's ir_hash. CV_RULE_GRAPH_WRITE_GOLDEN=1 rewrites the golden instead of comparing.
import { readFileSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import type { RuleIr } from "@candleviewer/protocol/rule-ir";
import { describe, expect, it } from "vitest";
import { isTree, readLayout, toGraph } from "../src/adapter/toGraph.js";
import { toCompileModel, type CompileModel } from "../src/adapter/toCompileModel.js";
import { isFormRepresentable } from "../src/analysis/formSubset.js";
import { RuleGraphError, isRuleGraphError } from "../src/errors.js";
import type { GraphLayout, GraphModel, GraphNode } from "../src/model.js";
import { compileBack } from "./support/compileBack.js";
import { generator } from "./support/generate.js";

const IR = {
  rule_id: "00000000-0000-4000-8000-000000001067",
  version: 3,
  name: "Tighten on a crossing",
  enabled: false,
  mode: "disabled",
  scope: { level: "symbol", symbols: ["BTCUSDT"] },
  trigger: { type: "on_bar_close", timeframe: "1m" },
  conditions: {
    node_id: "g1",
    op: "all_of",
    children: [
      {
        node_id: "c1",
        op: "gt",
        left: { metric: "price" },
        right: {
          node_id: "x1",
          op: "add",
          operands: [
            { metric: "atr", params: { n: 14 } },
            { node_id: "x2", op: "mul", operands: [{ const: 2 }, { metric: "atr" }] },
            { const: 1 },
          ],
        },
      },
      {
        node_id: "t1",
        op: "sustained_for",
        window_ms: 10000,
        child: { node_id: "c2", op: "is_true", left: { metric: "position_open" } },
      },
    ],
  },
  actions: [
    { node_id: "a2", type: "send_notification", params: { channel: "ui" } },
    {
      node_id: "a1",
      type: "modify_stop_loss",
      params: { mode: "atr", value: 2, only_tighten: true },
    },
  ],
  editor: "form",
  graph_layout: {
    positions: { g1: { x: 240, y: 0 } },
    comments: [{ id: "note1", text: "why" }],
    zoom: 1,
  },
} as unknown as RuleIr; // a test document: the generated type's optional fields are filled by default
const GRAPH = toGraph(IR);
const LAYOUT = readLayout(IR.graph_layout);
const MODEL = toCompileModel(GRAPH, LAYOUT);
const ids = (model: CompileModel) => model.nodes.map((node) => [node.id, node.type]);
const edge = (from: string, to: string, port: string) => ({ from, to, port });
const node = (
  id: string,
  type: GraphNode["type"],
  data: Record<string, unknown> = {},
): GraphNode => ({
  id,
  type,
  data,
});
const graphOf = (nodes: GraphNode[], edges: GraphModel["edges"] = []): GraphModel => ({
  envelope: { name: "x" },
  nodes,
  edges,
});
const link = (id: string, source: string, target: string, targetPort: string) => ({
  id,
  source,
  sourcePort: "out",
  target,
  targetPort,
});
/** The RuleGraphError `run` throws, or none. */
function thrown(run: () => unknown): RuleGraphError | undefined {
  try {
    run();
  } catch (error) {
    if (isRuleGraphError(error)) return error;
    throw error;
  }
  return undefined;
}

describe("toCompileModel: the shape compile reads", () => {
  it("spreads the envelope to the top level, with the trigger node's data as trigger", () => {
    expect(MODEL).toMatchObject({
      rule_id: IR.rule_id,
      version: 3,
      name: "Tighten on a crossing",
      scope: IR.scope,
      editor: "form",
      trigger: { type: "on_bar_close", timeframe: "1m" },
    });
    expect(MODEL).not.toHaveProperty("envelope");
    expect(MODEL.nodes.some((n) => n.id === "trigger")).toBe(false);
  });

  it("types each condition by its kind and a gate as boolean, operands as operand", () => {
    expect(ids(MODEL)).toEqual([
      ["a2", "action"],
      ["a1", "action"],
      ["g1", "boolean"],
      ["c1", "comparison"],
      ["x1", "arithmetic"],
      ["x1.in.1", "operand"],
      ["x1.in.3", "operand"],
      ["x2", "arithmetic"],
      ["x2.in.1", "operand"],
      ["x2.in.2", "operand"],
      ["t1", "temporal"],
      ["c2", "comparison"],
    ]);
  });

  it("keeps the actions in graph order, which is their IR order", () => {
    expect(MODEL.nodes.filter((n) => n.type === "action").map((n) => n.id)).toEqual(["a2", "a1"]);
  });

  it("strips the editor's kind from a condition's data and the list from a list node's", () => {
    const data = Object.fromEntries(MODEL.nodes.map((n) => [n.id, n.data]));
    expect(data["c1"]).toEqual({ op: "gt", left: { metric: "price" } });
    expect(data["x1"]).toEqual({ op: "add" });
    expect(data["g1"]).toEqual({ op: "all_of" });
    expect(data["t1"]).toEqual({ op: "sustained_for", window_ms: 10000 });
    for (const n of MODEL.nodes) expect(n.data, n.id).not.toHaveProperty("kind");
    expect(data["a1"]).toEqual({
      type: "modify_stop_loss",
      params: { mode: "atr", value: 2, only_tighten: true },
    });
  });

  it("writes each edge as from, to and the input it feeds, a list node's in list order", () => {
    expect(MODEL.edges).toEqual([
      edge("g1", "a2", "when"),
      edge("x1", "c1", "right"),
      edge("c2", "t1", "child"),
      edge("g1", "a1", "when"),
      edge("c1", "g1", "in"),
      edge("t1", "g1", "in"),
      edge("x1.in.1", "x1", "in"),
      edge("x2", "x1", "in"),
      edge("x1.in.3", "x1", "in"),
      edge("x2.in.1", "x2", "in"),
      edge("x2.in.2", "x2", "in"),
    ]);
  });

  it("turns each inline list operand into an operand node holding its value", () => {
    const data = Object.fromEntries(MODEL.nodes.map((n) => [n.id, n.data]));
    expect(data["x1.in.1"]).toEqual({ metric: "atr", params: { n: 14 } });
    expect(data["x1.in.3"]).toEqual({ const: 1 });
    expect(data["x2.in.1"]).toEqual({ const: 2 });
  });

  it("moves the comments to graph_layout.comments, beside the layout's positions", () => {
    expect(MODEL["graph_layout"]).toEqual({
      positions: { g1: { x: 240, y: 0 } },
      collapsed: [],
      comments: [{ id: "note1", text: "why" }],
    });
    expect(MODEL.nodes.some((n) => n.id === "note1")).toBe(false);
  });

  it("sends only the presentation keys the client owns: a stored layout's other keys stay home", () => {
    const stored = {
      ...IR.graph_layout,
      collapsed: ["g1"],
      node_only_constructs: [{ node_id: "x1", reason: "arithmetic operand in 'right'" }],
      auto: true,
    };
    const ir = { ...IR, graph_layout: stored } as RuleIr;
    const model = toCompileModel(toGraph(ir), readLayout(ir.graph_layout));
    expect(Object.keys(model["graph_layout"] as object).sort()).toEqual([
      "collapsed",
      "comments",
      "positions",
    ]);
    expect(model["graph_layout"]).toMatchObject({ collapsed: ["g1"] });
    expect(JSON.stringify(model)).not.toContain("node_only_constructs");
  });

  it("reads graph-only from the rule itself, never from a marker in its stored layout", () => {
    const form = {
      ...IR,
      conditions: { node_id: "c9", op: "is_true", left: { metric: "position_open" } },
    } as unknown as RuleIr; // a form-subset rule: one comparison
    const marked = { ...form, graph_layout: { node_only_constructs: [{ node_id: "c9" }] } };
    expect(isFormRepresentable(marked as RuleIr)).toEqual([]);
    expect(isFormRepresentable(marked as RuleIr)).toEqual(isFormRepresentable(form));
  });

  it("compiles, as the server builds it, back to the rule's own conditions and actions", () => {
    const back = compileBack(MODEL);
    expect(back["conditions"]).toEqual(IR.conditions);
    expect(back["actions"]).toEqual(IR.actions);
  });

  it("keeps its own graph_layout, nodes and edges over an envelope that holds them", () => {
    const envelope = { name: "x", graph_layout: { zoom: 2 }, nodes: ["n"], edges: ["e"] };
    const model = toCompileModel({ ...GRAPH, envelope }, LAYOUT);
    expect(model["graph_layout"]).toEqual(MODEL["graph_layout"]);
    expect([model.nodes, model.edges]).toEqual([MODEL.nodes, MODEL.edges]);
  });

  it("sends an empty layout by default, the comments still in it", () => {
    expect(toCompileModel(GRAPH)["graph_layout"]).toEqual({
      positions: {},
      collapsed: [],
      comments: [{ id: "note1", text: "why" }],
    });
  });
});

describe("toCompileModel: the editing graph as it stands", () => {
  const gate = (children?: unknown[]) =>
    node("g", "logicGate", children === undefined ? { op: "any_of" } : { op: "any_of", children });
  const cmp = (id: string) => node(id, "condition", { kind: "comparison", op: "is_true" });

  it("reads a list node with no list as one item per in edge, in edge order", () => {
    const model = toCompileModel(
      graphOf(
        [gate(), cmp("b"), cmp("a")],
        [link("e1", "b", "g", "in"), link("e2", "a", "g", "in")],
      ),
    );
    expect(model.edges).toEqual([edge("b", "g", "in"), edge("a", "g", "in")]);
  });

  it("puts in edges past the list's empty items after them, and drops an empty item no edge fills", () => {
    const more = graphOf(
      [gate([null]), cmp("b"), cmp("a")],
      [link("e1", "b", "g", "in"), link("e2", "a", "g", "in")],
    );
    expect(toCompileModel(more).edges).toEqual([edge("b", "g", "in"), edge("a", "g", "in")]);
    const fewer = graphOf([gate([null, null]), cmp("a")], [link("e1", "a", "g", "in")]);
    expect(toCompileModel(fewer).edges).toEqual([edge("a", "g", "in")]);
  });

  it("names an operand node apart from a node that holds its first-choice id", () => {
    const sum = node("s", "condition", { kind: "arithmetic", op: "add", operands: [{ const: 1 }] });
    const model = toCompileModel(graphOf([sum, cmp("s.in.1")]));
    expect(ids(model)).toEqual([
      ["s", "arithmetic"],
      ["s.in.1.2", "operand"],
      ["s.in.1", "comparison"],
    ]);
  });

  it("passes edges it cannot place through as they are, for compile to report", () => {
    const model = toCompileModel(graphOf([cmp("a")], [link("e1", "a", "gone", "in")]));
    expect(model.edges).toEqual([edge("a", "gone", "in")]);
  });

  it("refuses an edge on a port its node does not read: every edge sent feeds a read port", () => {
    const stray = graphOf([gate(), cmp("a")], [link("e1", "a", "g", "left")]);
    expect(thrown(() => toCompileModel(stray))).toMatchObject({
      code: "SCHEMA_VIOLATION",
      nodeIds: ["a", "g"],
    });
    const intoComparison = graphOf([cmp("a"), cmp("b")], [link("e1", "a", "b", "in")]);
    expect(thrown(() => toCompileModel(intoComparison))?.code).toBe("SCHEMA_VIOLATION");
  });

  it("sends no trigger when the graph has none, and refuses a second one", () => {
    expect(toCompileModel(graphOf([cmp("a")]))).not.toHaveProperty("trigger");
    const two = graphOf([node("t1", "trigger", { type: "on_timer" }), node("t2", "trigger")]);
    expect(thrown(() => toCompileModel(two))).toMatchObject({
      code: "SCHEMA_VIOLATION",
      nodeIds: ["t1", "t2"],
    });
  });

  it("refuses a node of no known kind with SCHEMA_VIOLATION", () => {
    const unknown = graphOf([node("w", "condition", { kind: "widget" })]);
    expect(thrown(() => toCompileModel(unknown))).toMatchObject({
      code: "SCHEMA_VIOLATION",
      nodeIds: ["w"],
    });
  });

  it("refuses an edge that names no nodes, a graph with no lists and a layout or envelope that is no object", () => {
    const bad = { ...graphOf([cmp("a")]), edges: [{ id: "e1" }] } as unknown as GraphModel;
    expect(thrown(() => toCompileModel(bad))?.code).toBe("SCHEMA_VIOLATION");
    const listless = { envelope: {}, nodes: {}, edges: [] } as unknown as GraphModel;
    expect(thrown(() => toCompileModel(listless))?.code).toBe("SCHEMA_VIOLATION");
    const layout = null as unknown as GraphLayout;
    expect(thrown(() => toCompileModel(graphOf([]), layout))?.code).toBe("SCHEMA_VIOLATION");
    const envelope = { ...graphOf([]), envelope: "x" } as unknown as GraphModel;
    expect(thrown(() => toCompileModel(envelope))?.code).toBe("SCHEMA_VIOLATION");
  });
});

describe("toCompileModel on documents from the server's generator (property)", () => {
  const sorted = (_: string, v: unknown) =>
    isTree(v) ? Object.fromEntries(Object.entries(v).sort()) : v;
  /** The JSON text of `ir`, keys in order, with no graph_layout (compile copies it as sent). */
  const whole = (ir: object) => JSON.stringify({ ...ir, graph_layout: null }, sorted);

  it(
    "compiles back to the very document, editor aside, for 2 000 seeded documents",
    { timeout: 60_000 },
    () => {
      const { rule } = generator(1067);
      let kept = 0;
      for (let i = 0; i < 2_000; i++) {
        const doc = rule(i % 3 === 2);
        let graph: GraphModel;
        try {
          graph = toGraph(doc);
        } catch (error) {
          if (isRuleGraphError(error)) continue; // a limit toGraph documents (property.test.ts)
          throw error;
        }
        const model = toCompileModel(graph, readLayout(doc.graph_layout));
        for (const n of model.nodes) {
          expect([
            "comparison",
            "boolean",
            "temporal",
            "arithmetic",
            "operand",
            "action",
          ]).toContain(n.type);
          expect(n.data, `document ${i}`).not.toHaveProperty("kind");
        }
        expect(whole(compileBack(model)), `document ${i}`).toBe(whole({ ...doc, editor: "graph" }));
        kept += 1;
      }
      expect(kept).toBeGreaterThan(1_000);
    },
  );
});

// The golden: one compile model per hash vector a JS client sends (js, with an ir_hash).
type Vector = { name: string; ir: string; js: boolean; ir_hash?: string };
type Golden = { $note: string; models: { name: string; ir_hash: string; model: CompileModel }[] };
const FIXTURES = join(import.meta.dirname, "..", "..", "fixtures/golden");
const VECTORS = join(FIXTURES, "rule-ir/hash_vectors.json");
const GOLDEN = join(FIXTURES, "rule-graph/compile_models.json");
const NOTE =
  "GENERATED - do not hand-edit. One compile model per hash vector a JS client sends (js, with an " +
  "ir_hash) of golden/rule-ir/hash_vectors.json: toCompileModel(toGraph(ir), " +
  "readLayout(ir.graph_layout)) from packages/rule-graph. Regenerate with " +
  "CV_RULE_GRAPH_WRITE_GOLDEN=1 on packages/rule-graph/test/compileModel.test.ts and review the " +
  "diff; services/api/tests/contract/test_rule_graph_compile_model_contract.py compiles each " +
  "model to its vector's ir_hash.";

function goldenNow(): Golden {
  const { vectors } = JSON.parse(readFileSync(VECTORS, "utf8")) as { vectors: Vector[] };
  const models = vectors
    .filter((v) => v.js && v.ir_hash !== undefined)
    .map((v) => {
      const ir = JSON.parse(v.ir) as RuleIr;
      const model = toCompileModel(toGraph(ir), readLayout(ir.graph_layout));
      return { name: v.name, ir_hash: v.ir_hash as string, model };
    });
  return { $note: NOTE, models };
}

describe("the compile-model golden (packages/fixtures/golden/rule-graph/compile_models.json)", () => {
  it("holds the model of every vector a JS client sends, as toCompileModel builds it now", () => {
    // Compact: the commit hook's prettier lays it out, keeping each short object on one line.
    const text = `${JSON.stringify(goldenNow())}\n`;
    if (process.env["CV_RULE_GRAPH_WRITE_GOLDEN"] === "1") writeFileSync(GOLDEN, text);
    // Compared as sent: JSON text, so a -0 is the 0 the client writes. Any layout of the file reads.
    const [stored, sent] = [readFileSync(GOLDEN, "utf8"), text].map((t) => JSON.parse(t) as Golden);
    expect(stored?.models.map((m) => m.name)).toEqual(sent?.models.map((m) => m.name));
    expect(stored, "stale: rerun with CV_RULE_GRAPH_WRITE_GOLDEN=1 and review the diff").toEqual(
      sent,
    );
  });
});

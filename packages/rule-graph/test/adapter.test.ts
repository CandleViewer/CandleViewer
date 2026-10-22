import { readFileSync } from "node:fs";
import { join } from "node:path";
import type { RuleIr } from "@candleviewer/protocol/rule-ir";
import { describe, expect, it } from "vitest";
import { nodesNeedingLayout, readLayout, toGraph } from "../src/adapter/toGraph.js";
import { toIr } from "../src/adapter/toIr.js";
import { canonicalise, hash } from "../src/canonical/canonicalise.js";
import type { GraphEdge, GraphModel, GraphNode } from "../src/model.js";

// Written and byte-checked by services/api/tests/rules/roundtrip/test_client_hash_vectors.py.
type V = { name: string; ir: string; js: boolean; canonical?: string; ir_hash?: string };
const FILE = join(import.meta.dirname, "..", "..", "fixtures/golden/rule-ir/hash_vectors.json");
const { vectors } = JSON.parse(readFileSync(FILE, "utf8")) as { vectors: V[] };
const sendable = vectors.filter((v) => v.js && v.canonical !== undefined);
const corpus = sendable.filter((v) => v.name.startsWith("corpus/"));
const doc = (name: string) => JSON.parse((vectors.find((v) => v.name === name) as V).ir) as RuleIr;
const BASE = doc("edge/base"); // condition c1 (gt, inline operands), action a1
const based = (edit: object) => ({ ...BASE, ...edit }) as RuleIr;
const G = toGraph(doc("corpus/07_sys_time_stop")); // trigger, a1, a2, g1 all_of [c1, c2]
const SV = "SCHEMA_VIOLATION";
const LONE: GraphNode = { id: "c9", type: "condition", data: { kind: "comparison", op: "x" } };
const node = (id: string) => G.nodes.find((n) => n.id === id) as GraphNode;
function edge(source: string, target: string, targetPort: string): GraphEdge {
  return { id: `${source}>${target}`, source, sourcePort: "out", target, targetPort };
}
const plus = (...nodes: GraphNode[]): GraphModel => ({ ...G, nodes: [...G.nodes, ...nodes] });
const wired = (...more: GraphEdge[]): GraphModel => ({ ...G, edges: [...G.edges, ...more] });
const refusal = (code: string, more: object) => expect.objectContaining({ code, ...more });

/** Trigger, action a1 and logic gates g0 to g`n`-1, each fed `width` times by the next. */
function chain(n: number, width: number): GraphModel {
  const data = { op: "all_of", children: Array(width).fill(null) };
  const gate = (i: number): GraphNode => ({ id: `g${i}`, type: "logicGate", data });
  const gates = Array.from({ length: n }, (_, i) => gate(i));
  const feeds = gates.flatMap((_, i) => Array(width).fill(edge(`g${i + 1}`, `g${i}`, "in")));
  const nodes = [node("trigger"), node("a1"), ...gates, { ...LONE, id: `g${n}` }];
  return { ...G, nodes, edges: [edge("g0", "a1", "when"), ...feeds] };
}

describe("toGraph then toIr", () => {
  it.each(sendable)("give $name the server's canonical bytes and ir_hash again (AC1)", (v) => {
    const { ir } = toIr(toGraph(JSON.parse(v.ir) as RuleIr));
    expect(canonicalise(ir)).toBe(v.canonical);
    expect(hash(ir)).toBe(v.ir_hash);
  });

  it("meet every op of each IR node kind in the 30 corpus rules, with booleans as gates", () => {
    const ops: Record<string, Set<unknown>> = {};
    for (const { nodes } of corpus.map((v) => toGraph(JSON.parse(v.ir) as RuleIr))) {
      for (const { type, data } of nodes)
        (ops[String(data["kind"] ?? type)] ??= new Set()).add(data["op"]);
    }
    const sizes = ["logicGate", "comparison", "temporal", "arithmetic"].map((k) => ops[k]?.size);
    expect([corpus.length, ...sizes]).toEqual([30, 4, 15, 4, 9]); // as many as the schema lists
  });

  it("keep metric and const operands inline, and feed a node operand to its port or slot", () => {
    const y = { node_id: "y", op: "neg", operands: [{ const: 2 }] };
    const right = { node_id: "x", op: "add", operands: [{ const: 1 }, y] };
    const { nodes, edges } = toGraph(based({ conditions: { ...BASE.conditions, right } }));
    const left = { metric: "price", params: { n: 14 } };
    expect(nodes.map(({ id, type, data }) => [id, type, data]).slice(1)).toEqual([
      ["a1", "action", { type: "send_notification", params: { channel: "ui" } }],
      ["c1", "condition", { kind: "comparison", op: "gt", left }],
      ["x", "condition", { kind: "arithmetic", op: "add", operands: [{ const: 1 }, null] }],
      ["y", "condition", { kind: "arithmetic", op: "neg", operands: [{ const: 2 }] }],
    ]);
    const wires = edges.map((e) => `${e.source}>${e.target}.${e.targetPort}`);
    expect(wires).toEqual(["c1>a1.when", "x>c1.right", "y>x.in"]);
  });

  it("keep a shared node once, with an edge to each node it feeds", () => {
    const { nodes, edges } = toGraph(doc("corpus/28_shared_atr_band"));
    expect(nodes.filter((n) => n.id === "c1")).toHaveLength(1);
    expect(edges.filter((e) => e.source === "c1").map((e) => e.target)).toEqual(["g2", "g3"]);
  });

  it("leave the hash alone when positions, collapsed states and comments change (AC2)", () => {
    const ir = doc("edge/presentation-and-metadata"); // a position, a collapsed node, comment k1
    const graph = toGraph(ir);
    expect(graph.nodes.at(-1)).toEqual({ id: "k1", type: "comment", data: { text: "note" } });
    const moved = { positions: { c1: { x: 1, y: 2 } }, collapsed: [] };
    const layout = { ...readLayout(ir.graph_layout), ...moved };
    const k2: GraphNode = { id: "k2", type: "comment", data: { text: "moved" } };
    const out = toIr({ ...graph, nodes: [...graph.nodes.slice(0, -1), k2] }, layout);
    expect(hash(out.ir)).toBe(hash(ir));
    expect(out.layout).toEqual({ ...layout, comments: [{ id: "k2", text: "moved" }] });
    expect(readLayout(out.ir["graph_layout"])).toEqual(out.layout);
  });

  it("read a stored graph_layout, keep the keys it does not know, and list unplaced nodes", () => {
    const stored = { auto: true, positions: { c1: { x: 0, y: 0 } }, node_only_constructs: [] };
    const extra = { auto: true, node_only_constructs: [] };
    const layout = readLayout(stored);
    expect(layout).toEqual({ positions: stored.positions, collapsed: [], comments: [], extra });
    expect(readLayout(null)).toEqual({ positions: {}, collapsed: [], comments: [], extra: {} });
    expect(nodesNeedingLayout(toGraph(BASE), layout)).toEqual(["trigger", "a1"]);
    for (const bad of [{ positions: [] }, { comments: [{ text: "no id" }] }]) {
      expect(() => readLayout(bad)).toThrow(refusal(SV, { nodeIds: [] }));
    }
  });
});

describe("toGraph refuses", () => {
  it("two different subtrees under one node_id, rather than merge them", () => {
    const c1 = BASE.conditions;
    const conditions = { node_id: "g", op: "all_of", children: [c1, { ...c1, op: "lt" }] };
    expect(() => toGraph(based({ conditions }))).toThrow(refusal(SV, { nodeIds: ["c1"] }));
  });

  it("an IR over the value bound, as canonicalise does", () => {
    const message = expect.stringContaining("$: the rule IR is over");
    expect(() => toGraph(based({ name: Array(20_000).fill(0) }))).toThrow(refusal(SV, { message }));
  });
});

describe("toIr refuses", () => {
  const inner = G.edges.slice(1, 3); // the edges into g1, none into an action
  const actionless = { ...G, nodes: G.nodes.filter((n) => n.type !== "action"), edges: inner };

  it("a cycle, naming its path, rather than emit an IR (AC4)", () => {
    const message = "The graph has a cycle: g1 -> c1 -> g1.";
    const cycle = refusal("CYCLE_DETECTED", { message, nodeIds: ["g1", "c1"] });
    expect(() => toIr(wired(edge("g1", "c1", "right2")))).toThrow(cycle);
  });

  it.each([
    ["actions fed by two roots", wired(edge("c1", "a2", "when")), "MULTIPLE_SINKS", ["g1", "c1"]],
    ["an action no condition feeds", { ...G, edges: G.edges.slice(0, 3) }, "DANGLING_PORT", ["a2"]],
    ["a condition no action follows", plus(LONE), "ORPHAN_NODE", ["c9"]],
    ["no action", actionless, "ORPHAN_NODE", ["g1", "c1", "c2"]],
    ["no trigger", { ...G, nodes: G.nodes.slice(1) }, SV, []],
    ["two triggers", plus({ ...node("trigger"), id: "t2" }), SV, ["trigger", "t2"]],
    ["a condition of no known kind", plus({ ...LONE, data: { kind: "boolean" } }), SV, ["c9"]],
    ["an edge from no node", wired(edge("zz", "g1", "in")), SV, ["zz", "g1"]],
    ["an edge into no node", wired(edge("c1", "zz", "in")), SV, ["c1", "zz"]],
    ["an edge to a port its node lacks", wired(edge("c1", "a1", "in")), SV, ["c1", "a1"]],
    ["an edge out of an action", wired(edge("a1", "g1", "in")), SV, ["a1", "g1"]],
    ["over 1 000 nodes", plus(...Array<GraphNode>(995).fill(LONE)), SV, []],
    ["a graph that expands past 20 000 nodes", chain(15, 2), SV, []],
    ["an IR nested past 64 levels", chain(40, 1), SV, []],
  ] as const)("%s", (_case, graph, code, nodeIds) => {
    expect(() => toIr(graph)).toThrow(refusal(code, { nodeIds }));
  });
});

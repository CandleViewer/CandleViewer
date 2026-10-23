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
/** G with `next` in place of the node of its id, and `more` edges. */
function swap(next: GraphNode, ...more: GraphEdge[]): GraphModel {
  const nodes = G.nodes.map((n) => (n.id === next.id ? next : n));
  return { ...G, nodes, edges: [...G.edges, ...more] };
}
const ids = (list: unknown) => (list as { node_id: string }[]).map((item) => item.node_id);
const refusal = (code: string, more: object) => expect.objectContaining({ code, ...more });

/** Trigger, action a1 and logic gates g0 to g`n`-1, each fed `width` times by the next. */
function chain(n: number, width: number, leaf: GraphNode["data"] = LONE.data): GraphModel {
  const data = { op: "all_of", children: Array(width).fill(null) };
  const gate = (i: number): GraphNode => ({ id: `g${i}`, type: "logicGate", data });
  const gates = Array.from({ length: n }, (_, i) => gate(i));
  const feeds = gates.flatMap((_, i) => Array(width).fill(edge(`g${i + 1}`, `g${i}`, "in")));
  const nodes = [node("trigger"), node("a1"), ...gates, { ...LONE, id: `g${n}`, data: leaf }];
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

  it("keep the envelope to the IR's other fields, edge ids unique and a gate's data", () => {
    const keys = "editor enabled ir_version limits mode name rule_id scope version".split(" ");
    expect(Object.keys(toGraph(BASE).envelope).sort()).toEqual(keys);
    expect(new Set(G.edges.map((e) => e.id)).size).toBe(G.edges.length);
    expect(G.edges.every((e) => e.sourcePort === "out")).toBe(true);
    expect(node("g1").data).toEqual({ op: "all_of", children: [null, null] });
  });

  it("keep a shared node once, with an edge to each node it feeds", () => {
    const { nodes, edges } = toGraph(doc("corpus/28_shared_atr_band"));
    expect(nodes.filter((n) => n.id === "c1")).toHaveLength(1);
    expect(edges.filter((e) => e.source === "c1").map((e) => e.target)).toEqual(["g2", "g3"]);
  });

  it("take the action order from the nodes and list order from the edges, never ids", () => {
    const graph = toGraph(doc("edge/renumbering")); // actions a10, then a2
    const actions = toIr({ ...graph, nodes: [...graph.nodes].reverse() }).ir["actions"];
    expect(ids(actions)).toEqual(["a2", "a10"]);
    const gate = toIr({ ...G, edges: [...G.edges].reverse() }).ir["conditions"];
    expect(ids((gate as { children: unknown }).children)).toEqual(["c2", "c1"]);
  });

  it.each([
    ["a2", "a10"],
    ["a10", "a2"],
  ])("keep two different actions in IR order, %s then %s, however their ids sort", (...kept) => {
    const [a] = BASE.actions;
    const other = { ...a, type: "flatten_position", params: {}, node_id: kept[1] };
    const graph = toGraph(based({ actions: [{ ...a, node_id: kept[0] }, other] }));
    expect(graph.nodes.filter((n) => n.type === "action").map((n) => n.id)).toEqual(kept);
    expect(ids(toIr(graph).ir["actions"])).toEqual(kept);
  });

  it("fill a null input, or a list a node lacks, from its edges, as the server does", () => {
    const c1 = { ...node("c1"), data: { ...node("c1").data, right2: null } };
    const { ir } = toIr(swap(c1, edge("c2", "c1", "right2")));
    const [first] = (ir["conditions"] as { children: { right2: unknown }[] }).children;
    expect(first?.right2).toMatchObject({ node_id: "c2" });
    const listless = swap({ ...node("g1"), data: { op: "all_of" } });
    expect(hash(toIr(listless).ir)).toBe(hash(doc("corpus/07_sys_time_stop")));
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

  it("carry the layout's other keys and collapsed list into graph_layout, else none", () => {
    const stored = { auto: true, collapsed: ["c1"], node_only_constructs: [] };
    const { extra, ...rest } = readLayout(stored);
    expect(toIr(G, { extra, ...rest }).ir["graph_layout"]).toEqual({ ...extra, ...rest });
    expect(toIr(G).layout).toEqual({ positions: {}, collapsed: [], comments: [], extra: {} });
  });

  it("read a stored graph_layout, keep the keys it does not know, and list unplaced nodes", () => {
    const stored = { auto: true, positions: { c1: { x: 0, y: 0 } }, node_only_constructs: [] };
    const extra = { auto: true, node_only_constructs: [] };
    const layout = readLayout(stored);
    expect(layout).toEqual({ positions: stored.positions, collapsed: [], comments: [], extra });
    expect(readLayout(null)).toEqual({ positions: {}, collapsed: [], comments: [], extra: {} });
    expect(nodesNeedingLayout(toGraph(BASE), layout)).toEqual(["trigger", "a1"]);
    const ghost = plus({ ...LONE, id: "constructor" }); // an inherited name is no position
    expect(nodesNeedingLayout(ghost, layout)).toContain("constructor");
    const odd = [{ positions: [] }, { collapsed: "c1" }, { comments: {} }, { comments: [null] }];
    for (const bad of [...odd, { comments: [{ text: "no id" }] }]) {
      expect(() => readLayout(bad)).toThrow(refusal(SV, { nodeIds: [] }));
    }
  });
});

describe("toGraph refuses", () => {
  const c1 = BASE.conditions;
  const twins = { node_id: "g", op: "all_of", children: [c1, { ...c1, op: "lt" }] };
  const flipped = { ...twins, children: [c1, Object.fromEntries(Object.entries(c1).reverse())] };

  it("what is no rule IR object before reading it", () => {
    for (const ir of [null, [], "x"]) expect(() => toGraph(ir as never)).toThrow(refusal(SV, {}));
  });

  it.each([
    ["two subtrees under one node_id", { conditions: twins }, ["c1"]],
    ["a shared node whose copy lists its keys in another order", { conditions: flipped }, ["c1"]],
    ["an action's node_id on a condition", { conditions: { ...c1, node_id: "a1" } }, ["a1"]],
    ["the trigger's id on a condition", { conditions: { ...c1, node_id: "trigger" } }, ["trigger"]],
    ["two actions under one node_id", { actions: [...BASE.actions, ...BASE.actions] }, ["a1"]],
    ["a node's id on a comment", { graph_layout: { comments: [{ id: "a1", text: "" }] } }, ["a1"]],
    ["no action", { actions: [] }, []],
    ["a null action", { actions: [null] }, []],
    ["an action with no node_id", { actions: [{ type: "pause_rule", params: {} }] }, []],
    ["no conditions", { conditions: undefined }, []],
    ["no trigger", { trigger: null }, []],
    ["an IR over the value bound", { name: Array(20_000).fill(0) }, [], "$: the rule IR is over"],
  ] as const)("%s", (_case, edit, nodeIds, message?: string) => {
    const refused = refusal(SV, { nodeIds, message: expect.stringContaining(message ?? "") });
    expect(() => toGraph(based(edit))).toThrow(refused);
  });
});

describe("toIr refuses", () => {
  const inner = G.edges.slice(1, 3); // the edges into g1, none into an action
  const actionless = { ...G, nodes: G.nodes.filter((n) => n.type !== "action"), edges: inner };
  const perAction = { ...G, edges: [...inner, G.edges[0] as GraphEdge, edge("c1", "a2", "when")] };
  const fewer = { ...G, edges: G.edges.filter((e) => e.source !== "c2") };
  const right2 = edge("c2", "c1", "right2");
  const in1 = edge("c1", "g1", "in");
  const crossed = wired(right2, edge("c1", "c2", "right2"));
  const keys = Object.fromEntries(Array.from({ length: 1_000 }, (_, i) => [`k${i}`, i]));
  const list = { kind: "arithmetic", op: "add", operands: Array(1_000).fill({ const: 1 }) };

  it("a cycle, naming its path, rather than emit an IR (AC4)", () => {
    const message = "The graph has a cycle: g1 -> c1 -> g1.";
    const cycle = refusal("CYCLE_DETECTED", { message, nodeIds: ["g1", "c1"] });
    expect(() => toIr(wired(edge("g1", "c1", "right2")))).toThrow(cycle);
  });

  it.each([
    ["a cycle that misses the root", crossed, "CYCLE_DETECTED", ["c1", "c2"]],
    ["actions fed by two roots", wired(edge("c1", "a2", "when")), "MULTIPLE_SINKS", ["g1", "c1"]],
    ["actions fed by a root each", perAction, "MULTIPLE_SINKS", ["g1", "c1"]],
    ["an action fed twice by its root", wired(edge("g1", "a1", "when")), "MULTIPLE_SINKS", ["a1"]],
    ["an action no condition feeds", { ...G, edges: G.edges.slice(0, 3) }, "DANGLING_PORT", ["a2"]],
    ["a condition no action follows", plus(LONE), "ORPHAN_NODE", ["c9"]],
    ["no action", actionless, "ORPHAN_NODE", ["g1", "c1", "c2"]],
    ["no trigger", { ...G, nodes: G.nodes.slice(1) }, SV, [], "one trigger"],
    ["two triggers", plus({ ...node("trigger"), id: "t2" }), SV, ["trigger", "t2"]],
    ["two nodes under one id", plus(node("c1")), SV, ["c1"]],
    ["a condition of no known kind", plus({ ...LONE, data: { kind: "boolean" } }), SV, ["c9"]],
    ["a condition of an action's kind", plus({ ...LONE, data: { kind: "action" } }), SV, ["c9"]],
    ["a condition with no data", plus({ id: "c9", type: "condition" } as GraphNode), SV, ["c9"]],
    ["a gate with no data", swap({ id: "g1", type: "logicGate" } as GraphNode), SV, ["g1"]],
    ["a node that is no object", plus(null as unknown as GraphNode), SV, []],
    ["an edge from no node", wired(edge("zz", "g1", "in")), SV, ["zz", "g1"]],
    ["an edge into no node", wired(edge("c1", "zz", "in")), SV, ["c1", "zz"]],
    ["an edge to a port its node lacks", wired(edge("c1", "a1", "in")), SV, ["c1", "a1"]],
    ["an edge out of an action", wired(edge("a1", "g1", "in")), SV, ["a1", "g1"]],
    ["an edge that is no object", wired(null as unknown as GraphEdge), SV, []],
    ["an input fed twice", wired(right2, right2), SV, ["c1"]],
    ["an input both inline and fed", wired(edge("c2", "c1", "left")), SV, ["c1"]],
    ["more list edges than empty slots", wired(in1), SV, ["g1"]],
    ["fewer list edges than empty slots", fewer, SV, ["g1"]],
    ["a list that is no list", swap({ ...node("g1"), data: { children: "x" } }), SV, ["g1"]],
    ["a graph with no node list", { ...G, nodes: "x" } as unknown as GraphModel, SV, [], "lists"],
    ["no graph at all", null as unknown as GraphModel, SV, [], "one trigger"],
    ["exactly 1 000 nodes, past the cap", plus(...Array<GraphNode>(994).fill(LONE)), SV, ["c9"]],
    ["over 1 000 nodes", plus(...Array<GraphNode>(995).fill(LONE)), SV, [], "Over 1 000"],
    ["exactly 4 000 edges, past the cap", wired(...Array<GraphEdge>(3_996).fill(in1)), SV, ["g1"]],
    ["over 4 000 edges", wired(...Array<GraphEdge>(3_997).fill(in1)), SV, [], "Over 1 000"],
    ["a graph that expands past 20 000 values", chain(15, 2), SV, [], "expands past 20000"],
    ["a fan-in on a node of 1 000 keys", chain(5, 2, { ...LONE.data, ...keys }), SV, [], "expands"],
    ["a fan-in on a list of 1 000 items", chain(5, 2, list), SV, [], "expands past"],
    ["an IR nested past 64 levels", chain(40, 1), SV, [], "64 levels deep"],
  ] as const)("%s", (_case, graph, code, nodeIds, message?: string) => {
    const refused = refusal(code, { nodeIds, message: expect.stringContaining(message ?? "") });
    expect(() => toIr(graph)).toThrow(refused);
  });
});

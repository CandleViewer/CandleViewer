import { readFileSync } from "node:fs";
import { join } from "node:path";
import type { RuleIr } from "@candleviewer/protocol/rule-ir";
import { describe, expect, it } from "vitest";
import { toGraph } from "../src/adapter/toGraph.js";
import { toIr } from "../src/adapter/toIr.js";
import { findCycles } from "../src/analysis/cycles.js";
import { isFormRepresentable } from "../src/analysis/formSubset.js";
import { findOrphans } from "../src/analysis/orphans.js";
import type { GraphEdge, GraphModel, GraphNode } from "../src/model.js";

// Written and byte-checked by services/api/tests/rules/roundtrip/test_client_hash_vectors.py:
// form_reasons is the server's form_incompatibility_reasons (rules/ir/form.py) for the body.
type V = { name: string; ir: string; js: boolean; canonical?: string; form_reasons?: string[] };
const FILE = join(import.meta.dirname, "..", "..", "fixtures/golden/rule-ir/hash_vectors.json");
const { vectors } = JSON.parse(readFileSync(FILE, "utf8")) as { vectors: V[] };
const doc = (name: string) => JSON.parse((vectors.find((v) => v.name === name) as V).ir) as RuleIr;
const sendable = vectors.filter((v) => v.js && v.canonical !== undefined);
const graphs = sendable.map((v) => [v.name, toGraph(JSON.parse(v.ir) as RuleIr)] as const);
const G = toGraph(doc("corpus/07_sys_time_stop")); // actions a1, a2 hang off g1, fed by c1, c2
const SV = expect.objectContaining({ code: "SCHEMA_VIOLATION" });
function edge(source: string, target: string, targetPort = "left"): GraphEdge {
  return { id: `${source}>${target}`, source, sourcePort: "out", target, targetPort };
}
const cond = (id: string): GraphNode => ({ id, type: "condition", data: { kind: "comparison" } });
const plus = (nodes: GraphNode[], ...more: GraphEdge[]): GraphModel => {
  return { ...G, nodes: [...G.nodes, ...nodes], edges: [...G.edges, ...more] };
};
const only = (...edges: GraphEdge[]) => findCycles({ envelope: {}, nodes: [], edges });
const [c8, c9] = [cond("c8"), cond("c9")];
const loop89 = [edge("c8", "c9"), edge("c9", "c8")]; // c8 and c9 feed each other alone
const perRoot = { ...G, edges: [...G.edges.slice(0, 3), edge("c1", "a2", "when")] };
const bare = { ...plus([{ ...c9, type: "comment" }]), edges: [] }; // and a comment, c9

describe("findCycles and findOrphans", () => {
  it.each(graphs)("find no cycle and no orphan in %s's graph", (_name, graph) => {
    expect([findCycles(graph), findOrphans(graph)]).toEqual([[], []]);
  });

  it.each([
    ["through the root", [], [edge("g1", "c1", "right2")], ["g1", "c1", "g1"]],
    ["no action reaches", [c8, c9], loop89, ["c8", "c9", "c8"]],
    ["of a node that feeds itself", [], [edge("c1", "c1", "right2")], ["c1", "c1"]],
  ] as const)("return the path of a cycle %s, which toIr refuses (AC4)", (_, nodes, more, path) => {
    const graph = plus([...nodes], ...more);
    expect(findCycles(graph)).toEqual(path); // in order, closing on its first node
    const message = `The graph has a cycle: ${path.join(" -> ")}.`;
    const refused = { code: "CYCLE_DETECTED", message, nodeIds: path.slice(0, -1) };
    expect(() => toIr(graph)).toThrow(expect.objectContaining(refused));
  });

  it("search from the ids in code point order, and each node's inputs in edge order", () => {
    const [high, astral] = ["\uffff", "\u{1f600}"]; // Python sorts U+FFFF first
    expect(only(edge(astral, astral), edge(high, high))).toEqual([high, high]);
    const [xy, xz] = [edge("y", "x"), edge("z", "x")]; // y and z each feed x, which feeds both
    expect(only(xy, edge("x", "y"), xz, edge("x", "z"))).toEqual(["x", "y", "x"]);
    expect(only(xz, edge("x", "z"), xy, edge("x", "y"))).toEqual(["x", "z", "x"]);
  });

  it("search without recursion: a cycle through 50 000 nodes", () => {
    const chain = Array.from({ length: 50_000 }, (_, i) => edge(`n${i + 1}`, `n${i}`));
    const path = only(...chain, edge("n0", "n50000"));
    expect([path.length, path[1], path.at(-2)]).toEqual([50_002, "n1", "n50000"]); // n0 on both ends
  });

  it.each([
    ["a condition that feeds nothing", plus([c9]), ["c9"]],
    ["a chain to nothing, in node order", plus([c8, c9], edge("c8", "c9")), ["c8", "c9"]],
    ["a cycle no action reaches", plus([c8, c9], ...loop89), ["c8", "c9"]],
    ["a condition fed to an action's other port", plus([c9], edge("c9", "a1")), ["c9"]],
    ["none on a cycle through the root", plus([], edge("g1", "c1", "right2")), []],
    ["none when the actions hang off a root each", perRoot, []],
    ["each gate and condition, not the trigger, a comment or an action", bare, ["g1", "c1", "c2"]],
  ] as const)("find as orphans %s", (_case, graph, found) => {
    expect(findOrphans(graph)).toEqual(found);
  });

  it("refuse what is no graph: no lists, an edge with no ids, a node of no kind", () => {
    const odd = [null, { ...edge("c1", "g1"), source: 7 }, { ...edge("c1", "g1"), target: null }];
    for (const graph of [null, { ...G, edges: "x" }, ...odd.map((e) => plus([], e as never))]) {
      for (const find of [findCycles, findOrphans]) expect(() => find(graph as never)).toThrow(SV);
    }
    expect(() => findOrphans(plus([{ ...c9, type: "gate" } as never]))).toThrow(SV); // portsOf's
  });
});

const BASE = doc("edge/base"); // its root is comparison c1 (gt, a metric and a const)
/** The verdict as the server words it: "<node id>: <reason>", in the server's order. */
const said = (ir: RuleIr) => isFormRepresentable(ir).map((r) => `${r.nodeId}: ${r.reason}`);
const rule = (conditions: object) => ({ ...BASE, conditions }) as RuleIr;
const [ONE, T] = [{ const: 1 }, { window_ms: 1e3 }];
const cmp = (node_id: string, more: object = {}) => ({ ...BASE.conditions, node_id, ...more });
const gate = (node_id: string, op: string, ...children: object[]) => ({ node_id, op, children });
const all = (id: string, ...children: object[]) => gate(id, "all_of", ...children);
const any = (id: string, ...children: object[]) => gate(id, "any_of", ...children);
const nOf = (id: string, ...children: object[]) => ({ ...gate(id, "n_of", ...children), n: 1 });
const wait = (id: string, op: string, child: object) => ({ ...T, node_id: id, op, child });
const sum = (id: string, ...xs: object[]) => ({ node_id: id, op: "add", operands: [ONE, ...xs] });
const [c1, c2, c3] = [cmp("c1"), cmp("c2"), cmp("c3")];
const cx = cmp("c1", { left: sum("x1") }); // c1 with a sum on its left
// form.py's words (:23-87); the vectors hold each to the server's own output but `deep` (:37).
const W = {
  sum: (id: string, at: string) => `${id}: arithmetic operand in '${at}' (graph-only construct)`,
  op: (id: string, op: string) => `${id}: boolean op '${op}' is graph-only`,
  deep: (id: string, op: string) => `${id}: boolean '${op}' nested deeper than two levels`,
  temporal: (id: string, op: string) => `${id}: temporal op '${op}' is graph-only`,
  wrap: (id: string) => `${id}: temporal node must directly wrap a comparison`,
  fan: (i: string, n: number) => `${i}: node fans out to ${n} consumers (shared node, graph-only)`,
};

describe("isFormRepresentable", () => {
  const judged = vectors.filter((v) => v.form_reasons !== undefined);
  it.each(judged)("give $name the server's form verdict, node ids and words alike (AC3)", (v) => {
    expect(said(JSON.parse(v.ir) as RuleIr)).toEqual(v.form_reasons);
  });

  const refused = vectors.filter((v) => v.name.startsWith("refused/") && v.js);
  it.each(refused)("refuse $name, as the server does, as a SCHEMA_VIOLATION", (v) => {
    expect(() => isFormRepresentable(JSON.parse(v.ir) as RuleIr)).toThrow(SV);
  });

  // One row per graph-only construct (24 §11.4) and per way form.py meets one; the vectors above
  // pin none_of (corpus/25), a gate under a root any_of (28), and other temporal ops (15, 22, 24).
  it.each([
    ["nested arithmetic", cmp("c1", { left: sum("x1", sum("x2")) }), [W.sum("c1", "left")]],
    ["a sum in right2", cmp("c1", { op: "between", right2: sum("x1") }), [W.sum("c1", "right2")]],
    ["an n_of node at the root", nOf("g1", c1, c2), [W.op("g1", "n_of")]],
    ["an n_of node under the root", all("g1", c1, nOf("g2", c2)), [W.deep("g2", "n_of")]],
    ["three-level boolean nesting", all("g1", any("g2", all("g3", c1))), [W.deep("g3", "all_of")]],
    ["an all_of under the root all_of", all("g1", all("g2", c1)), [W.deep("g2", "all_of")]],
    ["a sum under sustained_for", wait("t1", "sustained_for", cx), [W.sum("c1", "left")]],
    ["fan-out: a node used three times", all("g1", c1, any("g2", c1, c1)), [W.fan("c1", 3)]],
  ] as const)("name %s, in the server's words (AC3)", (_case, conditions, reasons) => {
    expect(said(rule(conditions))).toEqual(reasons);
  });

  it("name a temporal op and its child, every copy of a shared node, fan-out by code point", () => {
    const nested = wait("t1", "stable_for", wait("t2", "sustained_for", c1));
    expect(said(rule(nested))).toEqual([W.temporal("t1", "stable_for"), W.wrap("t1")]);
    const copies = [W.sum("c1", "left"), W.sum("c1", "left"), W.fan("c1", 2), W.fan("x1", 2)];
    expect(said(rule(all("g1", cx, any("g2", cx, c2))))).toEqual(copies); // form.py walks copies
    const [high, astral] = [cmp("\uffff"), cmp("\u{1f600}")]; // Python sorts U+FFFF first
    const shared = all("g1", astral, high, any("g2", astral, high));
    expect(said(rule(shared))).toEqual([W.fan("\uffff", 2), W.fan("\u{1f600}", 2)]);
  });

  it.each([
    ["a comparison at the root", c1],
    ["an all_of of any_of groups", all("g1", any("g2", c1, wait("t1", "sustained_for", c2)), c3)],
    ["an any_of of comparisons", any("g1", c1, c2)],
    ["sustained_for around a comparison", wait("t1", "sustained_for", c1)],
  ] as const)("find nothing in %s, which the form shows (AC3)", (_case, conditions) => {
    expect(said(rule(conditions))).toEqual([]);
  });

  it("find nothing where the root feeds two actions: AC3's fan-out is a node used twice", () => {
    expect(said(doc("corpus/07_sys_time_stop"))).toEqual([]); // actions a1 and a2, both on g1
  });
});

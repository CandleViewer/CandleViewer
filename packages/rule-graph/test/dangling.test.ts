import { readFileSync } from "node:fs";
import { join } from "node:path";
import type { RuleIr } from "@candleviewer/protocol/rule-ir";
import { describe, expect, it } from "vitest";
import { toGraph } from "../src/adapter/toGraph.js";
import { findDanglingPorts } from "../src/analysis/dangling.js";
import type { GraphEdge, GraphModel, GraphNode } from "../src/model.js";
import { canConnect, portsOf, type PortType } from "../src/ports.js";

// Written and byte-checked by services/api/tests/rules/roundtrip/test_client_hash_vectors.py.
type V = { name: string; ir: string; js: boolean; canonical?: string };
const FILE = join(import.meta.dirname, "..", "..", "fixtures/golden/rule-ir/hash_vectors.json");
const { vectors } = JSON.parse(readFileSync(FILE, "utf8")) as { vectors: V[] };
const sendable = vectors.filter((v) => v.js && v.canonical !== undefined);
const graphs = sendable.map((v) => [v.name, toGraph(JSON.parse(v.ir) as RuleIr)] as const);
const G = (graphs.find(([name]) => name === "corpus/07_sys_time_stop") as [string, GraphModel])[1];
const C1 = (G.nodes.find((n) => n.id === "c1") as GraphNode).data; // gt, both operands inline
const { left } = C1;
function edge(source: string, target: string, targetPort: string): GraphEdge {
  return { id: `${source}>${target}`, source, sourcePort: "out", target, targetPort };
}
/** G with new data for some of its nodes, `extra` nodes, and `edges` (by default its own). */
function edit(data: Record<string, GraphNode["data"]>, extra: object[] = [], edges = G.edges) {
  const nodes = G.nodes.map((n) => ({ ...n, data: data[n.id] ?? n.data }));
  return { ...G, nodes: [...nodes, ...(extra as GraphNode[])], edges };
}
const only = (edges: GraphEdge[]) => edit({}, [], edges);
const at = (c1: GraphNode["data"]) => edit({ c1 }); // comparison c1 with this data
const condition = (id: string, data: object) => ({ id, type: "condition", data });
const t1 = condition("t1", { kind: "temporal", op: "sustained_for", window_ms: 1_000 });
const x1 = (...operands: unknown[]) => condition("x1", { kind: "arithmetic", op: "add", operands });
const wired = (...more: GraphEdge[]) => [...G.edges, ...more];
const gates = G.edges.filter((e) => e.source === "g1"); // g1 feeds a1 and a2; c1, c2 fill its slots

describe("findDanglingPorts", () => {
  it.each(graphs)("find none in %s's graph, whose every edge connects by type", (_name, graph) => {
    expect(findDanglingPorts(graph)).toEqual([]);
    const ports = new Map(graph.nodes.map((node) => [node.id, portsOf(node)]));
    for (const { source, target, targetPort } of graph.edges) {
      const input = new Map(ports.get(target)?.inputs).get(targetPort) as PortType;
      expect(canConnect(ports.get(source)?.output as PortType, input)).toEqual({ ok: true });
    }
  });

  const fedRight = edit({ c1: { ...C1, right: null } }, [x1(2)], wired(edge("x1", "c1", "right")));
  const fedSlot = edit({}, [x1(null), { ...x1(2), id: "y" }], wired(edge("y", "x1", "in")));
  const oneSlot = only(G.edges.filter((e) => e.source !== "c2"));
  it.each([
    ["an action no edge feeds", only(G.edges.slice(0, 3)), ["a2.when"]],
    ["a gate whose slots no edge fills", only(gates), ["g1.in"]],
    ["a gate one of whose two slots no edge fills", oneSlot, ["g1.in"]],
    ["a gate with no list, which its edges fill", edit({ g1: { op: "all_of" } }), []],
    ["a comparison with no right operand", at({ kind: "comparison", left }), ["c1.right"]],
    ["a comparison whose right operand is null", at({ ...C1, right: null }), ["c1.right"]],
    ["a null operand an edge fills", fedRight, []],
    ["is_true, which takes one operand", at({ kind: "comparison", op: "is_true", left }), []],
    ["between, which takes three", at({ ...C1, op: "between" }), ["c1.right2"]],
    ["a temporal node with no child", edit({}, [t1]), ["t1.child"]],
    ["a temporal node fed its child", edit({}, [t1], wired(edge("c2", "t1", "child"))), []],
    ["arithmetic with inline operands", edit({}, [x1({ const: 1 }, { metric: "price" })]), []],
    ["arithmetic with an empty slot", edit({}, [x1({ const: 1 }, null)]), ["x1.in"]],
    ["arithmetic whose empty slot an edge fills", fedSlot, []],
    ["no edge at all, in node order", only([]), ["a1.when", "a2.when", "g1.in"]],
  ] as const)("find %s", (_case, graph, found) => {
    expect(findDanglingPorts(graph).map(({ nodeId, port }) => `${nodeId}.${port}`)).toEqual(found);
  });

  it("name each under the code DANGLING_PORT, in the server's words (graph.py:165)", () => {
    const message = "Node a2 is missing its 'when' input.";
    const found = findDanglingPorts(edit({}, [], G.edges.slice(0, 3)));
    expect(found).toEqual([{ code: "DANGLING_PORT", nodeId: "a2", port: "when", message }]);
  });

  it("refuse what is no graph: no lists, a non-object edge or node, a node of no kind", () => {
    const bad = [null, { ...G, nodes: "x" }, { ...G, edges: [null] }, edit({}, [null as never])];
    for (const graph of [...bad, edit({ c1: { kind: "x" } }), edit({}, [{ ...t1, id: 7 }])]) {
      const refused = expect.objectContaining({ code: "SCHEMA_VIOLATION" });
      expect(() => findDanglingPorts(graph as GraphModel)).toThrow(refused);
    }
  });
});

// The required inputs a graph leaves empty (E37-T01), as rules/compiler/graph.py:118-168 finds:
// an edge or an inline operand fills each input; a list needs an item and an edge per null slot.
import { SLOTS, isTree } from "../adapter/toGraph.js";
import { check } from "../errors.js";
import type { GraphModel } from "../model.js";
import { portsOf } from "../ports.js";

/** An input left empty: its node and port, under the stable code DANGLING_PORT. */
export type DanglingPort = { code: "DANGLING_PORT"; nodeId: string; port: string; message: string };
/** The empty required inputs of `graph`, in node order, then port order. */
export function findDanglingPorts(graph: GraphModel): DanglingPort[] {
  const { nodes, edges } = (isTree(graph) ? graph : {}) as Partial<GraphModel>;
  const lists = Array.isArray(nodes) && Array.isArray(edges);
  check(lists, "SCHEMA_VIOLATION", "A graph has a list of nodes and a list of edges.");
  const fed = new Map<string, number>(); // the edges into each [node, port]
  for (const edge of edges as GraphModel["edges"]) {
    check(isTree(edge), "SCHEMA_VIOLATION", "An edge of the graph is no object.");
    const slot = JSON.stringify([edge.target, edge.targetPort]);
    fed.set(slot, (fed.get(slot) ?? 0) + 1);
  }
  return (nodes as GraphModel["nodes"]).flatMap((node) => {
    const { kind, inputs } = portsOf(node);
    const slots = Object.entries(SLOTS[kind as keyof typeof SLOTS] ?? {}); // none: only an edge
    return inputs.flatMap(([port]) => {
      const key = slots.find(([, name]) => name === port)?.[0];
      const value = key === undefined ? undefined : node.data[key];
      const items: unknown[] = port !== "in" ? [value] : Array.isArray(value) ? value : [];
      const holes = items.filter((item) => item == null).length;
      const fills = fed.get(JSON.stringify([node.id, port])) ?? 0;
      if (fills >= holes && items.length - holes + fills > 0) return [];
      const message = `Node ${node.id} is missing its '${port}' input.`; // graph.py:165
      return [{ code: "DANGLING_PORT" as const, nodeId: node.id, port, message }];
    });
  });
}

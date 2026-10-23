// Cycles in the rule editor's graph (E37-T01), searched as the server's compile searches them
// (rules/compiler/graph.py:57-81): depth first over each node's inputs, with no recursion.
import { isTree } from "../adapter/toGraph.js";
import { byCodePoint } from "../canonical/canonicalise.js";
import { check } from "../errors.js";
import type { GraphEdge, GraphModel } from "../model.js";

/** Per node id, the sources of its input edges in edge order: the server's `adj` (:143-146). */
export function inputsOf(graph: GraphModel): Map<string, string[]> {
  const { nodes, edges } = (isTree(graph) ? graph : {}) as Partial<GraphModel>;
  const lists = Array.isArray(nodes) && Array.isArray(edges);
  check(lists, "SCHEMA_VIOLATION", "A graph has a list of nodes and a list of edges.");
  const inputs = new Map<string, string[]>();
  for (const edge of edges as GraphModel["edges"]) {
    const { source, target } = (isTree(edge) ? edge : {}) as GraphEdge;
    const ids = typeof source === "string" && typeof target === "string";
    check(ids, "SCHEMA_VIOLATION", "An edge of the graph does not join two node ids.");
    const into = inputs.get(target);
    if (into) into.push(source);
    else inputs.set(target, [source]);
  }
  return inputs;
}

/**
 * The first cycle the server's search meets, from the ids in code point order: its node ids in
 * order, each fed by the next (`["g1", "c1", "g1"]`: c1 feeds g1), closing on the first; `[]` for
 * none. Only the edges are read.
 */
export function findCycles(graph: GraphModel): string[] {
  const inputs = inputsOf(graph);
  const state = new Map<string, "open" | "done">(); // open while the node is on the path
  for (const start of [...inputs.keys()].sort(byCodePoint)) {
    if (state.has(start)) continue;
    const path: string[] = [];
    const stack: [string, number][] = [[start, 0]]; // a node, and the index of its next input
    while (stack.length > 0) {
      const [id, i] = stack.pop() as [string, number];
      const next = inputs.get(id)?.[i]; // none once every input is searched
      if (i === 0) path.push(id);
      state.set(id, next === undefined ? "done" : "open");
      if (next === undefined) {
        path.pop();
        continue;
      }
      stack.push([id, i + 1]);
      if (state.get(next) === "open") return [...path.slice(path.indexOf(next)), next];
      if (!state.has(next)) stack.push([next, 0]);
    }
  }
  return [];
}

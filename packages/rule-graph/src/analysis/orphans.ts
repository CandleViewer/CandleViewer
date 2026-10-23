// The nodes no action follows (E37-T01), found as rules/compiler/graph.py:190-204 finds them:
// reached backwards, over every edge, from the nodes that feed an action's `when`. The trigger, a
// comment and an action are never orphans: the server's graph holds only the actions of the three.
import type { GraphModel } from "../model.js";
import { portsOf } from "../ports.js";
import { inputsOf } from "./cycles.js";

/** The ids of the gates and conditions of `graph` that reach no action, in node order; the
 * server lists them in code point order (graph.py:197). */
export function findOrphans(graph: GraphModel): string[] {
  const inputs = inputsOf(graph); // the lists and edges checked
  const kinds = graph.nodes.map((node) => portsOf(node).kind); // each node checked
  const actions = new Set(graph.nodes.filter((_, i) => kinds[i] === "action").map(({ id }) => id));
  const roots = graph.edges.filter((e) => e.targetPort === "when" && actions.has(e.target));
  const todo = roots.map((e) => e.source);
  const reached = new Set<string>();
  for (let id = todo.pop(); id !== undefined; id = todo.pop()) {
    if (reached.has(id)) continue;
    reached.add(id);
    for (const source of inputs.get(id) ?? []) todo.push(source);
  }
  const free = new Set(["trigger", "comment", "action"]);
  return graph.nodes
    .filter((node, i) => !free.has(kinds[i] as string) && !reached.has(node.id))
    .map(({ id }) => id);
}

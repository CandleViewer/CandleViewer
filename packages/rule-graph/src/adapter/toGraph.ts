// Rule IR to the editor's graph (E37-T01), as the server's `to_graph_model` builds it
// (rules/compiler/graph.py:270-340), on the CMP-146 node types. Pure and synchronous.
import type { RuleIr } from "@candleviewer/protocol/rule-ir";
import { checkBounds } from "../canonical/schema.js";
import { check } from "../errors.js";
import type { GraphEdge, GraphLayout, GraphModel, GraphNode } from "../model.js";

export type Tree = Record<string, unknown>;
/** Per node kind: the IR keys that hold nodes, and the input port each one feeds. */
export const SLOTS = {
  logicGate: { children: "in" },
  temporal: { child: "child" },
  arithmetic: { operands: "in" },
  comparison: { left: "left", right: "right", right2: "right2" },
} as const;
const KIND_OF = { children: "logicGate", child: "temporal", operands: "arithmetic" } as const;
const GRAPH_KEYS = ["trigger", "conditions", "actions", "graph_layout"];

export const isTree = (value: unknown): value is Tree =>
  typeof value === "object" && value !== null && !Array.isArray(value);
const isNode = (v: unknown): v is Tree => isTree(v) && typeof v["node_id"] === "string";

/** A stored `graph_layout` as a GraphLayout; keys it does not know are kept in `extra`. */
export function readLayout(stored: unknown): GraphLayout {
  const source: Tree = isTree(stored) ? stored : {};
  const { positions = {}, collapsed = [], comments = [], ...extra } = source;
  const fits = isTree(positions) && Array.isArray(collapsed) && Array.isArray(comments);
  const named = fits && comments.every((note) => isTree(note) && typeof note["id"] === "string");
  check(named, "SCHEMA_VIOLATION", "$.graph_layout: not an editor layout");
  return { positions, collapsed, comments, extra } as GraphLayout;
}

/** The hook for auto-layout (E37-T02): the nodes `layout` gives no position, in graph order. */
export const nodesNeedingLayout = (graph: GraphModel, layout: GraphLayout): string[] =>
  graph.nodes.filter((node) => !Object.hasOwn(layout.positions, node.id)).map((node) => node.id);

/**
 * The graph of `ir`, with the comments of `layout` (by default its `graph_layout`) as nodes. A
 * shared node, one subtree under one `node_id`, is one node with an edge per use; any other reuse
 * of an id is refused, never merged.
 */
export function toGraph(ir: RuleIr, layout?: GraphLayout): GraphModel {
  const doc: unknown = ir; // the shape first, so a malformed IR is refused rather than misread
  const actions = isTree(doc) ? doc["actions"] : undefined;
  const listed = Array.isArray(actions) && actions.length > 0 && actions.every(isNode);
  const shaped = listed && isTree((doc as Tree)["trigger"]) && isNode((doc as Tree)["conditions"]);
  check(shaped, "SCHEMA_VIOLATION", "$: a rule IR has a trigger, a root condition and actions.");
  checkBounds(ir);
  const envelope = Object.fromEntries(Object.entries(ir).filter(([k]) => !GRAPH_KEYS.includes(k)));
  const nodes: GraphNode[] = [{ id: "trigger", type: "trigger", data: { ...ir.trigger } }];
  const edges: GraphEdge[] = [];
  const owners = new Map<string, unknown>([["trigger", ir.trigger]]);
  const fresh = (id: string, tree: unknown, shared: boolean): boolean => {
    const known = owners.has(id); // a shared node repeats as the same JSON text, nothing else may
    const same = known && shared && JSON.stringify(owners.get(id)) === JSON.stringify(tree);
    check(!known || same, "SCHEMA_VIOLATION", `The id ${id} names two different nodes.`, [id]);
    owners.set(id, tree);
    return !known;
  };
  const visit = (tree: Tree, target: string, targetPort: string): void => {
    const { node_id: id, ...data } = tree as Tree & { node_id: string };
    edges.push({ id: `e${edges.length + 1}`, source: id, sourcePort: "out", target, targetPort });
    if (!fresh(id, tree, true)) return;
    const kind = Object.entries(KIND_OF).find(([key]) => key in data)?.[1] ?? "comparison";
    const inputs: [Tree, string][] = [];
    for (const [key, port] of Object.entries(SLOTS[kind])) {
      const value = data[key];
      if (Array.isArray(value)) {
        data[key] = value.map((item) => (isNode(item) ? (inputs.push([item, port]), null) : item));
      } else if (isNode(value)) {
        delete data[key];
        inputs.push([value, port]);
      }
    }
    const node = kind === "logicGate" ? { data } : { data: { kind, ...data } };
    nodes.push({ id, type: kind === "logicGate" ? kind : "condition", ...node });
    for (const [item, port] of inputs) visit(item, id, port);
  };
  for (const { node_id: id, ...data } of ir.actions) {
    fresh(id, data, false);
    nodes.push({ id, type: "action", data });
  }
  const root: Tree = { ...ir.conditions };
  for (const action of ir.actions) visit(root, action.node_id, "when");
  // A layout given has its comments read as a stored one's are: a list of comments with ids.
  const given = layout == null ? ir.graph_layout : { comments: layout.comments ?? null };
  for (const { id, ...data } of readLayout(given).comments) {
    fresh(id, data, false);
    nodes.push({ id, type: "comment", data });
  }
  return { envelope, nodes, edges };
}

// The editor's graph as the compile route reads it (E37-S01): `POST /rules/{ruleId}/compile` with
// `editor: "graph"` takes the server's own graph model (rules/compiler/graph.py:1-14), which the
// published contract leaves an open object. The envelope's fields sit at the top level with the
// trigger node's data as `trigger`; a condition is typed by its kind and a gate is `boolean`; an
// edge names its input as `port`; the comments travel in `graph_layout`, which holds only the
// presentation keys the client owns (positions, collapsed nodes, comments). Structure is the
// server compile's to judge, by node id; the one check here is that every edge it sends into a node
// feeds a port its node reads (`NODE_PORTS`, as toIr checks). Pure and synchronous.
import { check } from "../errors.js";
import type { CommentNode, GraphLayout, GraphModel, GraphNode } from "../model.js";
import { NODE_PORTS, type NodeKind, portsOf } from "../ports.js";
import { SLOTS, type Tree, isTree } from "./toGraph.js";

/** A node as the server's graph compiler reads it; an `operand` is an inline metric or value. */
export interface CompileNode {
  readonly id: string;
  readonly type: "comparison" | "boolean" | "temporal" | "arithmetic" | "operand" | "action";
  readonly data: Readonly<Record<string, unknown>>;
}

/** `from` feeds input `port` of `to`; a node's `in` edges are its list, in order (graph.py:250). */
export interface CompileEdge {
  readonly from: string;
  readonly to: string;
  readonly port: string;
}

/** The compile body's `model`: the rule's other fields at the top level, then its graph. */
export type CompileModel = Readonly<Record<string, unknown>> & {
  readonly nodes: readonly CompileNode[];
  readonly edges: readonly CompileEdge[];
};

const SV = "SCHEMA_VIOLATION";
const BLANK: GraphLayout = { positions: {}, collapsed: [], comments: [], extra: {} };
const TYPE = {
  logicGate: "boolean",
  comparison: "comparison",
  temporal: "temporal",
  arithmetic: "arithmetic",
  action: "action",
} as const;
/** The list each list node keeps in `data` (`children`, `operands`), filled by its `in` edges. */
const LIST_KEY: Partial<Record<NodeKind, string>> = Object.fromEntries(
  Object.entries(SLOTS).flatMap(([kind, slots]) =>
    Object.entries(slots)
      .filter(([, port]) => port === "in")
      .map(([key]) => [kind, key]),
  ),
);

/** A condition's `data` without the editor's `kind`, and a list node's without its list. */
function ownData(kind: NodeKind, data: GraphNode["data"]): Tree {
  const out: Tree = { ...data };
  // The editor's own: IR condition nodes take none (rules/ir/rule-ir.json); toIr drops it too.
  if (kind !== "action") delete out["kind"];
  const key = LIST_KEY[kind];
  if (key !== undefined) delete out[key]; // the server builds the list from the `in` edges
  return out;
}

/**
 * The compile model of `graph`, which sends the positions and collapsed nodes of `layout` (by
 * default an empty one) with the graph's comments as its `graph_layout`; a layout key the client
 * does not own (`extra`) is not sent. A list's empty item takes the next `in` edge into its node,
 * in edge order, and an inline item becomes an `operand` node of its own, its id apart from every
 * id a node or an edge names; the node's `in` edges are emitted in list order, any edge past the
 * list's empty items after them. Refuses a node of no known kind, a malformed edge, an edge into a
 * node on a port that node does not read and a second trigger, which no compile model can hold.
 */
export function toCompileModel(graph: GraphModel, layout: GraphLayout = BLANK): CompileModel {
  check(isTree(layout), SV, "The layout given is not an object.");
  const { envelope = {}, nodes = [], edges = [] }: Partial<GraphModel> = isTree(graph) ? graph : {};
  check(Array.isArray(nodes) && Array.isArray(edges), SV, "A graph has nodes and edges, as lists.");
  check(isTree(envelope), SV, "The graph's envelope is not an object.");
  const kinds = new Map<string, NodeKind>();
  for (const node of nodes) kinds.set(node.id, portsOf(node).kind); // a known, well-formed kind
  const triggers = nodes.filter((node) => kinds.get(node.id) === "trigger");
  const triggerIds = triggers.map((node) => node.id);
  check(triggers.length <= 1, SV, "A graph has one trigger node.", triggerIds);
  const taken = new Set(nodes.map((node) => node.id)); // and every id an edge names, below
  const lists = new Map<string, string[]>(); // a list node's `in` sources, in edge order
  for (const [id, kind] of kinds) if (LIST_KEY[kind] !== undefined) lists.set(id, []);
  const out: CompileEdge[] = [];
  edges.forEach((edge, i) => {
    const { source, target, targetPort } = (isTree(edge) ? edge : {}) as Partial<Tree>;
    const named = [source, target, targetPort].every((value) => typeof value === "string");
    check(named, SV, `Edge ${i + 1} does not name its two nodes and its input.`);
    const [from, to, port] = [source, target, targetPort] as [string, string, string]; // checked
    taken.add(from).add(to); // an operand never takes an id an edge names: a dangling edge stays
    const into = kinds.get(to); // an edge into no node goes as it is, for compile to report
    const reads = into === undefined || Object.hasOwn(NODE_PORTS[into].inputs, port);
    check(reads, SV, `Edge ${i + 1} feeds \`${port}\`, which \`${to}\` does not read.`, [from, to]);
    const list = lists.get(to); // a list node's one input is `in`
    if (list === undefined) out.push({ from, to, port });
    else list.push(from);
  });
  const fresh = (base: string): string => {
    let id = base;
    for (let n = 2; taken.has(id); n += 1) id = `${base}.${n}`;
    taken.add(id);
    return id;
  };
  const compiled: CompileNode[] = [];
  const comments: CommentNode[] = [];
  for (const node of nodes) {
    const kind = kinds.get(node.id) as NodeKind;
    if (kind === "trigger") continue; // the envelope's `trigger`
    if (kind === "comment") {
      comments.push({ ...node.data, id: node.id } as CommentNode); // as toIr writes a comment
      continue;
    }
    compiled.push({ id: node.id, type: TYPE[kind], data: ownData(kind, node.data) });
    const key = LIST_KEY[kind];
    if (key === undefined) continue;
    const sources = [...(lists.get(node.id) ?? [])];
    const items = node.data[key];
    for (const [i, item] of (Array.isArray(items) ? items : []).entries()) {
      if (item === null) {
        const from = sources.shift(); // an empty item no edge is left for is dropped
        if (from !== undefined) out.push({ from, to: node.id, port: "in" });
        continue;
      }
      const id = fresh(`${node.id}.in.${i + 1}`);
      // An inline metric or value, as the editor holds it; the server's compile checks its shape.
      compiled.push({ id, type: "operand", data: item as Tree });
      out.push({ from: id, to: node.id, port: "in" });
    }
    for (const from of sources) out.push({ from, to: node.id, port: "in" });
  }
  const { positions, collapsed } = layout;
  const trigger = triggers.length === 0 ? {} : { trigger: (triggers[0] as GraphNode).data };
  return {
    ...envelope,
    ...trigger,
    graph_layout: { positions, collapsed, comments },
    nodes: compiled,
    edges: out,
  };
}

/**
 * The model behind the structural text view (E47-S03 Scope, BQ-06): the node list E37-S05 #1071
 * builds and binds (D02 §8; its chord is E37-S05's to register, BQ-12) IS this view, one linear list of every node in the documented order with its
 * type, parameters and every port: its type and what it connects to, an empty input included
 * (E37-D02 §14). It is a presentation of the same graph the canvas draws, never a second source of
 * truth: edits made from the list go through the same graph commands. Virtualisation beyond a few
 * hundred rows is the list UI's job (carried with E37-S05).
 */
import { copy, TYPE_LABEL } from "./copy.js";
import {
  adjacencyFor,
  adjacencyOf,
  OUTPUT_PORT,
  type GraphEdge,
  type A11yGraph,
  type GraphNode,
  type PortOracle,
} from "./graph.js";
import { traversalOrder, type TraversalEntry } from "./traversal.js";

/**
 * IR bookkeeping, never a parameter a user set. `account_id` is hidden as hardening: no adapter
 * flattens a metric's account reference into node data today, and if one ever does it is not read
 * aloud in the outline (security lens r1, Info).
 */
const HIDDEN = new Set(["name", "label", "kind", "node_id", "type", "account_id"]);

/** A node's own spoken name: `name` / `label` (and only a comment's `text`), else type and id. */
export function nodeName(node: GraphNode): string {
  const keys = node.type === "comment" ? ["name", "label", "text"] : ["name", "label"];
  for (const key of keys) {
    const value = node.data[key];
    if (typeof value === "string" && value.trim() !== "") return value.trim();
  }
  return `${TYPE_LABEL[node.type]} ${node.id}`;
}

/**
 * Every node's name as announced: a name two nodes share gets each one's position suffixed, so
 * links and announcements never point at two nodes with one name (a11y lens r1, A-9).
 */
export function nodeNames(
  graph: A11yGraph,
  order: readonly TraversalEntry[] = traversalOrder(graph),
): ReadonlyMap<string, string> {
  const nodes = new Map(graph.nodes.map((n) => [n.id, n]));
  const own = order.map((entry) => nodeName(nodes.get(entry.id) as GraphNode)); // order ⊆ nodes
  const uses = new Map<string, number>();
  for (const name of own) uses.set(name, (uses.get(name) ?? 0) + 1);
  return new Map(
    order.map((entry, i) => {
      const name = own[i] as string;
      return [entry.id, (uses.get(name) ?? 0) > 1 ? copy.disambiguated(name, i + 1) : name];
    }),
  );
}

const scalar = (v: unknown): v is string | number | boolean =>
  typeof v === "string" || (typeof v === "number" && Number.isFinite(v)) || typeof v === "boolean";

/** A list of nulls only stands in for connected nodes (rule-graph's gate `children`): not a setting. */
const placeholder = (v: unknown): boolean => Array.isArray(v) && v.every((item) => item === null);

/**
 * "op gt, threshold 14": the node's scalar parameters in key order. Settings that are not plain
 * values (nested lists or records) are counted, not read: "plus 2 more settings", or "parameters
 * set" when there is nothing else, never "no parameters" (A-9).
 */
export function parameterSummary(node: GraphNode): string {
  const keys = Object.keys(node.data)
    .filter((key) => !HIDDEN.has(key) && !(key === "text" && node.type === "comment"))
    .sort();
  const parts: string[] = [];
  let other = 0;
  for (const key of keys) {
    const value = node.data[key];
    if (scalar(value)) parts.push(`${key} ${String(value)}`);
    else if (value !== undefined && !placeholder(value)) other += 1;
  }
  if (parts.length === 0) return other === 0 ? copy.noParameters() : copy.parametersSet();
  return other === 0 ? parts.join(", ") : `${parts.join(", ")}, ${copy.moreSettings(other)}`;
}

export interface OutlineLink {
  readonly edgeId: string;
  /** The node at the other end of the edge. */
  readonly nodeId: string;
  /** The input port on the edge's target. */
  readonly port: string;
  readonly text: string;
}

export interface OutlinePort {
  readonly direction: "input" | "output";
  /** The input port's name, or `out`. */
  readonly port: string;
  /** The oracle's port type, or "type unknown" for a port only an edge names. */
  readonly type: string;
  /** Its edges, in the order of the node at the other end; empty when not connected. */
  readonly links: readonly OutlineLink[];
  /** "{Input | Output} port, {type}, {connected to … | not connected}" (E37-D02 §14 :392) */
  readonly text: string;
}

export interface OutlineRow {
  readonly id: string;
  readonly type: string;
  readonly name: string;
  readonly parameters: string;
  readonly depth: number;
  /** 1-based, with `size`, for `aria-posinset` / `aria-setsize`. */
  readonly index: number;
  readonly size: number;
  readonly inbound: readonly OutlineLink[];
  readonly outbound: readonly OutlineLink[];
  /** Inputs in the oracle's port order (then any port only an edge names), then the output. */
  readonly ports: readonly OutlinePort[];
  /** The whole row as one passage: the node's accessible description. */
  readonly description: string;
}

/** One row per node, in traversal order; links list in the order of the node at the other end. */
export function buildOutline(graph: A11yGraph, oracle: PortOracle): readonly OutlineRow[] {
  const order = traversalOrder(graph);
  const adj = adjacencyOf(graph);
  const nodes = new Map(graph.nodes.map((n) => [n.id, n]));
  const names = nodeNames(graph, order);
  const rank = new Map(order.map((entry, i) => [entry.id, i]));
  const nameFor = (id: string): string => names.get(id) ?? id;
  const link = (edge: GraphEdge, other: string, text: string): OutlineLink => ({
    edgeId: edge.id,
    nodeId: other,
    port: edge.targetPort,
    text,
  });
  const byOther = (a: OutlineLink, b: OutlineLink): number =>
    (rank.get(a.nodeId) ?? Infinity) - (rank.get(b.nodeId) ?? Infinity) ||
    (a.edgeId < b.edgeId ? -1 : a.edgeId > b.edgeId ? 1 : 0);
  const portOf = (output: boolean, port: string, type: string, links: OutlineLink[]) => ({
    direction: output ? ("output" as const) : ("input" as const),
    port,
    type,
    links,
    text: copy.port(
      output,
      type,
      links.map((l) => nameFor(l.nodeId)),
    ),
  });
  return order.map((entry, i) => {
    const node = nodes.get(entry.id) as GraphNode; // the order lists only the graph's own nodes
    const { inbound, outbound } = adjacencyFor(adj, entry.id);
    const ins = inbound
      .map((e) => link(e, e.source, copy.inboundFrom(nameFor(e.source), e.targetPort)))
      .sort(byOther);
    const outs = outbound
      .map((e) => link(e, e.target, copy.outboundTo(nameFor(e.target), e.targetPort)))
      .sort(byOther);
    const declared = oracle.inputsOf(node).map(([port, type]) => [port, type] as const);
    const named = new Set(declared.map(([port]) => port));
    const extra = [...new Set(ins.map((l) => l.port))].filter((port) => !named.has(port));
    const inputs = [...declared, ...extra.map((port) => [port, copy.unknownType()] as const)].map(
      ([port, type]) =>
        portOf(
          false,
          port,
          type,
          ins.filter((l) => l.port === port),
        ),
    );
    const outputType = oracle.outputOf(node) ?? (outs.length > 0 ? copy.unknownType() : null);
    const ports =
      outputType === null ? inputs : [...inputs, portOf(true, OUTPUT_PORT, outputType, outs)];
    const portText =
      ports.length === 0
        ? copy.noPorts()
        : [
            ...ports.map((p) => `${p.text}.`),
            ...(outputType === null ? [copy.noOutput()] : []),
          ].join(" ");
    const type = TYPE_LABEL[node.type];
    const name = nameFor(node.id);
    const parameters = parameterSummary(node);
    return {
      id: node.id,
      type,
      name,
      parameters,
      depth: entry.depth,
      index: i + 1,
      size: order.length,
      inbound: ins,
      outbound: outs,
      ports,
      description: copy.node(type, name, parameters, portText),
    };
  });
}

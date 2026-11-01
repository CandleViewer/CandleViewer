/**
 * The model behind the structural text view (E47-S03 Scope, BQ-06): the Alt+L node list of
 * E37-S05 #1071 IS this view, one linear list of every node in the documented order with its
 * type, parameters and inbound / outbound connections. It is a presentation of the same graph the
 * canvas draws, never a second source of truth: edits made from the list go through the same graph
 * commands. Virtualisation beyond a few hundred rows is the list UI's job (carried with E37-S05).
 */
import { copy, TYPE_LABEL } from "./copy.js";
import {
  adjacencyFor,
  adjacencyOf,
  type A11yEdge,
  type A11yGraph,
  type A11yNode,
} from "./graph.js";
import { traversalOrder } from "./traversal.js";

const NAME_KEYS = ["name", "label", "text"] as const;
/** IR bookkeeping that is not a parameter a user set. */
const HIDDEN = new Set(["name", "label", "text", "kind", "node_id", "type"]);

/** A node's spoken name: its own `name` / `label` (a comment's `text`), else type and id. */
export function nodeName(node: A11yNode): string {
  for (const key of NAME_KEYS) {
    const value = node.data[key];
    if (typeof value === "string" && value.trim() !== "") return value.trim();
  }
  return `${TYPE_LABEL[node.type]} ${node.id}`;
}

const scalar = (v: unknown): v is string | number | boolean =>
  typeof v === "string" || (typeof v === "number" && Number.isFinite(v)) || typeof v === "boolean";

/** "op gt, threshold 14": the node's scalar parameters in key order; nested IR is not summarised. */
export function parameterSummary(node: A11yNode): string {
  const parts = Object.keys(node.data)
    .filter((key) => !HIDDEN.has(key))
    .sort()
    .flatMap((key) => {
      const value = node.data[key];
      return scalar(value) ? [`${key} ${String(value)}`] : [];
    });
  return parts.length === 0 ? copy.noParameters() : parts.join(", ");
}

export interface OutlineLink {
  readonly edgeId: string;
  /** The node at the other end of the edge. */
  readonly nodeId: string;
  /** The input port on the edge's target. */
  readonly port: string;
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
  /** The whole row as one sentence: the node's accessible description. */
  readonly description: string;
}

/** One row per node, in traversal order; links list in the order of the node at the other end. */
export function buildOutline(graph: A11yGraph): readonly OutlineRow[] {
  const order = traversalOrder(graph);
  const adj = adjacencyOf(graph);
  const nodes = new Map(graph.nodes.map((n) => [n.id, n]));
  const rank = new Map(order.map((entry, i) => [entry.id, i]));
  const nameFor = (id: string): string => {
    const node = nodes.get(id);
    return node === undefined ? id : nodeName(node);
  };
  const link = (edge: A11yEdge, other: string, text: string): OutlineLink => ({
    edgeId: edge.id,
    nodeId: other,
    port: edge.targetPort,
    text,
  });
  const byOther = (a: OutlineLink, b: OutlineLink): number =>
    (rank.get(a.nodeId) ?? Infinity) - (rank.get(b.nodeId) ?? Infinity) ||
    (a.edgeId < b.edgeId ? -1 : a.edgeId > b.edgeId ? 1 : 0);
  const joined = (links: readonly OutlineLink[]): string =>
    links.length === 0 ? copy.noConnections() : links.map((l) => l.text).join("; ");
  return order.map((entry, i) => {
    const node = nodes.get(entry.id) as A11yNode; // the order lists only the graph's own nodes
    const { inbound, outbound } = adjacencyFor(adj, entry.id);
    const ins = inbound
      .map((e) => link(e, e.source, copy.inboundFrom(nameFor(e.source), e.targetPort)))
      .sort(byOther);
    const outs = outbound
      .map((e) => link(e, e.target, copy.outboundTo(nameFor(e.target), e.targetPort)))
      .sort(byOther);
    const type = TYPE_LABEL[node.type];
    const name = nodeName(node);
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
      description: copy.node(type, name, parameters, joined(ins), joined(outs)),
    };
  });
}

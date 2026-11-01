/**
 * The keyboard and screen-reader core of the node-graph rule editor (SCR-082, E47-S03): pure, no
 * React, no DOM. Dependency (E47-S03 BQ-12 (d), option 2, ruled in record 6563473726): the model
 * types are `@candleviewer/rule-graph`'s own, imported type-only from its public entry; none is
 * copied here. A rule-graph `GraphModel` is passed as is (this core reads its nodes and edges). No
 * wire DTO and no port table is written here: the port rules come in through the `PortOracle` the
 * screen (E37-S01) builds from rule-graph's `portsOf` / `canConnect`.
 */
import type { GraphEdge, GraphModel, GraphNode } from "@candleviewer/rule-graph";

export type { GraphEdge, GraphNode, GraphNodeType } from "@candleviewer/rule-graph";

/** The part of a rule-graph `GraphModel` this core reads. */
export type A11yGraph = Pick<GraphModel, "nodes" | "edges">;

export type ConnectVerdict =
  { readonly ok: true } | { readonly ok: false; readonly reason: string };

/** The port rules, supplied by the screen from rule-graph (`portsOf`, `canConnect`). */
export interface PortOracle {
  /** The node's output port type, or null when it has none (an action, a comment). */
  readonly outputOf: (node: GraphNode) => string | null;
  /** The node's input ports and their types, in port order. */
  readonly inputsOf: (node: GraphNode) => readonly (readonly [port: string, type: string])[];
  /** Whether an output of type `from` may feed an input of type `to`, else why not. */
  readonly canConnect: (from: string, to: string) => ConnectVerdict;
  /** Whether the input takes several edges (rule-graph's list port `in`). */
  readonly acceptsMany: (port: string) => boolean;
}

/** The name the output port carries on an edge (rule-graph's `sourcePort`). */
export const OUTPUT_PORT = "out";

export interface Adjacency {
  readonly inbound: readonly GraphEdge[];
  readonly outbound: readonly GraphEdge[];
}

const NONE: Adjacency = Object.freeze({ inbound: [], outbound: [] });

/** Per node id, its inbound and outbound edges: built once, O(nodes + edges). */
export function adjacencyOf(graph: A11yGraph): ReadonlyMap<string, Adjacency> {
  const map = new Map<string, { inbound: GraphEdge[]; outbound: GraphEdge[] }>();
  for (const node of graph.nodes) map.set(node.id, { inbound: [], outbound: [] });
  for (const edge of graph.edges) {
    map.get(edge.source)?.outbound.push(edge);
    map.get(edge.target)?.inbound.push(edge);
  }
  return map;
}

/** The node's edges, or none for an unknown id. */
export const adjacencyFor = (adj: ReadonlyMap<string, Adjacency>, id: string): Adjacency =>
  adj.get(id) ?? NONE;

/** Ids compare by code unit, never by locale, so the order is the same on every machine. */
export const byId = (a: string, b: string): number => (a < b ? -1 : a > b ? 1 : 0);

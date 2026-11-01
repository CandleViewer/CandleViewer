/**
 * The keyboard and screen-reader core of the node-graph rule editor (SCR-082, E47-S03): pure, no
 * React, no DOM. The shapes below are the structural subset of `@candleviewer/rule-graph`'s
 * `GraphNode` / `GraphEdge` / `GraphModel` (packages/rule-graph/src/model.ts) that this core reads,
 * so a rule-graph model is accepted as is. apps/web does not depend on that package yet; the
 * screen (E37-S01) adds the dependency and builds the `PortOracle` from its `portsOf` and
 * `canConnect`, so no DTO or port table is written twice here.
 */
export type A11yNodeType = "trigger" | "condition" | "action" | "logicGate" | "comment";

export interface A11yNode {
  readonly id: string;
  readonly type: A11yNodeType;
  readonly data: Readonly<Record<string, unknown>>;
}

/** `source`'s output feeds input `targetPort` of `target` (rule-graph's edge direction). */
export interface A11yEdge {
  readonly id: string;
  readonly source: string;
  readonly sourcePort: string;
  readonly target: string;
  readonly targetPort: string;
}

export interface A11yGraph {
  readonly nodes: readonly A11yNode[];
  readonly edges: readonly A11yEdge[];
}

export type ConnectVerdict =
  { readonly ok: true } | { readonly ok: false; readonly reason: string };

/** The port rules, supplied by the screen from rule-graph (`portsOf`, `canConnect`). */
export interface PortOracle {
  /** The node's output port type, or null when it has none (an action, a comment). */
  readonly outputOf: (node: A11yNode) => string | null;
  /** The node's input ports and their types, in port order. */
  readonly inputsOf: (node: A11yNode) => readonly (readonly [port: string, type: string])[];
  /** Whether an output of type `from` may feed an input of type `to`, else why not. */
  readonly canConnect: (from: string, to: string) => ConnectVerdict;
  /** Whether the input takes several edges (rule-graph's list port `in`). */
  readonly acceptsMany: (port: string) => boolean;
}

/** The name the output port carries on an edge (rule-graph's `sourcePort`). */
export const OUTPUT_PORT = "out";

export interface Adjacency {
  readonly inbound: readonly A11yEdge[];
  readonly outbound: readonly A11yEdge[];
}

const NONE: Adjacency = Object.freeze({ inbound: [], outbound: [] });

/** Per node id, its inbound and outbound edges: built once, O(nodes + edges). */
export function adjacencyOf(graph: A11yGraph): ReadonlyMap<string, Adjacency> {
  const map = new Map<string, { inbound: A11yEdge[]; outbound: A11yEdge[] }>();
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

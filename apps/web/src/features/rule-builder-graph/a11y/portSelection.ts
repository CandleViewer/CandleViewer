/**
 * Connecting and disconnecting ports without a pointer (WCAG 2.5.7; 05 §3.2, §3.4 item 8; E47-S03
 * BQ-05). A pure reducer: Enter or Space on a node's output port starts a pending connection; the
 * arrows cycle every input port of the other nodes (an unavailable one is announced with its
 * reason, focus stays pending), or Tab picks one directly; Enter confirms; Esc cancels. A confirm is
 * re-checked against the graph it is given, so a connection the graph cannot take is refused with
 * a reason and never produced: no self-loop, no duplicate, no second edge into a single input, no
 * type mismatch (the oracle, i.e. rule-graph's PORT_COMPAT), no loop.
 */
import { copy, REFUSAL } from "./copy.js";
import {
  adjacencyFor,
  adjacencyOf,
  OUTPUT_PORT,
  type A11yEdge,
  type A11yGraph,
  type A11yNode,
  type ConnectVerdict,
  type PortOracle,
} from "./graph.js";
import { nodeName } from "./outline.js";
import { traversalOrder } from "./traversal.js";

export type NewEdge = Omit<A11yEdge, "id">;

export interface Candidate {
  readonly node: string;
  readonly port: string;
  readonly verdict: ConnectVerdict;
}

export type PortSelection =
  | { readonly kind: "idle" }
  | {
      readonly kind: "pending";
      readonly source: string;
      readonly candidates: readonly Candidate[];
      /** The candidate in focus, or null before the first arrow / pick. */
      readonly index: number | null;
    };

export type PortEvent =
  | { readonly type: "start"; readonly node: string }
  | { readonly type: "cycle"; readonly step: 1 | -1 }
  | { readonly type: "pick"; readonly node: string; readonly port: string }
  | { readonly type: "confirm" }
  | { readonly type: "cancel" };

export type PortEffect =
  | { readonly kind: "none" }
  | { readonly kind: "announce"; readonly text: string }
  | { readonly kind: "connect"; readonly edge: NewEdge; readonly text: string }
  | { readonly kind: "refuse"; readonly reason: string; readonly text: string }
  | { readonly kind: "cancelled"; readonly text: string };

export interface PortStep {
  readonly state: PortSelection;
  readonly effect: PortEffect;
}

export const IDLE: PortSelection = Object.freeze({ kind: "idle" });

const refused = (reason: string): ConnectVerdict => ({ ok: false, reason });

/** Whether `source`'s output may feed `target`'s input `port` in `graph`, else why not. */
export function verdictFor(
  graph: A11yGraph,
  oracle: PortOracle,
  source: string,
  target: string,
  port: string,
): ConnectVerdict {
  const from = graph.nodes.find((n) => n.id === source);
  const to = graph.nodes.find((n) => n.id === target);
  if (from === undefined || to === undefined) return refused(REFUSAL.unknownNode);
  if (source === target) return refused(REFUSAL.selfLoop);
  const output = oracle.outputOf(from);
  if (output === null) return refused(REFUSAL.noOutput);
  const input = oracle.inputsOf(to).find(([name]) => name === port);
  if (input === undefined) return refused(REFUSAL.noInput);
  const adj = adjacencyOf(graph);
  const into = adjacencyFor(adj, target).inbound.filter((e) => e.targetPort === port);
  if (into.some((e) => e.source === source)) return refused(REFUSAL.duplicate);
  if (into.length > 0 && !oracle.acceptsMany(port)) return refused(REFUSAL.occupied);
  const types = oracle.canConnect(output, input[1]);
  if (!types.ok) return types;
  // A loop: the new edge closes one when `source` is already downstream of `target`.
  const seen = new Set([target]);
  const queue = [target];
  for (let head = 0; head < queue.length; head += 1) {
    for (const edge of adjacencyFor(adj, queue[head] as string).outbound) {
      if (edge.target === source) return refused(REFUSAL.loop);
      if (!seen.has(edge.target)) {
        seen.add(edge.target);
        queue.push(edge.target);
      }
    }
  }
  return { ok: true };
}

function candidatesFor(graph: A11yGraph, oracle: PortOracle, source: string): Candidate[] {
  const nodes = new Map(graph.nodes.map((n) => [n.id, n]));
  return traversalOrder(graph)
    .filter((entry) => entry.id !== source)
    .flatMap((entry) =>
      oracle.inputsOf(nodes.get(entry.id) as A11yNode).map(([port]) => ({
        node: entry.id,
        port,
        verdict: verdictFor(graph, oracle, source, entry.id, port),
      })),
    );
}

/** One keyboard event against the connection in progress; pure, the graph is never mutated. */
export function stepPortSelection(
  state: PortSelection,
  event: PortEvent,
  graph: A11yGraph,
  oracle: PortOracle,
): PortStep {
  const nodes = new Map(graph.nodes.map((n) => [n.id, n]));
  const name = (id: string): string => {
    const node = nodes.get(id);
    return node === undefined ? id : nodeName(node);
  };
  const refuse = (reason: string): PortStep => ({
    state,
    effect: { kind: "refuse", reason, text: copy.refused(reason) },
  });
  const focus = (s: Extract<PortSelection, { kind: "pending" }>, index: number): PortStep => {
    const c = s.candidates[index] as Candidate; // index is in range by construction
    const text = c.verdict.ok
      ? copy.candidate(name(c.node), c.port, index + 1, s.candidates.length)
      : copy.candidateRefused(name(c.node), c.port, c.verdict.reason);
    return { state: { ...s, index }, effect: { kind: "announce", text } };
  };
  switch (event.type) {
    case "start": {
      const node = nodes.get(event.node);
      if (node === undefined) return refuse(REFUSAL.unknownNode);
      if (oracle.outputOf(node) === null) return refuse(REFUSAL.noOutput);
      const candidates = candidatesFor(graph, oracle, node.id);
      return {
        state: { kind: "pending", source: node.id, candidates, index: null },
        effect: { kind: "announce", text: copy.connectStarted(name(node.id)) },
      };
    }
    case "cancel":
      if (state.kind === "idle") return { state, effect: { kind: "none" } };
      return { state: IDLE, effect: { kind: "cancelled", text: copy.cancelled() } };
    case "cycle": {
      if (state.kind === "idle" || state.candidates.length === 0) {
        return { state, effect: { kind: "none" } };
      }
      const n = state.candidates.length;
      const from = state.index ?? (event.step === 1 ? -1 : 0);
      return focus(state, (((from + event.step) % n) + n) % n);
    }
    case "pick": {
      if (state.kind === "idle") return refuse(REFUSAL.noSource);
      const at = state.candidates.findIndex((c) => c.node === event.node && c.port === event.port);
      return at < 0 ? refuse(REFUSAL.noInput) : focus(state, at);
    }
    case "confirm": {
      if (state.kind === "idle") return refuse(REFUSAL.noSource);
      const picked = state.index === null ? undefined : state.candidates[state.index];
      if (picked === undefined) return refuse(REFUSAL.noTarget);
      const verdict = verdictFor(graph, oracle, state.source, picked.node, picked.port);
      if (!verdict.ok) return refuse(verdict.reason);
      const edge: NewEdge = {
        source: state.source,
        sourcePort: OUTPUT_PORT,
        target: picked.node,
        targetPort: picked.port,
      };
      const text = copy.connected(name(edge.source), name(edge.target), edge.targetPort);
      return { state: IDLE, effect: { kind: "connect", edge, text } };
    }
  }
}

/** Removes the focused edge (Delete, or the "..." menu); undefined when it is not in the graph. */
export function disconnect(
  graph: A11yGraph,
  edgeId: string,
): { readonly edges: readonly A11yEdge[]; readonly text: string } | undefined {
  const edge = graph.edges.find((e) => e.id === edgeId);
  if (edge === undefined) return undefined;
  const nodes = new Map(graph.nodes.map((n) => [n.id, n]));
  const name = (id: string): string => {
    const node = nodes.get(id);
    return node === undefined ? id : nodeName(node);
  };
  return {
    edges: graph.edges.filter((e) => e.id !== edgeId),
    text: copy.disconnected(name(edge.source), name(edge.target), edge.targetPort),
  };
}

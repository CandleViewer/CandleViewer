/**
 * Connecting and disconnecting ports without a pointer (WCAG 2.5.7; 05 §3.2, §3.4 item 8; E37-D02
 * §13; E47-S03 BQ-05). A pure reducer: Space (`rules.connect`) on a node's output port starts a
 * pending connection, which announces how many inputs can take it and how many cannot, once; the
 * arrows cycle only the inputs that can take it ("k of n" counts those), and Tab picks any input
 * directly, an unavailable one announced with its reason; Space confirms; Esc cancels. A confirm
 * is re-checked against the graph it is given, so a connection the graph cannot take is refused
 * with a reason and never produced: no self-loop, no duplicate, no second edge into a single
 * input, no type mismatch (the oracle, i.e. rule-graph's PORT_COMPAT), no loop.
 *
 * Why Space, not D02's Enter: Enter is `rules.inspect_node` in the same Rules context and the
 * keymap lint refuses a same-context collision; 05 §3.3 item 6 lists "Enter/Space to connect", so
 * the registry binds Space and every string says Space. `rules.pan` is Space+drag, not Space: the
 * two never meet because pan arms only while Space is held with a pointer drag and no port focused
 * or connection pending, and connect acts on the keydown with a port focused or pending.
 *
 * Carried rows, hard gates for the wiring PR (E37-S05 #1071; E47-S08 #1322 for the hotkey layer):
 * - C-1: the connect handler calls `preventDefault()` on the Space keydown, so the focused port
 *   button's native click does not fire as well (one press = one `start` or one `confirm`).
 * - C-2: a click or native activation on a target port while pending dispatches `pick` then
 *   `confirm`; on an output port while idle it dispatches `start`.
 * - C-3: the graph region is a composite widget (a roving group; `role="application"` only if
 *   E37-D04 rules it), so NVDA and JAWS switch to focus mode and pass Space and Ctrl+arrows to the
 *   page instead of using them for browse-mode reading.
 * - C-4: the Rules context is active only while focus is inside the editor, so Replay's and the
 *   DOM ladder's Space are untouched elsewhere (the mutual shadows in keymap.json rely on this).
 * - C-5: edge focus: `GraphNavigator.edgesOf` is the model entry (the D02 adjacency sub-list); the
 *   key that focuses it, and Delete on a focused edge calling `disconnect`, are wired there.
 */
import { copy, REFUSAL } from "./copy.js";
import {
  adjacencyFor,
  adjacencyOf,
  OUTPUT_PORT,
  type A11yEdge,
  type A11yGraph,
  type A11yNode,
  type Adjacency,
  type ConnectVerdict,
  type PortOracle,
} from "./graph.js";
import { nodeNames } from "./outline.js";
import { traversalOrder } from "./traversal.js";

export type NewEdge = Omit<A11yEdge, "id">;

export interface Candidate {
  readonly node: string;
  readonly port: string;
  /** The input's port type, read with the candidate. */
  readonly type: string;
  readonly verdict: ConnectVerdict;
}

export type PortSelection =
  | { readonly kind: "idle" }
  | {
      readonly kind: "pending";
      readonly source: string;
      /** Every input of every other node, in node order; `verdict` says which can take it. */
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

/** What one verdict reads, built once per call so a whole candidate list costs O(n + e). */
interface Context {
  readonly nodes: ReadonlyMap<string, A11yNode>;
  readonly adj: ReadonlyMap<string, Adjacency>;
}

const contextOf = (graph: A11yGraph): Context => ({
  nodes: new Map(graph.nodes.map((n) => [n.id, n])),
  adj: adjacencyOf(graph),
});

/** `source` and every node upstream of it: an edge source -> target closes a loop iff target is here. */
function upstreamOf(ctx: Context, source: string): ReadonlySet<string> {
  const seen = new Set([source]);
  const queue = [source];
  for (let head = 0; head < queue.length; head += 1) {
    for (const edge of adjacencyFor(ctx.adj, queue[head] as string).inbound) {
      if (seen.has(edge.source)) continue;
      seen.add(edge.source);
      queue.push(edge.source);
    }
  }
  return seen;
}

function verdictIn(
  ctx: Context,
  oracle: PortOracle,
  upstream: () => ReadonlySet<string>,
  source: string,
  target: string,
  port: string,
): ConnectVerdict {
  const from = ctx.nodes.get(source);
  const to = ctx.nodes.get(target);
  if (from === undefined || to === undefined) return refused(REFUSAL.unknownNode);
  if (source === target) return refused(REFUSAL.selfLoop);
  const output = oracle.outputOf(from);
  if (output === null) return refused(REFUSAL.noOutput);
  const input = oracle.inputsOf(to).find(([name]) => name === port);
  if (input === undefined) return refused(REFUSAL.noInput);
  const into = adjacencyFor(ctx.adj, target).inbound.filter((e) => e.targetPort === port);
  if (into.some((e) => e.source === source)) return refused(REFUSAL.duplicate);
  if (into.length > 0 && !oracle.acceptsMany(port)) return refused(REFUSAL.occupied);
  const types = oracle.canConnect(output, input[1]);
  if (!types.ok) return types;
  return upstream().has(target) ? refused(REFUSAL.loop) : { ok: true };
}

const lazy = <T>(make: () => T): (() => T) => {
  let value: { readonly v: T } | undefined;
  return () => (value ??= { v: make() }).v;
};

/** Whether `source`'s output may feed `target`'s input `port` in `graph`, else why not. */
export function verdictFor(
  graph: A11yGraph,
  oracle: PortOracle,
  source: string,
  target: string,
  port: string,
): ConnectVerdict {
  const ctx = contextOf(graph);
  return verdictIn(
    ctx,
    oracle,
    lazy(() => upstreamOf(ctx, source)),
    source,
    target,
    port,
  );
}

/** Every input of every other node, in the documented order: adjacency and loop set built once. */
function candidatesFor(
  graph: A11yGraph,
  oracle: PortOracle,
  ctx: Context,
  source: string,
): Candidate[] {
  const upstream = lazy(() => upstreamOf(ctx, source));
  return traversalOrder(graph)
    .filter((entry) => entry.id !== source)
    .flatMap((entry) =>
      oracle.inputsOf(ctx.nodes.get(entry.id) as A11yNode).map(([port, type]) => ({
        node: entry.id,
        port,
        type,
        verdict: verdictIn(ctx, oracle, upstream, source, entry.id, port),
      })),
    );
}

/** The indices of the candidates that can take the connection: the ones the arrows cycle. */
const availableOf = (candidates: readonly Candidate[]): number[] =>
  candidates.flatMap((c, i) => (c.verdict.ok ? [i] : []));

/** One keyboard event against the connection in progress; pure, the graph is never mutated. */
export function stepPortSelection(
  state: PortSelection,
  event: PortEvent,
  graph: A11yGraph,
  oracle: PortOracle,
): PortStep {
  const ctx = contextOf(graph);
  const names = nodeNames(graph);
  const name = (id: string): string => names.get(id) ?? id;
  const refuse = (reason: string): PortStep => ({
    state,
    effect: { kind: "refuse", reason, text: copy.refused(reason) },
  });
  const focus = (s: Extract<PortSelection, { kind: "pending" }>, index: number): PortStep => {
    const c = s.candidates[index] as Candidate; // index is in range by construction
    const available = availableOf(s.candidates);
    const text = c.verdict.ok
      ? copy.candidate(name(c.node), c.port, c.type, available.indexOf(index) + 1, available.length)
      : copy.candidateRefused(name(c.node), c.port, c.verdict.reason);
    return { state: { ...s, index }, effect: { kind: "announce", text } };
  };
  switch (event.type) {
    case "start": {
      const node = ctx.nodes.get(event.node);
      if (node === undefined) return refuse(REFUSAL.unknownNode);
      if (oracle.outputOf(node) === null) return refuse(REFUSAL.noOutput);
      const candidates = candidatesFor(graph, oracle, ctx, node.id);
      const available = availableOf(candidates).length;
      return {
        state: { kind: "pending", source: node.id, candidates, index: null },
        effect: {
          kind: "announce",
          text: copy.connectStarted(name(node.id), available, candidates.length - available),
        },
      };
    }
    case "cancel":
      if (state.kind === "idle") return { state, effect: { kind: "none" } };
      return { state: IDLE, effect: { kind: "cancelled", text: copy.cancelled() } };
    case "cycle": {
      if (state.kind === "idle") return { state, effect: { kind: "none" } };
      const available = availableOf(state.candidates);
      if (available.length === 0) {
        return { state, effect: { kind: "announce", text: copy.noneAvailable() } };
      }
      // From a picked unavailable input too: the next available one in the arrow's direction.
      const at = state.index;
      const next =
        event.step === 1
          ? (available.find((i) => at === null || i > at) ?? available[0])
          : ([...available].reverse().find((i) => at === null || i < at) ??
            available[available.length - 1]);
      return focus(state, next as number); // available is not empty
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
  const names = nodeNames(graph);
  const name = (id: string): string => names.get(id) ?? id;
  return {
    edges: graph.edges.filter((e) => e.id !== edgeId),
    text: copy.disconnected(name(edge.source), name(edge.target), edge.targetPort),
  };
}

/** The Delete-node announcement: how many connections went with it (E37-D02 §13; A-8). */
export function deletedText(graph: A11yGraph, nodeId: string): string | undefined {
  if (!graph.nodes.some((n) => n.id === nodeId)) return undefined;
  const names = nodeNames(graph);
  const removed = graph.edges.filter((e) => e.source === nodeId || e.target === nodeId).length;
  return copy.nodeDeleted(names.get(nodeId) ?? nodeId, removed);
}

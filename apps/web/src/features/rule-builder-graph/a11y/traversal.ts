/**
 * The roving order and focus model of SCR-082, E37-D02 §13 "Roving order (BQ-15 RULED)"
 * (`docs/design/E37/E37-D02.md`:358) as ruled for E47-S03 BQ-04: derived from topology, never from
 * canvas coordinates. rule-graph edges run from an input's producer to the node it feeds, the root
 * condition feeds every action's `when`, and the trigger has no edge.
 *
 * The order (topological: a producer before the node it feeds):
 * 1. the trigger;
 * 2. the root condition's subtree, depth-first in `in`-edge order: each producer's own subtree
 *    before the next producer, the root after its producers (a node shared by two consumers is
 *    listed once, at its first use);
 * 3. the actions, in IR order (the model's array order, which rule-graph builds in IR order);
 * then the rest of the connected walk (a fragment not under an action, sink last; nodes only on a
 * loop); then the nodes with no connection (a fresh palette node, an `ORPHAN_NODE`, a comment) in
 * creation (array) order. Edges are read in array order, so the order never depends on id spelling.
 *
 * Keys (`GraphNavigator.next`; PROPOSED until E37-D04 #949 verifies the map, D02 §13 :363–365):
 * - Tab enters the graph region once (`enter`, the last focused node or the first); the region is
 *   one roving stop, Tab leaves it.
 * - Up / Down step along the order, except: at a fan-in, Up from the consumer goes to its FIRST
 *   `in` producer; at a fan-out, Down from the shared producer goes to its FIRST consumer.
 *   Home / End go to the ends of the order (an addition, PROPOSED).
 * - Left / Right move between the focused node's ports, a sub-position of the node focus: the
 *   ports read [inputs in port order, output]; Left from the node takes the first input, Right
 *   from the node takes the output; along the ports Left / Right step back / forward and stop at
 *   the ends. Down on a port focuses its first connection (D02 §6 E2: "→ onto its output port
 *   then ↓ onto the connection"), Down / Up step through that port's connections, Up from the
 *   first returns to the port and Up on a port returns to the node.
 * - Enter on a port starts / confirms a connect, Esc cancels and Delete on a connection
 *   disconnects (`portSelection.ts`); focus after a disconnect is the source node and after a
 *   node delete the previous node in the order (`afterDelete`), D02 §13 :369–370.
 * The node list (E37-S05 #1071) reads this same order and stays the complete path: at a fan-out the
 * Down override can skip a node (D02 accepts this: "the node list is always the complete path").
 */
import {
  adjacencyFor,
  adjacencyOf,
  byId,
  OUTPUT_PORT,
  type A11yEdge,
  type A11yGraph,
  type A11yNode,
  type Adjacency,
  type PortOracle,
} from "./graph.js";

export interface TraversalEntry {
  readonly id: string;
  /** Depth below the node the walk started from: 0 for a trigger, a root, an action or a start. */
  readonly depth: number;
}

/** The order every node appears in, each exactly once. */
export function traversalOrder(graph: A11yGraph): readonly TraversalEntry[] {
  const adj = adjacencyOf(graph);
  const nodes: A11yNode[] = [];
  const listed = new Set<string>();
  for (const node of graph.nodes) {
    if (listed.has(node.id)) continue;
    listed.add(node.id);
    nodes.push(node);
  }
  const producers = (id: string): string[] =>
    adjacencyFor(adj, id)
      .inbound.map((e) => e.source)
      .filter((s) => adj.has(s));
  const consumers = (id: string): string[] =>
    adjacencyFor(adj, id)
      .outbound.map((e) => e.target)
      .filter((t) => adj.has(t));
  const linked = (id: string): boolean => producers(id).length > 0 || consumers(id).length > 0;
  const seen = new Set<string>();
  const order: TraversalEntry[] = [];
  /** Post-order, depth-first up the producers; iterative, so a long chain cannot overflow. */
  const walk = (start: string): void => {
    const stack: { id: string; depth: number; done: boolean }[] = [
      { id: start, depth: 0, done: false },
    ];
    while (stack.length > 0) {
      const frame = stack.pop() as (typeof stack)[number]; // length checked
      if (frame.done) {
        order.push({ id: frame.id, depth: frame.depth });
        continue;
      }
      if (seen.has(frame.id)) continue;
      seen.add(frame.id); // on entry, so a loop ends here
      stack.push({ ...frame, done: true });
      const next = producers(frame.id);
      for (let i = next.length - 1; i >= 0; i -= 1) {
        const id = next[i] as string;
        if (!seen.has(id)) stack.push({ id, depth: frame.depth + 1, done: false });
      }
    }
  };
  const actions = nodes.filter((n) => n.type === "action" && linked(n.id));
  for (const node of nodes) if (node.type === "trigger") walk(node.id);
  for (const action of actions) for (const root of producers(action.id)) walk(root);
  for (const action of actions) walk(action.id);
  for (const node of nodes) if (linked(node.id) && consumers(node.id).length === 0) walk(node.id);
  for (const node of nodes) if (linked(node.id)) walk(node.id); // only loops are left here
  for (const node of nodes) walk(node.id);
  return order;
}

export type NavKey = "right" | "left" | "up" | "down" | "home" | "end";

export interface PortRef {
  readonly direction: "input" | "output";
  /** The input port's name, or `out`. */
  readonly port: string;
  /** The port's connections: an input's in `in`-edge order, the output's by consumer rank. */
  readonly edges: readonly A11yEdge[];
}

/** Where focus is inside the graph region: a node, one of its ports, or one of that port's edges. */
export type GraphFocus =
  | { readonly kind: "node"; readonly node: string }
  | {
      readonly kind: "port";
      readonly node: string;
      readonly direction: PortRef["direction"];
      readonly port: string;
    }
  | {
      readonly kind: "edge";
      readonly node: string;
      readonly direction: PortRef["direction"];
      readonly port: string;
      readonly edge: string;
    };

const atNode = (node: string): GraphFocus => ({ kind: "node", node });
const atPort = (node: string, ref: PortRef): GraphFocus => ({
  kind: "port",
  node,
  direction: ref.direction,
  port: ref.port,
});

export class GraphNavigator {
  readonly order: readonly TraversalEntry[];
  private readonly rank = new Map<string, number>();
  private readonly adj: ReadonlyMap<string, Adjacency>;
  private readonly nodes: ReadonlyMap<string, A11yNode>;

  /** Without an oracle a node's ports are the ones its edges name (no empty input is listed). */
  constructor(
    graph: A11yGraph,
    private readonly oracle?: PortOracle,
  ) {
    this.order = traversalOrder(graph);
    this.adj = adjacencyOf(graph);
    this.nodes = new Map(graph.nodes.map((n) => [n.id, n]));
    this.order.forEach((entry, i) => this.rank.set(entry.id, i));
  }

  /** 1-based position and set size, for `aria-posinset` / `aria-setsize`. */
  positionOf(id: string): { readonly index: number; readonly size: number } | undefined {
    const at = this.rank.get(id);
    return at === undefined ? undefined : { index: at + 1, size: this.order.length };
  }

  private byRank = (a: string, b: string): number =>
    (this.rank.get(a) ?? Infinity) - (this.rank.get(b) ?? Infinity) || byId(a, b);

  /** The node's distinct producers in `in`-edge order (the first is D02's "first producer"). */
  producersOf(id: string): readonly string[] {
    const ends = adjacencyFor(this.adj, id).inbound.map((e) => e.source);
    return [...new Set(ends)].filter((end) => this.rank.has(end));
  }

  /** The node's distinct consumers by order rank (the first is D02's "first consumer"). */
  consumersOf(id: string): readonly string[] {
    const ends = adjacencyFor(this.adj, id).outbound.map((e) => e.target);
    return [...new Set(ends)].filter((end) => this.rank.has(end)).sort(this.byRank);
  }

  /** The node's ports, left to right: inputs in port order, then the output. */
  portsOf(id: string): readonly PortRef[] {
    const node = this.nodes.get(id);
    if (node === undefined || !this.rank.has(id)) return [];
    const { inbound, outbound } = adjacencyFor(this.adj, id);
    const declared = this.oracle?.inputsOf(node).map(([port]) => port) ?? [];
    const named = [...new Set(inbound.map((e) => e.targetPort))].filter(
      (port) => !declared.includes(port),
    );
    const inputs: PortRef[] = [...declared, ...named].map((port) => ({
      direction: "input",
      port,
      edges: inbound.filter((e) => e.targetPort === port),
    }));
    const hasOutput =
      (this.oracle !== undefined && this.oracle.outputOf(node) !== null) || outbound.length > 0;
    if (!hasOutput) return inputs;
    const edges = [...outbound].sort((a, b) => this.byRank(a.target, b.target) || byId(a.id, b.id));
    return [...inputs, { direction: "output", port: OUTPUT_PORT, edges }];
  }

  /** Tab into the region: the last focus when it is still in the graph, else the first node. */
  enter(last?: GraphFocus): GraphFocus | undefined {
    if (last !== undefined && this.valid(last)) return last;
    const first = this.order[0]?.id;
    return first === undefined ? undefined : atNode(first);
  }

  /** Where focus goes after the node is deleted: the previous node in the order, else the next. */
  afterDelete(id: string): string | undefined {
    const at = this.rank.get(id);
    if (at === undefined) return undefined;
    return (this.order[at - 1] ?? this.order[at + 1])?.id;
  }

  private valid(focus: GraphFocus): boolean {
    if (focus.kind === "node") return this.rank.has(focus.node);
    const ref = this.portsOf(focus.node).find(
      (p) => p.direction === focus.direction && p.port === focus.port,
    );
    return (
      ref !== undefined && (focus.kind === "port" || ref.edges.some((e) => e.id === focus.edge))
    );
  }

  /** The node-level Up / Down / Home / End move, with D02's fan-in and fan-out rules. */
  private step(from: string, key: "up" | "down" | "home" | "end"): string {
    const at = this.rank.get(from) as number; // callers pass a ranked id
    if (key === "home") return (this.order[0] as TraversalEntry).id;
    if (key === "end") return (this.order[this.order.length - 1] as TraversalEntry).id;
    if (key === "up") {
      const producers = this.producersOf(from);
      if (producers.length > 1) return producers[0] as string; // fan-in: the first producer
      return this.order[at - 1]?.id ?? from;
    }
    const consumers = this.consumersOf(from);
    if (consumers.length > 1) return consumers[0] as string; // fan-out: the first consumer
    return this.order[at + 1]?.id ?? from;
  }

  /** The focus a key moves to; the same focus when there is nowhere to go. Pure. */
  next(focus: GraphFocus, key: NavKey): GraphFocus {
    if (!this.valid(focus)) return this.enter() ?? focus;
    const ports = this.portsOf(focus.node);
    if (focus.kind === "node") {
      if (key === "left" || key === "right") {
        const target =
          key === "left"
            ? ports.find((p) => p.direction === "input")
            : ports.find((p) => p.direction === "output");
        return target === undefined ? focus : atPort(focus.node, target);
      }
      return atNode(this.step(focus.node, key));
    }
    const i = ports.findIndex((p) => p.direction === focus.direction && p.port === focus.port);
    const ref = ports[i] as PortRef; // valid() found it
    if (key === "home" || key === "end") return atNode(this.step(focus.node, key));
    if (key === "left" || key === "right") {
      const to = ports[i + (key === "right" ? 1 : -1)];
      return to === undefined ? atPort(focus.node, ref) : atPort(focus.node, to);
    }
    if (focus.kind === "port") {
      const first = ref.edges[0];
      if (key === "up") return atNode(focus.node);
      if (first === undefined) return focus;
      return {
        kind: "edge",
        node: focus.node,
        direction: ref.direction,
        port: ref.port,
        edge: first.id,
      };
    }
    const e = ref.edges.findIndex((edge) => edge.id === focus.edge);
    const to = ref.edges[e + (key === "down" ? 1 : -1)];
    if (to !== undefined) return { ...focus, edge: to.id };
    return key === "up" ? atPort(focus.node, ref) : focus;
  }

  /** The edges reachable from a node: outbound first, then inbound, by rank (the adjacency list). */
  edgesOf(id: string): readonly A11yEdge[] {
    const { inbound, outbound } = adjacencyFor(this.adj, id);
    const sort = (key: "source" | "target") => (a: A11yEdge, b: A11yEdge) =>
      this.byRank(a[key], b[key]) || byId(a.id, b.id);
    return [...[...outbound].sort(sort("target")), ...[...inbound].sort(sort("source"))];
  }
}

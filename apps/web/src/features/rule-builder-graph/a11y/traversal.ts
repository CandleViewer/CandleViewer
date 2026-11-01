/**
 * The documented node order of SCR-082 (E37-D02 §13, BQ-15 RULED; E47-S03 Technical notes): derived
 * from topology, never from canvas coordinates. rule-graph edges run from an input's producer to
 * the node it feeds, the root condition feeds every action's `when`, and the trigger has no edge.
 * So the order is: the triggers; then the root's subtree depth-first, root first, each node's
 * producers in `in`-edge order (a node shared by two consumers is listed once, at its first use);
 * then the actions; then connected nodes no action is reached from (a fragment being built: its
 * sink first, then its subtree the same way; then nodes only on a loop); then the nodes with no
 * connection (a fresh palette node, an orphan, a comment). Within each step, "creation order" and
 * "IR order" are the model's array order (rule-graph builds the arrays in IR order), and edges are
 * read in array order, so the order does not depend on how ids are spelt.
 *
 * Keys (`GraphNavigator.move`; PROPOSED until E37-D04 #949 verifies the map):
 * - Up / Down step along that one linear order, so "Node i of n" always has a key to i + 1 and every
 *   node is reachable from every other by arrows alone; Home / End go to its ends.
 * - Right moves to a consumer of the focused node (what it feeds), Left to a producer (what feeds
 *   it). With several, each further press from the same node takes the next one, wrapping (BQ-04
 *   cycling), so Left back then Right again reaches the second branch.
 * Carried to E37-S05 #1071: D02 §13 puts the node's ports on Left / Right; ports are focusable
 * elements there (named per §14, see `outline.ts`), and an edge is focused from the adjacency
 * sub-list (`edgesOf`), never by coordinates.
 */
import {
  adjacencyFor,
  adjacencyOf,
  byId,
  type A11yEdge,
  type A11yGraph,
  type A11yNode,
  type Adjacency,
} from "./graph.js";

export interface TraversalEntry {
  readonly id: string;
  /** Depth in the walk that listed the node: 0 for a trigger, a root, an action or a start. */
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
  /** Pre-order, depth-first up the producers; iterative, so a long chain cannot overflow. */
  const walk = (start: string, depth: number): void => {
    const stack: TraversalEntry[] = [{ id: start, depth }];
    while (stack.length > 0) {
      const entry = stack.pop() as TraversalEntry; // length checked
      if (seen.has(entry.id)) continue;
      seen.add(entry.id);
      order.push(entry);
      const next = producers(entry.id);
      for (let i = next.length - 1; i >= 0; i -= 1) {
        stack.push({ id: next[i] as string, depth: entry.depth + 1 });
      }
    }
  };
  const actions = nodes.filter((n) => n.type === "action" && linked(n.id));
  for (const node of nodes) if (node.type === "trigger") walk(node.id, 0);
  for (const action of actions) for (const root of producers(action.id)) walk(root, 0);
  for (const action of actions) walk(action.id, 0);
  for (const node of nodes)
    if (linked(node.id) && consumers(node.id).length === 0) walk(node.id, 0);
  for (const node of nodes) if (linked(node.id)) walk(node.id, 0); // only loops are left here
  for (const node of nodes) walk(node.id, 0);
  return order;
}

export type NavKey = "right" | "left" | "up" | "down" | "home" | "end";

export class GraphNavigator {
  readonly order: readonly TraversalEntry[];
  private readonly rank = new Map<string, number>();
  private readonly adj: ReadonlyMap<string, Adjacency>;
  /** Per direction and node, the branch Right / Left took last: the cycling cursor. */
  private readonly branch = new Map<string, number>();

  constructor(graph: A11yGraph) {
    this.order = traversalOrder(graph);
    this.adj = adjacencyOf(graph);
    this.order.forEach((entry, i) => this.rank.set(entry.id, i));
  }

  /** 1-based position and set size, for `aria-posinset` / `aria-setsize`. */
  positionOf(id: string): { readonly index: number; readonly size: number } | undefined {
    const at = this.rank.get(id);
    return at === undefined ? undefined : { index: at + 1, size: this.order.length };
  }

  private byRank = (a: string, b: string): number =>
    (this.rank.get(a) ?? Infinity) - (this.rank.get(b) ?? Infinity) || byId(a, b);

  /** The node's consumers (Right) or producers (Left), once each, in order rank. */
  neighbours(id: string, key: "right" | "left"): readonly string[] {
    const edges = adjacencyFor(this.adj, id);
    const ends =
      key === "right" ? edges.outbound.map((e) => e.target) : edges.inbound.map((e) => e.source);
    return [...new Set(ends)].filter((end) => this.rank.has(end)).sort(this.byRank);
  }

  /**
   * The node the key moves focus to; the same id when there is nowhere to go. Right / Left advance
   * the node's cycling cursor, so this is the one stateful call (a new navigator starts afresh).
   */
  move(from: string, key: NavKey): string {
    const first = this.order[0]?.id;
    const last = this.order[this.order.length - 1]?.id;
    const at = this.rank.get(from);
    if (first === undefined || last === undefined || at === undefined) return first ?? from;
    if (key === "home") return first;
    if (key === "end") return last;
    if (key === "up" || key === "down") {
      return this.order[at + (key === "down" ? 1 : -1)]?.id ?? from;
    }
    const ends = this.neighbours(from, key);
    if (ends.length === 0) return from;
    const cursor = `${key}:${from}`;
    const next = ((this.branch.get(cursor) ?? -1) + 1) % ends.length;
    this.branch.set(cursor, next);
    return ends[next] as string; // next < ends.length
  }

  /** The edges reachable from a node for edge focus: outbound first, then inbound, by rank. */
  edgesOf(id: string): readonly A11yEdge[] {
    const { inbound, outbound } = adjacencyFor(this.adj, id);
    const sort = (key: "source" | "target") => (a: A11yEdge, b: A11yEdge) =>
      this.byRank(a[key], b[key]) || byId(a.id, b.id);
    return [...[...outbound].sort(sort("target")), ...[...inbound].sort(sort("source"))];
  }
}

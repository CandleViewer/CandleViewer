/**
 * The documented node order of SCR-082 (E47-S03 Technical notes, BQ-04): derived from topology,
 * never from canvas coordinates. Triggers first; then a breadth-first walk along the edges'
 * direction (inputs before what they feed, so a rule reads leaf conditions, gates, root, actions)
 * seeded by every node with outbound but no inbound edges; then nodes reached only through a loop;
 * then nodes with no edge at all (comments, orphans). Every tie is broken by node id, so the order
 * does not depend on the order of the model's arrays.
 *
 * Keyboard moves (`GraphNavigator.move`) are O(degree) per press after one O(n + e log e) build:
 * Right follows the first outbound edge, Left the first inbound one (by order rank), Up/Down step
 * between nodes of the same depth, Home/End go to the ends of the order.
 */
import {
  adjacencyFor,
  adjacencyOf,
  byId,
  type A11yEdge,
  type A11yGraph,
  type Adjacency,
} from "./graph.js";

export interface TraversalEntry {
  readonly id: string;
  /** Breadth-first level from the walk's seed; triggers and edgeless nodes are 0. */
  readonly depth: number;
}

/** The order every node appears in, each exactly once. */
export function traversalOrder(graph: A11yGraph): readonly TraversalEntry[] {
  const adj = adjacencyOf(graph);
  const ids = [...new Set(graph.nodes.map((n) => n.id))].sort(byId);
  const types = new Map(graph.nodes.map((n) => [n.id, n.type]));
  const seen = new Set<string>();
  const order: TraversalEntry[] = [];
  const walk = (seed: string): void => {
    if (seen.has(seed)) return;
    seen.add(seed);
    const queue: TraversalEntry[] = [{ id: seed, depth: 0 }];
    for (let head = 0; head < queue.length; head += 1) {
      const entry = queue[head] as TraversalEntry; // head < queue.length
      order.push(entry);
      const next = adjacencyFor(adj, entry.id)
        .outbound.map((e) => e.target)
        .filter((id) => adj.has(id))
        .sort(byId);
      for (const id of next) {
        if (seen.has(id)) continue;
        seen.add(id);
        queue.push({ id, depth: entry.depth + 1 });
      }
    }
  };
  const edgesOf = (id: string): Adjacency => adjacencyFor(adj, id);
  const edgeless = (id: string): boolean =>
    edgesOf(id).inbound.length === 0 && edgesOf(id).outbound.length === 0;
  for (const id of ids) if (types.get(id) === "trigger") walk(id);
  for (const id of ids) if (edgesOf(id).inbound.length === 0 && !edgeless(id)) walk(id);
  for (const id of ids) if (!edgeless(id)) walk(id); // only loops are left unvisited here
  for (const id of ids) walk(id);
  return order;
}

export type NavKey = "right" | "left" | "up" | "down" | "home" | "end";

export class GraphNavigator {
  readonly order: readonly TraversalEntry[];
  private readonly rank = new Map<string, number>();
  private readonly levels = new Map<number, string[]>();
  private readonly levelIndex = new Map<string, number>();
  private readonly adj: ReadonlyMap<string, Adjacency>;

  constructor(graph: A11yGraph) {
    this.order = traversalOrder(graph);
    this.adj = adjacencyOf(graph);
    this.order.forEach((entry, i) => {
      this.rank.set(entry.id, i);
      const level = this.levels.get(entry.depth) ?? [];
      this.levelIndex.set(entry.id, level.length);
      level.push(entry.id);
      this.levels.set(entry.depth, level);
    });
  }

  /** 1-based position and set size, for `aria-posinset` / `aria-setsize`. */
  positionOf(id: string): { readonly index: number; readonly size: number } | undefined {
    const at = this.rank.get(id);
    return at === undefined ? undefined : { index: at + 1, size: this.order.length };
  }

  private byRank = (a: string, b: string): number =>
    (this.rank.get(a) ?? Infinity) - (this.rank.get(b) ?? Infinity) || byId(a, b);

  /** The node the key moves focus to; the same id when there is nowhere to go. */
  move(from: string, key: NavKey): string {
    const first = this.order[0]?.id;
    const last = this.order[this.order.length - 1]?.id;
    if (first === undefined || last === undefined || !this.rank.has(from)) return first ?? from;
    if (key === "home") return first;
    if (key === "end") return last;
    if (key === "right" || key === "left") {
      const edges = adjacencyFor(this.adj, from);
      const ends =
        key === "right" ? edges.outbound.map((e) => e.target) : edges.inbound.map((e) => e.source);
      return ends.filter((id) => this.rank.has(id)).sort(this.byRank)[0] ?? from;
    }
    const entry = this.order[this.rank.get(from) as number] as TraversalEntry; // rank checked above
    const level = this.levels.get(entry.depth) as string[]; // every entry's depth has a level
    const at = (this.levelIndex.get(from) as number) + (key === "down" ? 1 : -1);
    return level[at] ?? from;
  }

  /** The edges reachable from a node for edge focus: outbound first, then inbound, by rank. */
  edgesOf(id: string): readonly A11yEdge[] {
    const { inbound, outbound } = adjacencyFor(this.adj, id);
    const sort = (key: "source" | "target") => (a: A11yEdge, b: A11yEdge) =>
      this.byRank(a[key], b[key]) || byId(a.id, b.id);
    return [...[...outbound].sort(sort("target")), ...[...inbound].sort(sort("source"))];
  }
}

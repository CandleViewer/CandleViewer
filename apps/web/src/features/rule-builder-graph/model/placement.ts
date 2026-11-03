/**
 * Where a node with no stored position goes (E37-S01; BQ-13: the server stores no `graph_layout`
 * yet, so every node of a loaded rule needs one). Deterministic and overlap-free, on the 240-unit
 * grid the editor fixtures use: a node's column is its layer, read in E47-S03's traversal order
 * (`a11y/traversal.ts`, a producer before the node it feeds), so the trigger is leftmost, each
 * condition sits right of every producer that feeds it and an action right of its condition; a
 * loop's closing edge, which the order meets last, is ignored. Its row is the first free one in
 * that column, in the same order. Positions stay a client concern until E37-T02's worker layout
 * replaces this pass, which reads rule-graph's `nodesNeedingLayout` hook as that layout will.
 */
import { nodesNeedingLayout, type GraphLayout, type GraphModel } from "@candleviewer/rule-graph";
import { adjacencyFor, adjacencyOf } from "../a11y/graph.js";
import type { Point } from "../a11y/nudge.js";
import { traversalOrder } from "../a11y/traversal.js";

/** The grid step, both axes, in canvas units: a cell holds one node card of any tier. */
export const GRID = 240;

const cellOf = (v: number): number => Math.floor(v / GRID);
const keyOf = (cx: number, cy: number): string => `${cx},${cy}`;

/**
 * The cells taken by node positions. Two nodes overlap when their positions are less than one grid
 * step apart on both axes; a node card is at most one cell wide and tall at every tier.
 */
export class Occupancy {
  private readonly cells = new Map<string, Point[]>();

  constructor(points: Iterable<Point> = []) {
    for (const point of points) this.add(point);
  }

  add(point: Point): void {
    const key = keyOf(cellOf(point.x), cellOf(point.y));
    const bucket = this.cells.get(key);
    if (bucket === undefined) this.cells.set(key, [point]);
    else bucket.push(point);
  }

  /** Whether a node at `point` would overlap none of the positions held. */
  isFree(point: Point): boolean {
    const [cx, cy] = [cellOf(point.x), cellOf(point.y)];
    for (let dx = -1; dx <= 1; dx += 1) {
      for (let dy = -1; dy <= 1; dy += 1) {
        const near = this.cells.get(keyOf(cx + dx, cy + dy)) ?? [];
        const hit = near.some(
          (q) => Math.abs(q.x - point.x) < GRID && Math.abs(q.y - point.y) < GRID,
        );
        if (hit) return false;
      }
    }
    return true;
  }

  /** The first free point at or below `point`, one grid step at a time; it is taken. */
  takeBelow(point: Point): Point {
    let at = point;
    while (!this.isFree(at)) at = { x: at.x, y: at.y + GRID };
    this.add(at);
    return at;
  }
}

/** The node's stored position, if any (an own key only: ids are user text). */
export const positionOf = (layout: GraphLayout, id: string): Point | undefined =>
  Object.hasOwn(layout.positions, id) ? layout.positions[id] : undefined;

/** Each node's column: 0 for the trigger, else one right of its furthest producer (at least 1). */
function layersOf(graph: Pick<GraphModel, "nodes" | "edges">): ReadonlyMap<string, number> {
  const adj = adjacencyOf(graph);
  const types = new Map(graph.nodes.map((node) => [node.id, node.type]));
  const layers = new Map<string, number>();
  for (const { id } of traversalOrder(graph)) {
    if (types.get(id) === "trigger") {
      layers.set(id, 0);
      continue;
    }
    let layer = 1;
    for (const edge of adjacencyFor(adj, id).inbound) {
      const from = layers.get(edge.source); // unset only on a loop's closing edge
      if (from !== undefined) layer = Math.max(layer, from + 1);
    }
    layers.set(id, layer);
  }
  return layers;
}

/** `layout` with a position for every node it has none for; the stored positions are kept. */
export function placeNodes(graph: GraphModel, layout: GraphLayout): GraphLayout {
  const missing = new Set(nodesNeedingLayout(graph, layout));
  if (missing.size === 0) return layout;
  const taken = new Occupancy(
    graph.nodes.flatMap((node) => {
      const at = positionOf(layout, node.id);
      return at === undefined ? [] : [at];
    }),
  );
  const layers = layersOf(graph);
  const placed = new Map<string, Point>();
  for (const { id } of traversalOrder(graph)) {
    if (!missing.has(id)) continue;
    placed.set(id, taken.takeBelow({ x: (layers.get(id) ?? 1) * GRID, y: 0 }));
  }
  const positions = Object.fromEntries([...Object.entries(layout.positions), ...placed]);
  return { ...layout, positions };
}

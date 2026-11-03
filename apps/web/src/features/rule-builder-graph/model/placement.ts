/**
 * Where a node with no usable stored position goes (E37-S01): a rule authored in the form stores
 * none, and the load-time normaliser (`layout.ts`) drops a position it cannot use. Deterministic
 * and overlap-free, on the 240-unit grid the editor fixtures use: a node's column is its layer,
 * read in E47-S03's traversal order (`a11y/traversal.ts`, a producer before the node it feeds), so
 * the trigger is leftmost, each condition sits right of every producer that feeds it and an action
 * right of its condition; a loop's closing edge, which the order meets last, is ignored. Its row
 * is the first free one in that column, in the same order. E37-T02's worker layout replaces this
 * pass.
 */
import type { GraphLayout, GraphModel } from "@candleviewer/rule-graph";
import { adjacencyFor, adjacencyOf } from "../a11y/graph.js";
import type { Point } from "../a11y/nudge.js";
import { traversalOrder } from "../a11y/traversal.js";
import { CANVAS_LIMIT, pointOf } from "./layout.js";

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
  private held = 0;

  constructor(points: Iterable<Point> = []) {
    for (const point of points) this.add(point);
  }

  add(point: Point): void {
    const key = keyOf(cellOf(point.x), cellOf(point.y));
    const bucket = this.cells.get(key);
    if (bucket === undefined) this.cells.set(key, [point]);
    else bucket.push(point);
    this.held += 1;
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

  /**
   * The first free point at or below `point`, one grid step at a time, or at or above it where the
   * walk down would pass the canvas bound; it is taken. A held point blocks at most two steps of a
   * column, so with n points held one of the first 2n + 1 steps is free and the walk stops there:
   * it ends even where a step no longer moves the number. From a point inside the bound it stays
   * inside while 2n steps fit in the bound (n up to 2,083, past the server's 1,000-node cap).
   */
  takeBelow(point: Point): Point {
    const steps = 2 * this.held;
    const step = point.y + steps * GRID <= CANVAS_LIMIT ? GRID : -GRID;
    let at = point;
    for (let k = 0; k < steps && !this.isFree(at); k += 1) at = { x: at.x, y: at.y + step };
    this.add(at);
    return at;
  }
}

/** The node's usable stored position, if any (an own key only: ids are user text). */
export const positionOf = (layout: GraphLayout, id: string): Point | undefined =>
  Object.hasOwn(layout.positions, id) ? pointOf(layout.positions[id]) : undefined;

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

/** `layout` with a position for every node it has no usable one for; the others are kept. */
export function placeNodes(graph: GraphModel, layout: GraphLayout): GraphLayout {
  const missing = new Set(
    graph.nodes.filter((node) => positionOf(layout, node.id) === undefined).map((node) => node.id),
  );
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

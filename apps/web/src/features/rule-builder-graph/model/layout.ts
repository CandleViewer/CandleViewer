/**
 * A stored layout as the editor reads it (E37-S01; SR-E37-04 in #1073's E37 threat model, §9). A
 * stored `graph_layout` holds whatever its writer sent, so it is normalised once, at load, before
 * any position is read: a position counts only when `x` and `y` are finite numbers, clamped to
 * ±`CANVAS_LIMIT`, and any other entry leaves its node unplaced, so `placeNodes` places it; a
 * `collapsed` entry counts only when it is a string id naming a node. The reducer (PR 4 of 9)
 * checks a move and a palette drop with the same `pointOf`. Pure.
 */
import type { GraphLayout, GraphModel } from "@candleviewer/rule-graph";
import type { Point } from "../a11y/nudge.js";

/**
 * The canvas bound, both axes, in canvas units: stored, moved and dropped points clamp to it, and
 * placement and insertion walk inside it, so every point a layout holds lies within it.
 */
export const CANVAS_LIMIT = 1_000_000;

// `+ 0` turns a -0 into 0, so a position is never negative zero.
const clamp = (v: number): number => Math.min(CANVAS_LIMIT, Math.max(-CANVAS_LIMIT, v)) + 0;

/** `value` as a position, a fresh object: finite `x` and `y`, clamped to the bound; else none. */
export function pointOf(value: unknown): Point | undefined {
  if (typeof value !== "object" || value === null) return undefined;
  const { x, y } = value as { readonly x?: unknown; readonly y?: unknown }; // checked just below
  const finite = (v: unknown): v is number => typeof v === "number" && Number.isFinite(v);
  return finite(x) && finite(y) ? { x: clamp(x), y: clamp(y) } : undefined;
}

/** `layout` keeping only the positions and collapsed ids the editor can use for `graph`'s nodes. */
export function normaliseLayout(
  graph: Pick<GraphModel, "nodes">,
  layout: GraphLayout,
): GraphLayout {
  const ids = new Set(graph.nodes.map((node) => node.id));
  const stored: unknown = layout.positions;
  const entries = typeof stored === "object" && stored !== null ? Object.entries(stored) : [];
  const positions = Object.fromEntries(
    entries.flatMap(([id, value]) => {
      const at = ids.has(id) ? pointOf(value) : undefined;
      return at === undefined ? [] : [[id, at] as const];
    }),
  );
  const listed: unknown = layout.collapsed;
  const collapsed = (Array.isArray(listed) ? listed : []).filter(
    (id): id is string => typeof id === "string" && ids.has(id),
  );
  return { ...layout, positions, collapsed };
}

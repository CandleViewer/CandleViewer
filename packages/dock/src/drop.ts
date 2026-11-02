/**
 * Drop resolution (CMP-214) and its keyboard twin (CMP-216's "Move panel" chooser, E15-D04 §5).
 * Both compute the same zone list (`dropZones`) and return a `DropTarget` that `relocate` applies:
 * one code path, two entry points, so the keyboard path cannot drift from the pointer one.
 */
import { DockError } from "./errors.js";
import {
  findNode,
  leavesOf,
  type DockNode,
  type DockTree,
  type NodeId,
  type PaneId,
  type Rect,
  type Size,
  type Zone,
} from "./model.js";
import { move, type OpContext } from "./ops.js";

export interface DropTarget {
  /** A panel box: a leaf outside any tab group, or a tab group. */
  readonly targetId: NodeId;
  readonly zone: Zone;
}

export interface DropZone extends DropTarget {
  readonly rect: Rect;
}

/** CMP-214 geometry: edge bands 25 % of the box, clamped to 48..160 px; a centre of 48 px or more. */
export const ZONE_GEOMETRY = Object.freeze({
  bandPct: 25,
  bandMin: 48,
  bandMax: 160,
  centreMin: 48,
});

/** Every node's rect in a dock of `viewport` px (a tab's rect is its group's). */
export function layoutRects(tree: DockTree, viewport: Size): Map<NodeId, Rect> {
  const rects = new Map<NodeId, Rect>();
  const walk = (node: DockNode, rect: Rect): void => {
    rects.set(node.id, rect);
    if (node.type === "leaf") return;
    if (node.type === "tabset") {
      for (const leaf of node.children) rects.set(leaf.id, rect);
      return;
    }
    let offset = 0;
    node.children.forEach((child, i) => {
      const share = node.sizes[i] ?? 0;
      walk(
        child,
        node.type === "row"
          ? {
              x: rect.x + offset * rect.width,
              y: rect.y,
              width: share * rect.width,
              height: rect.height,
            }
          : {
              x: rect.x,
              y: rect.y + offset * rect.height,
              width: rect.width,
              height: share * rect.height,
            },
      );
      offset += share;
    });
  };
  if (tree.root !== null) walk(tree.root, { x: 0, y: 0, ...viewport });
  return rects;
}

/** The panel boxes in reading order: leaves outside tab groups, and tab groups. */
export function panelBoxes(tree: DockTree): DockNode[] {
  const out: DockNode[] = [];
  const walk = (node: DockNode): void => {
    if (node.type === "leaf" || node.type === "tabset") out.push(node);
    else node.children.forEach(walk);
  };
  if (tree.root !== null) walk(tree.root);
  return out;
}

/** The box holding the pane: its leaf, or its tab group. */
function boxOf(tree: DockTree, paneId: PaneId): DockNode | null {
  return (
    panelBoxes(tree).find((box) => leavesOf(box).some((leaf) => leaf.paneId === paneId)) ?? null
  );
}

function zonesOf(box: DockNode, rect: Rect): DropZone[] {
  const band = (extent: number): number =>
    Math.min(
      Math.max((extent * ZONE_GEOMETRY.bandPct) / 100, ZONE_GEOMETRY.bandMin),
      ZONE_GEOMETRY.bandMax,
      extent / 2,
    );
  const bx = band(rect.width);
  const by = band(rect.height);
  const inner = {
    x: rect.x + bx,
    y: rect.y + by,
    width: rect.width - 2 * bx,
    height: rect.height - 2 * by,
  };
  const zones: DropZone[] = [
    { targetId: box.id, zone: "left", rect: { ...rect, width: bx } },
    { targetId: box.id, zone: "right", rect: { ...rect, x: rect.x + rect.width - bx, width: bx } },
    {
      targetId: box.id,
      zone: "top",
      rect: { x: inner.x, y: rect.y, width: inner.width, height: by },
    },
    {
      targetId: box.id,
      zone: "bottom",
      rect: { x: inner.x, y: rect.y + rect.height - by, width: inner.width, height: by },
    },
  ];
  if (inner.width >= ZONE_GEOMETRY.centreMin && inner.height >= ZONE_GEOMETRY.centreMin) {
    zones.push({ targetId: box.id, zone: "centre", rect: inner });
  }
  return zones;
}

/**
 * The zones a moving pane may drop on: every panel box but its own leaf; its own tab group offers
 * its edges only (dropping into the centre would change nothing).
 */
export function dropZones(tree: DockTree, viewport: Size, movingPaneId: PaneId): DropZone[] {
  const rects = layoutRects(tree, viewport);
  const own = boxOf(tree, movingPaneId);
  return panelBoxes(tree).flatMap((box) => {
    if (box.type === "leaf" && box.paneId === movingPaneId) return [];
    const zones = zonesOf(box, rects.get(box.id) as Rect); // every box has a rect
    return box === own ? zones.filter((z) => z.zone !== "centre") : zones;
  });
}

const inside = (r: Rect, x: number, y: number): boolean =>
  x >= r.x && x < r.x + r.width && y >= r.y && y < r.y + r.height;

/** The zone under the pointer, or null (CMP-214's pointer path). */
export function resolveDrop(
  tree: DockTree,
  viewport: Size,
  movingPaneId: PaneId,
  point: { readonly x: number; readonly y: number },
): DropTarget | null {
  const hit = dropZones(tree, viewport, movingPaneId).find((z) => inside(z.rect, point.x, point.y));
  return hit === undefined ? null : { targetId: hit.targetId, zone: hit.zone };
}

/** A stage-one step of the chooser: arrows by shared edge, `Tab` / `Shift+Tab` by reading order. */
export type ChooserStep = "left" | "right" | "up" | "down" | "next" | "prev";

const OVERLAP_EPSILON = 1e-6;

/** The box next to `fromId` in `step`, or null at an edge. */
export function neighbour(
  tree: DockTree,
  viewport: Size,
  fromId: NodeId,
  step: ChooserStep,
): NodeId | null {
  const boxes = panelBoxes(tree);
  const index = boxes.findIndex((box) => box.id === fromId);
  if (index === -1) return null;
  if (step === "next" || step === "prev")
    return boxes[index + (step === "next" ? 1 : -1)]?.id ?? null;
  const rects = layoutRects(tree, viewport);
  const from = rects.get(fromId) as Rect;
  const horizontal = step === "left" || step === "right";
  let best: { id: NodeId; overlap: number } | null = null;
  for (const box of boxes) {
    const r = rects.get(box.id) as Rect;
    const edge =
      step === "right"
        ? r.x - (from.x + from.width)
        : step === "left"
          ? from.x - (r.x + r.width)
          : step === "down"
            ? r.y - (from.y + from.height)
            : from.y - (r.y + r.height);
    if (Math.abs(edge) > OVERLAP_EPSILON) continue;
    const overlap = horizontal
      ? Math.min(from.y + from.height, r.y + r.height) - Math.max(from.y, r.y)
      : Math.min(from.x + from.width, r.x + r.width) - Math.max(from.x, r.x);
    if (overlap > OVERLAP_EPSILON && (best === null || overlap > best.overlap + OVERLAP_EPSILON)) {
      best = { id: box.id, overlap };
    }
  }
  return best?.id ?? null;
}

/**
 * CMP-216's keyboard path: from the pane's own box, walk `steps` to a target box (stage one), then
 * take `zone` of it (stage two). The result is a zone of `dropZones`, exactly as the pointer's.
 */
export function resolveDirectionalMove(
  tree: DockTree,
  viewport: Size,
  paneId: PaneId,
  steps: readonly ChooserStep[],
  zone: Zone,
): DropTarget | null {
  let at: NodeId | null = boxOf(tree, paneId)?.id ?? null;
  for (const step of steps) {
    if (at === null) return null;
    at = neighbour(tree, viewport, at, step);
  }
  const hit = dropZones(tree, viewport, paneId).find((z) => z.targetId === at && z.zone === zone);
  return hit === undefined ? null : { targetId: hit.targetId, zone: hit.zone };
}

/** Applies a drop target from either path: a re-parent of the pane's leaf. */
export function relocate(
  tree: DockTree,
  paneId: PaneId,
  target: DropTarget,
  ctx: OpContext,
): DockTree {
  if (tree.root === null || findNode(tree.root, target.targetId) === null) {
    throw new DockError("unknown_target", `no node ${target.targetId}`);
  }
  return move(tree, paneId, target.targetId, target.zone, ctx);
}

/** The panes drawn below their minimum in a dock of `viewport` px: SCR-021's compact view. */
export function compactPanes(tree: DockTree, viewport: Size): Set<PaneId> {
  const rects = layoutRects(tree, viewport);
  const out = new Set<PaneId>();
  const visit = (node: DockNode): void => {
    if (node.type !== "leaf") return node.children.forEach(visit);
    const r = rects.get(node.id) as Rect;
    if (r.width < node.minWidth - OVERLAP_EPSILON || r.height < node.minHeight - OVERLAP_EPSILON) {
      out.add(node.paneId);
    }
  };
  if (tree.root !== null) visit(tree.root);
  return out;
}

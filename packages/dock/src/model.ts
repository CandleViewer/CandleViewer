/**
 * The dock tree (E15-T02; E15-D02 §4 D-5): n-ary `row` / `column` splits, `tabset`s holding
 * leaves, and `leaf`s. Every node has a stable `id`; a leaf carries the `paneId` its panel is keyed
 * by, so a layout operation is a re-parent of a leaf and never a new panel. The tree is immutable
 * and plain data (serialisable): every operation returns a new tree.
 *
 * The package knows a `kind` is a string and a minimum is a number, nothing more.
 */

export type NodeId = string;
export type PaneId = string;

export interface DockLeaf {
  readonly type: "leaf";
  readonly id: NodeId;
  readonly paneId: PaneId;
  readonly kind: string;
  /** Px below which the app shows the compact view (SCR-021). */
  readonly minWidth: number;
  readonly minHeight: number;
}

export interface DockSplit {
  readonly type: "row" | "column";
  readonly id: NodeId;
  readonly children: readonly DockNode[];
  /** Fractions of the container, one per child, summing to 1. */
  readonly sizes: readonly number[];
}

export interface DockTabset {
  readonly type: "tabset";
  readonly id: NodeId;
  readonly children: readonly DockLeaf[];
  /** Index of the visible tab. */
  readonly active: number;
}

export type DockNode = DockSplit | DockTabset | DockLeaf;

/**
 * A layout's working copy. Panes that no leaf names are kept as `floating` (popped out) or
 * `minimised` (the tray): client state, `22` `LayoutGridSpec` ("placed by the client").
 */
export interface DockTree {
  readonly root: DockNode | null;
  readonly floating: readonly DockLeaf[];
  readonly minimised: readonly DockLeaf[];
  /** The pane drawn alone over the dock, or null. */
  readonly maximised: PaneId | null;
}

/** `22` `LayoutGridSpec`: depth at most 6 counting the root, at most 64 nodes and 16 leaves. */
export const MAX_DEPTH = 6;
export const MAX_NODES = 64;
export const MAX_LEAVES = 16;
/** Tolerance on a `sizes` sum (`22` rule `sizes_sum`). */
export const SIZE_EPSILON = 1e-6;

export type Direction = "left" | "right" | "top" | "bottom";
/** Where a pane lands relative to a target: one of its four sides, or the centre (a tab). */
export type Zone = Direction | "centre";

export interface Size {
  readonly width: number;
  readonly height: number;
}

export interface Rect {
  readonly x: number;
  readonly y: number;
  readonly width: number;
  readonly height: number;
}

export const EMPTY_TREE: DockTree = Object.freeze({
  root: null,
  floating: Object.freeze([]),
  minimised: Object.freeze([]),
  maximised: null,
}) as DockTree;

/** Every leaf under `node`, in reading order (children order, depth first). */
export function leavesOf(node: DockNode | null): DockLeaf[] {
  if (node === null) return [];
  if (node.type === "leaf") return [node];
  const out: DockLeaf[] = [];
  for (const child of node.children) out.push(...leavesOf(child));
  return out;
}

/** The leaves of the tree in reading order: the dock first, then floating, then minimised. */
export function allLeaves(tree: DockTree): DockLeaf[] {
  return [...leavesOf(tree.root), ...tree.floating, ...tree.minimised];
}

/**
 * The node with `id`, or the leaf whose `paneId` is `id`, or null. Node ids and pane ids come from
 * one minter per dock (`fromLayout`, the app's store), so the two never collide.
 */
export function findNode(node: DockNode | null, id: string): DockNode | null {
  if (node === null) return null;
  if (node.id === id || (node.type === "leaf" && node.paneId === id)) return node;
  if (node.type === "leaf") return null;
  for (const child of node.children) {
    const hit = findNode(child, id);
    if (hit !== null) return hit;
  }
  return null;
}

export function countNodes(node: DockNode | null): number {
  if (node === null) return 0;
  if (node.type === "leaf") return 1;
  return node.children.reduce((n, child) => n + countNodes(child), 1);
}

export function depthOf(node: DockNode | null): number {
  if (node === null) return 0;
  if (node.type === "leaf") return 1;
  return 1 + Math.max(...node.children.map(depthOf));
}

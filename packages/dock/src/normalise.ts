/**
 * `normalise`: every operation's last step. Collapses single-child splits and one-tab tabsets
 * (BQ-11: the contract allows either, the tree keeps the simpler), removes empty containers, merges
 * a split into a parent of the same direction, renormalises `sizes` to sum to 1 and, given the
 * dock's size, keeps every panel at or above its minimum where the dock can hold them all. It then
 * enforces `22`'s caps, so a hostile tree is refused here rather than rendered.
 */
import { DockError } from "./errors.js";
import {
  MAX_DEPTH,
  MAX_LEAVES,
  MAX_NODES,
  allLeaves,
  countNodes,
  depthOf,
  leavesOf,
  type DockNode,
  type DockSplit,
  type DockTree,
  type Size,
} from "./model.js";

/** The smallest share a child keeps, so no stored size is 0 (`22`: each size in (0, 1]). */
export const MIN_FRACTION = 0.01;

function normaliseSizes(raw: readonly number[]): number[] {
  const clean = raw.map((s) => (Number.isFinite(s) && s > 0 ? s : 0));
  const total = clean.reduce((a, b) => a + b, 0);
  const shares = total > 0 ? clean.map((s) => s / total) : clean.map(() => 1 / clean.length);
  const floored = shares.map((s) => Math.max(s, MIN_FRACTION));
  const sum = floored.reduce((a, b) => a + b, 0);
  return floored.map((s) => s / sum);
}

function normaliseNode(node: DockNode): DockNode | null {
  if (node.type === "leaf") return node;
  if (node.type === "tabset") {
    if (node.children.length === 0) return null;
    if (node.children.length === 1) return node.children[0] ?? null;
    const active = Math.min(Math.max(Math.trunc(node.active) || 0, 0), node.children.length - 1);
    return { ...node, active };
  }
  const children: DockNode[] = [];
  const sizes: number[] = [];
  node.children.forEach((child, i) => {
    const share = node.sizes[i] ?? 0;
    const kept = normaliseNode(child);
    if (kept === null) return;
    if (kept.type === node.type) {
      // A row inside a row is one row: its children take shares of its share.
      kept.children.forEach((grandchild, j) => {
        children.push(grandchild);
        sizes.push(share * (kept.sizes[j] ?? 0));
      });
      return;
    }
    children.push(kept);
    sizes.push(share);
  });
  if (children.length === 0) return null;
  if (children.length === 1) return children[0] ?? null;
  return { type: node.type, id: node.id, children, sizes: normaliseSizes(sizes) };
}

/** The px a node needs along `axis` so none of its panels is below its minimum. */
export function minExtent(node: DockNode, axis: "row" | "column"): number {
  if (node.type === "leaf") return axis === "row" ? node.minWidth : node.minHeight;
  const extents = node.children.map((child) => minExtent(child, axis));
  return node.type === axis ? extents.reduce((a, b) => a + b, 0) : Math.max(0, ...extents);
}

/** Raises a split's sizes to its children's minimums, taking the px from children above theirs. */
function fitSplit(node: DockSplit, size: Size): DockSplit {
  const px = node.type === "row" ? size.width : size.height;
  const raw = node.children.map((child) => (px > 0 ? minExtent(child, node.type) / px : 1));
  const rawTotal = raw.reduce((a, b) => a + b, 0);
  // A parent fitted to exactly this split's minimum hands it that px give or take a rounding
  // error, so a total within 1e-9 of the whole still fits (scaled to sum to 1).
  const fits = rawTotal <= 1 + 1e-9;
  const mins = rawTotal > 1 && fits ? raw.map((m) => m / rawTotal) : raw;
  let sizes = [...node.sizes];
  if (fits) {
    // Fix the children below their minimum, share what is left among the others by their sizes;
    // fixing one can push another below its own, so repeat (at most once per child).
    const fixed = new Set<number>();
    for (let pass = 0; pass < sizes.length; pass += 1) {
      const below = sizes.findIndex((s, i) => !fixed.has(i) && s < (mins[i] ?? 0) - 1e-12);
      if (below === -1) break;
      for (let i = 0; i < sizes.length; i += 1) {
        if (!fixed.has(i) && (sizes[i] ?? 0) < (mins[i] ?? 0)) fixed.add(i);
      }
      const free = 1 - [...fixed].reduce((a, i) => a + (mins[i] ?? 0), 0);
      const rest = sizes.reduce((a, s, i) => (fixed.has(i) ? a : a + s), 0);
      sizes = sizes.map((s, i) =>
        fixed.has(i) ? (mins[i] ?? 0) : rest > 0 ? (s / rest) * free : 0,
      );
    }
  }
  // Below a minimum only when the dock cannot hold every minimum: the app shows the compact view.
  const children = node.children.map((child, i) => {
    const share = sizes[i] ?? 0;
    const childSize =
      node.type === "row"
        ? { width: size.width * share, height: size.height }
        : { width: size.width, height: size.height * share };
    return fitMinimums(child, childSize);
  });
  return { ...node, children, sizes };
}

/** Applies the panels' minimums for a dock of `size` px (no-op on a leaf or a tabset). */
export function fitMinimums(node: DockNode, size: Size): DockNode {
  return node.type === "row" || node.type === "column" ? fitSplit(node, size) : node;
}

/** Throws the `22` rule a tree breaks: depth, node and leaf caps, and a pane named twice. */
export function assertCaps(tree: DockTree): void {
  if (depthOf(tree.root) > MAX_DEPTH) {
    throw new DockError("tree_too_deep", `the tree is deeper than ${MAX_DEPTH} levels`);
  }
  if (countNodes(tree.root) > MAX_NODES) {
    throw new DockError("tree_too_large", `the tree has more than ${MAX_NODES} nodes`);
  }
  const panes = allLeaves(tree).map((leaf) => leaf.paneId);
  if (panes.length > MAX_LEAVES) {
    throw new DockError("tree_too_large", `the layout has more than ${MAX_LEAVES} panes`);
  }
  if (new Set(panes).size !== panes.length) {
    throw new DockError("duplicate_leaf", "a pane appears twice in the layout");
  }
}

/**
 * The normal form of `tree`: no single-child container, no empty or one-tab tabset, every `sizes`
 * summing to 1, and, with `viewport`, no panel below its minimum where the dock can hold them all.
 * A `maximised` pane that is not in the dock is cleared. Throws `DockError` on a cap.
 */
export function normalise(tree: DockTree, viewport?: Size): DockTree {
  let root = tree.root === null ? null : normaliseNode(tree.root);
  if (root !== null && viewport !== undefined) root = fitMinimums(root, viewport);
  const docked = new Set(leavesOf(root).map((leaf) => leaf.paneId));
  const maximised = tree.maximised !== null && docked.has(tree.maximised) ? tree.maximised : null;
  const next: DockTree = { root, floating: tree.floating, minimised: tree.minimised, maximised };
  assertCaps(next);
  return next;
}

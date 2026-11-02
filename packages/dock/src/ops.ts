/**
 * The layout operations (E15-T02 scope). Each returns a new, normalised tree and never mutates its
 * input. A move takes the leaf object itself (same `id`, same `paneId`) to its new parent: the app
 * keys panels by `paneId`, so every operation is a re-parent and none recreates a panel.
 */
import { DockError } from "./errors.js";
import type { IdMinter } from "./ids.js";
import {
  allLeaves,
  findNode,
  leavesOf,
  type Direction,
  type DockLeaf,
  type DockNode,
  type DockTree,
  type PaneId,
  type Size,
  type Zone,
} from "./model.js";
import { MIN_FRACTION, assertCaps, normalise } from "./normalise.js";
import { PRESET_CELLS, presetToTree, type NamedPreset } from "./presets.js";

export interface OpContext {
  readonly mint: IdMinter;
  /** The dock's px size: with it, every result keeps panels at their minimums where it can. */
  readonly viewport?: Size;
}

/** `{splitId}/{index}`: the separator after child `index` of a split. */
export function separatorId(splitId: string, index: number): string {
  return `${splitId}/${index}`;
}

function done(tree: DockTree, ctx: OpContext): DockTree {
  return normalise(tree, ctx.viewport);
}

/** The tree without the leaf of `paneId` (not normalised), and that leaf. */
function detach(root: DockNode | null, paneId: PaneId): { root: DockNode | null; leaf: DockLeaf } {
  let found: DockLeaf | null = null;
  const walk = (node: DockNode): DockNode | null => {
    if (node.type === "leaf") {
      if (node.paneId !== paneId) return node;
      found = node;
      return null;
    }
    if (node.type === "tabset") {
      const index = node.children.findIndex((leaf) => leaf.paneId === paneId);
      if (index === -1) return node;
      found = node.children[index] ?? null;
      const children = node.children.filter((_, i) => i !== index);
      const active = node.active > index ? node.active - 1 : node.active;
      return { ...node, children, active: Math.min(active, children.length - 1) };
    }
    const kept = node.children.map(walk);
    return {
      ...node,
      children: kept.filter((child): child is DockNode => child !== null),
      sizes: node.sizes.filter((_, i) => kept[i] !== null),
    };
  };
  const next = root === null ? null : walk(root);
  if (found === null) throw new DockError("unknown_target", `no docked pane ${paneId}`);
  return { root: next, leaf: found };
}

/** The tabset holding `target` when it is a tab, else `target` itself: a tab is never split. */
function placement(root: DockNode, targetId: string): DockNode {
  const target = findNode(root, targetId);
  if (target === null) throw new DockError("unknown_target", `no node ${targetId}`);
  if (target.type !== "leaf") return target;
  const holder = (node: DockNode): DockNode | null => {
    if (node.type === "leaf") return null;
    if (node.type === "tabset") return node.children.includes(target) ? node : null;
    for (const child of node.children) {
      const hit = holder(child);
      if (hit !== null) return hit;
    }
    return null;
  };
  return holder(root) ?? target;
}

function replace(node: DockNode, id: string, next: DockNode): DockNode {
  if (node.id === id) return next;
  if (node.type === "leaf") return node;
  if (node.type === "tabset") return node;
  return { ...node, children: node.children.map((child) => replace(child, id, next)) };
}

/** `leaf` placed at `zone` of `targetId` (not normalised). */
function attach(
  root: DockNode | null,
  targetId: string,
  zone: Zone,
  leaf: DockLeaf,
  mint: IdMinter,
): DockNode {
  if (root === null) return leaf;
  const target = placement(root, targetId);
  let next: DockNode;
  if (zone === "centre") {
    if (target.type !== "leaf" && target.type !== "tabset") {
      throw new DockError("invalid_operation", "a pane can only become a tab of a panel");
    }
    const tabs: DockLeaf[] =
      target.type === "tabset" ? [...target.children, leaf] : [target as DockLeaf, leaf];
    // The moved pane is the active tab (E15-D15 FM-03).
    next = {
      type: "tabset",
      id: target.type === "tabset" ? target.id : mint(),
      children: tabs,
      active: tabs.length - 1,
    };
  } else {
    const type = zone === "left" || zone === "right" ? "row" : "column";
    const first = zone === "left" || zone === "top";
    next = {
      type,
      id: mint(),
      children: first ? [leaf, target] : [target, leaf],
      sizes: [0.5, 0.5],
    };
  }
  return replace(root, target.id, next);
}

/** Splits `targetId` (a node id or a pane id) with `newLeaf` on its `direction` side. */
export function split(
  tree: DockTree,
  targetId: string,
  direction: Direction,
  newLeaf: DockLeaf,
  ctx: OpContext,
): DockTree {
  if (allLeaves(tree).some((leaf) => leaf.paneId === newLeaf.paneId)) {
    throw new DockError("duplicate_leaf", `pane ${newLeaf.paneId} is already in the layout`);
  }
  return done({ ...tree, root: attach(tree.root, targetId, direction, newLeaf, ctx.mint) }, ctx);
}

/** Moves the pane to `zone` of `targetId`; the leaf object is kept, so the panel is re-parented. */
export function move(
  tree: DockTree,
  paneId: PaneId,
  targetId: string,
  zone: Zone,
  ctx: OpContext,
): DockTree {
  const target = tree.root === null ? null : findNode(tree.root, targetId);
  if (target === null) throw new DockError("unknown_target", `no node ${targetId}`);
  if (target.type === "leaf" && target.paneId === paneId) return tree;
  const { root, leaf } = detach(tree.root, paneId);
  return done({ ...tree, root: attach(root, target.id, zone, leaf, ctx.mint) }, ctx);
}

/** Makes the pane a tab of `targetId` (a panel or a tab group). */
export function tabify(tree: DockTree, paneId: PaneId, targetId: string, ctx: OpContext): DockTree {
  return move(tree, paneId, targetId, "centre", ctx);
}

/** Removes the pane from the layout, docked, floating or minimised. */
export function close(tree: DockTree, paneId: PaneId, ctx: OpContext): DockTree {
  const floating = tree.floating.filter((leaf) => leaf.paneId !== paneId);
  const minimised = tree.minimised.filter((leaf) => leaf.paneId !== paneId);
  if (floating.length !== tree.floating.length || minimised.length !== tree.minimised.length) {
    return done({ ...tree, floating, minimised }, ctx);
  }
  return done({ ...tree, root: detach(tree.root, paneId).root }, ctx);
}

/** Moves the separator `{splitId}/{index}` by `delta`, a fraction of the split (+ grows `index`). */
export function resize(tree: DockTree, separator: string, delta: number, ctx: OpContext): DockTree {
  const cut = separator.lastIndexOf("/");
  const splitId = separator.slice(0, cut);
  const index = Number(separator.slice(cut + 1));
  const node = tree.root === null ? null : findNode(tree.root, splitId);
  if (
    node === null ||
    (node.type !== "row" && node.type !== "column") ||
    !Number.isInteger(index) ||
    index < 0 ||
    index >= node.children.length - 1
  ) {
    throw new DockError("unknown_target", `no separator ${separator}`);
  }
  const a = node.sizes[index] ?? 0;
  const b = node.sizes[index + 1] ?? 0;
  const d = Math.min(
    Math.max(Number.isFinite(delta) ? delta : 0, MIN_FRACTION - a),
    b - MIN_FRACTION,
  );
  const sizes = node.sizes.map((s, i) => (i === index ? a + d : i === index + 1 ? b - d : s));
  return done({ ...tree, root: replace(tree.root as DockNode, node.id, { ...node, sizes }) }, ctx);
}

/** Equal sizes for every child of a split (CMP-083 `Home`, CMP-216 "Equal sizes"). */
export function equalise(tree: DockTree, splitId: string, ctx: OpContext): DockTree {
  const node = tree.root === null ? null : findNode(tree.root, splitId);
  if (node === null || (node.type !== "row" && node.type !== "column")) {
    throw new DockError("unknown_target", `no split ${splitId}`);
  }
  const sizes = node.children.map(() => 1 / node.children.length);
  return done({ ...tree, root: replace(tree.root as DockNode, node.id, { ...node, sizes }) }, ctx);
}

/** Shows the tab at `index` of a tab group. */
export function activateTab(
  tree: DockTree,
  tabsetId: string,
  index: number,
  ctx: OpContext,
): DockTree {
  const node = tree.root === null ? null : findNode(tree.root, tabsetId);
  if (node === null || node.type !== "tabset") {
    throw new DockError("unknown_target", `no tab group ${tabsetId}`);
  }
  return done(
    { ...tree, root: replace(tree.root as DockNode, node.id, { ...node, active: index }) },
    ctx,
  );
}

function docked(tree: DockTree, paneId: PaneId): void {
  if (!leavesOf(tree.root).some((leaf) => leaf.paneId === paneId)) {
    throw new DockError("unknown_target", `no docked pane ${paneId}`);
  }
}

export function maximise(tree: DockTree, paneId: PaneId, ctx: OpContext): DockTree {
  docked(tree, paneId);
  return done({ ...tree, maximised: paneId }, ctx);
}

export function restore(tree: DockTree, ctx: OpContext): DockTree {
  return done({ ...tree, maximised: null }, ctx);
}

/** Pops the pane out of the dock (its window is E15-S02's); the leaf is kept for `redock`. */
export function float(tree: DockTree, paneId: PaneId, ctx: OpContext): DockTree {
  const { root, leaf } = detach(tree.root, paneId);
  return done({ ...tree, root, floating: [...tree.floating, leaf] }, ctx);
}

/** Returns a floating or minimised pane to the dock, at `zone` of `targetId` (default: right). */
export function redock(
  tree: DockTree,
  paneId: PaneId,
  ctx: OpContext,
  target?: { readonly targetId: string; readonly zone: Zone },
): DockTree {
  const leaf = [...tree.floating, ...tree.minimised].find((l) => l.paneId === paneId);
  if (leaf === undefined) throw new DockError("unknown_target", `no undocked pane ${paneId}`);
  const rest = {
    floating: tree.floating.filter((l) => l !== leaf),
    minimised: tree.minimised.filter((l) => l !== leaf),
  };
  const at = target ?? { targetId: tree.root?.id ?? "", zone: "right" as const };
  return done(
    { ...tree, ...rest, root: attach(tree.root, at.targetId, at.zone, leaf, ctx.mint) },
    ctx,
  );
}

/**
 * The named preset over the existing panes: the docked panes in reading order, then the
 * minimised ones, fill the cells, so the same leaves (and panels) are reused; panes beyond the
 * cells are minimised; missing cells come from `makeLeaf`, or the preset is refused.
 */
export function applyPreset(
  tree: DockTree,
  preset: NamedPreset,
  ctx: OpContext & { readonly makeLeaf?: (cell: number) => DockLeaf },
): DockTree {
  const cells = PRESET_CELLS[preset];
  const pool = [...leavesOf(tree.root), ...tree.minimised];
  const used = pool.slice(0, cells);
  for (let cell = used.length; cell < cells; cell += 1) {
    if (ctx.makeLeaf === undefined) {
      throw new DockError("invalid_operation", `preset ${preset} needs ${cells} panes`);
    }
    used.push(ctx.makeLeaf(cell));
  }
  const next: DockTree = {
    root: presetToTree(preset, used, ctx.mint),
    floating: tree.floating,
    minimised: pool.slice(cells),
    maximised: null,
  };
  assertCaps(next);
  return done(next, ctx);
}

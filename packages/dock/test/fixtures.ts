import fc from "fast-check";
import {
  EMPTY_TREE,
  counterMinter,
  leavesOf,
  normalise,
  presetToTree,
  type DockLeaf,
  type DockNode,
  type DockSplit,
  type DockTree,
  type NamedPreset,
  type OpContext,
} from "../src/index.js";

export const VIEWPORT = { width: 1920, height: 1080 } as const;

/** A leaf whose node id is derived from its pane id, so tests read naturally. */
export function leaf(paneId: string, minWidth = 80, minHeight = 40): DockLeaf {
  return { type: "leaf", id: `leaf-${paneId}`, paneId, kind: "chart", minWidth, minHeight };
}

export function ctx(viewport = true): OpContext {
  return viewport
    ? { mint: counterMinter("node-n"), viewport: VIEWPORT }
    : { mint: counterMinter("node-n") };
}

export function treeOf(root: DockNode | null): DockTree {
  return normalise({ ...EMPTY_TREE, root });
}

export function preset(name: NamedPreset, panes: readonly string[]): DockTree {
  return treeOf(
    presetToTree(
      name,
      panes.map((p) => leaf(p)),
      counterMinter("node-p"),
    ),
  );
}

/** The arrangement with ids removed: what "structurally identical" compares. */
export function shape(node: DockNode | null): unknown {
  if (node === null) return null;
  if (node.type === "leaf") return { pane: node.paneId };
  if (node.type === "tabset") return { tabs: node.children.map(shape), active: node.active };
  return {
    [node.type]: node.children.map(shape),
    sizes: node.sizes.map((s) => Math.round(s * 1e6) / 1e6),
  };
}

export function paneIds(tree: DockTree): string[] {
  return [...leavesOf(tree.root), ...tree.floating, ...tree.minimised].map((l) => l.paneId).sort();
}

/** The invariants every operation's result holds (Gherkin "Every operation returns a normalised tree"). */
export function invariantViolations(tree: DockTree): string[] {
  const out: string[] = [];
  const ids = new Set<string>();
  const visit = (node: DockNode): void => {
    if (ids.has(node.id)) out.push(`node id ${node.id} twice`);
    ids.add(node.id);
    if (node.type === "leaf") return;
    if (node.children.length < 2)
      out.push(`${node.type} ${node.id} has ${node.children.length} child`);
    if (node.type === "tabset") return;
    const sum = node.sizes.reduce((a, b) => a + b, 0);
    if (Math.abs(sum - 1) > 1e-6) out.push(`${node.id} sizes sum ${sum}`);
    if (node.sizes.length !== node.children.length) out.push(`${node.id} sizes mismatch`);
    node.children.forEach(visit);
  };
  if (tree.root !== null) visit(tree.root);
  return out;
}

/** An arbitrary 1..16-pane preset tree with leaf minimums small enough for the viewport. */
export const arbPresetTree = fc
  .constantFrom<NamedPreset>("1x1", "2x1", "1x2", "2x2", "1+3", "3x3")
  .map((name) => {
    const cells = { "1x1": 1, "2x1": 2, "1x2": 2, "2x2": 4, "1+3": 4, "3x3": 9 }[name];
    return preset(
      name,
      Array.from({ length: cells }, (_, i) => `p${i}`),
    );
  });

/** `node` as a split, failing the test when it is not one. */
export function asSplit(node: DockNode | null | undefined): DockSplit {
  if (node?.type !== "row" && node?.type !== "column") throw new Error("not a split");
  return node;
}

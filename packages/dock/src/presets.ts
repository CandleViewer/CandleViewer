/**
 * The named grids of `lay_preset` (`21` §3.8.1; `22` `LayoutGridPreset`) as trees, and the reverse
 * match. Cells fill in row-major reading order; 1+3 is the large cell left at 0.6 with three equal
 * rows right (E15-D02 §4 tree (b), D-6, G-04).
 */
import { DockError } from "./errors.js";
import type { IdMinter } from "./ids.js";
import { SIZE_EPSILON, leavesOf, type DockLeaf, type DockNode, type DockTree } from "./model.js";

export type NamedPreset = "1x1" | "2x1" | "1x2" | "2x2" | "1+3" | "3x3";
export type Preset = NamedPreset | "custom";

export const PRESET_CELLS: Readonly<Record<NamedPreset, number>> = Object.freeze({
  "1x1": 1,
  "2x1": 2,
  "1x2": 2,
  "2x2": 4,
  "1+3": 4,
  "3x3": 9,
});

export const NAMED_PRESETS = Object.keys(PRESET_CELLS) as NamedPreset[];

const THIRD = 1 / 3;

/** The tree of a named preset holding `leaves` (exactly its cell count), new ids from `mint`. */
export function presetToTree(
  preset: NamedPreset,
  leaves: readonly DockLeaf[],
  mint: IdMinter,
): DockNode {
  const cells = PRESET_CELLS[preset];
  if (leaves.length !== cells) {
    throw new DockError(
      "invalid_operation",
      `preset ${preset} holds ${cells} panes, not ${leaves.length}`,
    );
  }
  const at = (i: number): DockLeaf => leaves[i] as DockLeaf; // length checked above
  const split = (
    type: "row" | "column",
    children: DockNode[],
    sizes = children.map(() => 1 / children.length),
  ): DockNode => ({ type, id: mint(), children, sizes });
  switch (preset) {
    case "1x1":
      return at(0);
    case "2x1":
      return split("row", [at(0), at(1)]);
    case "1x2":
      return split("column", [at(0), at(1)]);
    case "2x2":
      return split("column", [split("row", [at(0), at(1)]), split("row", [at(2), at(3)])]);
    case "1+3":
      return split(
        "row",
        [at(0), split("column", [at(1), at(2), at(3)], [THIRD, THIRD, THIRD])],
        [0.6, 0.4],
      );
    case "3x3":
      return split(
        "column",
        [0, 3, 6].map((r) => split("row", [at(r), at(r + 1), at(r + 2)])),
      );
  }
}

/** Same shape: types, child counts, sizes within 1e-6 and the same panes, ids ignored. */
export function sameShape(a: DockNode, b: DockNode): boolean {
  if (a.type !== b.type) return false;
  if (a.type === "leaf") return b.type === "leaf" && a.paneId === b.paneId;
  if (b.type === "leaf" || a.children.length !== b.children.length) return false;
  const other = (i: number): DockNode => b.children[i] as DockNode; // lengths equal
  if (a.type === "tabset" || b.type === "tabset") {
    return (
      a.type === "tabset" &&
      b.type === "tabset" &&
      a.active === b.active &&
      a.children.every((child, i) => sameShape(child, other(i)))
    );
  }
  return a.children.every(
    (child, i) =>
      Math.abs((a.sizes[i] ?? 0) - (b.sizes[i] ?? 0)) <= SIZE_EPSILON && sameShape(child, other(i)),
  );
}

/** The named preset the docked tree is, or `custom`. An empty dock is `1x1`, its stored form. */
export function matchPreset(tree: DockTree): Preset {
  if (tree.root === null) return "1x1";
  const leaves = leavesOf(tree.root);
  const mint = (): string => "";
  for (const preset of NAMED_PRESETS) {
    if (PRESET_CELLS[preset] !== leaves.length) continue;
    if (sameShape(tree.root, presetToTree(preset, leaves, mint))) return preset;
  }
  return "custom";
}

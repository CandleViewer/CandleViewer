/**
 * The tree against `22-api-openapi.yaml`: `toLayoutInput` writes the three `LayoutInput` fields a
 * layout's arrangement is (`grid_preset`, `grid_spec`, `panes`, E15-D02 §4 D-5) and `fromLayout`
 * reads them back from a `Layout` or a `LayoutInput`. Node ids, pane ids and minimums are client
 * state: they are stripped on write and re-minted on read (BQ-03: no contract change).
 *
 * `fromLayout` is the trust boundary for a stored or imported layout (E15-S07): it checks the
 * `LayoutGridSpec` rules with bounded recursion, and refuses a pane kind the caller does not know,
 * so a tampered layout cannot name an arbitrary component or recurse without bound.
 */
import type { generated } from "@candleviewer/protocol";
import { DockError, type DockErrorCode } from "./errors.js";
import type { IdMinter } from "./ids.js";
import {
  MAX_DEPTH,
  MAX_LEAVES,
  MAX_NODES,
  SIZE_EPSILON,
  leavesOf,
  type DockLeaf,
  type DockNode,
  type DockTree,
  type PaneId,
} from "./model.js";
import { normalise } from "./normalise.js";
import {
  NAMED_PRESETS,
  PRESET_CELLS,
  matchPreset,
  presetToTree,
  type NamedPreset,
} from "./presets.js";

type Schemas = generated.rest.components["schemas"];
export type GridSpec = Schemas["LayoutGridSpec"];
export type GridNode = Schemas["LayoutGridNode"];
export type LayoutPaneInput = Schemas["LayoutPaneInput"];
/** A pane's stored fields beyond its slot and kind: what the app keeps per pane. */
export type PaneFields = Omit<LayoutPaneInput, "slot_index" | "pane_kind">;
/** The arrangement half of `LayoutInput`; the caller adds `name` and the rest. */
export type LayoutArrangement = Pick<Schemas["LayoutInput"], "grid_preset" | "grid_spec"> & {
  panes: LayoutPaneInput[];
};
/** What `fromLayout` reads: a `Layout` or a `LayoutInput` (its panes, keyed by slot). */
export interface StoredArrangement {
  readonly grid_preset: Schemas["LayoutGridPreset"];
  readonly grid_spec: GridSpec | null;
  readonly panes: readonly (LayoutPaneInput | Schemas["LayoutPane"])[];
}

const EMPTY_PANE: PaneFields = {
  symbol: null,
  interval_code: null,
  chart_template_id: null,
  scale_mode: "auto",
};

function strip(node: DockNode, slots: ReadonlyMap<PaneId, number>): GridNode {
  const leaf = (l: DockLeaf): Schemas["LayoutGridLeaf"] => ({
    type: "leaf",
    slot: slots.get(l.paneId) ?? 0,
  });
  if (node.type === "leaf") return leaf(node);
  if (node.type === "tabset") {
    return { type: "tabset", active: node.active, children: node.children.map(leaf) };
  }
  return {
    type: node.type,
    sizes: [...node.sizes],
    children: node.children.map((child) => strip(child, slots)),
  };
}

/**
 * `slot_index` is reading order (the dock, then floating, then minimised), so unique and within
 * 0..15; a named grid stores `grid_spec: null`. A layout with no pane at all stores as the default
 * `1x1` with no panes, which `fromLayout` reads back as nothing docked; panes with none docked are
 * refused (`empty_dock`): `22` has no form for them. `panes` supplies each pane's stored fields; its
 * `pane_kind` is the leaf's `kind`, which the app took from its registry.
 */
export function toLayoutInput(
  tree: DockTree,
  panes: ReadonlyMap<PaneId, PaneFields>,
): LayoutArrangement {
  const ordered = [...leavesOf(tree.root), ...tree.floating, ...tree.minimised];
  if (ordered.length > MAX_LEAVES) {
    throw new DockError("tree_too_large", `the layout has more than ${MAX_LEAVES} panes`);
  }
  if (tree.root === null) {
    if (ordered.length > 0) {
      throw new DockError("empty_dock", "a layout with panes must dock at least one of them");
    }
    return { grid_preset: "1x1", grid_spec: null, panes: [] };
  }
  const slots = new Map(ordered.map((leaf, i) => [leaf.paneId, i] as const));
  const preset = matchPreset(tree);
  return {
    grid_preset: preset,
    grid_spec: preset === "custom" ? { version: 1, root: strip(tree.root, slots) } : null,
    panes: ordered.map((leaf, i) => ({
      ...EMPTY_PANE,
      ...panes.get(leaf.paneId),
      slot_index: i,
      // The kind came from the app's registry, which only holds `PaneKind` values.
      pane_kind: leaf.kind as Schemas["PaneKind"],
    })),
  };
}

export interface GridIssue {
  readonly rule: DockErrorCode;
  /** Field path under `grid_spec`, as the API reports it. */
  readonly path: string;
}

const isObject = (v: unknown): v is Record<string, unknown> =>
  typeof v === "object" && v !== null && !Array.isArray(v);
const keysWithin = (v: Record<string, unknown>, allowed: readonly string[]): boolean =>
  Object.keys(v).every((k) => allowed.includes(k));

/**
 * The first `22` `LayoutGridSpec` rule `spec` breaks, or null. Descent stops at depth 7 and node 65,
 * so a hostile spec costs at most that much work.
 */
export function validateGridSpec(spec: unknown, slots: ReadonlySet<number>): GridIssue | null {
  if (!isObject(spec) || spec["version"] !== 1 || !keysWithin(spec, ["version", "root"])) {
    return { rule: "invalid_node", path: "" };
  }
  let nodes = 0;
  let leaves = 0;
  const seen = new Set<number>();
  const visit = (node: unknown, path: string, depth: number): GridIssue | null => {
    if (depth > MAX_DEPTH) return { rule: "tree_too_deep", path };
    nodes += 1;
    if (nodes > MAX_NODES) return { rule: "tree_too_large", path };
    if (!isObject(node)) return { rule: "invalid_node", path };
    const type = node["type"];
    if (type === "leaf") {
      const slot = node["slot"];
      if (!keysWithin(node, ["type", "slot"]) || !Number.isInteger(slot)) {
        return { rule: "invalid_node", path };
      }
      leaves += 1;
      if (leaves > MAX_LEAVES) return { rule: "tree_too_large", path };
      if (!slots.has(slot as number)) return { rule: "unknown_slot", path: `${path}.slot` };
      if (seen.has(slot as number)) return { rule: "duplicate_leaf", path: `${path}.slot` };
      seen.add(slot as number);
      return null;
    }
    const children = node["children"];
    if (!Array.isArray(children) || children.length > 16) return { rule: "invalid_node", path };
    if (type === "tabset") {
      const active = node["active"] ?? 0;
      if (!keysWithin(node, ["type", "children", "active"]) || children.length < 1) {
        return { rule: "invalid_node", path };
      }
      for (const [i, child] of children.entries()) {
        if (!isObject(child) || child["type"] !== "leaf") {
          return { rule: "invalid_node", path: `${path}.children.${i}` };
        }
        const issue = visit(child, `${path}.children.${i}`, depth + 1);
        if (issue !== null) return issue;
      }
      if (
        !Number.isInteger(active) ||
        (active as number) < 0 ||
        (active as number) >= children.length
      ) {
        return { rule: "active_out_of_range", path: `${path}.active` };
      }
      return null;
    }
    if (type !== "row" && type !== "column") return { rule: "invalid_node", path };
    const sizes = node["sizes"];
    if (!keysWithin(node, ["type", "children", "sizes"]) || children.length < 2) {
      return { rule: "invalid_node", path };
    }
    if (!Array.isArray(sizes) || sizes.length !== children.length) {
      return { rule: "sizes_mismatch", path: `${path}.sizes` };
    }
    const valid = sizes.every((s) => typeof s === "number" && s > 0 && s <= 1);
    const sum = valid ? (sizes as number[]).reduce((a, b) => a + b, 0) : NaN;
    if (!(Math.abs(sum - 1) <= SIZE_EPSILON)) return { rule: "sizes_sum", path: `${path}.sizes` };
    for (const [i, child] of children.entries()) {
      const issue = visit(child, `${path}.children.${i}`, depth + 1);
      if (issue !== null) return issue;
    }
    return null;
  };
  const issue = visit(spec["root"], "root", 1);
  return issue === null ? null : { rule: issue.rule, path: issue.path };
}

export interface ReadContext {
  readonly mint: IdMinter;
  /** A kind's minimums, or null for a kind the app does not know (refused: `unknown_kind`). */
  readonly minimums: (kind: string) => { minWidth: number; minHeight: number } | null;
}

function build(node: GridNode, leafOf: (slot: number) => DockLeaf, mint: IdMinter): DockNode {
  if (node.type === "leaf") return leafOf(node.slot);
  if (node.type === "tabset") {
    return {
      type: "tabset",
      id: mint(),
      active: node.active,
      children: node.children.map((child) => leafOf(child.slot)),
    };
  }
  return {
    type: node.type,
    id: mint(),
    sizes: [...node.sizes],
    children: node.children.map((child) => build(child, leafOf, mint)),
  };
}

/**
 * The tree and the per-pane fields of a stored layout, with fresh ids. Panes no leaf names are
 * minimised; a named grid with fewer panes than cells lays them out as one row. A `grid_preset`
 * that is neither `custom` nor a named preset is refused (`unknown_preset`). Throws `DockError`.
 */
export function fromLayout(
  layout: StoredArrangement,
  ctx: ReadContext,
): { tree: DockTree; panes: Map<PaneId, PaneFields> } {
  if (layout.panes.length > MAX_LEAVES) {
    throw new DockError("tree_too_large", `the layout has more than ${MAX_LEAVES} panes`, "panes");
  }
  const bySlot = new Map<number, DockLeaf>();
  const panes = new Map<PaneId, PaneFields>();
  for (const [i, pane] of [...layout.panes].sort((a, b) => a.slot_index - b.slot_index).entries()) {
    const { slot_index: slot, pane_kind: kind, ...fields } = pane;
    // Stored values are untrusted and unbounded, so neither message echoes them; the path names
    // the pane.
    if (bySlot.has(slot)) throw new DockError("duplicate_slot", "a slot twice", `panes.${i}`);
    const min = ctx.minimums(kind);
    if (min === null) throw new DockError("unknown_kind", "an unknown pane kind", `panes.${i}`);
    const paneId = ctx.mint();
    bySlot.set(slot, { type: "leaf", id: ctx.mint(), paneId, kind, ...min });
    panes.set(paneId, fields);
  }
  const slots = [...bySlot.keys()];
  const used = new Set<number>();
  const leafOf = (slot: number): DockLeaf => {
    used.add(slot);
    return bySlot.get(slot) as DockLeaf; // validated: every leaf names a known slot
  };
  let root: DockNode | null = null;
  if (
    layout.grid_preset !== "custom" &&
    !NAMED_PRESETS.includes(layout.grid_preset as NamedPreset)
  ) {
    // A tampered or garbled preset is refused at the boundary, never read as "nothing docked".
    // The stored value is not echoed: it is untrusted and unbounded.
    throw new DockError("unknown_preset", "grid_preset is not a known preset", "grid_preset");
  }
  if (layout.grid_preset === "custom") {
    const issue = validateGridSpec(layout.grid_spec, new Set(slots));
    if (issue !== null) {
      throw new DockError(issue.rule, `grid_spec breaks rule ${issue.rule}`, issue.path);
    }
    root = build((layout.grid_spec as GridSpec).root, leafOf, ctx.mint);
  } else if (slots.length > 0) {
    const preset = layout.grid_preset as NamedPreset;
    const cells = slots.slice(0, PRESET_CELLS[preset]);
    root =
      cells.length === PRESET_CELLS[preset]
        ? presetToTree(preset, cells.map(leafOf), ctx.mint)
        : {
            type: "row",
            id: ctx.mint(),
            children: cells.map(leafOf),
            sizes: cells.map(() => 1 / cells.length),
          };
  }
  const minimised = slots
    .filter((slot) => !used.has(slot))
    .map((slot) => bySlot.get(slot) as DockLeaf);
  return { tree: normalise({ root, floating: [], minimised, maximised: null }), panes };
}

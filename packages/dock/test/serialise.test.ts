import { describe, expect, it } from "vitest";
import {
  DockError,
  counterMinter,
  fromLayout,
  leavesOf,
  toLayoutInput,
  validateGridSpec,
  type DockNode,
  type DockTree,
  type PaneFields,
  type ReadContext,
  type StoredArrangement,
} from "../src/index.js";
import { leaf, preset, shape, treeOf } from "./fixtures.js";

const KNOWN = new Set(["chart", "dom", "tape", "positions"]);
const read: ReadContext = {
  mint: counterMinter("r"),
  minimums: (kind) => (KNOWN.has(kind) ? { minWidth: 80, minHeight: 40 } : null),
};

/** A custom tree of 16 panes: a row of four columns of four, one of them a tab group. */
function sixteen(): DockTree {
  const column = (c: number): DockNode => ({
    type: "column",
    id: `c${c}`,
    sizes: [0.4, 0.2, 0.2, 0.2],
    children: [0, 1, 2, 3].map((r) => leaf(`p${c * 4 + r}`)),
  });
  const tabs: DockNode = {
    type: "tabset",
    id: "t",
    active: 1,
    children: [leaf("p12"), leaf("p13"), leaf("p14"), leaf("p15")],
  };
  return treeOf({
    type: "row",
    id: "root",
    sizes: [0.3, 0.3, 0.2, 0.2],
    children: [column(0), column(1), column(2), tabs],
  });
}

const code = (fn: () => unknown): string | null => {
  try {
    fn();
    return null;
  } catch (error) {
    return error instanceof DockError ? error.code : "other";
  }
};

describe("serialisation (Gherkin: Serialisation matches the stored schema)", () => {
  it("toLayoutInput of a custom 16-pane tree: unique slots 0..15, custom, a valid spec, and back", () => {
    const tree = sixteen();
    const fields = new Map<string, PaneFields>([
      [
        "p0",
        { symbol: "BTCUSDT", interval_code: "time:1", chart_template_id: null, scale_mode: "log" },
      ],
    ]);
    const out = toLayoutInput(tree, fields);
    const slots = out.panes.map((p) => p.slot_index);
    expect(new Set(slots).size).toBe(16);
    expect(Math.min(...slots)).toBe(0);
    expect(Math.max(...slots)).toBe(15);
    expect(out.grid_preset).toBe("custom");
    expect(validateGridSpec(out.grid_spec, new Set(slots))).toBeNull();
    expect(out.panes[0]).toMatchObject({
      slot_index: 0,
      pane_kind: "chart",
      symbol: "BTCUSDT",
      scale_mode: "log",
    });
    expect(out.panes[1]).toMatchObject({ symbol: null, scale_mode: "auto" });
    const back = fromLayout(out, read);
    // Structurally identical: the same arrangement, writing the same body again.
    const relabel = new Map(leavesOf(back.tree.root).map((l, i) => [l.paneId, `p${i}`]));
    const named = (n: unknown): unknown =>
      JSON.parse(JSON.stringify(n), (k, v) => (k === "pane" ? relabel.get(v) : v));
    expect(named(shape(back.tree.root))).toEqual(shape(tree.root));
    expect(toLayoutInput(back.tree, back.panes)).toEqual(out);
  });

  it("a named grid stores no spec; floating then minimised panes take the slots after the cells", () => {
    const tree = { ...preset("2x1", ["a", "b"]), floating: [leaf("f")], minimised: [leaf("m")] };
    const out = toLayoutInput(tree, new Map());
    expect(out).toMatchObject({ grid_preset: "2x1", grid_spec: null });
    expect(out.panes.map((p) => p.slot_index)).toEqual([0, 1, 2, 3]);
    const back = fromLayout(out, read).tree;
    expect(leavesOf(back.root)).toHaveLength(2);
    expect(back.minimised).toHaveLength(2);
  });

  it("reads a named grid short of panes as one row, and an empty grid as nothing docked", () => {
    const pane = (slot: number) => ({
      slot_index: slot,
      pane_kind: "chart" as const,
      symbol: null,
      interval_code: null,
      chart_template_id: null,
      scale_mode: "auto" as const,
    });
    expect(
      shape(
        fromLayout({ grid_preset: "2x2", grid_spec: null, panes: [pane(0), pane(3)] }, read).tree
          .root,
      ),
    ).toMatchObject({ row: [{}, {}] });
    expect(
      fromLayout({ grid_preset: "1x1", grid_spec: null, panes: [] }, read).tree.root,
    ).toBeNull();
  });

  it("fromLayout_unknownPreset_rejects: a preset neither custom nor named is refused, not minimised", () => {
    const pane = {
      slot_index: 0,
      pane_kind: "chart" as const,
      symbol: null,
      interval_code: null,
      chart_template_id: null,
      scale_mode: "auto" as const,
    };
    for (const grid_preset of ["4x4", "", "CUSTOM", null, 7]) {
      const odd = { grid_preset, grid_spec: null, panes: [pane] } as unknown as StoredArrangement;
      expect(() => fromLayout(odd, read)).toThrow(
        expect.objectContaining({ code: "unknown_preset", path: "grid_preset" }),
      );
    }
  });

  it("refuses more than 16 panes on write", () => {
    const tree = { ...sixteen(), minimised: [leaf("x")] };
    expect(code(() => toLayoutInput(tree, new Map()))).toBe("tree_too_large");
  });
});

describe("the import boundary (error paths, BQ-11)", () => {
  const pane = (slot: number, kind = "chart") => ({
    slot_index: slot,
    pane_kind: kind,
    symbol: null,
    interval_code: null,
    chart_template_id: null,
    scale_mode: "auto",
  });
  const custom = (root: unknown, panes = [pane(0), pane(1)]) =>
    ({
      grid_preset: "custom",
      grid_spec: { version: 1, root },
      panes,
    }) as unknown as StoredArrangement;
  const L = (slot: number) => ({ type: "leaf", slot });

  it("fromLayout_tooDeep_rejects: depth 7 is refused before it is walked further", () => {
    let node: unknown = L(0);
    for (let i = 0; i < 6; i += 1)
      node = { type: "row", sizes: [0.5, 0.5], children: [node, L(1)] };
    expect(code(() => fromLayout(custom(node), read))).toBe("tree_too_deep");
    let deep: unknown = L(0);
    for (let i = 0; i < 100_000; i += 1)
      deep = { type: "row", sizes: [0.5, 0.5], children: [deep, L(1)] };
    expect(validateGridSpec({ version: 1, root: deep }, new Set([0, 1]))?.rule).toBe(
      "tree_too_deep",
    );
  });

  it("fromLayout_unknownKind_rejects: a kind the registry does not know is never mounted", () => {
    expect(code(() => fromLayout(custom(L(0), [pane(0, "script")]), read))).toBe("unknown_kind");
  });

  it("toLayoutInput_17Panes_rejects and fromLayout refuses 17 panes or a slot twice", () => {
    const many = Array.from({ length: 17 }, (_, i) => pane(i % 16));
    expect(code(() => fromLayout(custom(L(0), many), read))).toBe("tree_too_large");
    expect(code(() => fromLayout(custom(L(0), [pane(0), pane(0)]), read))).toBe("duplicate_slot");
  });

  it.each([
    ["unknown_slot", L(7)],
    ["duplicate_leaf", { type: "row", sizes: [0.5, 0.5], children: [L(0), L(0)] }],
    ["sizes_mismatch", { type: "row", sizes: [1], children: [L(0), L(1)] }],
    ["sizes_sum", { type: "row", sizes: [0.5, 0.6], children: [L(0), L(1)] }],
    ["sizes_sum", { type: "row", sizes: [0, 1], children: [L(0), L(1)] }],
    ["active_out_of_range", { type: "tabset", active: 2, children: [L(0), L(1)] }],
    [
      "invalid_node",
      { type: "tabset", children: [{ type: "row", sizes: [0.5, 0.5], children: [L(0), L(1)] }] },
    ],
    ["invalid_node", { type: "tabset", children: [] }],
    ["invalid_node", { type: "row", sizes: [1], children: [L(0)] }],
    ["invalid_node", { type: "leaf", slot: 0, extra: true }],
    ["invalid_node", { type: "grid", children: [] }],
    ["invalid_node", "leaf"],
  ])("refuses rule %s", (rule, root) => {
    expect(code(() => fromLayout(custom(root), read))).toBe(rule);
  });

  it("refuses a missing or malformed spec, and more than 16 leaves", () => {
    expect(
      code(() => fromLayout({ grid_preset: "custom", grid_spec: null, panes: [] }, read)),
    ).toBe("invalid_node");
    const wide = (n: number, child: (i: number) => unknown) => ({
      type: "row",
      sizes: Array(n).fill(1 / n),
      children: Array.from({ length: n }, (_, i) => child(i)),
    });
    const slots = new Set(Array.from({ length: 16 }, (_, i) => i));
    const tabs = (i: number) => ({
      type: "tabset",
      children: [0, 1, 2, 3].map((j) => L(i * 4 + j)),
    });
    const single = (i: number) => ({ type: "tabset", children: [L(i)] });
    expect(validateGridSpec({ version: 1, root: wide(16, single) }, slots)).toBeNull();
    expect(
      validateGridSpec(
        { version: 1, root: wide(5, tabs) },
        new Set(Array.from({ length: 20 }, (_, i) => i)),
      )?.rule,
    ).toBe("tree_too_large");
  });
});

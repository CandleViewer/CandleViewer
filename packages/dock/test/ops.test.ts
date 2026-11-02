import { describe, expect, it } from "vitest";
import {
  EMPTY_TREE,
  activateTab,
  allLeaves,
  close,
  compactPanes,
  equalise,
  counterMinter,
  float,
  isDockError,
  maximise,
  move,
  normalise,
  redock,
  resize,
  restore,
  separatorId,
  split,
  tabify,
  type DockNode,
  type DockTree,
} from "../src/index.js";
import { VIEWPORT, asSplit, ctx, leaf, preset, shape, treeOf } from "./fixtures.js";

const code = (fn: () => unknown): string | null => {
  try {
    fn();
    return null;
  } catch (error) {
    return isDockError(error) ? error.code : "not a DockError";
  }
};

describe("normalise", () => {
  it("collapses single-child splits and one-tab tabsets, merges same-direction splits", () => {
    const root: DockNode = {
      type: "row",
      id: "r",
      sizes: [2, 2],
      children: [
        { type: "row", id: "inner", sizes: [0.5, 0.5], children: [leaf("a"), leaf("b")] },
        {
          type: "column",
          id: "c",
          sizes: [1],
          children: [{ type: "tabset", id: "t", active: 4, children: [leaf("c")] }],
        },
      ],
    };
    expect(shape(treeOf(root).root)).toEqual({
      row: [{ pane: "a" }, { pane: "b" }, { pane: "c" }],
      sizes: [0.25, 0.25, 0.5],
    });
  });

  it("removes empty containers and clamps a tab group's active index", () => {
    const empty: DockNode = { type: "tabset", id: "t", active: 0, children: [] };
    expect(
      treeOf({ type: "row", id: "r", sizes: [1, 1], children: [empty, empty] }).root,
    ).toBeNull();
    const tabs = treeOf({ type: "tabset", id: "t", active: 9, children: [leaf("a"), leaf("b")] });
    expect(tabs.root).toMatchObject({ active: 1 });
  });

  it("gives every share a floor and equal shares when the stored ones are unusable", () => {
    const tree = treeOf({
      type: "row",
      id: "r",
      sizes: [Number.NaN, -1],
      children: [leaf("a"), leaf("b")],
    });
    expect(tree.root).toMatchObject({ sizes: [0.5, 0.5] });
    const tiny = treeOf({ type: "row", id: "r", sizes: [1, 0], children: [leaf("a"), leaf("b")] });
    expect(asSplit(tiny.root).sizes[1]).toBeGreaterThan(0);
  });

  it("raises a panel to its minimum when the dock can hold every minimum", () => {
    const root: DockNode = {
      type: "row",
      id: "r",
      sizes: [0.99, 0.01],
      children: [leaf("a"), leaf("b", 400)],
    };
    const tree = normalise({ ...EMPTY_TREE, root }, VIEWPORT);
    expect(compactPanes(tree, VIEWPORT).size).toBe(0);
    // A dock smaller than the minimums keeps the sizes and reports the compact view (SCR-021).
    expect([
      ...compactPanes(normalise({ ...EMPTY_TREE, root }, { width: 300, height: 300 }), {
        width: 300,
        height: 300,
      }),
    ]).toEqual(["b"]);
  });

  it("refuses a pane twice, and clears a maximised pane that left the dock", () => {
    const dup = { ...EMPTY_TREE, root: leaf("a"), floating: [leaf("a")] };
    expect(code(() => normalise(dup))).toBe("duplicate_leaf");
    expect(normalise({ ...EMPTY_TREE, root: leaf("a"), maximised: "zz" }).maximised).toBeNull();
  });
});

describe("operations", () => {
  const grid = (): DockTree => preset("2x2", ["a", "b", "c", "d"]);

  it("split puts the new pane on the named side of a pane", () => {
    const tree = split(preset("1x1", ["a"]), "a", "left", leaf("n"), ctx());
    expect(shape(tree.root)).toEqual({ row: [{ pane: "n" }, { pane: "a" }], sizes: [0.5, 0.5] });
    expect(shape(split(tree, "a", "bottom", leaf("m"), ctx()).root)).toEqual({
      row: [{ pane: "n" }, { column: [{ pane: "a" }, { pane: "m" }], sizes: [0.5, 0.5] }],
      sizes: [0.5, 0.5],
    });
    expect(code(() => split(tree, "a", "top", leaf("n"), ctx()))).toBe("duplicate_leaf");
    expect(code(() => split(tree, "nope", "top", leaf("z"), ctx()))).toBe("unknown_target");
    expect(shape(split(EMPTY_TREE, "x", "left", leaf("z"), ctx()).root)).toEqual({ pane: "z" });
  });

  it("move re-parents the same leaf object; onto itself it changes nothing", () => {
    const before = grid();
    const a = allLeaves(before).find((l) => l.paneId === "a");
    const after = move(before, "a", "d", "right", ctx());
    expect(allLeaves(after).find((l) => l.paneId === "a")).toBe(a);
    expect(shape(after.root)).toEqual({
      column: [
        { pane: "b" },
        { row: [{ pane: "c" }, { pane: "d" }, { pane: "a" }], sizes: [0.5, 0.25, 0.25] },
      ],
      sizes: [0.5, 0.5],
    });
    expect(move(before, "a", "a", "left", ctx())).toBe(before);
    expect(code(() => move(before, "a", "nope", "left", ctx()))).toBe("unknown_target");
    expect(code(() => move(before, "zz", "b", "left", ctx()))).toBe("unknown_target");
  });

  it("tabify makes the moved pane the active tab; a tab moved out splits the group", () => {
    const tabbed = tabify(grid(), "a", "d", ctx());
    expect(shape(tabbed.root)).toMatchObject({
      column: [
        { pane: "b" },
        { row: [{ pane: "c" }, { tabs: [{ pane: "d" }, { pane: "a" }], active: 1 }] },
      ],
    });
    const three = tabify(tabbed, "b", "a", ctx());
    expect(shape(three.root)).toMatchObject({
      row: [{ pane: "c" }, { tabs: [{ pane: "d" }, { pane: "a" }, { pane: "b" }], active: 2 }],
    });
    const out = move(three, "a", "c", "top", ctx());
    expect(shape(out.root)).toMatchObject({
      row: [
        { column: [{ pane: "a" }, { pane: "c" }] },
        { tabs: [{ pane: "d" }, { pane: "b" }], active: 1 },
      ],
    });
    const rowId = asSplit(grid().root).children[0]?.id as string;
    expect(code(() => tabify(grid(), "d", rowId, ctx()))).toBe("invalid_operation");
    const shown = activateTab(three, asSplit(three.root).children[1]?.id as string, 0, ctx());
    expect(shape(shown.root)).toMatchObject({ row: [{ pane: "c" }, { active: 0 }] });
    expect(code(() => activateTab(three, "nope", 0, ctx()))).toBe("unknown_target");
  });

  it("activateTab clamps an out-of-range or non-integer index into the group (pinned, not refused)", () => {
    // A UI op, not the import boundary: `22`'s active_out_of_range applies to a stored spec, which
    // fromLayout refuses; a stale index from the UI lands on the nearest tab instead.
    const two = tabify(preset("2x1", ["a", "b"]), "a", "b", ctx());
    expect(shape(two.root)).toMatchObject({ tabs: [{ pane: "b" }, { pane: "a" }], active: 1 });
    const active = (index: number): unknown => {
      const node = activateTab(two, two.root?.id as string, index, ctx()).root;
      return node?.type === "tabset" ? node.active : "not a tab group";
    };
    expect(active(99)).toBe(1);
    expect(active(-3)).toBe(0);
    expect(active(Number.NaN)).toBe(0);
    expect(active(Number.POSITIVE_INFINITY)).toBe(1);
    expect(active(1.7)).toBe(1);
  });

  it("close removes a docked, floating or minimised pane", () => {
    expect(shape(close(grid(), "a", ctx()).root)).toMatchObject({
      column: [{ pane: "b" }, { row: [{ pane: "c" }, { pane: "d" }] }],
    });
    const floated = float(grid(), "b", ctx());
    expect(close(floated, "b", ctx()).floating).toEqual([]);
    const minimised = { ...grid(), root: leaf("a"), minimised: [leaf("m")] };
    expect(close(minimised, "m", ctx()).minimised).toEqual([]);
    expect(code(() => close(grid(), "zz", ctx()))).toBe("unknown_target");
  });

  it("resize moves one separator and keeps both neighbours above the floor", () => {
    const tree = preset("2x1", ["a", "b"]);
    const sep = separatorId(tree.root?.id as string, 0);
    expect(resize(tree, sep, 0.1, ctx(false)).root).toMatchObject({ sizes: [0.6, 0.4] });
    const far = asSplit(resize(tree, sep, 5, ctx(false)).root);
    expect(far.sizes[1]).toBeCloseTo(0.01);
    expect(resize(tree, sep, Number.NaN, ctx(false)).root).toMatchObject({ sizes: [0.5, 0.5] });
    // Pinned clamps: a delta past either floor stops at the floor; a non-finite delta is no move.
    const back = asSplit(resize(tree, sep, -5, ctx(false)).root);
    expect(back.sizes[0]).toBeCloseTo(0.01);
    const inf = resize(tree, sep, Number.NEGATIVE_INFINITY, ctx(false)).root;
    expect(inf).toMatchObject({ sizes: [0.5, 0.5] });
    expect(code(() => resize(tree, `${tree.root?.id}/1`, 0.1, ctx()))).toBe("unknown_target");
    expect(code(() => resize(tree, "nope/0", 0.1, ctx()))).toBe("unknown_target");
    const moved = resize(tree, sep, 0.2, ctx(false));
    expect(equalise(moved, tree.root?.id as string, ctx(false)).root).toMatchObject({
      sizes: [0.5, 0.5],
    });
    expect(code(() => equalise(tree, "nope", ctx()))).toBe("unknown_target");
  });

  it("maximise, restore, float and redock keep the leaf", () => {
    const max = maximise(grid(), "c", ctx());
    expect(max.maximised).toBe("c");
    expect(restore(max, ctx()).maximised).toBeNull();
    expect(code(() => maximise(grid(), "zz", ctx()))).toBe("unknown_target");
    const floated = float(grid(), "c", ctx());
    expect(floated.floating.map((l) => l.paneId)).toEqual(["c"]);
    const back = redock(floated, "c", ctx());
    expect(back.floating).toEqual([]);
    expect(shape(back.root)).toMatchObject({
      row: [{ column: [{ row: [{ pane: "a" }, { pane: "b" }] }, { pane: "d" }] }, { pane: "c" }],
    });
    const placed = redock(floated, "c", ctx(), { targetId: "a", zone: "centre" });
    expect(shape(placed.root)).toMatchObject({
      column: [{ row: [{ tabs: [{ pane: "a" }, { pane: "c" }] }, { pane: "b" }] }, { pane: "d" }],
    });
    expect(code(() => redock(grid(), "a", ctx()))).toBe("unknown_target");
    const lone = redock({ ...EMPTY_TREE, minimised: [leaf("m")] }, "m", { mint: counterMinter() });
    expect(shape(lone.root)).toEqual({ pane: "m" });
  });

  it("never mutates its input", () => {
    const tree = grid();
    const frozen = JSON.stringify(tree);
    move(tree, "a", "d", "centre", ctx());
    close(tree, "b", ctx());
    expect(JSON.stringify(tree)).toBe(frozen);
  });
});

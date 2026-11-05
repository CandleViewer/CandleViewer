import { describe, expect, it } from "vitest";
import {
  EMPTY_TREE,
  NAMED_PRESETS,
  PRESET_CELLS,
  allLeaves,
  applyPreset,
  counterMinter,
  isDockError,
  leavesOf,
  matchPreset,
  presetToTree,
  sameShape,
  split,
  type DockLeaf,
  type DockNode,
} from "../src/index.js";
import { ctx, leaf, preset, shape, treeOf } from "./fixtures.js";

const panes = (n: number): string[] => Array.from({ length: n }, (_, i) => `p${i}`);

describe("presets (Gherkin: Preset detection and reconstruction round-trip)", () => {
  it("applyPreset('2x2') is matched as 2x2 and presetToTree rebuilds it with the same pane ids", () => {
    const four = treeOf(presetToTree("1x2", [leaf("a"), leaf("b")], counterMinter()));
    const built = applyPreset(
      split(split(four, "a", "right", leaf("c"), ctx()), "b", "right", leaf("d"), ctx()),
      "2x2",
      ctx(),
    );
    expect(matchPreset(built)).toBe("2x2");
    const rebuilt = presetToTree("2x2", leavesOf(built.root), counterMinter("x"));
    expect(sameShape(built.root as DockNode, rebuilt)).toBe(true);
    expect(leavesOf(rebuilt).map((l) => l.paneId)).toEqual(
      leavesOf(built.root).map((l) => l.paneId),
    );
  });

  it.each(NAMED_PRESETS)("matches %s and fills its cells in row-major reading order", (name) => {
    const tree = preset(name, panes(PRESET_CELLS[name]));
    expect(matchPreset(tree)).toBe(name);
    expect(leavesOf(tree.root).map((l) => l.paneId)).toEqual(panes(PRESET_CELLS[name]));
  });

  it("1+3 is the large cell left at 0.6 and three equal rows right (E15-D02 tree (b))", () => {
    expect(shape(preset("1+3", ["a", "b", "c", "d"]).root)).toEqual({
      row: [
        { pane: "a" },
        {
          column: [{ pane: "b" }, { pane: "c" }, { pane: "d" }],
          sizes: [0.333333, 0.333333, 0.333333],
        },
      ],
      sizes: [0.6, 0.4],
    });
  });

  it("a dragged divider, a tab group or an empty dock is custom", () => {
    const dragged = treeOf({
      type: "row",
      id: "r",
      sizes: [0.7, 0.3],
      children: [leaf("a"), leaf("b")],
    });
    expect(matchPreset(dragged)).toBe("custom");
    expect(
      matchPreset(treeOf({ type: "tabset", id: "t", active: 0, children: [leaf("a"), leaf("b")] })),
    ).toBe("custom");
    expect(matchPreset(EMPTY_TREE)).toBe("1x1");
    expect(sameShape(leaf("a"), leaf("b"))).toBe(false);
    expect(
      sameShape(
        { type: "row", id: "r", sizes: [0.5, 0.5], children: [leaf("a"), leaf("b")] },
        leaf("a"),
      ),
    ).toBe(false);
  });

  it("presetToTree refuses the wrong number of panes", () => {
    expect(() => presetToTree("2x2", [leaf("a")], counterMinter())).toThrow(/holds 4 panes/);
  });
});

describe("applyPreset (Gherkin: Applying a preset preserves matching panes)", () => {
  it("2x2 -> 1+3 reuses the four existing leaf objects in the new slots", () => {
    const grid = preset("2x2", ["a", "b", "c", "d"]);
    const before = leavesOf(grid.root);
    const after = applyPreset(grid, "1+3", ctx());
    expect(matchPreset(after)).toBe("1+3");
    const reused = leavesOf(after.root);
    expect(reused).toHaveLength(4);
    reused.forEach((l, i) => expect(l).toBe(before[i]));
  });

  it("minimises panes beyond the cells and draws missing ones from makeLeaf, or refuses", () => {
    const grid = preset("2x2", ["a", "b", "c", "d"]);
    const one = applyPreset(grid, "1x1", ctx());
    expect(one.minimised.map((l) => l.paneId)).toEqual(["b", "c", "d"]);
    expect(leavesOf(applyPreset(one, "2x2", ctx()).root).map((l) => l.paneId)).toEqual([
      "a",
      "b",
      "c",
      "d",
    ]);
    const made: DockLeaf[] = [];
    const nine = applyPreset(grid, "3x3", {
      ...ctx(),
      makeLeaf: (cell) => (made.push(leaf(`new${cell}`)), made.at(-1) as DockLeaf),
    });
    expect(allLeaves(nine)).toHaveLength(9);
    expect(made.map((l) => l.paneId)).toEqual(["new4", "new5", "new6", "new7", "new8"]);
    try {
      applyPreset(grid, "3x3", ctx());
      expect.unreachable();
    } catch (error) {
      expect(isDockError(error) && error.code).toBe("invalid_operation");
    }
  });
});

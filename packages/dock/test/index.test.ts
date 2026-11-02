import { describe, expect, it } from "vitest";
import { DOCK_ERROR_CODES, layoutChanged } from "../src/index.js";
import { preset } from "./fixtures.js";

// The public entry is the package's contract: pin what it exports at runtime.
describe("the public entry", () => {
  it("exports exactly the tree, operations, presets, serialisation and drop resolution", async () => {
    expect(Object.keys(await import("../src/index.js")).sort()).toEqual([
      "DOCK_ERROR_CODES",
      "DockError",
      "EMPTY_TREE",
      "MAX_DEPTH",
      "MAX_LEAVES",
      "MAX_NODES",
      "MIN_FRACTION",
      "NAMED_PRESETS",
      "PRESET_CELLS",
      "SIZE_EPSILON",
      "ZONE_GEOMETRY",
      "activateTab",
      "allLeaves",
      "applyPreset",
      "close",
      "compactPanes",
      "countNodes",
      "counterMinter",
      "depthOf",
      "dropZones",
      "equalise",
      "findNode",
      "float",
      "fromLayout",
      "isDockError",
      "layoutChanged",
      "layoutRects",
      "leavesOf",
      "matchPreset",
      "maximise",
      "minExtent",
      "move",
      "neighbour",
      "normalise",
      "panelBoxes",
      "presetToTree",
      "redock",
      "relocate",
      "resize",
      "resolveDirectionalMove",
      "resolveDrop",
      "restore",
      "sameShape",
      "separatorId",
      "split",
      "tabify",
      "toLayoutInput",
      "validateGridSpec",
    ]);
  });

  it("keeps the API's rule codes first and frozen", () => {
    expect(DOCK_ERROR_CODES.slice(0, 8)).toEqual([
      "tree_too_deep",
      "tree_too_large",
      "unknown_slot",
      "duplicate_leaf",
      "sizes_mismatch",
      "sizes_sum",
      "active_out_of_range",
      "duplicate_slot",
    ]);
    expect(Object.isFrozen(DOCK_ERROR_CODES)).toBe(true);
  });

  it("layoutChanged reports the op, pane count, preset and duration", () => {
    expect(layoutChanged("apply_preset", preset("2x2", ["a", "b", "c", "d"]), 3)).toEqual({
      op: "apply_preset",
      paneCount: 4,
      preset: "2x2",
      durationMs: 3,
    });
  });
});

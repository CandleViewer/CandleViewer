// E14-T04 (#359) contract: the drawing and selection commands are validated at the worker boundary
// before the runtime reads them (bounded ids, anchors in pairs, whole-number handles).
import { describe, expect, it } from "vitest";
import { MAX_ANCHORS, MAX_SELECTION, rejectReason } from "../../src/worker/protocol.js";

const cmd = (c: object): object => ({ t: "command", id: 1, cmd: c });

describe("E14-T04 commands at the worker boundary", () => {
  it.each([
    { k: "addDrawing", drawingId: "d", kind: "trendline" },
    {
      k: "addDrawing",
      drawingId: "d",
      kind: "fib-retracement",
      anchors: [1e15, 10, 1e15 + 6e7, 20],
      widthPx: 2,
      zIndex: 3,
      locked: true,
      visible: false,
      levels: [0, 0.618, 1],
    },
    { k: "removeDrawing", drawingId: "d" },
    { k: "setSelection", ids: ["a", "b"], op: "replace" },
    { k: "setSelection", ids: [], op: "clear" },
    { k: "selectAll" },
    { k: "selectAll", pane: 0 },
    { k: "setInteractionMode", mode: "select-area" },
    { k: "setInteractionMode", mode: "cursor", readOnly: true },
    { k: "focusObject", drawingId: null },
    { k: "focusObject", drawingId: "d", handle: 1 },
  ])("accepts $k", (c) => {
    expect(rejectReason(cmd(c))).toBeNull();
  });

  it.each([
    ["odd anchors", { k: "addDrawing", drawingId: "d", kind: "x", anchors: [1, 2, 3] }],
    ["no anchors", { k: "addDrawing", drawingId: "d", kind: "x", anchors: [] }],
    ["a NaN anchor", { k: "addDrawing", drawingId: "d", kind: "x", anchors: [1, Number.NaN] }],
    [
      "too many anchors",
      {
        k: "addDrawing",
        drawingId: "d",
        kind: "x",
        anchors: new Array(2 * MAX_ANCHORS + 2).fill(1),
      },
    ],
    ["a long id", { k: "addDrawing", drawingId: "x".repeat(257), kind: "x" }],
    ["a negative width", { k: "addDrawing", drawingId: "d", kind: "x", widthPx: -1 }],
    ["a string lock", { k: "addDrawing", drawingId: "d", kind: "x", locked: "yes" }],
    [
      "too many levels",
      { k: "addDrawing", drawingId: "d", kind: "x", levels: new Array(33).fill(0) },
    ],
    ["an unknown op", { k: "setSelection", ids: [], op: "xor" }],
    ["a non-string id", { k: "setSelection", ids: [1], op: "add" }],
    ["too many ids", { k: "setSelection", ids: new Array(MAX_SELECTION + 1).fill("a"), op: "add" }],
    ["a negative pane", { k: "selectAll", pane: -1 }],
    ["an unknown mode", { k: "setInteractionMode", mode: "lasso" }],
    ["a fractional handle", { k: "focusObject", drawingId: "d", handle: 0.5 }],
    ["a handle under -1", { k: "focusObject", drawingId: "d", handle: -2 }],
    ["a removeDrawing without id", { k: "removeDrawing" }],
  ])("rejects %s", (_name, c) => {
    expect(rejectReason(cmd(c))).toBe("malformed command");
  });
});

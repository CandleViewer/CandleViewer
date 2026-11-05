// E14-T04 (#359) through the runtime: drawings register from `addDrawing`, hidden ones are never
// hovered, the selection is worker-owned and posted on change only, the keyboard's `focusObject`
// behaves as a press (BQ-05).
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { INPUT } from "../../src/worker/protocol.js";
import { drawingRig, type DrawingRig } from "./drawing-rig.js";

let r: DrawingRig;

beforeEach(() => {
  r = drawingRig();
});

afterEach(() => {
  vi.useRealTimers();
});

const selections = () => r.of("selection").map((m) => [m.ids, m.focused, m.handle, m.mode]);

describe("registration", () => {
  it("an addDrawing with anchors is hovered; without anchors nothing registers", () => {
    r.draw("t", "trendline", [r.at(0.2, 0.5), r.at(0.8, 0.5)]);
    r.cmd({ k: "addDrawing", drawingId: "bare", kind: "trendline" });
    expect(r.objects.size).toBe(1);
    const [x, y] = r.xy(r.at(0.5, 0.5));
    r.input([INPUT.move, x, y, 0, 0, 16]);
    expect(r.of("pick").at(-1)).toMatchObject({ objectId: "t", kind: "drawing", part: "body" });
  });

  it("Scenario: Hidden objects are not pickable (hover posts nothing, so no cursor change)", () => {
    r.draw("h", "trendline", [r.at(0.2, 0.5), r.at(0.8, 0.5)], { visible: false });
    const [x, y] = r.xy(r.at(0.5, 0.5));
    r.input([INPUT.move, x, y, 0, 0, 16]);
    r.input([INPUT.move, x + 30, y, 0, 0, 16]);
    expect(r.of("pick")).toEqual([]);
    r.draw("h", "trendline", [r.at(0.2, 0.5), r.at(0.8, 0.5)]); // shown again: hovered
    r.input([INPUT.move, x, y, 0, 0, 16]);
    expect(r.of("pick").map((m) => m.objectId)).toEqual(["h"]);
  });

  it("a ceiling refusal is a recoverable error and leaves no stale selection", () => {
    const bubble = { kind: "bubble", paneId: "main", zIndex: 0, widthPx: 0 } as const;
    for (let i = 0; i < 10_000; i += 1) {
      r.objects.registerPickable({ id: `o${i}`, ...bubble, geometry: { type: "hline", p: i } });
    }
    r.draw("x", "trendline", [r.at(0.2, 0.5), r.at(0.8, 0.5)]);
    expect(r.of("error").at(-1)).toMatchObject({ code: "ENGINE_DECODE_ERROR", recoverable: true });
  });
});

describe("the selection set", () => {
  beforeEach(() => {
    for (const id of ["a", "b", "c"]) r.draw(id, "horizontal_line", [r.at(0.5, 0.3)]);
    r.draw("hid", "horizontal_line", [r.at(0.5, 0.7)], { visible: false });
  });

  it("replace, add, toggle and clear post once per change; unknown ids are ignored", () => {
    r.cmd({ k: "setSelection", ids: ["a", "ghost"], op: "replace" });
    r.cmd({ k: "setSelection", ids: ["a"], op: "replace" }); // no change: no message
    r.cmd({ k: "setSelection", ids: ["b"], op: "add" });
    r.cmd({ k: "setSelection", ids: ["a"], op: "add" }); // no change
    r.cmd({ k: "setSelection", ids: ["a", "c"], op: "toggle" });
    r.cmd({ k: "setSelection", ids: [], op: "clear" });
    r.cmd({ k: "setSelection", ids: [], op: "clear" });
    expect(selections().map((s) => s[0])).toEqual([["a"], ["a", "b"], ["b", "c"], []]);
    expect(r.objects.counters.selectionSize).toBe(0);
  });

  it("selectAll takes every visible drawing on the pane; the tree may still pick a hidden one", () => {
    r.cmd({ k: "selectAll" });
    r.cmd({ k: "selectAll", pane: 1 }); // no such pane yet: empty
    r.cmd({ k: "setSelection", ids: ["hid"], op: "add" });
    expect(selections().map((s) => s[0])).toEqual([["a", "b", "c"], [], ["hid"]]);
  });

  it("focusObject behaves as a press (the same selection event); hidden or unknown is ignored", () => {
    r.cmd({ k: "setSelection", ids: ["a", "b"], op: "replace" });
    r.cmd({ k: "focusObject", drawingId: "b", handle: 0 });
    r.cmd({ k: "focusObject", drawingId: "c" });
    r.cmd({ k: "focusObject", drawingId: "ghost" }); // unknown: ignored
    r.cmd({ k: "focusObject", drawingId: "hid" }); // hidden (unregistered, BQ-05): ignored
    r.cmd({ k: "focusObject", drawingId: "c", handle: 1 }); // one anchor: handle 1 is refused
    r.cmd({ k: "focusObject", drawingId: null });
    expect(selections()).toEqual([
      [["a", "b"], null, -1, "cursor"],
      [["a", "b"], "b", 0, "cursor"],
      [["c"], "c", -1, "cursor"],
      [["c"], null, -1, "cursor"],
    ]);
  });

  it("removing a drawing drops it from the set and the focus", () => {
    r.cmd({ k: "focusObject", drawingId: "a" });
    r.cmd({ k: "removeDrawing", drawingId: "a" });
    expect(selections().at(-1)).toEqual([[], null, -1, "cursor"]);
    expect(r.objects.size).toBe(2);
  });

  it("the interaction mode rides the event; read-only alone posts nothing", () => {
    r.cmd({ k: "setInteractionMode", mode: "select-area" });
    r.cmd({ k: "setInteractionMode", mode: "select-area", readOnly: true });
    r.cmd({ k: "setInteractionMode", mode: "cursor" });
    expect(selections().map((s) => s[3])).toEqual(["select-area", "cursor"]);
  });
});

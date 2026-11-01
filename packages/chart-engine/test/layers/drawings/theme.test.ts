// E14-T03, #358 BQ-4 and BQ-358-7: colours arrive as numbers or as theme token keys resolved
// through the theme object (never CSS, SR-E14-04); every alpha passes the premultiplied "flatten
// opacity" path; the dash table is one named constant, the default pending E14-D04's value.
import { describe, expect, it } from "vitest";
import { DASH_LUT } from "../../../src/gl/shaders/drawing-line.js";
import { DRAWING_DASH, setDrawingsReason } from "../../../src/layers/drawings/model.js";
import {
  FALLBACK_COLOUR,
  parseHex,
  resolveColour,
  toRecord,
} from "../../../src/layers/drawings/record.js";
import { flatten } from "../../../src/layers/drawings/ring.js";
import { harness } from "./harness.js";
import { minuteMap } from "../../interaction/fixtures.js";

const T = (i: number): number => minuteMap().indexToTime(i);
const seg = (colour: number | string, extra = {}) => ({
  ...{ id: "s", kind: "segment" as const, points: [T(10), 1010, T(40), 1040] },
  style: { colour, width: 2, dash: 0 as const },
  ...extra,
});

describe("the premultiplied flatten-opacity path (BQ-4)", () => {
  it("scales the alpha by the opacity, then every channel by that alpha", () => {
    const out = new Float64Array(4);
    flatten(0x2962ff80, 0.5, out);
    const a = (0x80 / 255) * 0.5;
    expect([...out]).toEqual([(0x29 / 255) * a, (0x62 / 255) * a, (0xff / 255) * a, a]);
    flatten(0xffffffff, 7, out); // clamped to 1
    expect([...out]).toEqual([1, 1, 1, 1]);
    flatten(0xffffffff, -1, out); // clamped to 0: fully transparent, premultiplied black
    expect([...out]).toEqual([0, 0, 0, 0]);
  });

  it("setDrawings' opacity is validated and lands on every drawing's alpha", () => {
    expect(setDrawingsReason({ op: "patch", drawings: [], opacity: 1.5 })).toBe("opacity");
    expect(setDrawingsReason({ op: "patch", drawings: [], opacity: Number.NaN })).toBe("opacity");
    const { node, frame, ctx2d } = harness(1, false, [seg(0xff0000ff)]);
    expect(node.apply({ op: "patch", drawings: [], opacity: 0.25 })).toBeNull();
    frame();
    expect(node.lines.data[15]).toBe(0.25);
    expect(ctx2d.paths[0]?.style).toBe("rgba(255, 0, 0, 0.25098039215686274)");
  });
});

describe("theme token colours (BQ-4)", () => {
  it.each([
    ["color.drawing.default", null],
    ["color.drawing.palette.3", null],
    ["color.position.long-entry", null],
    ["red", "style colour"],
    ["#ff0000", "style colour"],
    ["color.ui.accent", "style colour"],
    ["color.drawing.x;background:url(a)", "style colour"],
    [`color.drawing.${"a".repeat(64)}`, "style colour"],
  ])("%s → %s", (colour, why) => {
    expect(setDrawingsReason({ op: "patch", drawings: [seg(colour)] })).toBe(why);
  });

  it("resolves a key through the theme, then color.drawing.default, then a fixed grey", () => {
    const theme = { "color.drawing.palette.1": "#0af", "color.drawing.default": "#11223344" };
    expect(resolveColour("color.drawing.palette.1", theme)).toBe(0x00aaffff);
    expect(resolveColour("color.drawing.palette.9", theme)).toBe(0x11223344);
    expect(resolveColour("color.drawing.palette.9", {})).toBe(FALLBACK_COLOUR);
    expect(resolveColour(0x01020304, theme)).toBe(0x01020304);
    expect([parseHex("rgb(1, 2, 3)"), parseHex(undefined), parseHex("#abc")]).toEqual([
      null,
      null,
      0xaabbccff,
    ]);
    expect(toRecord(seg("color.drawing.default")).colour).toBe(FALLBACK_COLOUR); // until a theme
  });

  it("a theme change (STYLE) re-encodes the token colours; a pan does not", () => {
    const { node, graph, frame } = harness(1, false, [seg("color.drawing.default")]);
    node.theme = { "color.drawing.default": "#ff0000" };
    graph.markTheme();
    frame();
    expect([...node.lines.data.slice(12, 16)]).toEqual([1, 0, 0, 1]);
    const encodes = node.encodes;
    graph.markViewport();
    frame();
    expect(node.encodes).toBe(encodes);
  });
});

describe("the dash table (BQ-358-7)", () => {
  it("is one named constant: dashed 4w on, 2w off; dotted a 1w dot, 2w off; one table", () => {
    expect(DRAWING_DASH).toEqual([
      [0, 0],
      [3, 6], // a 3w core + two half-width caps = 4w on, then 2w off
      [0, 3], // a zero core + caps = a 1w dot, then 2w off
    ]);
    expect(DASH_LUT).toBe(DRAWING_DASH);
  });
});

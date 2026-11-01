// E14-T03 slice 1: the drawing input's worker-boundary validation (E14-X01 DR8, DR9, DR29;
// SR-E14-03, SR-E14-04) and the atomic set: every refusal leaves the state as it was.
import { describe, expect, it } from "vitest";
import * as m from "../../../src/layers/drawings/model.js";
import { DrawingSet } from "../../../src/layers/drawings/set.js";
import { rejectReason } from "../../../src/worker/protocol.js";

const style = { colour: 0xff8800ff, width: 2, dash: 0 } as const;
const seg = (id: string, extra: object = {}): m.DrawingInput => ({
  ...{ id, kind: "segment", points: [0, 10, 60e6, 20], style },
  ...extra,
});
const check = (drawings: unknown[], extra: object = {}): string | null =>
  m.setDrawingsReason({ op: "patch", drawings, ...extra });

describe("setDrawings validation (E14-X01 DR8, DR9, DR29)", () => {
  it("accepts every kind at its anchor count, as an array or a Float64Array", () => {
    for (const kind of m.DRAWING_KINDS) {
      const points = new Float64Array(2 * m.DRAWING_POINTS[kind][0]).fill(1);
      expect(check([{ id: kind, kind, points, style }]), kind).toBeNull();
    }
    expect(check([seg("a", { label: "x", z: -5, visible: false, points: [1, 2, 3, 4] })])).toBe(
      null,
    );
  });

  it.each([
    ["an unknown kind", { kind: "html" }, "unknown drawing kind html"],
    ["a prototype key as kind", { kind: "constructor" }, "unknown drawing kind constructor"],
    ["a wrong anchor count", { points: [0, 1, 2, 3, 4, 5] }, "segment takes 2,2"],
    ["an odd point array", { points: [0, 1, 2] }, "segment takes 2,2"],
    ["a NaN anchor", { points: [0, 1, Number.NaN, 3] }, "non-finite point"],
    ["an infinite anchor", { points: [0, Infinity, 2, 3] }, "non-finite point"],
    ["a string anchor", { points: [0, "1", 2, 3] }, "non-finite point"],
    ["points as an object", { points: { length: 4 } }, "points"],
    ["a CSS string colour", { style: { ...style, colour: "red;x:url(a)" } }, "style colour"],
    ["a colour past 32 bits", { style: { ...style, colour: 2 ** 32 } }, "style colour"],
    ["a bad fill", { style: { ...style, fill: -1 } }, "style colour"],
    ["a width past 8", { style: { ...style, width: 9 } }, "style width or dash"],
    ["an unknown dash", { style: { ...style, dash: 3 } }, "style width or dash"],
    ["an unknown style key", { style: { ...style, css: "x" } }, "style key css"],
    ["a NaN font size", { style: { ...style, fontSize: Number.NaN } }, "fontSize"],
    ["no style", { style: null }, "style is not an object"],
    ["a non-string label", { label: 7 }, "label"],
    ["a z out of int16", { z: 40_000 }, "z"],
    ["a non-boolean visible", { visible: 1 }, "visible"],
    ["an id with markup", { id: "<b>" }, "drawing id"],
    ["an id over 64 chars", { id: "a".repeat(65) }, "drawing id"],
    ["an unknown top-level key", { onclick: "x" }, "drawing key onclick"],
    ["a raw label over 480 units", { label: "x".repeat(481) }, "label"],
    ["a time past 2^53 µs", { points: [2 ** 53 + 2, 1, 0, 1] }, "point out of range"],
    ["a tick past the int32 base", { points: [0, 2 ** 30 + 1, 0, 1] }, "point out of range"],
  ])("refuses %s", (_, change, why) => {
    expect(check([{ ...seg("a"), ...change }])).toBe(why);
  });

  it("refuses a bad envelope, and names the reason at the worker boundary", () => {
    expect(m.setDrawingsReason({ op: "merge", drawings: [] })).toBe("op");
    expect(m.setDrawingsReason({ op: "patch", drawings: null })).toBe("drawings");
    expect(check([seg("a"), seg("a")])).toBe("duplicate drawing a");
    expect(m.setDrawingsReason({ op: "replace", drawings: [], remove: ["a"] })).toBe("remove");
    expect([check([], { remove: ["<x>"] }), check([], { remove: "a" })]).toEqual([
      "remove",
      "remove",
    ]);
    const over = Array.from({ length: m.MAX_DRAWINGS + 1 }, (_, i) => seg(`d${i}`));
    expect(check(over)).toBe("drawings");
    const cmd = { k: "setDrawings", op: "patch", drawings: [seg("a", { kind: "svg" })] };
    expect(rejectReason({ t: "command", id: 1, cmd })).toBe(
      "setDrawings: unknown drawing kind svg",
    );
  });
});

describe("labels are data (SR-E14-03)", () => {
  it("strips controls, line separators, bidi marks and lone surrogates; parses nothing", () => {
    const evil = "a\u0000b\u001b[31mc\u007f\u0085 ‮d⁦e‏f؜\ud800";
    expect(m.clampLabel(evil)).toBe("ab[31mcdef");
    expect(m.clampLabel("<img src=x onerror=alert(1)>")).toBe("<img src=x onerror=alert(1)>");
  });

  it("keeps 120 code points (an astral glyph is one) and clamps the font to 8..48", () => {
    expect([...m.clampLabel("😀".repeat(500))]).toHaveLength(m.LABEL_MAX);
    expect(m.clampLabel("x".repeat(10_000))).toHaveLength(m.LABEL_MAX);
    expect([m.clampFont(1), m.clampFont(20), m.clampFont(1e9)]).toEqual([8, 20, 48]);
  });
});

describe("the drawing set", () => {
  const make = (): DrawingSet<m.DrawingInput> => {
    const s = new DrawingSet<m.DrawingInput>((d) => d);
    s.apply({ op: "replace", drawings: [seg("a"), seg("b"), seg("c")] });
    return s;
  };
  const state = (s: DrawingSet<m.DrawingInput>) => [[...s.ids], s.anchors, s.rev];

  it("replaces whole; a patch removes first, then upserts in place or appends", () => {
    const s = make();
    const moved = seg("b", { points: [0, 1, 1, 2] });
    expect(s.apply({ op: "patch", drawings: [moved, seg("d")], remove: ["a", "zz"] })).toBeNull();
    expect([s.ids, s.order[0]]).toEqual([["b", "c", "d"], moved]);
    s.apply({ op: "patch", drawings: [seg("c")], remove: ["c"] });
    expect(s.ids).toEqual(["b", "d", "c"]); // removed then re-added: drawn last
    s.apply({ op: "replace", drawings: [seg("x")] });
    expect(state(s)).toEqual([["x"], 2, 4]);
  });

  it("refuses past MAX_DRAWINGS or MAX_ANCHORS and leaves the set unchanged", () => {
    const s = make();
    const many = Array.from({ length: m.MAX_DRAWINGS - 2 }, (_, i) => seg(`n${i}`));
    expect(s.apply({ op: "patch", drawings: many })).toBe("more than 1000 drawings");
    expect(state(s)).toEqual([["a", "b", "c"], 6, 1]);
    const poly = (id: string): m.DrawingInput =>
      seg(id, { kind: "polyline", points: new Float64Array(1000) });
    const fits = Math.floor((m.MAX_ANCHORS - 6) / 500); // polylines of 500 beside the 6 held
    s.apply({ op: "patch", drawings: Array.from({ length: fits }, (_, i) => poly(`p${i}`)) });
    const before = state(s);
    expect(s.apply({ op: "patch", drawings: [poly("over")] })).toBe("more than 65536 anchors");
    expect(state(s)).toEqual(before);
    // The patch's net change counts: replacing a polyline with a segment frees room.
    expect(s.apply({ op: "patch", drawings: [seg("p0"), poly("over")] })).toBeNull();
    const t = make(); // exactly at the cap is fine
    expect([t.apply({ op: "patch", drawings: many, remove: ["a"] }), t.size]).toEqual([null, 1000]);
  });
});

describe("copyInput: the worker's and the host's own copy", () => {
  it("keeps known keys only, copies the points and clamps the label and font", () => {
    const points = [0, 10, 60e6, 20];
    const d = { ...seg("a", { points, label: "a\u202eb", z: 3 }), extra: 1 } as m.DrawingInput;
    const style = { ...d.style, fontSize: 99, css: "x" } as m.DrawingStyle;
    const c = m.copyInput({ ...d, style });
    expect(c).toEqual({
      ...{ id: "a", kind: "segment", points: Float64Array.from(points), label: "ab", z: 3 },
      style: { colour: 0xff8800ff, width: 2, dash: 0, fontSize: 48 },
    });
    points[0] = 99; // the caller mutates its array after the command
    (style as { width: number }).width = 8;
    expect([c.points[0], c.style.width]).toEqual([0, 2]);
    expect(m.drawingReason(seg("b", { points: [-(2 ** 53), -(2 ** 30), 2 ** 53, 2 ** 30] }))).toBe(
      null,
    );
  });
});

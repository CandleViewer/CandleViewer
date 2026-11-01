// E14-T03 PR 2: drawing labels behind the `GlyphSource` seam (#358 BQ-1). The fake atlas's
// metrics; the `drawing-label` ring (one glyph instance per drawn code point, one run per label,
// device px at any DPR, compare-first change ranges); each label's box inside the drawing's
// screen bounds; the Canvas 2D path's `fillText` of the clamped, stripped label with a font built
// from its size alone (SR-E14-03/04); the GL stand-in and the 2D path putting a label's baseline
// on the same pixel; and Scenario 3, the text budget.
import { describe, expect, it } from "vitest";
import { DrawingsDragBench } from "../../../bench/scenes/drawings-drag.js";
import { mulberry32 } from "../../../bench/fixtures/rng.mjs";
import { GLBackend } from "../../../src/gl/backend.js";
import {
  FakeAtlas,
  GLYPH,
  GLYPH_WORDS,
  glyphOf,
  type GlyphSource,
  measure,
} from "../../../src/layers/drawings/glyphs.js";
import {
  LABEL_FONT_PX,
  LABEL_OFFSET_PX,
  LABEL_STRIDE,
  LabelInstances,
  RUN,
  RUN_STRIDE,
} from "../../../src/layers/drawings/labels.js";
import {
  clampLabel,
  type DrawingInput,
  type DrawingKind,
} from "../../../src/layers/drawings/model.js";
import { reindex, toRecord } from "../../../src/layers/drawings/project.js";
import { attributeOffset, PROGRAM } from "../../../src/scene/instance-layout.js";
import { FakeGl } from "../../gl/fake-gl.js";
import { minuteMap } from "../../interaction/fixtures.js";
import { harness, standIn } from "./harness.js";

const T = (i: number): number => minuteMap().indexToTime(i);
const style = { colour: 0x2962ff80, width: 2, dash: 0 } as const;
const input = (kind: DrawingKind, points: number[], label: string, extra = {}): DrawingInput => ({
  ...{ id: `${kind}-${label.length}`, kind, points, style, label },
  ...extra,
});
const BOX = attributeOffset(PROGRAM.drawingLabel, "a_glyph");
const COLOR = attributeOffset(PROGRAM.drawingLabel, "a_color");
const atlas = new FakeAtlas();
const rec = (d: DrawingInput, glyphs: GlyphSource = atlas) => {
  const r = toRecord(d);
  reindex(r, minuteMap(), 1);
  const m = new Float64Array(2);
  measure(glyphs, d.label ?? "", m);
  [r.labelEm, r.labelGlyphs] = [m[0] as number, m[1] as number];
  return r;
};

describe("the GlyphSource seam and its fake atlas", () => {
  it("printable ASCII on a 16 × 8 grid, 0.6 em each; the space advances with no box", () => {
    const g = new Float64Array(GLYPH_WORDS);
    expect(atlas.glyph(0x41, g)).toBe(true); // "A": slot 33, column 1, row 2
    expect([...g]).toEqual([0.6, 0.05, -0.75, 0.55, 0.2, 1 / 16, 2 / 8, 2 / 16, 3 / 8]);
    expect(atlas.glyph(0x20, g)).toBe(true);
    expect([g[GLYPH.advance], (g[GLYPH.x1] as number) - (g[GLYPH.x0] as number)]).toEqual([0.6, 0]);
    expect([atlas.glyph(0x1f, g), atlas.glyph(0x7f, g), atlas.glyph(0x1f600, g)]).toEqual([
      false,
      false,
      false,
    ]);
  });

  it("a code point the atlas lacks draws `?` (26 §3.7); a source without `?` draws nothing", () => {
    const [q, e] = [new Float64Array(GLYPH_WORDS), new Float64Array(GLYPH_WORDS)];
    glyphOf(atlas, 0x3f, q);
    glyphOf(atlas, 0xe9, e); // "é"
    expect([...e]).toEqual([...q]);
    const none: GlyphSource = { texture: 0, ascent: 1, descent: 0, glyph: () => false };
    glyphOf(none, 0x41, e.fill(9));
    expect([...e]).toEqual(Array(GLYPH_WORDS).fill(0));
  });

  it("measures an advance in em and the glyphs drawn; a pair is one code point", () => {
    const m = new Float64Array(2);
    measure(atlas, "ab c", m);
    expect([(m[0] as number) / 0.6, m[1]]).toEqual([4, 3]);
    measure(atlas, "x😀", m); // the pair draws one `?`
    expect([Math.round((m[0] as number) / 0.6), m[1]]).toEqual([2, 2]);
  });
});

describe("the drawing-label ring", () => {
  it("writes one run per label and one glyph per drawn code point, in device px", () => {
    const ring = new LabelInstances();
    const seg = rec(input("segment", [T(10) + 15e6, 1012.75, T(12), 1000], "Hi there"));
    const big = { ...style, fontSize: 20 };
    const text = rec(input("text", [T(20), 1010], "ok", { style: big }));
    ring.encode([seg, text], atlas, 1.5);
    expect([ring.count, ring.runCount, ring.texts]).toEqual([9, 2, ["Hi there", "ok"]]);
    const [f, i] = [ring.data, ring.ints];
    expect([i[0], i[1], f[2], f[3]]).toEqual([10, 1012, 0.25, 0.75]); // the first anchor
    const size = LABEL_FONT_PX * 1.5;
    const off = LABEL_OFFSET_PX * 1.5;
    const fr = Math.fround;
    expect([...f.slice(BOX, BOX + 4)]).toEqual(
      [off + 0.05 * size, -off - 0.75 * size, 0.5 * size, 0.95 * size].map(fr),
    );
    const a = 0x80 / 255; // premultiplied, as the other drawing rings
    expect([...f.slice(COLOR, COLOR + 4)]).toEqual(
      [0x29, 0x62, 0xff].map((v) => fr((v / 255) * a)).concat(fr(a)),
    );
    // "Hi there": the space draws none, so "t" is glyph 2 at pen 3 advances.
    expect(f[2 * LABEL_STRIDE + BOX]).toBe(fr(off + (3 * 0.6 + 0.05) * size));
    // The text kind sits on its anchor: no offset, its own font size.
    const o = 7 * LABEL_STRIDE;
    expect([f[o + BOX], f[o + BOX + 1]]).toEqual([fr(0.05 * 30), fr(-0.75 * 30)]);
    expect([...ring.runs.slice(RUN.x, RUN.font + 1)]).toEqual([off, -off, size]);
    expect([...ring.runs.slice(RUN_STRIDE + RUN.x, RUN_STRIDE + RUN.font + 1)]).toEqual([0, 0, 30]);
  });

  it("draws nothing for a hidden drawing, an empty label or none", () => {
    const ring = new LabelInstances();
    const none: DrawingInput = { id: "none", kind: "hline", points: [T(1), 1], style };
    const recs = [
      rec(input("hline", [T(1), 1], "x", { visible: false })),
      rec(input("hline", [T(1), 1], "")),
      rec(none),
    ];
    ring.encode(recs, atlas, 1);
    expect([ring.count, ring.runCount, ring.texts]).toEqual([0, 0, []]);
  });

  it("an unchanged re-encode reports no range; moving one drawing reports its glyphs alone", () => {
    const ring = new LabelInstances();
    const recs = ["one", "two", "six"].map((l, k) => rec(input("ray", [T(k), k, T(k + 1), k], l)));
    ring.encode(recs, atlas, 1);
    ring.encode(recs, atlas, 1);
    expect([ring.lo, ring.hi]).toEqual([0, 0]);
    recs[1] = rec(input("ray", [T(9), 1, T(10), 1], "two"));
    ring.encode(recs, atlas, 1);
    expect([ring.lo, ring.hi]).toEqual([3, 6]);
  });

  it("grows the run table past its first 16 runs, keeping every text", () => {
    const ring = new LabelInstances();
    const recs = Array.from({ length: 40 }, (_, k) => rec(input("hline", [T(k), k], `L${k}`)));
    ring.encode(recs, atlas, 1);
    expect([ring.runCount, ring.texts.at(-1), ring.runs.length >= 40 * RUN_STRIDE]).toEqual([
      40,
      "L39",
      true,
    ]);
  });
});

describe("labels in the bounds and on the Canvas 2D path", () => {
  it("every glyph the GL stand-in places lies inside its drawing's bounds (seeded, 60 cases)", () => {
    const rng = mulberry32(358);
    const kinds: DrawingKind[] = ["segment", "ray", "hline", "vline", "rect", "text", "band"];
    for (let c = 0; c < 60; c += 1) {
      const kind = kinds[c % kinds.length] as DrawingKind;
      const n =
        kind === "band" ? 3 : kind === "hline" || kind === "vline" || kind === "text" ? 1 : 2;
      const points = Array.from({ length: n }, () => [
        T(5 + rng() * 40),
        1_000 + rng() * 50,
      ]).flat();
      const label = "W".repeat(1 + Math.floor(rng() * 30));
      const s = { ...style, fontSize: 8 + Math.floor(rng() * 41) };
      const dpr = [1, 1.5, 2][c % 3] as number;
      const { node, block } = harness(dpr, c % 2 === 1, [input(kind, points, label, { style: s })]);
      const at = (k: number): number => node.bounds[k] as number;
      const [x0, y0, x1, y1] = [at(0), at(1), at(2), at(3)];
      const ring = node.labels;
      for (let g = 0; g < ring.count; g += 1) {
        const [ax, ay] = standIn(ring, g, 0, block);
        const o = g * LABEL_STRIDE + BOX;
        const box = (k: number): number => ring.data[o + k] as number;
        const [bx, by, bw, bh] = [box(0), box(1), box(2), box(3)];
        const eps = 1e-3;
        expect((ax + bx) / dpr, `case ${c}`).toBeGreaterThanOrEqual(x0 - eps);
        expect((ax + bx + bw) / dpr, `case ${c}`).toBeLessThanOrEqual(x1 + eps);
        expect((ay + by) / dpr, `case ${c}`).toBeGreaterThanOrEqual(y0 - eps);
        expect((ay + by + bh) / dpr, `case ${c}`).toBeLessThanOrEqual(y1 + eps);
      }
    }
  });

  it("fillText draws the clamped, stripped label as data; the font comes from the size alone", () => {
    const raw = `<b>x</b>\u202e;font:99px\u0000 ${"é".repeat(200)}`;
    const big = { ...style, fontSize: 900 }; // clamped to 48
    const { ctx2d } = harness(2, false, [input("text", [T(10), 1_020], raw, { style: big })]);
    expect(ctx2d.texts).toHaveLength(1);
    const [text, , , font, fill] = ctx2d.texts[0] as [string, number, number, string, string];
    expect(text).toBe(clampLabel(raw));
    expect([...text].length).toBe(120);
    expect([...text].some((c) => c === "\u0000" || c === "\u202e")).toBe(false);
    expect([font, fill]).toEqual(["96px sans-serif", "rgba(41, 98, 255, 0.5019607843137255)"]);
  });

  it("a label batch with no pane block is skipped, not drawn at the origin", () => {
    const { backend, frame, ctx2d } = harness(1, false, [input("hline", [T(5), 1_020], "abc")]);
    backend.setPaneUniforms(null);
    const skipped = backend.trace.skipped;
    frame();
    expect([ctx2d.texts.length, backend.trace.skipped > skipped]).toEqual([0, true]);
  });

  it.each([1, 1.5, 2])(
    "dpr %s: the 2D baseline is the GL stand-in's anchor plus the run offset (parity)",
    (dpr) => {
      const d = [
        input("segment", [T(12) + 7e6, 1_011.5, T(30), 1_040], "trend"),
        input("text", [T(40), 1_030], "note"),
      ];
      for (const log of [false, true]) {
        const { node, block, ctx2d } = harness(dpr, log, d);
        const ring = node.labels;
        let g = 0;
        for (let k = 0; k < ring.runCount; k += 1) {
          const [ax, ay] = standIn(ring, g, 0, block);
          const [, x, y] = ctx2d.texts[k] as [string, number, number, string, string];
          expect(x).toBeCloseTo(ax + (ring.runs[k * RUN_STRIDE + RUN.x] as number), 2);
          expect(y).toBeCloseTo(ay + (ring.runs[k * RUN_STRIDE + RUN.y] as number), 2);
          g += [...(ring.texts[k] as string)].length; // no spaces: one glyph per code point
        }
      }
    },
  );

  it("a new GlyphSource re-measures every label and binds its atlas texture on the batch", () => {
    const { node, frame, builder } = harness(1, false, [input("hline", [T(5), 1_020], "abc")]);
    const before = (node.bounds[2] as number) - (node.bounds[0] as number);
    const wide: GlyphSource = {
      texture: 3,
      ascent: 1,
      descent: 0.25,
      glyph: (cp, out) => (atlas.glyph(cp, out) ? ((out[GLYPH.advance] = 2), true) : false),
    };
    node.setGlyphs(wide);
    frame();
    const after = (node.bounds[2] as number) - (node.bounds[0] as number);
    expect(after).toBeGreaterThanOrEqual(LABEL_OFFSET_PX + 3 * 2 * LABEL_FONT_PX);
    expect(after).toBeGreaterThanOrEqual(before);
    const labels = builder.drawList.slice(0, builder.drawCount).find((b) => b.program === 7);
    expect(labels?.texture).toBe(3);
  });
});

describe("Scenario: Text budget is respected", () => {
  it("200 drawings + 50 order lines, each labelled: one label draw, 3 drawings draws a pane", () => {
    const gl = new FakeGl();
    const backend = new GLBackend(gl, null);
    const bench = new DrawingsDragBench(100_000, 358, backend);
    const { drawList, drawCount } = bench.builder;
    const text = drawList.slice(0, drawCount).filter((b) => b.program === PROGRAM.drawingLabel);
    expect(bench.drawings.labels.runCount).toBe(250);
    expect([text.length, backend.trace.draws]).toEqual([1, 3]);
    expect(bench.drawings.metrics().textDrawCalls).toBeLessThanOrEqual(3);
    bench.run();
    expect([backend.trace.draws, bench.drawings.metrics().textDrawCalls]).toEqual([3, 1]);
  });
});

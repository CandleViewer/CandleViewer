// E11-S11 PR B: glyph runs, the atlas metrics (S06's TextMeasure), the text batch's instances and
// its three modes, the shaders' layout, and outline contrast over every delta-ramp endpoint.
import { describe, expect, it } from "vitest";
import { mulberry32 } from "../../bench/fixtures/rng.mjs";
import { buildAtlas } from "../../bench/scenes/atlas-build.js";
import { PROGRAMS } from "../../src/gl/program-cache.js";
import { INSTANCE_LAYOUTS, PROGRAM } from "../../src/scene/instance-layout.js";
import { PooledBatchSink } from "../../src/scene/pool.js";
import { METRIC_STRIDE } from "../../src/text/atlas-build.js";
import { outlineContrast } from "../../src/text/contrast.js";
import { AtlasMetrics, RUN_CACHE_MAX, SIZE_CLASS, SIZE_PX } from "../../src/text/glyph-runs.js";
import { TEXT_STRIDE, TextBatch, type TextInk } from "../../src/text/text-batch.js";
import RAMP from "./fixtures/ramp-endpoints.json" with { type: "json" };

const image = buildAtlas();
const ink: TextInk = { rgba: Float32Array.of(0.1, 0.2, 0.3, 1), css: "#1a334d" };

describe("glyph runs (BQ-269)", () => {
  it("a string is built once: later lookups are hits, the same run", () => {
    const m = new AtlasMetrics(image);
    const a = m.run("64,050.5");
    expect([a.count, m.run("64,050.5"), m.counters.runMisses]).toEqual([8, a, 1]);
    const adv = Array.from(m.advances.subarray(a.start, a.start + a.count));
    expect(a.width).toBeCloseTo(
      adv.reduce((s, v) => s + v, 0),
      6,
    );
  });

  it("an out-of-set character draws `?` from the same family and is counted", () => {
    const m = new AtlasMetrics(image);
    const q = m.run("?");
    const r = m.run("1€2");
    expect(m.ids[r.start + 1]).toBe(m.ids[q.start]);
    expect(m.counters.replacedGlyphs).toBe(1);
    expect(() => new AtlasMetrics(image, undefined, true).run("€")).toThrow(/not in set/);
  });

  it("the cache is bounded: the oldest run leaves first; a full arena drops every run", () => {
    const m = new AtlasMetrics(image);
    for (let i = 0; i <= RUN_CACHE_MAX; i += 1) m.run(`${i}`);
    m.run(`${RUN_CACHE_MAX}`);
    expect(m.counters.runMisses).toBe(RUN_CACHE_MAX + 1);
    m.run("0"); // evicted
    expect(m.counters.runMisses).toBe(RUN_CACHE_MAX + 2);
    const big = new AtlasMetrics(image);
    for (let i = 0; i < 5; i += 1) big.run(String(i).repeat(8000));
    expect(big.counters.flushes).toBe(1);
  });

  it("a run held across a flush is stale: `live` rebuilds it from its string, never other slots", () => {
    const m = new AtlasMetrics(image);
    const held = m.run("64,050.5");
    const ids = Array.from(m.ids.subarray(held.start, held.start + held.count));
    for (let i = 0; i < 5; i += 1) m.run(String(i).repeat(8000)); // flushes, overwrites slot 0..
    expect(m.counters.flushes).toBe(1);
    expect(held.generation).not.toBe(m.generation);
    const now = m.live(held);
    expect(now.generation).toBe(m.generation);
    expect(Array.from(m.ids.subarray(now.start, now.start + now.count))).toEqual(ids);
    expect(m.live(now)).toBe(now);
    const strict = new AtlasMetrics(image, undefined, true);
    const old = strict.run("1");
    for (let i = 0; i < 5; i += 1) strict.run(String(i).repeat(8000));
    expect(() => strict.live(old)).toThrow(/stale/);
  });

  it("a string longer than the arena: one miss, cached under the whole string", () => {
    const m = new AtlasMetrics(image);
    const long = "1".repeat(RUN_CACHE_MAX * 8 + 5);
    const r = m.run(long);
    expect([r.count, m.counters.runMisses, m.run(long), m.counters.runMisses]).toEqual([
      RUN_CACHE_MAX * 8,
      1,
      r,
      1,
    ]);
  });

  it("metrics that do not match the glyph table are refused at construction", () => {
    const short = { ...image, metrics: image.metrics.subarray(0, METRIC_STRIDE) };
    expect(() => new AtlasMetrics(short)).toThrow(/do not match/);
  });

  it("measure: advances sum to the measured width within 0.5 px, for any string of the set", () => {
    const m = new AtlasMetrics(image);
    const rnd = mulberry32(336);
    const chars = "0123456789.,-+% :ADFJMNOSabceglnoprtuvy";
    for (let i = 0; i < 500; i += 1) {
      const text = Array.from({ length: 1 + Math.floor(rnd() * 12) }, () =>
        chars.charAt(Math.floor(rnd() * chars.length)),
      ).join("");
      const cls = i % 3;
      const glyphs = [...text].map((c) => m.run(c).width).reduce((s, v) => s + v, 0);
      const want = (glyphs * (SIZE_PX[cls as 0] ?? 0)) / m.rasterPx(0);
      expect(Math.abs(m.measure(text, cls) - want)).toBeLessThanOrEqual(0.5);
    }
    expect(m.measureFor(1)).toBe(m.measureFor(1));
    expect(m.measureFor(1).height).toBe(13); // 11 px × 1.2
    expect(SIZE_CLASS).toEqual({ xs: 0, sm: 1, md: 2 }); // C-103: §8 unchanged
  });
});

describe("the text batch (BQ-267, BQ-268)", () => {
  const glyphs = (): TextBatch => {
    const t = new TextBatch("t");
    t.mode = "glyphs";
    t.metrics = new AtlasMetrics(image);
    return t;
  };

  it("writes stride-12 instances: device px y up, the UV rect flipped, the colour per glyph", () => {
    const t = glyphs();
    t.begin(2, 200);
    t.label("1", 10, 50, 1, 0, ink);
    const m = t.metrics as AtlasMetrics;
    const s = (m.ids[m.run("1").start] as number) * METRIC_STRIDE;
    const [x, y, w, h, , bx, by] = Array.from(image.metrics.subarray(s, s + 7)) as number[];
    const scale = (11 * 2) / m.rasterPx(0);
    const top = (50 + 0.36 * 11) * 2 + (by as number) * scale;
    const want = [20 + (bx as number) * scale, 200 - top - (h as number) * scale];
    expect(Array.from(t.data.subarray(0, 2))).toEqual(want.map(Math.fround));
    expect(t.data[2]).toBeCloseTo((w as number) * scale, 4);
    expect(t.data[5]).toBeCloseTo(((y as number) + (h as number)) / image.height, 6);
    expect(t.data[7]).toBeCloseTo(-(h as number) / image.height, 6);
    expect(t.data[4]).toBeCloseTo((x as number) / image.width, 6);
    expect(Array.from(t.data.subarray(8, 12))).toEqual(Array.from(ink.rgba));
    expect(t.count).toBe(1);
  });

  it("centre and right alignment move the pen by half and all of the run's width", () => {
    const at = (align: number): number => {
      const t = glyphs();
      t.begin(1, 100);
      t.label("88", 100, 50, 1, align, ink);
      return t.data[0] as number;
    };
    const width = (glyphs().metrics as AtlasMetrics).measure("88", 1);
    expect(at(0) - at(0.5)).toBeCloseTo(width / 2, 3);
    expect(at(0) - at(1)).toBeCloseTo(width, 3);
  });

  it("collect: one entry on the atlas texture in glyphs mode; none drawn when off", () => {
    const sink = new PooledBatchSink(4);
    const t = glyphs();
    t.begin(1, 100);
    t.label("12:30", 0, 10, 1, 0, ink);
    t.collect(sink);
    const off = new TextBatch("off");
    off.begin(1, 100);
    off.label("12:30", 0, 10, 1, 0, ink);
    off.collect(sink);
    const [a, b] = [sink.at(0), sink.at(1)];
    expect([a.program, a.texture, a.count]).toEqual([PROGRAM.sdfText, 1, 5]);
    expect([b.count, off.labels]).toEqual([0, 0]);
  });

  it("labels mode records each string, its place in device px and its ink for fillText", () => {
    const t = new TextBatch("t");
    t.mode = "labels";
    t.begin(2, 100);
    t.label("Oct", 30, 40, 2, 0.5, ink);
    expect([t.labels, t.texts[0], t.inks[0], t.count]).toEqual([1, "Oct", ink.css, 0]);
    expect(Array.from(t.lab.subarray(0, 4))).toEqual([60, 80, 26, 0.5]);
  });

  it("formatting is not per-frame work: 60 frames of the same labels build no run, grow nothing", () => {
    const t = glyphs();
    const m = t.metrics as AtlasMetrics;
    const labels = ["64,050.5", "64,051.0", "13:30", "14 Oct", "2026"];
    const frame = (dx: number): void => {
      t.begin(1, 600);
      labels.forEach((s, i) => t.label(s, 10 + dx, 20 * i, 1, 0, ink));
    };
    frame(0);
    const [misses, grown] = [m.counters.runMisses, t.grown];
    for (let f = 1; f <= 60; f += 1) frame(f);
    expect([m.counters.runMisses - misses, t.grown - grown]).toEqual([0, 0]);
  });
});

describe("the text programs (BQ-267, C-100, C-101)", () => {
  it("both read a stride-12 instance: rect, uv and colour; no u_color, the fwidth band", () => {
    for (const p of [PROGRAM.sdfText, PROGRAM.sdfTextOutline]) {
      expect(INSTANCE_LAYOUTS[p]?.stride).toBe(TEXT_STRIDE);
      const src = PROGRAMS[p];
      expect(src?.fragment).toContain("fwidth(d)");
      expect(src?.uniforms).not.toContain("u_color");
    }
    expect(PROGRAMS[PROGRAM.sdfTextOutline]?.fragment).toContain("u_outlineColor");
  });
});

describe("Numbers stay legible over saturated fills (BQ-274, G-86)", () => {
  it.each(Object.entries(RAMP.themes))("%s: >= 4.5:1 over every ramp endpoint", (_, t) => {
    for (const fill of t.fills) {
      expect(outlineContrast(t.text, t.outline, RAMP.alpha, fill)).toBeGreaterThanOrEqual(4.5);
    }
  });
  it("the outline is what carries it: the bare text fails on a saturated fill (E06-D01 §5)", () => {
    const d = RAMP.themes.dark;
    expect(outlineContrast(d.text, d.outline, 0, d.fills[0] as string)).toBeLessThan(4.5);
  });
  it.todo(
    "golden images: glyph × class × DPR and the outline over the LUT (pending: E11-T08 #391)",
  );
});

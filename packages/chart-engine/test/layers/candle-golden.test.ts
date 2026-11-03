// E12-S06 goldens. BQ-5 (ruled): until E11-T08 (#391) ships the SwiftShader harness, a CPU
// stand-in rasterises what the Canvas2D backend paints (the geometry twin's rects, the palette
// rows as letters) and pins it as text; every real golden case is an `it.todo` that becomes a row
// on #391 (the G-16 precedent): candles and OHLC × spacings × dark / light × doji / zero-range / gap.
// E12-S07: hollow candles (the four marks of D06 §4.2) and Heikin-Ashi rows, the same way.
// E12-S10 adds the forming ring and the corrected square (E12-D06 §7.1 / §7.3).
import { describe, expect, it } from "vitest";
import { Canvas2DBackend } from "../../src/canvas2d/backend.js";
import { BarSeries, CandleRing, CandleSeries, PALETTE } from "../../src/layers/index.js";
import { BarStore } from "../../src/model/index.js";
import type { RetainedBatch } from "../../src/scene/batch-builder.js";
import { PROGRAM } from "../../src/scene/instance-layout.js";
import { ChartViewport, createPaneUniforms, writePaneUniforms } from "../../src/viewport/index.js";
import { FakeCtx2D } from "../canvas2d/fake-ctx2d.js";

/** One colour per palette row, so a raster cell names the row it was painted with. */
const THEME = {
  "color.candle.up": "#00ff00",
  "color.candle.down": "#ff0000",
  "color.candle.wick": "#808080",
  "color.surface.canvas": "#000000",
};
const W = 40;
const H = 22;

/** Up, down, doji, zero-range (a gap before it): 4 bars, 10 CSS px apart, 1 px per tick. */
const MIXED = [
  [6, 16, 4, 14],
  [14, 18, 8, 9],
  [10, 15, 5, 10],
  [10, 10, 10, 10],
];
/** D06 §4.2's four marks: hollow up (the first bar), solid down, hollow down, solid up. */
const FOUR = [
  [6, 16, 4, 14],
  [16, 18, 8, 12],
  [5, 13, 3, 11],
  [15, 17, 9, 11],
];

/**
 * The four hosts: the two bar parts, the seam, the marks. `flags` per bar (by default a gap before
 * MIXED's zero-range bar).
 */
function raster(
  shape: "candles" | "bars" | "hollow",
  rows = MIXED,
  ha = false,
  flags = [0, 0, 0, rows === MIXED ? 1 : 0],
): string[] {
  const store = new BarStore({ initialCapacity: 8 });
  const ring = new CandleRing();
  const c = shape === "bars" ? new BarSeries(ring) : new CandleSeries(ring, shape);
  const col = (k: number): Int32Array => Int32Array.from(rows, (r) => r[k] ?? 0);
  ring.sync(
    store,
    store.append({
      time: Float64Array.from(rows, (_, i) => i * 60e6),
      open: col(0),
      high: col(1),
      low: col(2),
      close: col(3),
      volume: new Float32Array(4).fill(1),
      flags: Uint8Array.from(flags),
      priceOrigin: 0,
      tickSize: 1,
    }),
  );
  if (ha) c.setKind(shape, true, store);
  const vp = new ChartViewport(store);
  vp.setSize(W, H, 1);
  vp.setPanePlot(0, 0, H);
  vp.setPriceInfo(0, 0, 1);
  vp.setPriceRange(0, 0, H);
  vp.setTimeRange(-30e6, 210e6); // 10 px a bar, every bar whole
  const block = createPaneUniforms();
  writePaneUniforms(vp, 0, block);
  block.floats[4] = W;
  block.floats[5] = H;
  c.setTheme(THEME);
  c.frame(vp.barSpacing, 1, 0, 3);
  const ctx = new FakeCtx2D();
  const be = new Canvas2DBackend(ctx);
  const ids = ["a", "b", "seam", "marks"];
  ids.forEach((id, i) => be.attach(id, c.sources[i] ?? ring));
  be.setPaneUniforms(() => block);
  be.setBatchUniforms((b) => c.blocks[ids.indexOf(b.nodeId)] ?? null);
  const list = ids.map((nodeId, i) => {
    const count = i === 2 ? c.seams.capacity : i === 3 ? c.marks.capacity : ring.capacity;
    return { nodeId, program: PROGRAM.candle, texture: 0, first: 0, count, layer: 0, seq: i };
  });
  be.submit(list as RetainedBatch[], 4, W, H);
  // A cell is the palette row it was filled with, later paths on top: U up, D down, t the up
  // tint, | neutral (wick, doji, zero-range, seam), . nothing.
  const letter = (style: string): string => {
    const rows: Record<number, string> = {
      [PALETTE.up]: "U",
      [PALETTE.down]: "D",
      [PALETTE.wick]: "|",
      [PALETTE.upTint]: "t",
    };
    for (const [row, ch] of Object.entries(rows)) {
      const p = c.palette;
      const b = (i: number): number => Math.round((p[Number(row) * 4 + i] ?? 0) * 255);
      if (style === `rgba(${b(0)}, ${b(1)}, ${b(2)}, ${b(3) / 255})`) return ch;
    }
    return "?";
  };
  const grid = Array.from({ length: H }, () => Array.from({ length: W }, () => "."));
  for (const path of ctx.paths) {
    const ch = letter(String(path.style));
    for (const r of path.parts) {
      const [x, y, w, h] = r.split(" ").slice(1).map(Number) as [number, number, number, number];
      for (let py = Math.round(y); py < Math.round(y + h); py += 1) {
        for (let px = Math.round(x); px < Math.round(x + w); px += 1) {
          const row = grid[py];
          if (row !== undefined && px >= 0 && px < W) row[px] = ch;
        }
      }
    }
  }
  return grid.map((r) => r.join(""));
}

describe("CPU stand-in raster (BQ-5): what the 2D backend paints, as text", () => {
  it("OHLC: stems and ticks by weight and colour; a neutral doji; the zero-range mark; the seam", () => {
    expect(raster("bars")).toEqual([
      "..............................|.........",
      "..............................|.........",
      "..............................|.........",
      "..............................|.........",
      "...............DD.............|.........",
      "...............DD.............|.........",
      ".....U.........DD.............|.........",
      ".....U......DDDDD........|....|.........",
      ".....UUUU...DDDDD........|....|.........",
      ".....U.........DD........|....|.........",
      ".....U.........DD........|....|.........",
      ".....U.........DD........|....|.|||||||.",
      ".....U.........DDDDD..|||||||.|.|||||||.",
      ".....U.........DDDDD.....|....|.........",
      ".....U...................|....|.........",
      ".....U...................|....|.........",
      "..UUUU...................|....|.........",
      ".....U........................|.........",
      "..............................|.........",
      "..............................|.........",
      "..............................|.........",
      "..............................|.........",
    ]);
  });

  it("candles: wicks under outlined up / solid down bodies; doji and zero-range neutral", () => {
    expect(raster("candles")).toEqual([
      "..............................|.........",
      "..............................|.........",
      "..............................|.........",
      "..............................|.........",
      "...............||.............|.........",
      "...............||.............|.........",
      ".....|.........||.............|.........",
      ".....|.........||........|....|.........",
      "..UUUUUUU...DDDDDDD......|....|.........",
      "..UtttttU...DDDDDDD......|....|.........",
      "..UtttttU...DDDDDDD......|....|.........",
      "..UtttttU...DDDDDDD...|||||||.|.|||||||.",
      "..UtttttU...DDDDDDD...|||||||.|.|||||||.",
      "..UtttttU......||........|....|.........",
      "..UtttttU................|....|.........",
      "..UUUUUUU................|....|.........",
      ".....|...................|....|.........",
      ".....|........................|.........",
      "..............................|.........",
      "..............................|.........",
      "..............................|.........",
      "..............................|.........",
    ]);
  });
});

describe("CPU stand-in raster, E12-S07: hollow candles and Heikin-Ashi", () => {
  it("hollow: the four marks, outline-only hollow bodies, wick weight by colour", () => {
    expect(raster("hollow", FOUR)).toEqual(HOLLOW);
  });

  it("Heikin-Ashi candles: the HA bars of the same data", () => {
    expect(raster("candles", FOUR, true)).toEqual(HA);
  });
});

describe("CPU stand-in raster: the forming ring and the corrected square (E12-S10)", () => {
  it("candles: a corrected down bar's square; the forming doji's dashed ring", () => {
    // The square: 3 × 3 above the down bar's high (row 4), 2 rows clear; its top row is off the
    // canvas. The ring: 1 px, 1 px clear of the doji's wick and body union, dashed 2 / 2.
    expect(raster("candles", MIXED, false, [0, 8, 2, 0])).toEqual([
      "..............|||.......................",
      "..............|||.......................",
      "........................................",
      "........................................",
      "...............||.......................",
      "...............||...||..||..||..........",
      ".....|.........||...|.........|.........",
      ".....|.........||........|....|.........",
      "..UUUUUUU...DDDDDDD......|..............",
      "..UtttttU...DDDDDDD.|....|..............",
      "..UtttttU...DDDDDDD.|....|....|.........",
      "..UtttttU...DDDDDDD...|||||||.|.|||||||.",
      "..UtttttU...DDDDDDD...|||||||...|||||||.",
      "..UtttttU......||...|....|..............",
      "..UtttttU...........|....|....|.........",
      "..UUUUUUU................|....|.........",
      ".....|...................|..............",
      ".....|..............|...................",
      "......................||..||..|.........",
      "........................................",
      "........................................",
      "........................................",
    ]);
  });

  it("Heikin-Ashi hollow (E12-S07): the marks place on the drawn HA candle", () => {
    // The square sits 2 rows above bar 2's HA high (its 2-px colour-down wick); the forming ring
    // clears bar 3's HA wick and body by one row and column (its right side is off the canvas).
    // Every other pixel is the unmarked `raster("hollow", FOUR, true)`'s (asserted below): the
    // marks only add wick-coloured pixels and never alter the bar.
    const marked = raster("hollow", FOUR, true, [0, 0, 8, 2]);
    const plain = raster("hollow", FOUR, true);
    const added: string[] = [];
    marked.forEach((row, y) =>
      [...row].forEach((ch, x) => {
        if (ch !== plain[y]?.[x]) added.push(`${x},${y}:${plain[y]?.[x]}>${ch}`);
      }),
    );
    expect(added.length).toBeGreaterThan(0);
    expect(
      added.every((d) => d.endsWith(".>|")),
      added.join(" "),
    ).toBe(true);
    expect(marked).toEqual([
      "........................................",
      "........................................",
      "........................................",
      "..............................||..||..||",
      "...............|........|||...|.........",
      "...............|........|||........|....",
      ".....|.........|........|||........|....",
      ".....|.........|..............|....|....",
      ".....|......UUUUUUU...........|....|....",
      ".....|......U..|..U......||.....UUUUUUU.",
      ".....|......U..|..U...DDDDDDD...U..|..U.",
      "..UUUUUUU...UUUUUUU...DDDDDDD.|.UUUUUUU.",
      "..UUUUUUU......|......DDDDDDD.|....|....",
      ".....|.........|......DDDDDDD...........",
      ".....|...................||...||..||..||",
      ".....|...................||.............",
      ".....|...................||.............",
      ".....|...................||.............",
      ".........................||.............",
      "........................................",
      "........................................",
      "........................................",
    ]);
  });
});

describe("goldens on the SwiftShader harness (E11-T08 #391 rows; BQ-5)", () => {
  for (const kind of ["hollow candles", "Heikin-Ashi candles", "Heikin-Ashi hollow"]) {
    for (const spacing of [2, 3, 12, 48]) {
      for (const theme of ["dark", "light"]) {
        it.todo(`${kind} at ${spacing} px, ${theme} theme: the four marks (golden, ≤ 0.1 % diff)`);
      }
    }
  }
  for (const shape of ["candles", "OHLC bars"]) {
    for (const spacing of [3, 5, 12, 48]) {
      for (const theme of ["dark", "light"]) {
        for (const c of ["doji", "zero-range", "gap seam", "forming ring", "corrected square"]) {
          it.todo(`${shape} at ${spacing} px, ${theme} theme: ${c} (golden, ≤ 0.1 % pixel diff)`);
        }
      }
    }
  }
});

// U / D the up / down colour, t the up tint, | neutral, . unpainted (a hollow body's interior).
const HOLLOW = [
  "........................................",
  "........................................",
  "........................................",
  "........................................",
  "...............||.......................",
  "...............||..................|....",
  ".....|......DDDDDDD................|....",
  ".....|......DDDDDDD.............UUUUUUU.",
  "..UUUUUUU...DDDDDDD.............UUUUUUU.",
  "..U..|..U...DDDDDDD......||.....UUUUUUU.",
  "..U..|..U......||........||.....UUUUUUU.",
  "..U..|..U......||.....DDDDDDD......|....",
  "..U..|..U......||.....D..||.D......|....",
  "..U..|..U......||.....D..||.D...........",
  "..U..|..U.............D..||.D...........",
  "..UUUUUUU.............D..||.D...........",
  ".....|................DDDDDDD...........",
  ".....|...................||.............",
  ".........................||.............",
  "........................................",
  "........................................",
  "........................................",
];
const HA = [
  "........................................",
  "........................................",
  "........................................",
  "........................................",
  "...............|........................",
  "...............|...................|....",
  ".....|.........|...................|....",
  ".....|.........|...................|....",
  ".....|......UUUUUUU................|....",
  ".....|......UtttttU......||.....UUUUUUU.",
  ".....|......UtttttU...DDDDDDD...UtttttU.",
  "..|||||||...UUUUUUU...DDDDDDD...UUUUUUU.",
  "..|||||||......|......DDDDDDD......|....",
  ".....|.........|......DDDDDDD...........",
  ".....|...................||.............",
  ".....|...................||.............",
  ".....|...................||.............",
  ".....|...................||.............",
  ".........................||.............",
  "........................................",
  "........................................",
  "........................................",
];

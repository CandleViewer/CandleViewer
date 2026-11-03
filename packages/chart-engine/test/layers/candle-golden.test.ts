// E12-S06 goldens. BQ-5 (ruled): until E11-T08 (#391) ships the SwiftShader harness, a CPU
// stand-in rasterises what the Canvas2D backend paints (the geometry twin's rects, the palette
// rows as letters) and pins it as text; every real golden case is an `it.todo` that becomes a row
// on #391 (the G-16 precedent): candles and OHLC × spacings × dark / light × doji / zero-range / gap.
// E12-S07: hollow candles (the four marks of D06 §4.2) and Heikin-Ashi rows, the same way.
// E12-S09: the L1 mark, the L2 column with two spikes, and the forming bar at L2 (rows on #391).
import { describe, expect, it } from "vitest";
import { Canvas2DBackend } from "../../src/canvas2d/backend.js";
import {
  BarSeries,
  CandleRing,
  CandleSeries,
  ColumnEntries,
  foldEnd,
  PALETTE,
} from "../../src/layers/index.js";
import { BAR_FLAG, BarStore } from "../../src/model/index.js";
import type { RetainedBatch } from "../../src/scene/batch-builder.js";
import { PROGRAM } from "../../src/scene/instance-layout.js";
import { ChartViewport, createPaneUniforms, writePaneUniforms } from "../../src/viewport/index.js";
import { FakeCtx2D } from "../canvas2d/fake-ctx2d.js";
import { columnOf, foldOracle, rowsBatch } from "./column-oracle.js";

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

function raster(shape: "candles" | "bars" | "hollow", rows = MIXED, ha = false): string[] {
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
      flags: Uint8Array.of(0, 0, 0, rows === MIXED ? 1 : 0),
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
  const ids = ["a", "b", "seam"];
  ids.forEach((id, i) => be.attach(id, c.sources[i] ?? ring));
  be.setPaneUniforms(() => block);
  be.setBatchUniforms((b) => c.blocks[ids.indexOf(b.nodeId)] ?? null);
  const list = ids.map((nodeId, i) => {
    const count = i === 2 ? c.seams.capacity : ring.capacity;
    return { nodeId, program: PROGRAM.candle, texture: 0, first: 0, count, layer: 0, seq: i };
  });
  be.submit(list as RetainedBatch[], 3, W, H);
  return gridOf(ctx, c.palette);
}

/**
 * The painted paths as text. A cell is the palette row it was filled with, later paths on top: U
 * up, D down, t the up tint, | neutral (wick, doji, zero-range, seam), n the neutral tint (an L2
 * column, E12-S09), . nothing.
 */
function gridOf(ctx: FakeCtx2D, p: Float32Array): string[] {
  const letter = (style: string): string => {
    const rows: Record<number, string> = {
      [PALETTE.up]: "U",
      [PALETTE.down]: "D",
      [PALETTE.wick]: "|",
      [PALETTE.upTint]: "t",
      [PALETTE.neutral]: "n",
    };
    for (const [row, ch] of Object.entries(rows)) {
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

/**
 * E12-S09: the candle series at L1 (2 px a bar) or L2 (0.5 px: 2 bars a column, the oracle's
 * columns as `ColumnEntries`, the forming bar its own entry), painted by the 2D backend.
 */
function rasterLod(tier: 1 | 2, rows: readonly (readonly number[])[], forming = false): string[] {
  const store = new BarStore({ initialCapacity: 64 });
  const ring = new CandleRing();
  const c = new CandleSeries(ring);
  const flags = new Uint8Array(rows.length);
  if (forming) flags[rows.length - 1] = BAR_FLAG.forming;
  ring.sync(store, store.append(rowsBatch(rows, flags)));
  const vp = new ChartViewport(store);
  vp.setSize(W, H, 1);
  vp.setPanePlot(0, 0, H);
  vp.setPriceInfo(0, 0, 1);
  vp.setPriceRange(0, 0, H);
  const s = tier === 1 ? 2 : 0.5;
  vp.setTimeRange(0, (W / s - 1) * 60e6);
  const block = createPaneUniforms();
  writePaneUniforms(vp, 0, block);
  block.floats[4] = W;
  block.floats[5] = H;
  c.setTheme(THEME);
  const entries = new ColumnEntries(W);
  const last = store.length - 1;
  entries.write(foldOracle(store, vp.leftIndex, s, foldEnd(store), W), store, columnOf(last, 0, s));
  c.frame(vp.barSpacing, 1, 0, last, 0, 0, tier, entries);
  const ctx = new FakeCtx2D();
  const be = new Canvas2DBackend(ctx);
  const ids = ["a", "b"];
  ids.forEach((id) => be.attach(id, tier === 2 ? entries : ring));
  be.setPaneUniforms(() => block);
  be.setBatchUniforms((b) => c.blocks[ids.indexOf(b.nodeId)] ?? null);
  const list = ids.map((nodeId, i) => {
    return { nodeId, program: PROGRAM.candle, texture: 0, first: 0, count: 64, layer: 0, seq: i };
  });
  be.submit(list as RetainedBatch[], 2, W, H);
  return gridOf(ctx, c.palette);
}

/** 20 bars, 2 px apart: up, down and doji, rising then falling. */
const L1_ROWS = Array.from({ length: 20 }, (_, i) => {
  const m = 6 + (i < 10 ? i : 19 - i);
  const dir = i % 3; // 0 up, 1 down, 2 doji
  return [m, m + 3, m - 3, dir === 0 ? m + 2 : dir === 1 ? m - 2 : m];
});
/** 80 flat bars at 0.5 px (40 columns), one high spike and one low spike. */
const SPIKE_ROWS = Array.from({ length: 80 }, (_, i) =>
  i === 23 ? [10, 21, 9, 11] : i === 58 ? [11, 12, 1, 10] : [10 + (i % 2), 12, 9, 11 - (i % 2)],
);

describe("CPU stand-in raster, E12-S09: the L1 mark and the L2 column", () => {
  it("L1: hairline wicks, down bodies solid, 1 px up bodies dash.1-1, dojis neutral", () => {
    expect(rasterLod(1, L1_ROWS)).toEqual(L1);
  });

  it("L2: one neutral column per device px with its span; both spikes reach the column", () => {
    expect(rasterLod(2, SPIKE_ROWS)).toEqual(L2_SPIKE);
  });

  it("L2: the forming bar is its own entry, drawn over its column, never folded", () => {
    const rows = SPIKE_ROWS.slice(0, 79).concat([[10, 20, 3, 18]]);
    expect(rasterLod(2, rows, true)).toEqual(L2_FORMING);
  });
});

describe("goldens on the SwiftShader harness (E11-T08 #391 rows; BQ-5)", () => {
  for (const mark of ["L1 hairline mark", "L2 column", "L2 spike", "L2 forming bar"]) {
    for (const dpr of [1, 1.5, 2]) {
      for (const theme of ["dark", "light"]) {
        it.todo(`E12-S09 ${mark} at dpr ${dpr}, ${theme} theme (golden, ≤ 0.1 % pixel diff)`);
      }
    }
  }
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
        for (const c of ["doji", "zero-range", "gap seam"]) {
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
const L1 = [
  "........................................",
  "........................................",
  "........................................",
  "........................................",
  "..................|..|..................",
  "................|.U..|.|................",
  "..............|.|.|..|.|.|..............",
  "............|.|.|.|..D.|.U.|............",
  "..........|.|.|.|.|..D.|.|.|.|..........",
  "........|.|.U.D.|.|..|.|.|.|.|.|........",
  "......|.|.|.|.D.|......|.|.D.|.|.|......",
  "....|.U.|.|.|.|..........|.D.|.U.|.|....",
  "..|.|.|.D.|.|..............|.|.|.|.|.|..",
  "|.|.|.|.D.|..................|.|.D.|.U..",
  "|.|.|.|.|......................|.D.|.|..",
  "U.D.|.|..........................|.|.|..",
  "|.D.|..............................|.|..",
  "|.|..................................|..",
  "|.......................................",
  "........................................",
  "........................................",
  "........................................",
];
const L2_SPIKE = [
  "........................................",
  "...........n............................",
  "...........n............................",
  "...........n............................",
  "...........n............................",
  "...........n............................",
  "...........n............................",
  "...........n............................",
  "...........n............................",
  "...........n............................",
  "nnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnn",
  "nnnnnnnnnnnUnnnnnnnnnnnnnnnnnDnnnnnnnnnn",
  "|||||||||||n|||||||||||||||||n||||||||||",
  ".............................n..........",
  ".............................n..........",
  ".............................n..........",
  ".............................n..........",
  ".............................n..........",
  ".............................n..........",
  ".............................n..........",
  ".............................n..........",
  "........................................",
];
const L2_FORMING = [
  "........................................",
  "...........n............................",
  "...........n...........................n",
  "...........n...........................n",
  "...........n...........................n",
  "...........n...........................U",
  "...........n...........................n",
  "...........n...........................U",
  "...........n...........................n",
  "...........n...........................U",
  "nnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnn",
  "nnnnnnnnnnnUnnnnnnnnnnnnnnnnnDnnnnnnnnnU",
  "|||||||||||n|||||||||||||||||n|||||||||n",
  ".............................n.........n",
  ".............................n.........n",
  ".............................n.........n",
  ".............................n.........n",
  ".............................n.........n",
  ".............................n.........n",
  ".............................n..........",
  ".............................n..........",
  "........................................",
];

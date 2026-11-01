// E12-S06 goldens. BQ-5 (ruled): until E11-T08 (#391) ships the SwiftShader harness, a CPU
// stand-in rasterises what the Canvas2D backend paints (the geometry twin's rects, the palette
// rows as letters) and pins it as text; every real golden case is an `it.todo` that becomes a row
// on #391 (the G-16 precedent): candles and OHLC × spacings × dark / light × doji / zero-range / gap.
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
function raster(shape: "candles" | "bars"): string[] {
  const store = new BarStore({ initialCapacity: 8 });
  const ring = new CandleRing();
  const c = shape === "bars" ? new BarSeries(ring) : new CandleSeries(ring);
  const open = Int32Array.of(6, 14, 10, 10);
  ring.sync(
    store,
    store.append({
      time: Float64Array.from(open, (_, i) => i * 60e6),
      open,
      high: Int32Array.of(16, 18, 15, 10),
      low: Int32Array.of(4, 8, 5, 10),
      close: Int32Array.of(14, 9, 10, 10),
      volume: new Float32Array(4).fill(1),
      flags: Uint8Array.of(0, 0, 0, 1),
      priceOrigin: 0,
      tickSize: 1,
    }),
  );
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

describe("goldens on the SwiftShader harness (E11-T08 #391 rows; BQ-5)", () => {
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

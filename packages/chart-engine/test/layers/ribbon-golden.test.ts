// E12-S07 PR B goldens. BQ-5 (ruled): until E11-T08 (#391) ships the SwiftShader harness, a CPU
// stand-in rasterises what the Canvas2D backend paints for the line family (the twin's polygons,
// each pixel centre tested with the nonzero rule, the palette rows as letters) and pins it as
// text; every real golden case is an `it.todo` that becomes a row on #391 (the G-16 precedent).
import { describe, expect, it } from "vitest";
import { Canvas2DBackend } from "../../src/canvas2d/backend.js";
import {
  CandleRing,
  RIBBON_PALETTE,
  type RibbonKind,
  RibbonSeries,
} from "../../src/layers/index.js";
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
  "color.chart.line": "#ff00ff",
};
const W = 40;
const H = 22;
/** Five closes 8 px apart, 1 px per tick; a gap before the fourth bar (R-2). */
const CLOSES = [6, 16, 10, 14, 4];

function raster(kind: RibbonKind, gap = false, base: number | null = null): string[] {
  const store = new BarStore({ initialCapacity: 8 });
  const ring = new CandleRing();
  const close = Int32Array.from(CLOSES);
  ring.sync(
    store,
    store.append({
      time: Float64Array.from(CLOSES, (_, i) => i * 60e6),
      open: close.slice(),
      high: close.map((c) => c + 1),
      low: close.map((c) => c - 1),
      close,
      volume: new Float32Array(5).fill(1),
      flags: Uint8Array.of(0, 0, 0, gap ? 1 : 0, 0),
      priceOrigin: 0,
      tickSize: 1,
    }),
  );
  const r = new RibbonSeries(ring, kind);
  r.baseTick = base;
  const vp = new ChartViewport(store);
  vp.setSize(W, H, 1);
  vp.setPanePlot(0, 0, H);
  vp.setPriceInfo(0, 0, 1);
  vp.setPriceRange(0, 0, H);
  vp.setTimeRange(-30e6, 270e6); // 8 px a bar
  const block = createPaneUniforms();
  writePaneUniforms(vp, 0, block);
  block.floats[4] = W;
  block.floats[5] = H;
  r.setTheme(THEME);
  r.frame(vp.barSpacing, 1, 0);
  const ctx = new FakeCtx2D();
  const be = new Canvas2DBackend(ctx);
  const ids = r.blocks.map((_, i) => `h${i}`);
  for (const id of ids) be.attach(id, r.source);
  be.setPaneUniforms(() => block);
  be.setBatchUniforms((b) => r.blocks[ids.indexOf(b.nodeId)] ?? null);
  const list = ids.map((nodeId, i) => {
    return { nodeId, program: PROGRAM.ribbon, texture: 0, first: 0, count: 8, layer: 0, seq: i };
  });
  be.submit(list as RetainedBatch[], ids.length, W, H);
  // A cell is the palette row it was filled with, later paths on top: L the line, a the area
  // tint, u / d the baseline's up / down tints, | the base line, . nothing.
  const LETTERS: Record<number, string> = {
    [RIBBON_PALETTE.line]: "L",
    [RIBBON_PALETTE.area]: "a",
    [RIBBON_PALETTE.above]: "u",
    [RIBBON_PALETTE.below]: "d",
    [RIBBON_PALETTE.base]: "|",
  };
  const letter = (style: string): string => {
    for (const [row, ch] of Object.entries(LETTERS)) {
      const p = r.palette;
      const b = (i: number): number => Math.round((p[Number(row) * 4 + i] ?? 0) * 255);
      if (style === `rgba(${b(0)}, ${b(1)}, ${b(2)}, ${b(3) / 255})`) return ch;
    }
    return "?";
  };
  const grid = Array.from({ length: H }, () => Array.from({ length: W }, () => "."));
  for (const path of ctx.paths) {
    const ch = letter(String(path.style));
    const polys: number[][][] = [];
    for (const part of path.parts) {
      const [op, x, y] = part.split(" ");
      if (op === "moveTo") polys.push([]);
      polys[polys.length - 1]?.push([Number(x), Number(y)]);
    }
    for (let py = 0; py < H; py += 1) {
      for (let px = 0; px < W; px += 1) {
        if (winding(polys, px + 0.5, py + 0.5) !== 0) (grid[py] as string[])[px] = ch;
      }
    }
  }
  return grid.map((row) => row.join(""));
}

/** The nonzero winding number of (x, y) over closed polygons (a canvas `fill`). */
function winding(polys: number[][][], x: number, y: number): number {
  let w = 0;
  for (const poly of polys) {
    for (let i = 0; i < poly.length; i += 1) {
      const [ax = 0, ay = 0] = poly[i] ?? [];
      const [bx = 0, by = 0] = poly[(i + 1) % poly.length] ?? [];
      const cross = (bx - ax) * (y - ay) - (x - ax) * (by - ay);
      if (ay <= y && by > y && cross > 0) w += 1;
      else if (ay > y && by <= y && cross < 0) w -= 1;
    }
  }
  return w;
}

describe("CPU stand-in raster (BQ-5), E12-S07 PR B: line, area and baseline as text", () => {
  it("line: the 2 px polyline, round joins, the last-point disc", () => {
    expect(raster("line")).toEqual(LINE);
  });

  it("line across a gap (R-2): never bridged", () => {
    expect(raster("line", true)).toEqual(LINE_GAP);
  });

  it("area: the line over its 16 % fill to the plot's bottom edge, closed at the gap", () => {
    expect(raster("area", true)).toEqual(AREA_GAP);
  });

  it("baseline at the first close: up tint above B, down tint below, the neutral base line", () => {
    expect(raster("baseline")).toEqual(BASELINE);
  });

  it("baseline at a user B crossing every segment: the split exactly at each crossing", () => {
    expect(raster("baseline", false, 11)).toEqual(BASELINE_USER);
  });
});

describe("goldens on the SwiftShader harness (E11-T08 #391 rows; BQ-5)", () => {
  for (const kind of ["line", "area", "baseline"]) {
    for (const spacing of [0.6, 1.5, 3, 12, 48]) {
      for (const theme of ["dark", "light"]) {
        it.todo(`${kind} at ${spacing} px, ${theme} theme (golden, ≤ 0.1 % pixel diff)`);
      }
    }
    it.todo(`${kind} across a coverage gap: no bridge, fills closed at the break (golden)`);
  }
  for (const side of ["above", "below", "crossing"]) {
    it.todo(`baseline with the line ${side} B at dpr 1, 1.5 and 2 (golden)`);
  }
});

// L the line, a the area tint, u / d the baseline's up / down tints, | the base line, . nothing.
const LINE: string[] = [
  "........................................",
  "........................................",
  "........................................",
  "........................................",
  "........................................",
  "...........LL...........................",
  "..........LLLL..........................",
  "..........LLLLLL...........LL...........",
  ".........LL...LLL........LLLLL..........",
  "........LL.....LLL.....LLLL.LL..........",
  ".......LLL......LLLL.LLLL....LL.........",
  "......LLL.........LLLLL.......LL........",
  "......LL...........LL.........LLL.......",
  ".....LL........................LLL......",
  "....LL..........................LL......",
  "...LLL...........................LLLLL..",
  "...LL............................LLLLLL.",
  ".................................LLLLLL.",
  ".................................LLLLLL.",
  ".................................LLLLLL.",
  "..................................LLLL..",
  "........................................",
];
const LINE_GAP: string[] = [
  "........................................",
  "........................................",
  "........................................",
  "........................................",
  "........................................",
  "...........LL...........................",
  "..........LLLL..........................",
  "..........LLLLLL...........LL...........",
  ".........LL...LLL..........LLL..........",
  "........LL.....LLL..........LL..........",
  ".......LLL......LLLL.........LL.........",
  "......LLL.........LLL.........LL........",
  "......LL...........LL.........LLL.......",
  ".....LL........................LLL......",
  "....LL..........................LL......",
  "...LLL...........................LLLLL..",
  "...LL............................LLLLLL.",
  ".................................LLLLLL.",
  ".................................LLLLLL.",
  ".................................LLLLLL.",
  "..................................LLLL..",
  "........................................",
];
const AREA_GAP: string[] = [
  "........................................",
  "........................................",
  "........................................",
  "........................................",
  "........................................",
  "...........LL...........................",
  "..........LLLL..........................",
  "..........LLLLLL...........LL...........",
  ".........LLaaaLLL..........LLL..........",
  "........LLaaaaaLLL..........LL..........",
  ".......LLLaaaaaaLLLL........aLL.........",
  "......LLLaaaaaaaaaLLL.......aaLL........",
  "......LLaaaaaaaaaaaLL.......aaLLL.......",
  ".....LLaaaaaaaaaaaaa........aaaLLL......",
  "....LLaaaaaaaaaaaaaa........aaaaLL......",
  "...LLLaaaaaaaaaaaaaa........aaaaaLLLLL..",
  "...LLaaaaaaaaaaaaaaa........aaaaaLLLLLL.",
  "....aaaaaaaaaaaaaaaa........aaaaaLLLLLL.",
  "....aaaaaaaaaaaaaaaa........aaaaaLLLLLL.",
  "....aaaaaaaaaaaaaaaa........aaaaaLLLLLL.",
  "....aaaaaaaaaaaaaaaa........aaaaaaLLLL..",
  "....aaaaaaaaaaaaaaaa........aaaaaaaa....",
];
const BASELINE: string[] = [
  "........................................",
  "........................................",
  "........................................",
  "........................................",
  "........................................",
  "...........LL...........................",
  "..........LLLL..........................",
  "..........LLLLLL...........LL...........",
  ".........LLuuuLLL........LLLLL..........",
  "........LLuuuuuLLL.....LLLLuLL..........",
  ".......LLLuuuuuuLLLL.LLLLuuuuLL.........",
  "......LLLuuuuuuuuuLLLLLuuuuuuuLL........",
  "......LLuuuuuuuuuuuLLuuuuuuuuuLLL.......",
  ".....LLuuuuuuuuuuuuuuuuuuuuuuuuLLL......",
  "....LLuuuuuuuuuuuuuuuuuuuuuuuuuuLL......",
  "...LLLuuuuuuuuuuuuuuuuuuuuuuuuuuuLLLLL..",
  "|||LL||||||||||||||||||||||||||||LLLLLL|",
  ".................................LLLLLL.",
  ".................................LLLLLL.",
  ".................................LLLLLL.",
  "..................................LLLL..",
  "........................................",
];
const BASELINE_USER: string[] = [
  "........................................",
  "........................................",
  "........................................",
  "........................................",
  "........................................",
  "...........LL...........................",
  "..........LLLL..........................",
  "..........LLLLLL...........LL...........",
  ".........LLuuuLLL........LLLLL..........",
  "........LLuuuuuLLL.....LLLLuLL..........",
  ".......LLLuuuuuuLLLL.LLLLuuuuLL.........",
  "||||||LLL|||||||||LLLLL|||||||LL||||||||",
  "....ddLL...........LL.........LLLddd....",
  "....dLL........................LLLdd....",
  "....LL..........................LLdd....",
  "...LLL...........................LLLLL..",
  "...LL............................LLLLLL.",
  ".................................LLLLLL.",
  ".................................LLLLLL.",
  ".................................LLLLLL.",
  "..................................LLLL..",
  "........................................",
];

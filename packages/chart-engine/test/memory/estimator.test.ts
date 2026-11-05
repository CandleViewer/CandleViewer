// E11-S15 PR-1: estimateLoad (26 §7/§8, BQ-S15-05/06). The calibration cases build the real
// allocators (BarStore, FootprintStore, HeatmapRing, GlBuffers, GlTextures on the fake GL) and hold
// the estimate within ±20 % of what they charge; the rows with an allocator match it exactly. The
// property cases are seeded mulberry32 loops (fast-check is not in the lockfile, README BQ-30).
import { describe, expect, it } from "vitest";
import { mulberry32 } from "../../bench/fixtures/rng.mjs";
import { GlBuffers } from "../../src/gl/buffers.js";
import { GlRegistry } from "../../src/gl/registry.js";
import { GlTextures } from "../../src/gl/textures.js";
import {
  DEFAULT_LOOKBACK_DAYS,
  estimateLoad,
  MAX_BARS_CEILING,
  MEMORY_BUDGET_CEILING_MB,
  MEMORY_BUDGET_FLOOR_MB,
  type LoadEstimate,
  type LoadEstimateParams,
} from "../../src/memory/index.js";
import { barSlots, ESTIMATE_ITEMS } from "../../src/memory/Estimator.js";
import { CandleRing } from "../../src/layers/candle/ring.js";
import { BAR_BYTES } from "../../src/model/BarStore.js";
import { BarStore, FootprintStore, HeatmapRing } from "../../src/model/index.js";
import { DEFAULT_MAX_CELLS } from "../../src/model/FootprintStore.js";
import type { RetainedBatch } from "../../src/scene/batch-builder.js";
import { FakeGl } from "../gl/fake-gl.js";
import { bars } from "../model/fixtures.js";

const MIB = 2 ** 20;
type Item = (typeof ESTIMATE_ITEMS)[number];
const byItem = (e: LoadEstimate): Record<Item, number> =>
  Object.fromEntries(e.items.map((i) => [i.item, i.bytes])) as Record<Item, number>;

/** A footprint batch of `n` bars × `k` cells, prices increasing within each bar. */
function footprint(n: number, k: number) {
  const cells = n * k;
  const price = new Int32Array(cells);
  for (let i = 0; i < cells; i += 1) price[i] = i % k;
  return {
    barIndexOffsets: Uint32Array.from({ length: n + 1 }, (_, b) => b * k),
    cellPriceLevel: price,
    cellBidVol: new Float32Array(cells),
    cellAskVol: new Float32Array(cells),
    cellTradeCount: new Uint16Array(cells),
    priceOrigin: 50_000,
    tickSize: 0.5,
  };
}

/**
 * What the engine's own counters hold for `p`: the real stores' `bytes`, plus the GL counters for
 * the real `CandleRing` mirror of the store uploaded through them, and for the rows whose layer
 * allocator is not built yet (glyph runs 12 B a cell, E18; the coarse ring, E21) at the size the
 * layer will hold. The
 * framebuffer is the exact backing store (the estimate charges the padded upper bound); the misc
 * allowance has no allocator and is the §7 figure on both sides.
 */
function measured(p: LoadEstimateParams): number {
  const store = new BarStore({ maxBars: p.maxBars ?? 200_000 });
  for (let at = 0; at < p.bars; at += 50_000) store.append(bars(at, Math.min(50_000, p.bars - at)));
  const gl = new FakeGl();
  const registry = new GlRegistry(gl);
  const buffers = new GlBuffers(gl, registry);
  const textures = new GlTextures(gl, registry);
  const upload = (id: string, floats: number): void => {
    buffers.attach(id, { data: new Float32Array(floats), head: 0, stride: 1 });
    buffers.uploadSubRange({ nodeId: id } as RetainedBatch, 0, 1);
  };
  const ring = new CandleRing();
  ring.sync(store, { op: "replace", from: 0, to: store.length, indexShift: 0 });
  buffers.attach("candles", ring);
  buffers.uploadSubRange({ nodeId: "candles" } as RetainedBatch, 0, 1);
  let sum = store.bytes;
  const fpBars = p.footprintBars ?? 0;
  if (fpBars > 0) {
    const fp = new FootprintStore({ maxBars: fpBars });
    const k = p.cellsPerBar ?? 40;
    fp.replace(footprint(fpBars, k));
    sum += fp.bytes;
    upload("glyphs", fpBars * k * 3);
  }
  if ((p.heatmapFineColumns ?? 0) > 0) sum += new HeatmapRing().bytes;
  const coarse = p.heatmapCoarseColumns ?? 0;
  if (coarse > 0) textures.define(2, coarse, p.heatmapRows ?? 512, null);
  textures.define(1, 1024, 1024, null, "r8"); // the SDF atlas
  const [w, h] = p.backingStorePx;
  return sum + buffers.bytes + textures.bytes + 8 * MIB + w * h * 4;
}

const CASES: [string, LoadEstimateParams][] = [
  [
    "§7's 100k bars / 4 h heatmap",
    {
      bars: 100_000,
      footprintBars: 20_000,
      heatmapFineColumns: 2048,
      heatmapCoarseColumns: 14_400,
      backingStorePx: [5120, 2880],
    },
  ],
  ["30 days of 1-minute bars (US-CHART-010)", { bars: 30 * 1440, backingStorePx: [1920, 1080] }],
  ["one bar", { bars: 1, backingStorePx: [800, 600] }],
  ["maxBars, at the ceiling capacity", { bars: 200_000, backingStorePx: [2560, 1440] }],
  ["3 days of footprint", { bars: 4320, footprintBars: 4320, backingStorePx: [1920, 1080] }],
];

describe("Scenario: The estimate matches what the allocators hold (AC1, ±20 %)", () => {
  it.each(CASES)("%s", (_, p) => {
    const real = measured(p);
    const { totalBytes } = estimateLoad(p, 600);
    expect(Math.abs(totalBytes - real) / real).toBeLessThanOrEqual(0.2);
  });

  it("charges 30 d × 1 m at the ring's 65,536 slots, as the BarStore does (BQ-S15-05)", () => {
    const store = new BarStore();
    store.append(bars(0, 43_200));
    const e = byItem(estimateLoad({ bars: 43_200, backingStorePx: [0, 0] }, 600));
    expect([e.bars, store.bytes, store.capacity]).toEqual([
      65_536 * BAR_BYTES,
      65_536 * BAR_BYTES,
      65_536,
    ]);
  });

  it("charges the footprint and fine heatmap rows exactly as their stores count them", () => {
    const fp = new FootprintStore();
    fp.replace(footprint(500, 40));
    const e = byItem(
      estimateLoad(
        { bars: 1, footprintBars: 500, heatmapFineColumns: 2048, backingStorePx: [1, 1] },
        600,
      ),
    );
    expect([e.footprint, e.heatmapFine]).toEqual([fp.bytes, new HeatmapRing().bytes]);
  });
});

describe("Scenario: each §7 row by its formula", () => {
  it("reproduces §7's 100k / 4 h column, row by row (MiB)", () => {
    const e = estimateLoad(CASES[0]![1], 600);
    const mib = e.items.map((i) => [i.item, Math.round((i.bytes / MIB) * 100) / 100]);
    expect(mib).toEqual([
      ["bars", 4.13],
      ["candleBuffers", 2.5],
      ["footprint", 13.81],
      ["footprintGlyphs", 9.16],
      ["heatmapFine", 4.02],
      ["heatmapCoarse", 28.13],
      ["atlas", 1],
      ["misc", 8],
      ["framebuffer", 57.5],
    ]);
    expect(e.totalBytes).toBe(e.items.reduce((s, i) => s + i.bytes, 0));
    expect(Math.round(e.totalBytes / MIB)).toBe(128);
  });

  it("charges one bar 33 KiB (the 1024-slot floor) and no layer it does not have", () => {
    const e = byItem(estimateLoad({ bars: 1, backingStorePx: [0, 0] }, 600));
    expect(e).toEqual({
      bars: 33 * 1024,
      candleBuffers: 20 * 1024,
      footprint: 0,
      footprintGlyphs: 0,
      heatmapFine: 0,
      heatmapCoarse: 0,
      atlas: MIB,
      misc: 8 * MIB,
      framebuffer: 0,
    });
  });

  it("asks for confirmation only above 70 % of the budget (AC2)", () => {
    const p: LoadEstimateParams = { bars: 1, backingStorePx: [0, 0] }; // 9.05 MiB
    const at = (mb: number) => estimateLoad(p, mb);
    expect([at(64).budgetBytes, at(64).requiresConfirmation]).toEqual([64 * MIB, false]);
    const big = estimateLoad({ ...CASES[0]![1], bars: 2_000_000, maxBars: 2_000_000 }, 64);
    expect([big.requiresConfirmation, big.totalBytes > 0.7 * big.budgetBytes]).toEqual([
      true,
      true,
    ]);
  });

  it("caps a finite huge cellsPerBar (1e308) at the store's DEFAULT_MAX_CELLS, never Infinity", () => {
    const e = estimateLoad(
      { bars: 1, footprintBars: 2, cellsPerBar: 1e308, backingStorePx: [0, 0] },
      600,
    );
    const rows = byItem(e);
    expect([rows.footprint, rows.footprintGlyphs]).toEqual([
      DEFAULT_MAX_CELLS * 18 + 3 * 4,
      DEFAULT_MAX_CELLS * 12,
    ]);
    expect(Number.isFinite(e.totalBytes)).toBe(true);
  });

  it("charges footprint offsets for at most maxBars bars, as the store refuses more", () => {
    const at = (footprintBars: number): ReturnType<typeof byItem> =>
      byItem(
        estimateLoad(
          { bars: 1, maxBars: 1000, footprintBars, cellsPerBar: 0, backingStorePx: [0, 0] },
          600,
        ),
      );
    expect(at(Number.MAX_SAFE_INTEGER).footprint).toBe(at(1000).footprint);
    expect(at(1000).footprint).toBe(1001 * 4);
  });

  it("returns a frozen result in §7 row order", () => {
    const e = estimateLoad({ bars: 10, backingStorePx: [10, 10] }, 600);
    expect(e.items.map((i) => i.item)).toEqual([...ESTIMATE_ITEMS]);
    expect([Object.isFrozen(e), Object.isFrozen(e.items), Object.isFrozen(e.items[0])]).toEqual([
      true,
      true,
      true,
    ]);
  });
});

describe("Scenario: the F-08 constants and lookback defaults are pinned (26 §8)", () => {
  it("pins the ceilings, the floor and the lookbacks", () => {
    expect([MAX_BARS_CEILING, MEMORY_BUDGET_CEILING_MB, MEMORY_BUDGET_FLOOR_MB]).toEqual([
      2_097_152, 4096, 64,
    ]);
    expect(DEFAULT_LOOKBACK_DAYS).toEqual({ chart: 30, footprint: 3, profile: 7, replay: 1 });
    expect(Object.isFrozen(DEFAULT_LOOKBACK_DAYS)).toBe(true);
  });

  it("holds the ceiling BarStore at 2^22 slots, 132 MiB", () => {
    expect(barSlots(MAX_BARS_CEILING, MAX_BARS_CEILING)).toBe(2 ** 22);
    const e = byItem(
      estimateLoad(
        { bars: MAX_BARS_CEILING, maxBars: MAX_BARS_CEILING, backingStorePx: [0, 0] },
        600,
      ),
    );
    expect([e.bars, e.candleBuffers]).toEqual([132 * MIB, 80 * MIB]);
  });

  it("each default lookback stays under 70 % of 600 MiB at 1 m bars and 40 cells", () => {
    const px: [number, number] = [5120, 2880];
    for (const days of Object.values(DEFAULT_LOOKBACK_DAYS)) {
      const n = days * 1440;
      const e = estimateLoad({ bars: n, footprintBars: n, backingStorePx: px }, 600);
      expect(e.requiresConfirmation, `${days} d`).toBe(false);
    }
  });
});

describe("Scenario: hostile parameters are refused, never estimated (fuzz)", () => {
  const ok: LoadEstimateParams = { bars: 10, backingStorePx: [100, 100] };
  const bad: [string, LoadEstimateParams, number][] = [
    ["NaN bars", { ...ok, bars: Number.NaN }, 600],
    ["negative bars", { ...ok, bars: -1 }, 600],
    ["fractional bars", { ...ok, bars: 1.5 }, 600],
    ["infinite bars", { ...ok, bars: Number.POSITIVE_INFINITY }, 600],
    ["maxBars 0", { ...ok, maxBars: 0 }, 600],
    ["maxBars over the ceiling", { ...ok, maxBars: MAX_BARS_CEILING + 1 }, 600],
    ["negative footprintBars", { ...ok, footprintBars: -3 }, 600],
    ["NaN cellsPerBar", { ...ok, cellsPerBar: Number.NaN }, 600],
    ["negative cellsPerBar", { ...ok, cellsPerBar: -1 }, 600],
    ["fractional heatmap rows", { ...ok, heatmapRows: 0.5 }, 600],
    ["negative coarse columns", { ...ok, heatmapCoarseColumns: -1 }, 600],
    [
      "a one-axis backing store",
      { ...ok, backingStorePx: [1] as unknown as [number, number] },
      600,
    ],
    ["a NaN backing axis", { ...ok, backingStorePx: [Number.NaN, 1] }, 600],
    ["a budget under the floor", ok, MEMORY_BUDGET_FLOOR_MB - 1],
    ["a budget over the ceiling", ok, MEMORY_BUDGET_CEILING_MB + 1],
    ["a NaN budget", ok, Number.NaN],
    ["a fractional budget", ok, 600.5],
  ];
  it.each(bad)("%s throws RangeError", (_, p, mb) => {
    expect(() => estimateLoad(p, mb)).toThrow(RangeError);
  });

  it("any seeded junk value either throws RangeError or yields a finite, non-negative estimate", () => {
    const junk = [
      Number.NaN,
      -1,
      -0.5,
      0,
      0.5,
      1,
      63,
      64,
      4096,
      4097,
      2 ** 53,
      1e308,
      Infinity,
      -Infinity,
    ];
    for (let c = 0; c < 2_000; c += 1) {
      const rng = mulberry32(20261102 + c);
      const pick = (): number => junk[Math.floor(rng() * junk.length)] as number;
      const p: LoadEstimateParams = {
        bars: pick(),
        maxBars: pick(),
        footprintBars: rng() < 0.5 ? 0 : pick(),
        cellsPerBar: pick(),
        heatmapRows: pick(),
        backingStorePx: [pick(), pick()],
      };
      try {
        const e = estimateLoad(p, pick());
        expect(Number.isFinite(e.totalBytes) && e.totalBytes >= 0, `seed ${20261102 + c}`).toBe(
          true,
        );
      } catch (err) {
        expect(err, `seed ${20261102 + c}`).toBeInstanceOf(RangeError);
      }
    }
  });
});

describe("property: the bars row equals the BarStore's bytes after any append sequence", () => {
  it("holds for 1 000 seeded cases", { timeout: 60_000 }, () => {
    const failures: string[] = [];
    for (let c = 0; c < 1_000 && failures.length === 0; c += 1) {
      const seed = 20261102 + c;
      const rng = mulberry32(seed);
      const int = (n: number): number => Math.floor(rng() * n);
      const maxBars = 1 + int(3000);
      const store = new BarStore({ maxBars });
      let appended = 0;
      for (let s = 0, steps = int(6); s < steps; s += 1) {
        const k = 1 + int(Math.min(maxBars, 1 + int(2 * maxBars)));
        store.append(bars(appended, k));
        appended += k;
      }
      const e = byItem(estimateLoad({ bars: appended, maxBars, backingStorePx: [0, 0] }, 600));
      if (e.bars !== store.bytes) failures.push(`seed=${seed}: ${e.bars} vs ${store.bytes}`);
    }
    expect(failures).toEqual([]);
  });

  it("the footprint row equals the FootprintStore's bytes for any bars × cells", () => {
    for (let c = 0; c < 200; c += 1) {
      const rng = mulberry32(20261102 + c);
      const [n, k] = [1 + Math.floor(rng() * 300), Math.floor(rng() * 60)];
      const fp = new FootprintStore();
      fp.replace(footprint(n, k));
      const e = byItem(
        estimateLoad({ bars: 1, footprintBars: n, cellsPerBar: k, backingStorePx: [0, 0] }, 600),
      );
      expect(e.footprint, `seed ${20261102 + c}`).toBe(fp.bytes);
    }
  });
});

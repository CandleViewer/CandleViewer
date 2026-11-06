// E11-S11 PR A: the atlas service on the procedural stand-in platform — cache across launches,
// F-03's verification, regeneration after a bad record, borrowing, and every generation failure.
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { mulberry32 } from "../../bench/fixtures/rng.mjs";
import { AxisTicksBench } from "../../bench/scenes/axis-ticks.js";
import {
  MemoryKv,
  proceduralPlatform,
  TEST_FONTS,
  type ProceduralOptions,
} from "../../bench/fixtures/text-platform.js";
import {
  civil,
  clockText,
  createZoned,
  dateText,
  DAY_MS,
  formatNumber,
  MONTHS,
} from "../../src/axes/format.js";
import { METRIC_STRIDE, type AtlasImage } from "../../src/text/atlas-build.js";
import {
  encodeRecord,
  INDEX_KEY,
  MAX_PRUNE,
  type AtlasRecord,
} from "../../src/text/atlas-cache.js";
import {
  AtlasService,
  ENGINE_ATLAS_CACHE_INVALID,
  ENGINE_ATLAS_GENERATION_FAILED,
} from "../../src/text/atlas.js";
import { ATLAS_CONFIG, TRADING_GLYPHS, type AtlasConfig } from "../../src/text/config.js";
import { atlasGlyphs } from "../../src/text/glyph-set.js";
import { fnv1a } from "../../src/text/hash.js";
import type { ChartFont, TextPlatform } from "../../src/text/platform.js";

beforeEach(() => void vi.useFakeTimers());
afterEach(() => void vi.useRealTimers());

async function launch(platform: TextPlatform | null, fonts = TEST_FONTS, config?: AtlasConfig) {
  const events: [string, boolean, unknown][] = [];
  const ready: AtlasImage[] = [];
  const svc = new AtlasService({
    platform,
    now: () => 0,
    setTimer: (cb, ms) => void setTimeout(cb, ms),
    ready: (img) => ready.push(img),
    emit: (code, _m, recoverable, details) => events.push([code, recoverable, details]),
    ...(config && { config }),
  });
  const done = svc.start(fonts as ChartFont[]);
  await vi.runAllTimersAsync();
  await done;
  return { svc, events, ready, img: ready[0] };
}

const digest = (img: AtlasImage | undefined) => img && [fnv1a(img.rows), img.usedHeight];
const TRADING = [...TRADING_GLYPHS].length;

describe("F-03's glyph set", () => {
  it("is the digits, their separators and signs, the space, `?`, `:`, `/` and month letters", () => {
    expect(TRADING_GLYPHS).toBe("0123456789.,-+%×KMB▲▼() ?:/ADFJNOSabceglnoprtuvy");
  });
  it("every glyph the axis formatters emit is in the set (E11-S11 PR B)", () => {
    const seen = new Set<string>();
    const add = (t: string): void => [...t].forEach((c) => seen.add(c));
    const rnd = mulberry32(20261101);
    for (let i = 0; i < 10_000; i += 1) {
      const v = (rnd() - 0.5) * 10 ** Math.floor(rnd() * 16);
      add(`${v > 0 ? "+" : ""}${formatNumber(v, i % 11)}%`); // the percent kind's label too
    }
    const z = createZoned();
    for (let day = -800_000; day < 800_000; day += 997) {
      civil(day, z);
      add(`${z.year}`);
      add(dateText(z));
      add(clockText((((day * 7919) % DAY_MS) + DAY_MS) % DAY_MS, true));
    }
    MONTHS.forEach(add);
    // Deterministic edges: exponent form, the decimals cap, negative zero, non-finite (""),
    // the largest safe integer and the smallest subnormal.
    for (const v of [1e21, -1e21, 1e-7, -0, 0, Infinity, -Infinity, NaN, 2 ** 53, 5e-324])
      for (let d = 0; d <= 10; d += 1) add(formatNumber(v, d));
    expect([formatNumber(Infinity, 2), formatNumber(NaN, 0), formatNumber(1e21, 0)]).toEqual([
      "",
      "",
      "1e+21",
    ]);
    const bench = new AxisTicksBench(5_000, "America/New_York");
    for (let f = 0; f < 60; f += 1) bench.step();
    [...bench.axes.priceLabels, ...bench.axes.timeLabels].forEach(add);
    expect([...seen].filter((c) => !TRADING_GLYPHS.includes(c))).toEqual([]);
  });
});

describe("the store connection is closed (BQ-273)", () => {
  it("after a build, a cache hit and a failure; never left open", async () => {
    const kv = new MemoryKv();
    await launch(proceduralPlatform({ store: kv }));
    await launch(proceduralPlatform({ store: kv }));
    expect(kv.closes).toBe(2);
    const bad = new MemoryKv();
    await launch(proceduralPlatform({ store: bad, failRaster: 0x37 }));
    expect(bad.closes).toBe(1);
  });
  it("a store that hangs past the bound is closed, and so is one that answers late", async () => {
    const hung = new MemoryKv();
    hung.get = () => new Promise<never>(() => undefined);
    await launch(proceduralPlatform({ store: hung }));
    expect(hung.closes).toBe(1);
    const late = new MemoryKv();
    const p = proceduralPlatform({
      store: () => new Promise((r) => void setTimeout(() => r(late), 5000)),
    });
    await launch(p);
    expect(late.closes).toBe(1);
    expect(late.calls).toEqual({ get: 0, put: 0, delete: 0 });
  });
});

describe("dispose and a late store (BQ-273)", () => {
  const mk = (platform: TextPlatform) =>
    new AtlasService({
      platform,
      now: () => 0,
      setTimer: (cb, ms) => void setTimeout(cb, ms),
      ready: () => undefined,
      emit: () => undefined,
    });
  it("dispose closes the store once; a dispose while the store is opening closes it on arrival", async () => {
    const kv = new MemoryKv();
    const svc = mk(proceduralPlatform({ store: kv }));
    const done = svc.start(TEST_FONTS as ChartFont[]);
    await vi.runAllTimersAsync();
    await done;
    svc.dispose();
    svc.dispose();
    expect(kv.closes).toBe(1);
    const late = new MemoryKv();
    const opening = mk(
      proceduralPlatform({
        store: () => new Promise((r) => void setTimeout(() => r(late), 100)),
      }),
    );
    const run = opening.start(TEST_FONTS as ChartFont[]);
    await vi.advanceTimersByTimeAsync(10); // the store is now opening
    opening.dispose();
    await vi.runAllTimersAsync();
    await run;
    expect(late.closes).toBe(1);
    expect(late.calls).toEqual({ get: 0, put: 0, delete: 0 }); // a dropped store is never touched
  });
  it("a late store whose close throws is swallowed, never thrown", async () => {
    const late = new MemoryKv();
    late.close = () => {
      throw new Error("boom");
    };
    const svc = mk(
      proceduralPlatform({
        store: () => new Promise((r) => void setTimeout(() => r(late), 5000)),
      }),
    );
    const run = svc.start(TEST_FONTS as ChartFont[]);
    await vi.runAllTimersAsync();
    await expect(run).resolves.toBeUndefined();
  });
});

describe("Scenario: Atlas generation is cached across launches", () => {
  it("the first launch generates 194 glyphs and writes one record; the second reads it", async () => {
    const kv = new MemoryKv();
    const first = await launch(proceduralPlatform({ store: kv }));
    expect(first.svc.phase).toBe("ready");
    expect(first.svc.counters).toMatchObject({ cacheHit: false, rasterized: 194 });
    expect(first.img?.metrics).toHaveLength(194 * METRIC_STRIDE);
    expect(first.img?.usedHeight).toBeLessThan(ATLAS_CONFIG.height);
    const records = () => kv.puts.filter((k) => k !== INDEX_KEY);
    expect(records()).toHaveLength(1);
    const p = proceduralPlatform({ store: kv });
    const second = await launch(p);
    // F-03: only the trading glyphs are re-derived; nothing is regenerated or rewritten.
    expect(p.rasters).toBe(TRADING);
    expect(second.svc.counters.cacheHit).toBe(true);
    expect(records()).toHaveLength(1);
    expect(digest(second.img)).toEqual(digest(first.img));
    expect([first.events, second.events]).toEqual([[], []]);
  });

  it("generation is deterministic, and stale records are pruned (at most 16 per launch)", async () => {
    const kv = new MemoryKv();
    for (let i = 0; i < MAX_PRUNE + 4; i += 1) kv.map.set(`old-${i}`, {});
    const a = await launch(proceduralPlatform({ store: kv }));
    const b = await launch(proceduralPlatform({ store: null }));
    expect(digest(a.img)).toEqual(digest(b.img));
    expect(kv.calls.delete).toBe(MAX_PRUNE);
    await launch(proceduralPlatform({ store: kv })); // a hit prunes the rest
    expect(kv.map.size).toBe(2); // the record and the recency index
  });

  it("the two records kept are the most recently used, not the first by key order", async () => {
    const kv = new MemoryKv();
    const fonts = (seed: number): ChartFont[] =>
      TEST_FONTS.map((f, i) => ({ ...f, bytes: Uint8Array.of(seed, i).buffer }));
    const keys = async (seed: number) => {
      await launch(proceduralPlatform({ store: kv }), fonts(seed));
      return (kv.map.get(INDEX_KEY) as string[])[0] as string;
    };
    const k1 = await keys(1);
    const k2 = await keys(2);
    expect(await keys(1)).toBe(k1); // a hit: k1 is the most recent again
    const k3 = await keys(3);
    expect(new Set(kv.map.keys())).toEqual(new Set([INDEX_KEY, k3, k1]));
    expect(kv.map.has(k2)).toBe(false);
  });
});

describe("Scenario: A corrupt cached atlas is detected and regenerated", () => {
  const slot = (ch: string) =>
    atlasGlyphs(ATLAS_CONFIG).findIndex((e) => e.family === 0 && e.ch === ch) * METRIC_STRIDE;
  const tamper: Record<string, (r: AtlasRecord, key: string) => unknown> = {
    "a flipped byte": (r) => ({ ...r, rows: r.rows.map((v, i) => (i === 3 ? v ^ 1 : v)) }),
    "truncated rows": (r) => ({ ...r, rows: r.rows.subarray(0, r.rows.length - 1) }),
    "an older version": (r) => ({ ...r, v: 0 }),
    // CE-T14 / RR3: "9" drawn where "0" is, with a recomputed checksum; only F-03 catches it.
    'a "9" swapped with a "0" under a recomputed checksum': (r, key) => {
      const rows = r.rows.slice();
      const [m, n] = [slot("9"), slot("0")];
      const [x9, y9, w, h, x0, y0] = [m, m + 1, m + 2, m + 3, n, n + 1].map(
        (k) => r.metrics[k] as number,
      );
      for (let y = 0; y < (h as number); y += 1) {
        const a = ((y9 as number) + y) * ATLAS_CONFIG.width + (x9 as number);
        const b = ((y0 as number) + y) * ATLAS_CONFIG.width + (x0 as number);
        rows.set(r.rows.subarray(b, b + (w as number)), a);
        rows.set(r.rows.subarray(a, a + (w as number)), b);
      }
      return encodeRecord({ ...decodeShape(r), rows }, key);
    },
    // A sheared "9": its slot moved to the right edge, where a sampler would wrap.
    "a trading glyph relocated to the texture's right edge under a recomputed checksum": (
      r,
      key,
    ) => {
      const metrics = r.metrics.slice();
      metrics[slot("9")] = ATLAS_CONFIG.width - 1;
      return encodeRecord({ ...decodeShape(r), metrics }, key);
    },
    // `?` (BQ-269's replacement), `:` and `/` (time axis) are trading glyphs too: each re-pointed
    // at a digit under a recomputed checksum must fail F-03.
    ...Object.fromEntries(
      ["?", ":", "/"].map((ch) => [
        `the "${ch}" re-pointed at a digit under a recomputed checksum`,
        (r: AtlasRecord, key: string) => {
          const metrics = r.metrics.slice();
          const [at, one] = [slot(ch), slot("1")];
          for (const k of [0, 1, 2, 3, 5, 6, 7]) metrics[at + k] = r.metrics[one + k] as number;
          return encodeRecord({ ...decodeShape(r), metrics }, key);
        },
      ]),
    ),
    // A mono space has a digit's advance: " 95.50" would draw as "195.50".
    "the space re-pointed at a digit under a recomputed checksum": (r, key) => {
      const metrics = r.metrics.slice();
      const [sp, one] = [slot(" "), slot("1")];
      for (const k of [0, 1, 2, 3, 5, 6, 7]) metrics[sp + k] = r.metrics[one + k] as number;
      return encodeRecord({ ...decodeShape(r), metrics }, key);
    },
    "a record valid under another key": (r) => encodeRecord(decodeShape(r), "another key"),
  };

  const decodeShape = (r: AtlasRecord): AtlasImage => ({
    width: ATLAS_CONFIG.width,
    height: ATLAS_CONFIG.height,
    usedHeight: r.usedHeight,
    rows: r.rows,
    metrics: r.metrics,
    occupancyPct: 0,
  });

  it.each(Object.keys(tamper))(
    "%s: ENGINE_ATLAS_CACHE_INVALID once, then the true atlas",
    async (name) => {
      const kv = new MemoryKv();
      const clean = await launch(proceduralPlatform({ store: kv }));
      const [key] = kv.map.get(INDEX_KEY) as [string];
      kv.map.set(key, tamper[name]?.(kv.map.get(key) as AtlasRecord, key));
      const again = await launch(proceduralPlatform({ store: kv }));
      expect(again.events).toEqual([[ENGINE_ATLAS_CACHE_INVALID, true, undefined]]);
      expect(again.ready).toHaveLength(1); // nothing drawn from the bad record
      expect(digest(again.img)).toEqual(digest(clean.img));
      expect(again.svc.counters.cacheHit).toBe(false);
      expect(digest(decodeShape(kv.map.get(key) as AtlasRecord))).toEqual(digest(clean.img));
    },
  );
});

describe("glyph coverage and generation failures (BQ-259, BQ-272)", () => {
  it("a glyph one family lacks is drawn from the other", async () => {
    const { img, events } = await launch(
      proceduralPlatform({ missing: { "JetBrains Mono": [0x41] } }),
    );
    const i = atlasGlyphs(ATLAS_CONFIG).findIndex((g) => g.family === 0 && g.ch === "A");
    expect(events).toEqual([]);
    expect(img?.metrics[i * METRIC_STRIDE + 7]).toBe(1);
  });

  const failures: [string, ProceduralOptions, readonly ChartFont[], AtlasConfig | undefined][] = [
    ["no-font", {}, TEST_FONTS.slice(0, 1), undefined],
    ["font-load", { failLoad: true }, TEST_FONTS, undefined],
    ["coverage", { missing: { "JetBrains Mono": [0x41], Inter: [0x41] } }, TEST_FONTS, undefined],
    ["overflow", {}, TEST_FONTS, { ...ATLAS_CONFIG, width: 64, height: 64 }],
    ["raster", { failRaster: 0x37 }, TEST_FONTS, undefined],
  ];

  it.each(failures)(
    "%s: GENERATION_FAILED once, not recoverable, no atlas",
    async (reason, o, f, c) => {
      const { svc, events, ready } = await launch(proceduralPlatform(o), f, c);
      expect(events).toEqual([[ENGINE_ATLAS_GENERATION_FAILED, false, { atlasReason: reason }]]);
      expect([svc.phase, ready]).toEqual(["failed", []]);
      await svc.start(TEST_FONTS); // a later chart never restarts it
      expect(events).toHaveLength(1);
    },
  );

  it("a digest that rejects is no cache: the atlas is generated, no code, the store untouched", async () => {
    const kv = new MemoryKv();
    const p = proceduralPlatform({ store: kv });
    p.digest = () => Promise.reject(new Error("subtle unusable"));
    const { svc, events } = await launch(p);
    expect([svc.phase, events, kv.calls]).toEqual(["ready", [], { get: 0, put: 0, delete: 0 }]);
  });

  it("the faces are released once the atlas is built, and after a failure", async () => {
    const ok = proceduralPlatform();
    await launch(ok);
    const bad = proceduralPlatform({ failRaster: 0x37 });
    await launch(bad);
    expect([ok.loads, ok.releases, bad.loads, bad.releases]).toEqual([2, 2, 2, 2]);
  });

  it("dispose stops a build in flight: nothing published or emitted, the faces released", async () => {
    const p = proceduralPlatform();
    const events: unknown[] = [];
    const ready: unknown[] = [];
    const svc = new AtlasService({
      platform: p,
      now: () => 0,
      setTimer: (cb, ms) => void setTimeout(cb, ms),
      ready: (img) => ready.push(img),
      emit: (code) => events.push(code),
    });
    const raster = p.rasterize.bind(p);
    p.rasterize = (...a) => {
      if (p.rasters === 0) svc.dispose(); // the runtime goes away during the mono task
      return raster(...a);
    };
    const done = svc.start(TEST_FONTS);
    await vi.runAllTimersAsync();
    await done;
    expect([events, ready, svc.image, p.loads, p.releases]).toEqual([[], [], null, 2, 2]);
    expect(p.rasters).toBeLessThan(194); // the ui task never ran
    expect((p.kv as MemoryKv).closes).toBe(1); // the store, open mid-build, is closed by dispose
  });

  it("a dispose during the F-03 yield re-derives nothing and deletes no valid record", async () => {
    const kv = new MemoryKv();
    await launch(proceduralPlatform({ store: kv }));
    const p = proceduralPlatform({ store: kv });
    const events: unknown[] = [];
    const before = kv.calls.delete;
    // The first 0 ms timer after the record was read is the verify yield: dispose lands in it.
    const svc: AtlasService = new AtlasService({
      platform: p,
      now: () => 0,
      setTimer: (cb, ms) =>
        void setTimeout(() => {
          if (ms === 0 && kv.calls.get > 0) svc.dispose();
          cb();
        }, ms),
      ready: () => undefined,
      emit: (code) => events.push(code),
    });
    const done = svc.start(TEST_FONTS);
    await vi.runAllTimersAsync();
    await done;
    expect([p.rasters, kv.calls.delete - before, events, svc.image]).toEqual([0, 0, [], null]);
    expect(p.releases).toBe(p.loads);
  });

  it("no platform in this runtime is a font-load failure, never a fallback face", async () => {
    const { events } = await launch(null);
    expect(events).toEqual([[ENGINE_ATLAS_GENERATION_FAILED, false, { atlasReason: "font-load" }]]);
  });
});

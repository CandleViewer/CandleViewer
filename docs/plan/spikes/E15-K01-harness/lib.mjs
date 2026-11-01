// THROWAWAY SPIKE HARNESS (E15-K01 #371). Self-contained helpers: they MIRROR, they do not import, the
// definitions the chart-engine bench uses (BQ-02 ruling: nothing from the engine package, the E14-K01 rule),
// so the numbers stay comparable with the ones CI gates on. Pure: no DOM, no Node APIs (served to the page and
// imported by the Node driver alike). Nothing here is product code.

/** Nearest-rank percentile (the bench's definition): rank = ceil(p/100 * n) - 1, clamped. Not mutating. */
export function percentile(values, p) {
  if (values.length === 0) return 0;
  const sorted = [...values].sort((a, b) => a - b);
  const rank = Math.ceil((p / 100) * sorted.length) - 1;
  return sorted[Math.min(sorted.length - 1, Math.max(0, rank))];
}

/** Median of the per-rep p95s (the bench's cross-rep figure). */
export function medianOfP95(xs) {
  if (xs.length === 0) return 0;
  const s = [...xs].sort((a, b) => a - b);
  const m = Math.floor(s.length / 2);
  return s.length % 2 === 0 ? (s[m - 1] + s[m]) / 2 : s[m];
}

/** The bench's admissibility rule: three reps or more. */
export const isAdmissible = (reps) => reps >= 3;

export function summariseFrames(ms) {
  return {
    p50: percentile(ms, 50),
    p95: percentile(ms, 95),
    p99: percentile(ms, 99),
    over33: ms.filter((v) => v > 33.3).length,
    over200: ms.filter((v) => v > 200).length,
    max: ms.reduce((a, b) => (b > a ? b : a), 0),
  };
}

/** mulberry32: a tiny seeded PRNG, the same sequence everywhere. */
export function mulberry32(seed) {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

/**
 * Synthetic 1-minute bars in integer ticks with volatility clustering and rare session gaps: the same shape
 * as the bench's fixture generator (seeded, deterministic), written here so nothing is imported.
 */
export function generateBars({
  seed,
  count = 100_000,
  originTicks = 6_000_000,
  startMs = Date.UTC(2026, 0, 1),
}) {
  const rng = mulberry32(seed);
  const bars = new Array(count);
  let price = originTicks,
    vol = 1;
  for (let i = 0; i < count; i += 1) {
    vol = Math.min(4, Math.max(0.3, vol + (rng() - 0.5) * 0.08));
    const gap = i > 0 && rng() < 0.002;
    if (gap) price += Math.round((rng() - 0.5) * 400 * vol);
    const o = price;
    let h = o,
      l = o,
      c = o;
    for (let s = 0; s < 4; s += 1) {
      c += Math.round((rng() - 0.5) * 60 * vol);
      if (c > h) h = c;
      if (c < l) l = c;
    }
    bars[i] = {
      tOpenMs: startMs + i * 60_000,
      o,
      h,
      l,
      c,
      v: Math.max(1, Math.round(rng() * 5000 * vol)),
      gap,
    };
    price = c;
  }
  return bars;
}

/** The bench's pinned CI flag set (software GL), restated (not imported) for the SwiftShader device. */
export const SWIFTSHADER_FLAGS = Object.freeze([
  "--use-gl=angle",
  "--use-angle=swiftshader",
  "--disable-gpu-vsync",
  "--enable-webgl2",
  "--force-color-profile=srgb",
]);

// ---- Mirrors of the app's rules, for the harness to apply to the measured series ---------------------------
// The app's own code is `apps/web/src/lib/capability/` (not imported here either). Its unit test
// `e15k01Fixture.test.ts` checks the app's `classify` against the answers this harness wrote into the fixture,
// and loads this file to run the app's `classify` and `reducedTrigger` beside these mirrors (`outliers:
// "isolated"`) on the measured windows, so the mirror and the app cannot drift silently. This file still
// imports nothing from the app.

/** Mirror of `frameProbe.ts` `classify` (PROPOSED values, E15-K01 §5). */
export function classify(
  windows,
  { budgetMs = 16.6, headroom = 1.2, hardCap = 16, fullMin = 4 } = {},
) {
  const pts = windows.map((w) => ({ n: w.paneCount, p95: percentile(w.frameMs, 95) }));
  const top = pts.reduce((m, p) => (p.n > m.n ? p : m));
  let fixed = 0,
    perPane = top.p95 / top.n;
  if (new Set(pts.map((p) => p.n)).size >= 2) {
    const mx = pts.reduce((s, p) => s + p.n, 0) / pts.length,
      my = pts.reduce((s, p) => s + p.p95, 0) / pts.length;
    const sxx = pts.reduce((s, p) => s + (p.n - mx) ** 2, 0);
    const slope = pts.reduce((s, p) => s + (p.n - mx) * (p.p95 - my), 0) / sxx;
    // a slope <= 0 is noise, not a free pane: keep the one-window rule on the top point (added after the
    // run with the app's guard, E15-K01 D-8; it changes one stored probe run, the order-flow proxy's rep 0)
    if (slope > 0) {
      perPane = slope;
      fixed = Math.max(0, my - slope * mx);
    }
  }
  const limit = budgetMs / headroom;
  const fit = perPane > 0 ? Math.floor((limit - fixed) / perPane) : fixed <= limit ? hardCap : 0;
  // never at or above a pane count whose own window missed (with the slope guard, D-8)
  const missed = pts.filter((p) => p.p95 > limit).map((p) => p.n);
  const max = Math.max(
    0,
    Math.min(hardCap, missed.length ? Math.min(...missed) - 1 : hardCap, fit),
  );
  return {
    p95FrameMs: top.p95,
    recommendedMaxPanes: max,
    recommendedProfile: max >= fullMin ? "full" : "reduced",
    paneCount: top.n,
  };
}

/**
 * Mirror of `frameProbe.ts` `warmWindow`: the probe's warm-up in clock time (`warmupMs`, the 7 s settle bound
 * of §9 T4; the run recorded it as 420 frames at 60 Hz, `decision.trigger.probeWarmupFrames`), then at most
 * `windowFrames` frames. Over (time from the pane-count change, frameMs) samples. Added with the app's change
 * from a frame count to a time (r2 read of record); the run applied neither, so no stored outcome changes.
 */
export function warmWindow(paneCount, samples, { warmupMs = 7_000, windowFrames = 120 } = {}) {
  const warm = samples.filter((s) => s.t >= warmupMs).slice(0, windowFrames);
  return { paneCount, frameMs: warm.map((s) => s.ms) };
}

/**
 * Mirror of `frameProbe.ts` `reducedTrigger`: the E15-D12 BQ-10 runtime trigger. Over (time, frameMs) samples
 * taken while visible and focused: drop everything before `warmupMs`, drop frames over `outlierMs`, then fire
 * when the p95 of the trailing `windowMs` is above `thresholdMs` (evaluated once the window is full).
 * `outliers: "all"` (what the run applied: every frame over `outlierMs` dropped) or `"isolated"` (only a frame
 * whose neighbours are not over it: the reading E15-K01 §9 T3 adopts and the app implements). A window is full
 * when the kept frames span it and, counting each frame as at least 1/60 s, cover `minCoverage` of it (added
 * after the run with the app's rule, D-8; the run's samples are contiguous, so no stored outcome changes).
 */
export function reducedTrigger(
  samples,
  {
    thresholdMs = 18.2,
    windowMs = 60_000,
    warmupMs = 10_000,
    outlierMs = 200,
    outliers = "all",
    minCoverage = 0.5,
  } = {},
) {
  const warm = samples.filter((s) => s.t >= warmupMs);
  const slow = (s) => s !== undefined && s.ms > outlierMs;
  const kept =
    outliers === "all"
      ? warm.filter((s) => !slow(s))
      : warm.filter((s, i) => !(slow(s) && !slow(warm[i - 1]) && !slow(warm[i + 1])));
  if (kept.length === 0 || kept[kept.length - 1].t - kept[0].t < windowMs * 0.999)
    return { fired: false, p95: null, frames: kept.length };
  const end = kept[kept.length - 1].t;
  const win = kept.filter((s) => s.t > end - windowMs).map((s) => s.ms);
  if (win.reduce((c, ms) => c + Math.max(ms, 1000 / 60), 0) < windowMs * minCoverage)
    return { fired: false, p95: null, frames: win.length };
  const p95 = percentile(win, 95);
  return { fired: p95 > thresholdMs, p95, frames: win.length };
}

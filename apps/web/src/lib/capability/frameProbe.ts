/**
 * The measured capability probe (E15-K01 #371, BQ-10). It classifies a device from the engine's own frame
 * times, never from what the browser says it is: no user-agent, no GPU renderer string, no memory or core
 * count is read anywhere in this module (asserted by `test/lib/capability/noSniff.test.ts`). The inputs are
 * the per-frame `frameTimeMs` the engine reports in its `frame` message (26 §6) while `paneCount` panes
 * draw; a cold first frame is never classified (a warm-up is dropped first). The spike harness imports
 * nothing from here: it mirrors `classify` and `reducedTrigger` (`docs/plan/spikes/E15-K01-harness/lib.mjs`),
 * and `test/lib/capability/e15k01Fixture.test.ts` checks this file reaches the mirror's answers on the
 * measured windows.
 *
 * Every threshold here is PROPOSED (E15-K01 §5; owner approval pending).
 * The rule (written before the run, E15-K01 §5): p95 per window, nearest rank; a straight line through the
 * windows' p95s (or through zero with one window, which errs low, and with a fitted slope <= 0, which is noise,
 * not a free pane); `recommendedMaxPanes` is the largest pane
 * count whose projected p95, with 20 % headroom, stays within the 16.6 ms budget, capped at SCR-020's 16;
 * the profile is `reduced` below four panes (US-LAY-001's four). The intended calibration is one window at
 * one pane and one at four (E15-K01 §6).
 * Distinct from the engine's static `RenderProfile` (E11-S02), which this module does not touch.
 * `reducedTrigger` is E15-D12 BQ-10's runtime trigger (when to propose the reduced profile), as calibrated by
 * E15-K01 §9.
 */

export type CapabilityProfile = "full" | "reduced";

export interface CapabilityResult {
  /** The p95 frame time at the largest pane count sampled. */
  readonly p95FrameMs: number;
  readonly recommendedMaxPanes: number;
  readonly recommendedProfile: CapabilityProfile;
  /** The largest pane count sampled (the one `p95FrameMs` belongs to). */
  readonly paneCount: number;
  /** Frames classified, over every window (after the warm-up was dropped). */
  readonly sampleCount: number;
}

/** One warm window: the frame times while `paneCount` panes drew. */
export interface FrameWindow {
  readonly paneCount: number;
  readonly frameMs: readonly number[];
}

/** Budget #1 (`06` §2): 16.6 ms p95. */
export const FRAME_BUDGET_MS = 16.6;
/** The projected p95 must fit the budget with this factor to spare (E15-K01 §5). */
export const HEADROOM = 1.2;
/** SCR-020: more than 16 panels is the degraded state. */
export const HARD_CAP_PANES = 16;
/** US-LAY-001: four panes is the layout the full profile must hold. */
export const FULL_MIN_PANES = 4;
/**
 * Frames dropped before sampling: a cold frame misclassifies every device (#371 Technical notes). E15-K01
 * §9's rule: max(30, the measured settle at 60 Hz). The settle search was bounded at 7 s and five cells reached
 * that bound, so 7 s is a lower bound on the slowest settle, not a measurement (E15-K01 §9 T4; re-checked on
 * the owner leg OL-1): 420 frames, or `WARMUP_MAX_MS` of frames on a slower device, whichever comes first.
 */
export const WARMUP_FRAMES = 420;
/** The warm-up's time cap: 420 frames at 60 Hz (each frame counted as at least `FRAME_INTERVAL_MS`). */
export const WARMUP_MAX_MS = 7_000;
/** Minimum window: at 60 frames or more, one outlier moves the nearest-rank p95 by one rank at most. */
export const MIN_WINDOW_FRAMES = 60;
/** The window the sampler collects after the warm-up. */
export const WINDOW_FRAMES = 120;
/**
 * The window's time cap: it closes at `WINDOW_FRAMES` frames or at this much frame time, whichever comes
 * first. A window that closes on time with fewer than `MIN_WINDOW_FRAMES` frames (slower than about 217 ms
 * per frame) is starved: see `classifyStarved`. So one calibration step takes at most
 * `WARMUP_MAX_MS + WINDOW_MAX_MS` (20 s) plus two frames, and the probe at most twice that.
 */
export const WINDOW_MAX_MS = 13_000;
/** A frame counts as at least one 60 Hz interval when frame time is summed into elapsed time. */
export const FRAME_INTERVAL_MS = 1000 / 60;
/** Elapsed time a frame stands for: its frame time, at least one 60 Hz interval. */
export const frameSpanMs = (frameMs: number): number => Math.max(frameMs, FRAME_INTERVAL_MS);

/** Nearest-rank percentile, the bench harness's definition (`packages/chart-engine/bench/stats.mjs`). */
export function percentile(values: readonly number[], p: number): number {
  if (values.length === 0) return 0;
  const sorted = [...values].sort((a, b) => a - b);
  const rank = Math.ceil((p / 100) * sorted.length) - 1;
  return sorted[Math.min(sorted.length - 1, Math.max(0, rank))] ?? 0;
}

function check(w: FrameWindow): void {
  if (!Number.isInteger(w.paneCount) || w.paneCount < 1)
    throw new RangeError("paneCount must be >= 1");
  if (w.frameMs.length < MIN_WINDOW_FRAMES)
    throw new RangeError(`a window needs at least ${MIN_WINDOW_FRAMES} frames`);
  if (w.frameMs.some((v) => !Number.isFinite(v) || v < 0))
    throw new RangeError("frame times must be finite and >= 0");
}

/**
 * Classifies one or more warm windows (the warm-up already dropped; see `classifySeries`). With windows at
 * two or more pane counts the cost is fitted as p95(N) = fixed + perPane * N (least squares over each
 * window's p95); with one pane count, or a fitted slope <= 0, the fixed cost is charged to the top window's
 * panes (fixed = 0, perPane = its p95 / its pane count), which errs low.
 * `recommendedMaxPanes` is the largest N with p95(N) * HEADROOM <= FRAME_BUDGET_MS, at most HARD_CAP_PANES and
 * below the smallest sampled pane count whose own window missed that.
 */
export function classify(windows: readonly FrameWindow[]): CapabilityResult {
  if (windows.length === 0) throw new RangeError("at least one window is needed");
  windows.forEach(check);
  const pts = windows.map((w) => ({ n: w.paneCount, p95: percentile(w.frameMs, 95) }));
  const top = pts.reduce((m, p) => (p.n > m.n ? p : m));
  const ns = new Set(pts.map((p) => p.n));
  let fixed = 0;
  let perPane = top.p95 / top.n;
  if (ns.size >= 2) {
    const mx = pts.reduce((s, p) => s + p.n, 0) / pts.length;
    const my = pts.reduce((s, p) => s + p.p95, 0) / pts.length;
    const sxx = pts.reduce((s, p) => s + (p.n - mx) ** 2, 0);
    const slope = pts.reduce((s, p) => s + (p.n - mx) * (p.p95 - my), 0) / sxx;
    // more panes measured no slower: noise (a late shader compile, a 120-frame window), not a free pane.
    // Keep the one-window rule on the top point instead of promising the cap (E15-K01 r1 lens).
    if (slope > 0) {
      perPane = slope;
      fixed = Math.max(0, my - slope * mx);
    }
  }
  const limit = FRAME_BUDGET_MS / HEADROOM;
  const fit =
    perPane > 0 ? Math.floor((limit - fixed) / perPane) : fixed <= limit ? HARD_CAP_PANES : 0;
  // never at or above a pane count whose own window missed the budget, whatever the line says
  const missed = pts.filter((p) => p.p95 > limit).map((p) => p.n);
  const missCap = missed.length > 0 ? Math.min(...missed) - 1 : HARD_CAP_PANES;
  const recommendedMaxPanes = Math.max(0, Math.min(HARD_CAP_PANES, missCap, fit));
  return {
    p95FrameMs: top.p95,
    recommendedMaxPanes,
    recommendedProfile: recommendedMaxPanes >= FULL_MIN_PANES ? "full" : "reduced",
    paneCount: top.n,
    sampleCount: windows.reduce((s, w) => s + w.frameMs.length, 0),
  };
}

/**
 * The result when a calibration window starved (closed on `WINDOW_MAX_MS` with fewer than `MIN_WINDOW_FRAMES`
 * frames): the device is too slow to classify at `starved.paneCount`, so the answer is the earlier windows'
 * (none: 0) capped below that pane count. `p95FrameMs` and `paneCount` are the starved window's.
 */
export function classifyStarved(
  earlier: readonly FrameWindow[],
  starved: FrameWindow,
): CapabilityResult {
  if (!Number.isInteger(starved.paneCount) || starved.paneCount < 1 || starved.frameMs.length === 0)
    throw new RangeError("a starved window needs a pane count and one frame");
  const before = earlier.length > 0 ? classify(earlier).recommendedMaxPanes : 0;
  const recommendedMaxPanes = Math.max(0, Math.min(before, starved.paneCount - 1));
  return {
    p95FrameMs: percentile(starved.frameMs, 95),
    recommendedMaxPanes,
    recommendedProfile: recommendedMaxPanes >= FULL_MIN_PANES ? "full" : "reduced",
    paneCount: starved.paneCount,
    sampleCount: earlier.reduce((s, w) => s + w.frameMs.length, 0) + starved.frameMs.length,
  };
}

/** Drops the warm-up from each raw series and keeps at most `WINDOW_FRAMES`. */
export function warmWindow(paneCount: number, series: readonly number[]): FrameWindow {
  return { paneCount, frameMs: series.slice(WARMUP_FRAMES, WARMUP_FRAMES + WINDOW_FRAMES) };
}

/** The plain-text form SCR-153 and US-LAY-008 show: "measured 24 ms per frame with 6 panes". */
export function describeMeasurement(r: CapabilityResult): string {
  const ms = r.p95FrameMs < 10 ? r.p95FrameMs.toFixed(1) : String(Math.round(r.p95FrameMs));
  return `measured ${ms} ms per frame with ${r.paneCount} ${r.paneCount === 1 ? "pane" : "panes"}`;
}

/** E15-D12 BQ-10 trigger (RULED; calibrated in E15-K01 §9, PROPOSED as its A-row): US-LAY-001's 18.2 ms. */
export const TRIGGER_THRESHOLD_MS = 18.2;
/** The rolling window the trigger's p95 is taken over. */
export const TRIGGER_WINDOW_MS = 60_000;
/** Nothing is sampled for this long after a boot, a restore or a layout change. */
export const TRIGGER_WARMUP_MS = 10_000;
/**
 * A single frame over this is dropped as an outlier (a GC pause, a tab switch). "Single" means isolated: a run
 * of slow frames is the device, not an outlier, so a device slower than 200 ms per frame still fires
 * (E15-K01 §9, T3). A run is two frames or more: two back-to-back GC pauses count, by design.
 */
export const TRIGGER_OUTLIER_MS = 200;
/**
 * The trailing window is full only when its frames, each counted as `frameSpanMs`, cover at least this share
 * of it: a long hidden or unfocused gap leaves the span full but the window nearly empty.
 */
export const TRIGGER_MIN_COVERAGE = 0.5;

/**
 * One frame sampled while the window was visible and focused; `atMs` counts from the boot / restore / layout
 * change. The caller restarts the series (and `atMs`) at each of those, or the warm-up is skipped (E15-S08).
 */
export interface TimedFrame {
  readonly atMs: number;
  readonly frameMs: number;
}

export interface TriggerResult {
  /** True when the reduced profile should be proposed (never applied without the user's click). */
  readonly fired: boolean;
  /** The p95 over the trailing window, or `null` until a full window after the warm-up exists. */
  readonly p95FrameMs: number | null;
  /** Frames in the trailing window after the outliers were dropped. */
  readonly frameCount: number;
}

const slow = (f: TimedFrame | undefined): boolean =>
  f !== undefined && f.frameMs > TRIGGER_OUTLIER_MS;

/**
 * The runtime trigger: drops the frames before `TRIGGER_WARMUP_MS` and every isolated frame over
 * `TRIGGER_OUTLIER_MS` (neither neighbour over it), then fires when the p95 of the trailing
 * `TRIGGER_WINDOW_MS` is above `TRIGGER_THRESHOLD_MS`. Nothing fires until a full window is held: the kept
 * frames span it and cover `TRIGGER_MIN_COVERAGE` of it. The newest frame, when slow after a fast one, is
 * undecided (its right neighbour has not arrived) and is left out until the next call. The caller feeds only
 * frames sampled while visible and focused, in time order.
 */
export function reducedTrigger(frames: readonly TimedFrame[]): TriggerResult {
  const warm = frames.filter((f) => f.atMs >= TRIGGER_WARMUP_MS);
  const kept = warm.filter((f, i) => !(slow(f) && !slow(warm[i - 1]) && !slow(warm[i + 1])));
  const first = kept[0];
  const last = kept[kept.length - 1];
  if (
    first === undefined ||
    last === undefined ||
    last.atMs - first.atMs < TRIGGER_WINDOW_MS * 0.999
  )
    return { fired: false, p95FrameMs: null, frameCount: kept.length };
  const win = kept.filter((f) => f.atMs > last.atMs - TRIGGER_WINDOW_MS).map((f) => f.frameMs);
  if (win.reduce((c, ms) => c + frameSpanMs(ms), 0) < TRIGGER_WINDOW_MS * TRIGGER_MIN_COVERAGE)
    return { fired: false, p95FrameMs: null, frameCount: win.length };
  const p95 = percentile(win, 95);
  return { fired: p95 > TRIGGER_THRESHOLD_MS, p95FrameMs: p95, frameCount: win.length };
}

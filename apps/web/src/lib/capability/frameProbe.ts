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
 * windows' p95s (or through zero with one window, which errs low); `recommendedMaxPanes` is the largest pane
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
 * §9's rule: max(30, the measured settle at 60 Hz); the slowest measured settle was 7 s, so 420.
 */
export const WARMUP_FRAMES = 420;
/** Minimum window: at 60 frames or more, one outlier moves the nearest-rank p95 by one rank at most. */
export const MIN_WINDOW_FRAMES = 60;
/** The window the sampler collects after the warm-up. */
export const WINDOW_FRAMES = 120;

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
 * window's p95); with one pane count the fixed cost is charged to the panes (fixed = 0), which errs low.
 * `recommendedMaxPanes` is the largest N with p95(N) * HEADROOM <= FRAME_BUDGET_MS, at most HARD_CAP_PANES.
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
    perPane = Math.max(0, pts.reduce((s, p) => s + (p.n - mx) * (p.p95 - my), 0) / sxx);
    fixed = Math.max(0, my - perPane * mx);
  }
  const limit = FRAME_BUDGET_MS / HEADROOM;
  const fit =
    perPane > 0 ? Math.floor((limit - fixed) / perPane) : fixed <= limit ? HARD_CAP_PANES : 0;
  const recommendedMaxPanes = Math.max(0, Math.min(HARD_CAP_PANES, fit));
  return {
    p95FrameMs: top.p95,
    recommendedMaxPanes,
    recommendedProfile: recommendedMaxPanes >= FULL_MIN_PANES ? "full" : "reduced",
    paneCount: top.n,
    sampleCount: windows.reduce((s, w) => s + w.frameMs.length, 0),
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
 * (E15-K01 §9, T3).
 */
export const TRIGGER_OUTLIER_MS = 200;

/** One frame sampled while the window was visible and focused; `atMs` counts from the boot / restore / layout change. */
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
 * `TRIGGER_WINDOW_MS` is above `TRIGGER_THRESHOLD_MS`. Nothing fires until a full window is held. The caller
 * feeds only frames sampled while visible and focused, in time order.
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
  const p95 = percentile(win, 95);
  return { fired: p95 > TRIGGER_THRESHOLD_MS, p95FrameMs: p95, frameCount: win.length };
}

/**
 * The probe's runtime half (E15-K01 #371, BQ-10): it listens to the engine's per-frame times, classifies once
 * the warm-up and the window are collected, remembers the result per device (US-LAY-008) and reports
 * `capability.profile_measured` once per session through the caller's analytics seam. Every input is
 * injected, so nothing here reads the environment; the result holds aggregate timing only, never an
 * identifier, and nothing is sent anywhere (#371 Security notes).
 */
import {
  classify,
  classifyStarved,
  frameSpanMs,
  FULL_MIN_PANES,
  HARD_CAP_PANES,
  MIN_WINDOW_FRAMES,
  WARMUP_FRAMES,
  WARMUP_MAX_MS,
  WINDOW_FRAMES,
  WINDOW_MAX_MS,
  type CapabilityProfile,
  type CapabilityResult,
  type FrameWindow,
} from "./frameProbe";

/** The calibration: a window at one pane, then one at four (E15-K01 §6). */
export const CALIBRATION_PANES: readonly number[] = [1, 4];

/** Device-scoped storage key; bump the version when the rule in `frameProbe.ts` changes. */
export const PROBE_STORAGE_KEY = "cv.capability.v1";

export interface ProfileMeasuredEvent {
  readonly name: "capability.profile_measured";
  readonly p95FrameMs: number;
  readonly recommendedProfile: CapabilityProfile;
  readonly paneCount: number;
}

export interface ProbeDeps {
  /**
   * Subscribes to the calibration scene's per-frame time, GPU completion included (E15-K01 §6); returns the
   * unsubscribe.
   */
  readonly onFrame: (listener: (frameTimeMs: number) => void) => () => void;
  /** Sets the number of panes the calibration scene draws. */
  readonly drawPanes: (paneCount: number) => void;
  readonly storage: Pick<Storage, "getItem" | "setItem">;
  readonly report: (event: ProfileMeasuredEvent) => void;
}

const intIn = (v: unknown, min: number, max: number): v is number =>
  typeof v === "number" && Number.isInteger(v) && v >= min && v <= max;

/** A stored record is used only when every field is in range and the profile agrees with the pane count. */
function isResult(v: unknown): v is CapabilityResult {
  if (typeof v !== "object" || v === null) return false;
  const r = v as Partial<Record<keyof CapabilityResult, unknown>>;
  return (
    typeof r.p95FrameMs === "number" &&
    Number.isFinite(r.p95FrameMs) &&
    r.p95FrameMs >= 0 &&
    intIn(r.recommendedMaxPanes, 0, HARD_CAP_PANES) &&
    r.recommendedProfile === (r.recommendedMaxPanes >= FULL_MIN_PANES ? "full" : "reduced") &&
    intIn(r.paneCount, 1, HARD_CAP_PANES) &&
    intIn(r.sampleCount, 1, Number.MAX_SAFE_INTEGER)
  );
}

/** The remembered result for this device, or `null` when there is none or it does not parse. */
export function readCachedResult(storage: Pick<Storage, "getItem">): CapabilityResult | null {
  const raw = storage.getItem(PROBE_STORAGE_KEY);
  if (raw === null) return null;
  try {
    const v: unknown = JSON.parse(raw);
    return isResult(v) ? v : null;
  } catch {
    return null;
  }
}

/**
 * Starts the probe. Resolves with the cached result at once when one exists; otherwise, for each count in
 * `CALIBRATION_PANES`, draws that many panes, drops the warm-up (`WARMUP_FRAMES` or `WARMUP_MAX_MS`) and
 * collects a window (`WINDOW_FRAMES` or `WINDOW_MAX_MS`), then classifies, stores and reports. Time is the
 * sum of `frameSpanMs`, so a step takes at most 20 s plus two frames and the probe at most 40 s plus four frames
 * (a 160 ms-per-frame device: about 40 s, not 540 frames per step). A window that starves (fewer than
 * `MIN_WINDOW_FRAMES` frames in `WINDOW_MAX_MS`) ends the probe with `classifyStarved`. `cancel()` stops
 * sampling; the promise then never settles.
 */
export function startProbe(deps: ProbeDeps): {
  readonly result: Promise<CapabilityResult>;
  readonly cancel: () => void;
} {
  const cached = readCachedResult(deps.storage);
  if (cached !== null) return { result: Promise.resolve(cached), cancel: () => undefined };
  const windows: FrameWindow[] = [];
  let warmFrames = 0;
  let warmMs = 0;
  let series: number[] = [];
  let seriesMs = 0;
  let step = 0;
  let stop: () => void = () => undefined;
  let done = false;
  const result = new Promise<CapabilityResult>((resolve) => {
    const finish = (r: CapabilityResult): void => {
      done = true;
      stop();
      deps.storage.setItem(PROBE_STORAGE_KEY, JSON.stringify(r));
      deps.report({
        name: "capability.profile_measured",
        p95FrameMs: r.p95FrameMs,
        recommendedProfile: r.recommendedProfile,
        paneCount: r.paneCount,
      });
      resolve(r);
    };
    deps.drawPanes(CALIBRATION_PANES[0] ?? 1);
    stop = deps.onFrame((ms) => {
      if (done) return;
      if (warmFrames < WARMUP_FRAMES && warmMs < WARMUP_MAX_MS) {
        warmFrames += 1;
        warmMs += frameSpanMs(ms);
        return;
      }
      series.push(ms);
      seriesMs += frameSpanMs(ms);
      if (series.length < WINDOW_FRAMES && seriesMs < WINDOW_MAX_MS) return;
      const w: FrameWindow = { paneCount: CALIBRATION_PANES[step] ?? 1, frameMs: series };
      if (series.length < MIN_WINDOW_FRAMES) {
        finish(classifyStarved(windows, w));
        return;
      }
      windows.push(w);
      series = [];
      seriesMs = 0;
      warmFrames = 0;
      warmMs = 0;
      step += 1;
      const next = CALIBRATION_PANES[step];
      if (next !== undefined) {
        deps.drawPanes(next);
        return;
      }
      finish(classify(windows));
    });
  });
  return {
    result,
    cancel: () => {
      done = true;
      stop();
    },
  };
}

/**
 * The probe's runtime half (E15-K01 #371, BQ-10): it listens to the engine's per-frame times, classifies once
 * the warm-up and the window are collected, remembers the result per device (US-LAY-008) and reports
 * `capability.profile_measured` once per session through the caller's analytics seam. Every input is
 * injected, so nothing here reads the environment; the result holds aggregate timing only, never an
 * identifier, and nothing is sent anywhere (#371 Security notes).
 */
import {
  classify,
  warmWindow,
  WARMUP_FRAMES,
  WINDOW_FRAMES,
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

function isResult(v: unknown): v is CapabilityResult {
  if (typeof v !== "object" || v === null) return false;
  const r = v as Partial<Record<keyof CapabilityResult, unknown>>;
  return (
    typeof r.p95FrameMs === "number" &&
    typeof r.recommendedMaxPanes === "number" &&
    (r.recommendedProfile === "full" || r.recommendedProfile === "reduced") &&
    typeof r.paneCount === "number" &&
    typeof r.sampleCount === "number"
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
 * `CALIBRATION_PANES`, draws that many panes and samples `WARMUP_FRAMES + WINDOW_FRAMES` frames, then
 * classifies, stores and reports. `cancel()` stops sampling; the promise then never settles.
 */
export function startProbe(deps: ProbeDeps): {
  readonly result: Promise<CapabilityResult>;
  readonly cancel: () => void;
} {
  const cached = readCachedResult(deps.storage);
  if (cached !== null) return { result: Promise.resolve(cached), cancel: () => undefined };
  const windows: FrameWindow[] = [];
  let series: number[] = [];
  let step = 0;
  let stop: () => void = () => undefined;
  let done = false;
  const result = new Promise<CapabilityResult>((resolve) => {
    deps.drawPanes(CALIBRATION_PANES[0] ?? 1);
    stop = deps.onFrame((ms) => {
      if (done) return;
      series.push(ms);
      if (series.length < WARMUP_FRAMES + WINDOW_FRAMES) return;
      windows.push(warmWindow(CALIBRATION_PANES[step] ?? 1, series));
      series = [];
      step += 1;
      const next = CALIBRATION_PANES[step];
      if (next !== undefined) {
        deps.drawPanes(next);
        return;
      }
      done = true;
      stop();
      const r = classify(windows);
      deps.storage.setItem(PROBE_STORAGE_KEY, JSON.stringify(r));
      deps.report({
        name: "capability.profile_measured",
        p95FrameMs: r.p95FrameMs,
        recommendedProfile: r.recommendedProfile,
        paneCount: r.paneCount,
      });
      resolve(r);
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

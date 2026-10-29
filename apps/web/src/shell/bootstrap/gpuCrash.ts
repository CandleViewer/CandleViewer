/**
 * E10-S04 (#306) slice 9c: SCR-159's GPU-unavailable state, the desktop app's only (F15; the ruling
 * of record on #306, BQ-9.1 to 9.4). Each `cv:gpu:crashed` the preload forwards lands in the shell
 * store for the page and is reported once as `shell.gpu_unavailable`, by its reason class only. The
 * host's GPU is the shell port's: the Electron adapter where the preload ran. In a tab nothing
 * reports a crash: the browser adapter's `onCrashed` is a no-op, its retry refused.
 */
import { crashLogSettled } from "../crash/reportCrash.js";
import { createShellPort } from "../createShellPort.js";
import type { GpuCrash, GpuCrashReason, ShellPort } from "../ShellPort.js";
import { applyGpuCrash } from "./store.js";
import { THEME_ANALYTICS_EVENT } from "./themeStore.js";

export type GpuPort = Pick<ShellPort["gpu"], "onCrashed" | "retry">;

/** Retry waits this long at most for the crash log's appends: one lost line beats a dead Retry. */
export const CRASH_LOG_WAIT_MS = 2_000;

let active: GpuPort | null = null;
let retrying: Promise<void> | null = null;

/** `GpuCrashReason`'s values; a missing or an extra one fails the typecheck. */
const REASONS: Readonly<Record<GpuCrashReason, true>> = {
  "clean-exit": true,
  "abnormal-exit": true,
  killed: true,
  crashed: true,
  oom: true,
  "launch-failed": true,
  "integrity-failure": true,
  "memory-eviction": true,
  unknown: true,
};
const isCount = (v: unknown): v is number =>
  typeof v === "number" && Number.isSafeInteger(v) && v >= 0;
const isReason = (v: unknown): v is GpuCrashReason =>
  typeof v === "string" && Object.hasOwn(REASONS, v);

/** The preload's check again (SR-111, both sides): a fresh copy of the three fields, or nothing. */
function checked(payload: unknown): GpuCrash | undefined {
  if (typeof payload !== "object" || payload === null) return undefined;
  const { crashedAtMs, restartCount, reason } = payload as Partial<Record<keyof GpuCrash, unknown>>;
  return isCount(crashedAtMs) && isCount(restartCount) && isReason(reason)
    ? { crashedAtMs, restartCount, reason }
    : undefined;
}

/** Feeds the host's GPU crashes to the store; returns the unsubscribe. It never stops a start. */
export function watchGpu(gpu: GpuPort = createShellPort().gpu): () => void {
  let unsubscribe = (): void => undefined;
  try {
    unsubscribe = gpu.onCrashed((payload: unknown) => {
      const crash = checked(payload);
      if (crash === undefined) return;
      applyGpuCrash(crash);
      const detail = { name: "shell.gpu_unavailable", reason: crash.reason };
      window.dispatchEvent(new CustomEvent(THEME_ANALYTICS_EVENT, { detail }));
    });
    active = gpu;
  } catch {
    // a bridge without the GPU event: no page, and the shell starts all the same
    console.error("watchGpu: the GPU-crash event could not be subscribed");
  }
  return () => {
    unsubscribe();
    if (active !== gpu) return;
    active = null;
    retrying = null; // a restarted shell's next click reaches its own port
  };
}

/** The crash log's appends in flight, settled, or CRASH_LOG_WAIT_MS gone, whichever is first. */
function appendsSettled(): Promise<void> {
  let timer: ReturnType<typeof setTimeout> | undefined;
  const late = new Promise<void>((resolve) => {
    timer = setTimeout(resolve, CRASH_LOG_WAIT_MS);
  });
  return Promise.race([crashLogSettled(), late]).finally(() => clearTimeout(timer));
}

/**
 * SCR-159's Retry now on the GPU page, from a click only: one try at a time, and only once the
 * crash log's appends in flight have settled (main's relaunch, `app.exit(0)`, drops one still
 * open), or CRASH_LOG_WAIT_MS has gone. Rejects when main refuses (no crash this session, or a
 * retry in the last 60 s).
 */
export function retryGpuNow(): Promise<void> {
  const gpu = active;
  if (gpu === null) return Promise.reject(new Error("GPU retry: not watching the GPU"));
  if (retrying === null) {
    const attempt: Promise<void> = appendsSettled()
      .then(() => gpu.retry())
      .finally(() => {
        if (retrying === attempt) retrying = null;
      });
    retrying = attempt;
  }
  return retrying;
}

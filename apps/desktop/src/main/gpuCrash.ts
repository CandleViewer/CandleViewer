/**
 * The `cv:gpu:crashed` payload (F15, E10-S04), checked again in preload (SR-111): what the crash
 * page shows, never Electron's exit code, process name or other platform text. No imports, so the
 * sandboxed preload can bundle it; apps/web's `GpuCrash` mirrors it by shape (desktop-not-to-web).
 * `cv:gpu:info` carries the last one as `lastCrash` (#4951), for a page that subscribed after it.
 */

/** Electron's `child-process-gone` reasons; any other value is sent as "unknown". */
const GPU_CRASH_REASONS = [
  "clean-exit",
  "abnormal-exit",
  "killed",
  "crashed",
  "oom",
  "launch-failed",
  "integrity-failure",
  "memory-eviction",
  "unknown",
] as const;

export type GpuCrashReason = (typeof GPU_CRASH_REASONS)[number];

export interface GpuCrash {
  /** Main's clock, epoch milliseconds. */
  readonly crashedAtMs: number;
  /** GPU-process restarts this session, this one included. */
  readonly restartCount: number;
  readonly reason: GpuCrashReason;
}

/** `cv:gpu:info`'s `lastCrash`: this session's last GPU crash, as `cv:gpu:crashed` sent it. */
export interface GpuLastCrash extends GpuCrash {
  /** A `cv:gpu:retry` was accepted after it: the app is relaunching. */
  readonly retried: boolean;
}

function isGpuCrashReason(value: unknown): value is GpuCrashReason {
  return GPU_CRASH_REASONS.some((reason) => reason === value);
}

/** The reason class of an Electron `child-process-gone` reason. */
export function toGpuCrashReason(value: unknown): GpuCrashReason {
  return isGpuCrashReason(value) ? value : "unknown";
}

function isCount(value: unknown): value is number {
  return typeof value === "number" && Number.isSafeInteger(value) && value >= 0;
}

/** A fresh, frozen copy of a `cv:gpu:crashed` payload's three fields, or undefined. */
export function parseGpuCrash(value: unknown): GpuCrash | undefined {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    return undefined;
  }
  // A cast only to name the fields: each is checked below before it is used.
  const { crashedAtMs, restartCount, reason } = value as Partial<Record<keyof GpuCrash, unknown>>;
  return isCount(crashedAtMs) && isCount(restartCount) && isGpuCrashReason(reason)
    ? Object.freeze({ crashedAtMs, restartCount, reason })
    : undefined;
}

/**
 * `cv:gpu:info`'s `lastCrash`, checked as a `cv:gpu:crashed` payload is: null for none, a fresh,
 * frozen copy of its four fields, or undefined.
 */
export function parseGpuLastCrash(value: unknown): GpuLastCrash | null | undefined {
  if (value === null) {
    return null;
  }
  const crash = parseGpuCrash(value);
  if (crash === undefined) {
    return undefined;
  }
  // parseGpuCrash took `value` for an object; `retried` is checked before it is used.
  const { retried } = value as { retried?: unknown };
  return typeof retried === "boolean" ? Object.freeze({ ...crash, retried }) : undefined;
}

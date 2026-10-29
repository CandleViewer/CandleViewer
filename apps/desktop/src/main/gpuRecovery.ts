/**
 * GPU-process crash recovery in main (F15, E10-S04): each GPU `child-process-gone` becomes one
 * `cv:gpu:crashed` payload; `cv:gpu:retry` relaunches the app only after a crash this session, at
 * most once per GPU_RETRY_INTERVAL_MS across relaunches, and audits a refusal by reason only.
 */
import { rateLimitedAudit } from "./crashLog.js";
import { toGpuCrashReason, type GpuCrash } from "./gpuCrash.js";

export const GPU_RETRY_INTERVAL_MS = 60_000;
/** Main adds this value-less token to a GPU relaunch's argv once; it only makes retry stricter. */
export const GPU_RELAUNCH_MARKER = "--cv-gpu-relaunched";

/** What the renderer sees for a refused retry: a fixed message, never the reason. */
export class GpuRetryRefusedError extends Error {
  constructor() {
    super("GPU retry refused");
    this.name = "GpuRetryRefusedError";
  }
}

export interface GpuRecoveryOptions {
  /** This launch's arguments (`process.argv.slice(1)`): only the exact marker is read. */
  readonly argv: readonly string[];
  /** index.ts: `app.relaunch({ args })`, then `app.exit(0)`. */
  readonly relaunch: (args: string[]) => void;
  readonly audit?: (event: string, detail: Record<string, unknown>) => void;
  /** Main's clock (ms): stamps the crash and windows the limits. */
  readonly now?: () => number;
}

export interface GpuRecovery {
  /** Electron's `child-process-gone`: the payload for the shell page if the GPU process went. */
  childProcessGone(details: { type: string; reason: string }): GpuCrash | undefined;
  /** `cv:gpu:retry`, after the sender check: relaunches, or throws GpuRetryRefusedError. */
  readonly retry: () => void;
}

export function createGpuRecovery(options: GpuRecoveryOptions): GpuRecovery {
  const now = options.now ?? Date.now;
  const audit = options.audit ?? (() => undefined);
  const auditRefusal = rateLimitedAudit(audit, now, "gpu-retry-audit-suppressed");
  const argv = [...options.argv];
  const relaunched = argv.includes(GPU_RELAUNCH_MARKER);
  let restartCount = 0;
  // A launch a retry relaunched counts as a retry accepted at start, so the bound spans relaunches.
  let acceptedAt: number | undefined = relaunched ? now() : undefined;

  const refusalOf = (at: number): string | undefined =>
    restartCount === 0
      ? "no-crash"
      : acceptedAt !== undefined && at - acceptedAt < GPU_RETRY_INTERVAL_MS
        ? "rate-limited"
        : undefined;

  return {
    childProcessGone(details) {
      if (details.type !== "GPU") {
        return undefined;
      }
      restartCount += 1;
      const reason = toGpuCrashReason(details.reason);
      audit("gpu-process-gone", { reason, restartCount });
      return { crashedAtMs: now(), restartCount, reason };
    },
    retry: () => {
      const at = now();
      const refusal = refusalOf(at);
      if (refusal !== undefined) {
        auditRefusal("gpu-retry-refused", { reason: refusal });
        throw new GpuRetryRefusedError();
      }
      acceptedAt = at;
      audit("gpu-retry-accepted", { restartCount });
      options.relaunch(relaunched ? [...argv] : [...argv, GPU_RELAUNCH_MARKER]);
    },
  };
}

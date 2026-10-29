/**
 * GPU-process crash recovery in main (F15, E10-S04): each GPU `child-process-gone` becomes one
 * `cv:gpu:crashed` payload; `cv:gpu:retry` relaunches the app only after a crash this session, at
 * most once per GPU_RETRY_INTERVAL_MS across relaunches, and audits a refusal by reason only. The
 * last crash stays readable for `cv:gpu:info` (#4951): a page that subscribed after it missed it.
 * `cv:gpu:keepSoftware` marks it kept (#306), so a reload or a new window shows SCR-153's row.
 */
import { rateLimitedAudit } from "./crashLog.js";
import { toGpuCrashReason, type GpuCrash, type GpuLastCrash } from "./gpuCrash.js";

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

/** What the renderer sees for a refused keep (no GPU crash this launch): a fixed message. */
export class GpuKeepRefusedError extends Error {
  constructor() {
    super("GPU keep refused");
    this.name = "GpuKeepRefusedError";
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
  /** `cv:gpu:keepSoftware`, after the sender check: keeps the last crash, or refuses (throws). */
  readonly keepSoftware: () => void;
  /** `cv:gpu:info`'s `lastCrash`: this session's last GPU crash, or null before one. */
  readonly lastCrash: () => GpuLastCrash | null;
}

export function createGpuRecovery(options: GpuRecoveryOptions): GpuRecovery {
  const now = options.now ?? Date.now;
  const audit = options.audit ?? (() => undefined);
  const auditRefusal = rateLimitedAudit(audit, now, "gpu-retry-audit-suppressed");
  const auditKeepRefusal = rateLimitedAudit(audit, now, "gpu-keep-audit-suppressed");
  const argv = [...options.argv];
  const relaunched = argv.includes(GPU_RELAUNCH_MARKER);
  let restartCount = 0;
  // A launch a retry relaunched counts as a retry accepted at start, so the bound spans relaunches.
  let acceptedAt: number | undefined = relaunched ? now() : undefined;
  let last: GpuCrash | undefined;
  let retried = false; // a retry was accepted after `last`
  let kept = false; // the user kept software rendering for `last`

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
      last = { crashedAtMs: now(), restartCount, reason };
      retried = false;
      kept = false;
      return last;
    },
    retry: () => {
      const at = now();
      const refusal = refusalOf(at);
      if (refusal !== undefined) {
        auditRefusal("gpu-retry-refused", { reason: refusal });
        throw new GpuRetryRefusedError();
      }
      acceptedAt = at;
      retried = true;
      audit("gpu-retry-accepted", { restartCount });
      options.relaunch(relaunched ? [...argv] : [...argv, GPU_RELAUNCH_MARKER]);
    },
    // Idempotent; one audit line per crash kept, and refusals bounded per window as retry's are.
    // No argument (the ruled shape): a crash main handles inside the click's round trip is kept
    // with it. That's presentation only: its own page still shows, and a reload shows it as the row.
    keepSoftware: () => {
      if (last === undefined) {
        auditKeepRefusal("gpu-keep-refused", { reason: "no-crash" });
        throw new GpuKeepRefusedError();
      }
      if (!kept) {
        kept = true;
        audit("gpu-software-kept", { restartCount: last.restartCount });
      }
    },
    lastCrash: () => (last === undefined ? null : { ...last, retried, kept }),
  };
}

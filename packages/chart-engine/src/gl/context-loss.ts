// Context-loss recovery (E11-S02, 26 §3.4, README BQ-49): a pure state machine on injected timers.
// `lost` drops GPU state and parks the frame loop; each of three attempts waits for `restored`
// for its backoff (1 / 2 / 4 s), and a rebuild that loses again is a failed attempt. The third
// failure gives up for good: the host swaps the canvas and the chart goes `degraded-2d` (BQ-53).
// The R1 budget (30 §5.3 exit criterion 8: 2 s) runs from `lost` to the first complete frame.
export const ENGINE_CONTEXT_LOST = "ENGINE_CONTEXT_LOST";
export const ENGINE_CONTEXT_RESTORED = "ENGINE_CONTEXT_RESTORED";
export const ENGINE_CONTEXT_RESTORE_FAILED = "ENGINE_CONTEXT_RESTORE_FAILED";
/** The R1 restore budget in ms (30 §5.3 exit criterion 8). */
export const RESTORE_BUDGET_MS = 2000;

export type LossPhase = "live" | "lost" | "restoring" | "failed";

export interface LossHooks {
  /** Each attempt's wait for `restored`; its length is the attempt count. */
  readonly backoffMs: readonly number[];
  now(): number;
  setTimer(cb: () => void, ms: number): void;
  /** Drops every GL object (CPU state stays) and parks the frame loop. */
  park(): void;
  /** Rebuilds GPU state from CPU state; false when the context was lost again. */
  rebuild(): boolean;
  /** Unparks the loop with every node DATA-dirty. */
  resume(): void;
  /** The last attempt failed: the loop stays parked for good. */
  giveUp(): void;
  emit(code: string, message: string, recoverable: boolean, details?: LossDetails): void;
}

/** `ChartEvents.error.details`, set only on `ENGINE_CONTEXT_LOST` (BQ-64). */
export interface LossDetails {
  readonly attempt: number;
  readonly maxAttempts: number;
  readonly nextTryMs: number;
}

export class ContextLoss {
  phase: LossPhase = "live";
  /** 1-based attempt in progress; 0 while live. */
  attempt = 0;
  /** `engine.gl.context_losses`, failed attempts, `engine.gl.restore_ms` of the last restore. */
  readonly stats = { losses: 0, failures: 0, restoreMs: Number.NaN };
  private lostAt = 0;
  private epoch = 0; // bumped to cancel an attempt's timer (no clearTimeout needed)

  constructor(private readonly h: LossHooks) {}

  /** `webglcontextlost`: `preventDefault()` asks the browser to restore the context. */
  lost(ev?: { preventDefault(): void }): void {
    ev?.preventDefault();
    if (this.phase === "restoring") this.fail(); // lost again before a complete frame
    if (this.phase !== "live") return; // a repeat while an attempt waits, or after giving up
    this.phase = "lost";
    this.stats.losses += 1;
    this.lostAt = this.h.now();
    this.attempt = 0;
    this.h.park();
    this.next();
  }

  /** `webglcontextrestored`: rebuild now; the attempt fails if the context is lost again. */
  restored(): void {
    if (this.phase !== "lost") return;
    this.epoch += 1;
    this.phase = "restoring";
    let ok = false;
    try {
      ok = this.h.rebuild();
    } catch {
      ok = false; // a driver fault mid-rebuild is a failed attempt, never a hang
    }
    if (ok) this.h.resume();
    else this.fail();
  }

  /** The chart was released or re-inited: a pending attempt's timer does nothing. */
  cancel(): void {
    this.epoch += 1;
    this.phase = "failed";
  }

  /** The first complete frame after a rebuild closes the episode and records the restore time. */
  framed(): void {
    if (this.phase !== "restoring") return;
    this.phase = "live";
    this.attempt = 0;
    this.stats.restoreMs = this.h.now() - this.lostAt;
    this.h.emit(ENGINE_CONTEXT_RESTORED, `Chart restored in ${this.stats.restoreMs} ms`, true);
  }

  private next(): void {
    this.attempt += 1;
    const ms = this.h.backoffMs[this.attempt - 1] ?? 0;
    const epoch = (this.epoch += 1);
    const n = this.h.backoffMs.length;
    const at = `attempt ${this.attempt} of ${n}, next try in ${ms / 1000} s`;
    const details = { attempt: this.attempt, maxAttempts: n, nextTryMs: ms };
    this.h.emit(ENGINE_CONTEXT_LOST, `Graphics context lost: restoring, ${at}`, true, details);
    this.h.setTimer(() => {
      if (epoch === this.epoch) this.fail();
    }, ms);
  }

  private fail(): void {
    this.epoch += 1;
    this.stats.failures += 1;
    this.h.park();
    if (this.attempt < this.h.backoffMs.length) {
      this.phase = "lost";
      this.next();
      return;
    }
    this.phase = "failed";
    const message = `Graphics context could not be restored after ${this.attempt} attempts`;
    this.h.emit(ENGINE_CONTEXT_RESTORE_FAILED, message, false);
    this.h.giveUp();
  }
}

// The per-frame context (E11-S01): internal, not §8's `RenderContext`; one reused per chart.
import type { ViewportState } from "../viewport/types.js";
import { ChartViewport } from "../viewport/Viewport.js";

/** What `update(frameCtx)` receives: read-only, except the counters in `stats`. */
export type FrameCtx = Readonly<Omit<FrameContext, "begin" | "viewport">> & {
  readonly viewport: ViewportState;
};

export class FrameContext {
  t = 0;
  dt = 0;
  theme: unknown = null;
  lod = 0;
  budgetMsRemaining = 0;
  prefersReducedMotion = false;
  readonly stats = { collected: 0, deferred: 0, updated: 0 };
  private started = false;

  /** The chart's shared transform (E11-S03): nodes project through `src/viewport/transform`. */
  constructor(readonly viewport: ViewportState = new ChartViewport()) {}

  /** Starts a frame at `t` ms: `dt` is elapsed time (0 on the first frame); counters reset. */
  begin(t: number, budgetMs: number): void {
    this.dt = this.started ? Math.max(0, t - this.t) : 0;
    this.started = true;
    this.t = t;
    this.budgetMsRemaining = budgetMs;
    this.stats.collected = this.stats.deferred = this.stats.updated = 0;
  }
}

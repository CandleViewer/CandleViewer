// The per-frame context (E11-S01): internal, not §8's `RenderContext`; one reused per chart.

/** What `update(frameCtx)` receives: read-only, except the counters in `stats`. */
export type FrameCtx = Readonly<Omit<FrameContext, "begin" | "viewport">> & {
  readonly viewport: Readonly<FrameContext["viewport"]>;
};

export class FrameContext {
  t = 0;
  dt = 0;
  /** A placeholder until E11-S03's viewport maths; not §8's `Viewport` (BQ-25). */
  readonly viewport = { fromIndex: 0, toIndex: 0, priceMin: 0, priceMax: 0 };
  theme: unknown = null;
  lod = 0;
  budgetMsRemaining = 0;
  prefersReducedMotion = false;
  readonly stats = { collected: 0, deferred: 0, updated: 0 };
  private started = false;

  /** Starts a frame at `t` ms: `dt` is elapsed time (0 on the first frame); counters reset. */
  begin(t: number, budgetMs: number): void {
    this.dt = this.started ? Math.max(0, t - this.t) : 0;
    this.started = true;
    this.t = t;
    this.budgetMsRemaining = budgetMs;
    this.stats.collected = this.stats.deferred = this.stats.updated = 0;
  }
}

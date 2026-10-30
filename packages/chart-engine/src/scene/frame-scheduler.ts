// The frame scheduler (E11-S01, 26 §3.2): render on demand, one frame per wake, a clamped mutation
// drain, dt-based animation, 06 §4.3 stage timings and the 06 §4.4 shedding ladder with the LOD
// step-down trigger. DOM-free: the clock is injected (BQ-36); nothing here allocates per frame.
import { DeferClass } from "./dirty.js";
import type { FrameClock } from "./frame-clock.js";
import { FrameContext, type FrameCtx } from "./frame-context.js";
import type { SceneGraph } from "./graph.js";
import { type Mutation, MutationQueue } from "./mutation-queue.js";
import { PooledBatchSink } from "./pool.js";

/** 06 §4.3's nine stages, the names `bench/instrumentation.mjs` records. */
export const FRAME_STAGES = [
  "inputHandling",
  "dataWindowRecompute",
  "candleGeometry",
  "footprintTextGeometry",
  "heatmapUpload",
  "paneRedraw",
  "overlayRedraw",
  "domMirrorSync",
  "compositePresent",
] as const;
export type FrameStage = (typeof FRAME_STAGES)[number];

/** 06 §4.3's nominal slice per stage, ms, in `FRAME_STAGES` order. */
export const STAGE_SLICE_MS = [1, 2, 2, 4, 2, 2, 1, 1, 1.6] as const;

const [INPUT, DATA_WINDOW, GEOMETRY, PANE, PRESENT] = [0, 1, 2, 5, 8] as const; // FRAME_STAGES indexes
export const HEATMAP_CADENCE_MS = 250; // 06 §4.4 rung 1, relaxed from 100 ms
const CADENCE_MS = [0, HEATMAP_CADENCE_MS, 500, 0, 500] as const; // a shed rung's longest wait
const RECOVER_BELOW = 0.85; // a frame under 85 % of budget counts toward recovery (BQ-38)
const RECOVER_MS = 500; // = the longest cadence; strict < here vs >= in shedMask: zero margin
const RUN = 3; // consecutive frames that trigger a step-down or a recovery

const LAYOUT_SLICE_MS = 2; // the ticket's layout clamp (C-3), timed apart from 06's nine (BQ-43)

/** Per-stage durations of the last frame, ms (internal, BQ-S3: §8 `FrameStats` is frozen). */
export class FrameTimings {
  readonly ms = new Float64Array(FRAME_STAGES.length);
  layoutMs = 0;
  total = 0;

  /** The stage furthest over its slice (the first stage when none is over). */
  worstStage(): FrameStage | "layout" {
    let worst = 0;
    for (let i = 1; i < this.ms.length; i += 1) {
      const over = (this.ms[i] as number) - (STAGE_SLICE_MS[i] as number);
      if (over > (this.ms[worst] as number) - (STAGE_SLICE_MS[worst] as number)) worst = i;
    }
    const over = (this.ms[worst] as number) - (STAGE_SLICE_MS[worst] as number);
    return this.layoutMs - LAYOUT_SLICE_MS > over ? "layout" : (FRAME_STAGES[worst] as FrameStage);
  }
}

export const ENGINE_LOD_STEPDOWN = "ENGINE_LOD_STEPDOWN";
export const ENGINE_FRAME_BUDGET_EXCEEDED = "ENGINE_FRAME_BUDGET_EXCEEDED";

/** One reused notice per code, forwarded as `ChartEvents.error`, `recoverable: true` (BQ-S3). */
export class FrameNotice {
  readonly recoverable = true;
  from = 0; // LOD levels (ENGINE_LOD_STEPDOWN only)
  to = 0;
  totalMs = 0;
  stage: FrameStage | "layout" = "inputHandling";
  readonly timings = new Float64Array(FRAME_STAGES.length);
  layoutMs = 0;
  pending = false;

  constructor(readonly code: string) {}

  raise(timings: FrameTimings): void {
    this.totalMs = timings.total;
    this.stage = timings.worstStage();
    this.timings.set(timings.ms);
    this.layoutMs = timings.layoutMs;
    this.pending = true;
  }
}

/** A time-based animation (26 §3.2 rule 2): it sees elapsed ms only, never a frame count. */
export interface Animation {
  /** Integrates `dtMs` (and may mark the graph); `false` once it has come to rest. */
  step(dtMs: number, ctx: FrameCtx): boolean;
}

/** The stages bound by the runtime: input router, `LayoutEngine`, `BatchBuilder`, GL submit. */
export interface SchedulerHooks {
  input?(ctx: FrameContext): void;
  layout?(ctx: FrameContext): void;
  build?(sink: PooledBatchSink, ctx: FrameContext): void;
  submit?(sink: PooledBatchSink, ctx: FrameContext): void;
}

export class FrameScheduler {
  readonly ctx = new FrameContext();
  readonly sink = new PooledBatchSink();
  readonly queue = new MutationQueue();
  readonly timings = new FrameTimings();
  readonly notice = new FrameNotice(ENGINE_LOD_STEPDOWN);
  /** Raised on the first frame of each over-budget run, never once per frame (BQ-44). */
  readonly budgetNotice = new FrameNotice(ENGINE_FRAME_BUDGET_EXCEEDED);
  /** 0 to 4: rungs 1..shedLevel of 06 §4.4 are shed; `critical` nodes never are. */
  shedLevel = 0;
  lod = 0;
  frames = 0;
  deferredMutations = 0; // engine.frame.deferred_mutations: left queued by the last drain
  parkedMs = 0; // engine.frame.parked_ms: total time with no frame requested
  private readonly animations: Animation[] = [];
  private readonly onFrame = (t: number): void => this.frame(t);
  private handle = 0; // -1 once disposed: `wake()` is then a no-op
  private scheduled = false;
  private parkedAt = Number.NaN; // NaN until the first park, and while a frame is requested or runs
  private resumed = true; // the next frame follows a park
  private over = 0; // consecutive frames over budget
  private under = 0;
  private underFrom = 0; // `t` of the first frame of the current run under 85 %
  private readonly shedAt = new Float64Array(CADENCE_MS.length).fill(-Infinity);

  constructor(
    readonly graph: SceneGraph,
    private readonly clock: FrameClock,
    private readonly hooks: SchedulerHooks = {},
    readonly budgetMs = 16.7,
    readonly drainMs = 4,
    readonly maxLod = 2,
  ) {}

  /** No frame is requested: nothing is dirty, queued or animating. */
  get parked(): boolean {
    return !this.scheduled;
  }

  /** Called by the data port, the input router and the sync group: one frame, never two. */
  wake(): void {
    if (this.scheduled || this.handle < 0) return;
    if (!Number.isNaN(this.parkedAt)) this.parkedMs += this.clock.now() - this.parkedAt;
    this.parkedAt = Number.NaN;
    this.scheduled = true;
    this.handle = this.clock.requestFrame(this.onFrame);
  }

  enqueue(mutation: Mutation): void {
    this.queue.push(mutation);
    this.wake();
  }

  animate(animation: Animation): void {
    this.animations.push(animation);
    this.wake();
  }

  /** The pending notice, once; `null` when none was raised since the last call. */
  takeNotice(notice: FrameNotice = this.notice): FrameNotice | null {
    if (!notice.pending) return null;
    notice.pending = false;
    return notice;
  }

  dispose(): void {
    if (this.scheduled) this.clock.cancel(this.handle);
    this.scheduled = false;
    this.handle = -1;
  }

  /** A throwing mutation or hook ends the frame, never the loop: the queue left re-wakes it. */
  private frame(t: number): void {
    this.scheduled = false;
    let done = false;
    try {
      this.run(t);
      done = true;
    } finally {
      if (!done) this.settle(this.queue.length > 0); // the throw itself propagates (26 §11)
    }
  }

  /** input → drain → layout → update/collect → build → submit (06 §4.3, BQ-S4, BQ-43). */
  private run(t: number): void {
    const { ctx, sink, timings, hooks } = this;
    const start = this.clock.now();
    timings.ms.fill(0);
    ctx.begin(t, this.budgetMs);
    if (this.resumed) ctx.dt = 0; // nothing animated while parked
    this.resumed = false;
    ctx.lod = this.lod;
    hooks.input?.(ctx);
    const live = this.animations; // a finished animation is swap-removed: no allocation
    for (let i = live.length - 1; i >= 0; i -= 1) {
      if ((live[i] as Animation).step(ctx.dt, ctx)) continue;
      live[i] = live[live.length - 1] as Animation; // already stepped: the walk runs backwards
      live.length -= 1;
    }
    let at = this.stage(INPUT, start);
    this.deferredMutations = this.queue.drain(this.clock, this.drainMs);
    at = this.stage(DATA_WINDOW, at);
    hooks.layout?.(ctx);
    const laidOut = this.clock.now();
    timings.layoutMs = laidOut - at;
    at = laidOut;
    ctx.budgetMsRemaining = this.budgetMs - (at - start);
    sink.reset();
    // Spent before collect: shed every rung, each still on its cadence floor (BQ-35 closed).
    const level = ctx.budgetMsRemaining < 0 ? DeferClass.BACKGROUND_PANES : this.shedLevel;
    this.graph.frame(ctx, sink, this.shedMask(t, level));
    at = this.stage(GEOMETRY, at);
    hooks.build?.(sink, ctx);
    at = this.stage(PANE, at);
    hooks.submit?.(sink, ctx);
    timings.total = this.stage(PRESENT, at) - start;
    this.frames += 1;
    this.account(timings.total, t);
    const busy = ctx.stats.deferred > 0 || ctx.stats.updated > ctx.stats.collected;
    this.settle(busy || this.queue.length > 0 || this.animations.length > 0);
  }

  private settle(busy: boolean): void {
    if (busy) this.wake();
    else if (!this.scheduled) {
      this.parkedAt = this.clock.now();
      this.resumed = true;
    }
  }

  private stage(index: number, from: number): number {
    const now = this.clock.now();
    this.timings.ms[index] = (this.timings.ms[index] as number) + now - from;
    return now;
  }

  /** The rungs shed this frame, each on its cadence, so none goes stale (BQ-26, BQ-35). */
  private shedMask(t: number, level: number): number {
    let mask = 0;
    for (let r = 1; r <= level; r += 1) {
      const late = t - (this.shedAt[r] as number) >= (CADENCE_MS[r] as number);
      if (r === DeferClass.INDICATOR_COALESCE ? (this.frames & 1) === 0 : late) this.shedAt[r] = t;
      else mask |= 1 << r;
    }
    for (let r = level + 1; r < CADENCE_MS.length; r += 1) this.shedAt[r] = t;
    return mask;
  }

  /** 3 frames over budget: shed a rung, step LOD down; 3 under 85 % over 500 ms: recover one. */
  private account(totalMs: number, t: number): void {
    if (totalMs <= this.budgetMs) {
      this.over = 0;
      this.under = totalMs < RECOVER_BELOW * this.budgetMs ? this.under + 1 : 0;
      if (this.under === 1) this.underFrom = t;
      if (this.under < RUN || t - this.underFrom < RECOVER_MS || this.shedLevel === 0) return;
      this.under = 0;
      this.shedLevel -= 1;
      return;
    }
    this.under = 0;
    this.over += 1;
    if (this.over === 1) this.budgetNotice.raise(this.timings);
    if (this.over % RUN !== 0) return;
    this.shedLevel = Math.min(this.shedLevel + 1, DeferClass.BACKGROUND_PANES);
    if (this.lod >= this.maxLod) return;
    this.notice.from = this.lod;
    this.notice.to = this.lod += 1;
    this.notice.raise(this.timings);
  }
}

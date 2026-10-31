// `input-router` scene (E11-S04 PR 1, BQ-112): the worker's input stage over 100 000 bars at a
// 240 Hz trackpad's rate. Each step is one frame: a drag's four coalesced move rows (or a folded
// wheel row) go through `Gestures` in the scheduler's input hook, then the glide, if any, steps.
// The unit test counts (no registration, pool or buffer grows per frame); the .perf.test.ts times
// 06 §4.3's input stage (≤ 1 ms). No stage here allocates: the batches are built once.
import { Gestures } from "../../src/interaction/gestures.js";
import { plotWidthOf } from "../../src/interaction/wheel.js";
import { BarStore } from "../../src/model/BarStore.js";
import type { FrameCallback } from "../../src/scene/frame-clock.js";
import { FrameScheduler } from "../../src/scene/frame-scheduler.js";
import { SceneGraph } from "../../src/scene/graph.js";
import { ChartViewport } from "../../src/viewport/index.js";
import { INPUT, INPUT_STRIDE } from "../../src/worker/protocol.js";
import { bars } from "./pan-zero-upload.js";

const SIZE = { width: 1280, height: 744 }; // a 1216 × 720 plot
const MOVES = 4; // a 240 Hz trackpad's samples per 60 Hz frame

export class InputRouterBench {
  readonly viewport: ChartViewport;
  readonly gestures: Gestures;
  readonly scheduler: FrameScheduler;
  /** Viewport changes applied, and glides registered with the scheduler. */
  changes = 0;
  registrations = 0;
  /** `inputHandling` (06 §4.3) summed over the steps, ms. */
  inputMs = 0;
  private pending: FrameCallback | null = null;
  private readonly drag = new Float32Array(MOVES * INPUT_STRIDE);
  private readonly wheel = new Float32Array(INPUT_STRIDE);
  private readonly edge = new Float32Array(INPUT_STRIDE); // a down or an up
  private readonly idle = new Float32Array(0); // a frame with no input: the glide alone
  private batch: Float32Array = this.drag;
  private x = 600;

  constructor(
    n = 100_000,
    private readonly now: () => number = () => 0,
  ) {
    const store = new BarStore();
    store.append(bars(n));
    this.viewport = new ChartViewport(store);
    this.viewport.setSize(plotWidthOf(SIZE.width), 720, 1);
    this.viewport.pan(-(n / 2) * this.viewport.barSpacing);
    this.scheduler = new FrameScheduler(
      new SceneGraph(),
      {
        now: () => this.now(),
        requestFrame: (cb) => ((this.pending = cb), 1),
        cancel: () => (this.pending = null),
      },
      { input: () => this.gestures.apply(false, this.batch) },
    );
    this.gestures = new Gestures(this.viewport, SIZE, {
      moved: (c) => void (this.changes += c ? 1 : 0),
      hover: () => undefined,
      animate: (m) => {
        this.registrations += 1;
        this.scheduler.animate(m);
      },
    });
    this.wheel.set([INPUT.wheel, 600, 300, -12, 0, 4]);
  }

  /** One frame at `tMs`: frames 0-29 of every 60 drag right, 30 releases, 31-59 glide or wheel. */
  step(f: number, tMs: number): void {
    const phase = f % 60;
    if (phase === 0) this.edge.set([INPUT.down, (this.x = 600), 300, 1, 0, 0]);
    if (phase === 30) this.edge.set([INPUT.up, this.x, 300, 0, 0, 4]);
    if (phase === 0 || phase === 30) this.batch = this.edge;
    else if (phase < 30) {
      for (let i = 0; i < MOVES; i += 1) {
        const o = i * INPUT_STRIDE;
        this.x += 6; // 1.5 px/ms
        this.drag[o] = INPUT.move;
        this.drag[o + 1] = this.x;
        this.drag[o + 2] = 300;
        this.drag[o + 3] = 1;
        this.drag[o + 5] = 4;
      }
      this.batch = this.drag;
    } else this.batch = phase === 50 ? this.wheel : this.idle;
    this.scheduler.wake();
    const frame = this.pending;
    this.pending = null;
    frame?.(tMs);
    this.inputMs += this.scheduler.timings.ms[0] as number;
  }
}

// `resize-drag` scene (E11-S10 PR 2, README BQ-154): a seeded 2 s splitter drag, 120 frames of
// ±1–6 px, the first 60 growing the pane's width and the last 60 shrinking it, through the host's
// growth policy (`BackingSizer`, BQ-149) and the render runtime on an injected GL, then the quiet
// frames that trim the store. The canvas counts every reallocation and every shrink. The unit test
// counts; the .perf.test.ts times the CPU per resize. The real-GPU p95 is G-35 (E11-T08 / E11-Q02).
// Deviation (README BQ-154): the scene drives the host's policy and messages, not `createChartHost`
// (a DOM-program module); the host's own settle loop is covered by test/api/growth.test.ts.
import { mulberry32 } from "../fixtures/rng.mjs";
import type { GL2Like } from "../../src/gl/gl-types.js";
import { BackingSizer, SETTLE_FRAMES } from "../../src/worker/backing.js";
import type { CapabilityReport, FromWorker } from "../../src/worker/protocol.js";
import { createRenderRuntime, type RenderRuntime } from "../../src/worker/runtime.js";

export const DRAG_FRAMES = 120;
export const DRAG_START = { width: 1200, height: 800 };
const START = DRAG_START;

/** A canvas that records its backing-store reallocations (a width or height that changes). */
class CountingCanvas {
  private w = START.width;
  private h = START.height;
  reallocations = 0;
  shrinks = 0;
  constructor(private readonly gl: GL2Like) {}
  get width(): number {
    return this.w;
  }
  set width(v: number) {
    this.count(v, this.w);
    this.w = v;
  }
  get height(): number {
    return this.h;
  }
  set height(v: number) {
    this.count(v, this.h);
    this.h = v;
  }
  getContext(id: string): unknown {
    return id === "webgl2" ? this.gl : null;
  }
  private count(next: number, prev: number): void {
    if (next === prev) return;
    this.reallocations += 1;
    if (next < prev) this.shrinks += 1;
  }
}

export class ResizeDragBench {
  readonly canvas: CountingCanvas;
  readonly runtime: RenderRuntime;
  readonly sizer = new BackingSizer(START.width, START.height, 1);
  readonly posted: FromWorker[] = [];
  /** The widest exact size the drag reached, and the store's reallocations and shrinks in it. */
  maxWidth = START.width;
  dragReallocations = 0;
  dragShrinks = 0;
  /** Quiet frames until the trim, and the trims posted after the drag. */
  settleFrames = 0;
  trims = 0;
  private pending: (() => void) | null = null;
  private width = START.width;
  private readonly widths: number[];

  constructor(gl: GL2Like, probe: () => CapabilityReport, seed = 0x5eed) {
    this.canvas = new CountingCanvas(gl);
    this.runtime = createRenderRuntime({
      runMode: "inline",
      post: (m) => void this.posted.push(m),
      requestFrame: (cb) => void (this.pending = cb),
      now: () => 0,
      setTimer: () => undefined,
      probe,
    });
    const config = { bench: false, syncGroup: null };
    this.runtime.handle({ t: "init", id: 1, canvas: this.canvas, dpr: 1, theme: {}, config });
    this.frame(); // opens the backend: the first frame is not a drag frame
    this.widths = ResizeDragBench.widths(seed);
  }

  /** The drag's widths (CSS px) for a seed: 120 moves of 1–6 px, out for 60, back for 60. */
  static widths(seed = 0x5eed): number[] {
    const rng = mulberry32(seed);
    let w = START.width;
    return Array.from({ length: DRAG_FRAMES }, (_, f) => {
      const dx = 1 + Math.floor(rng() * 6);
      return (w += f < DRAG_FRAMES / 2 ? dx : -dx);
    });
  }

  /** One drag frame: the splitter moves 1–6 px (out for the first half, back in for the second). */
  step(f: number): void {
    this.width = this.widths[f] ?? this.width;
    this.maxWidth = Math.max(this.maxWidth, this.width);
    this.sizer.resize(this.width, START.height, 1);
    this.post();
    this.frame();
  }

  /** The whole drag, then quiet frames until the host's policy trims the store. */
  run(): this {
    for (let f = 0; f < DRAG_FRAMES; f += 1) this.step(f);
    return this.settle();
  }

  /** After the drag: quiet frames until the host's policy trims the store. */
  settle(): this {
    this.dragReallocations = this.canvas.reallocations;
    this.dragShrinks = this.canvas.shrinks;
    while (this.sizer.settling) {
      this.settleFrames += 1;
      if (this.sizer.frame()) {
        this.trims += 1;
        this.post();
      }
      this.frame();
    }
    return this;
  }

  /** What the host sends: the exact CSS size, plus the padded store while there is one. */
  private post(): void {
    const { sizer } = this;
    const pad = sizer.padded && { backingWidth: sizer.width, backingHeight: sizer.height };
    const { height } = START;
    this.runtime.handle({ t: "resize", id: 1, width: this.width, height, dpr: 1, ...pad });
  }

  private frame(): void {
    const cb = this.pending;
    this.pending = null;
    cb?.();
  }
}

export { SETTLE_FRAMES };

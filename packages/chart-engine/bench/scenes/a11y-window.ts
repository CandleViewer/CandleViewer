// `a11y-window` scene (E11-S13 PR-1, BQ-S13-01; rule 31): the a11y window over a 200k-bar
// BarStore. `A11yWindowBench` drives the real render runtime (`createRenderRuntime`, the BarStore as
// its test-only `timeMap`, a no-op 2D context) through pan frames, each a `setViewport` that moves
// the visible range, so every frame runs `publishA11y` and posts one `a11y`. `A11yComputeBench`
// runs the per-frame core alone on a ChartViewport: `computeA11yWindow`, the two edge-trigger
// comparisons and the copy. The .perf.test.ts times both and
// asserts, through `probeAllocations` and V8's GC profiler, that neither allocates.
import { computeA11yWindow, copyA11yWindow } from "../../src/a11y/window.js";
import { EMPTY_A11Y_WINDOW, sameCursorWindow, sameView } from "../../src/a11y/window.js";
import type { MutableA11yWindow } from "../../src/a11y/window.js";
import type { Ctx2DLike } from "../../src/canvas2d/ctx2d.js";
import { selectProfile } from "../../src/gl/capability.js";
import { BarStore } from "../../src/model/BarStore.js";
import { ChartViewport } from "../../src/viewport/index.js";
import { BACKGROUND_TOKEN, type FromWorker, type ToWorker } from "../../src/worker/protocol.js";
import { createRenderRuntime, type RenderRuntime } from "../../src/worker/runtime.js";

export const A11Y_BARS = 200_000;
const STEP_US = 60_000_000;
const T0 = Date.UTC(2026, 9, 30) * 1000;
/** Bars in view and the pan per frame, in bars; a pan cycle wraps well inside the store. */
const VIEW_BARS = 200;
const PAN_BARS = 3;
const FRAMES = 600;

/** A 200k-bar one-minute BarStore (tick 1000 + i % 50). */
export function a11yStore(n = A11Y_BARS): BarStore {
  const store = new BarStore();
  const open = Int32Array.from({ length: n }, (_, i) => 1_000 + (i % 50));
  const time = Float64Array.from({ length: n }, (_, i) => T0 + i * STEP_US);
  const volume = new Float32Array(n).fill(1);
  store.replace({
    time,
    open,
    high: open,
    low: open,
    close: open,
    volume,
    priceOrigin: 0,
    tickSize: 1,
  });
  return store;
}

const noop = (): void => undefined;
/** A 2D context that does nothing: the frame cost is the engine's CPU side alone. */
const SILENT: Ctx2DLike = {
  fillStyle: "",
  strokeStyle: "",
  lineWidth: 1,
  clearRect: noop,
  fillRect: noop,
  beginPath: noop,
  rect: noop,
  moveTo: noop,
  lineTo: noop,
  fill: noop,
  stroke: noop,
};
const REPORT = selectProfile(null);

export class A11yWindowBench {
  readonly store: BarStore;
  readonly runtime: RenderRuntime;
  /** `a11y` posts and recoverable errors seen; the last posted visible range. */
  a11yPosts = 0;
  errors = 0;
  lastViewFirst = -1;
  lastError = "";
  private pending: (() => void) | null = null;
  private clock = 1_000;
  private frameNo = 0;
  /** Every pan command, built once: a step only hands one to the runtime. */
  private readonly pans: ToWorker[] = [];

  constructor(n = A11Y_BARS) {
    this.store = a11yStore(n);
    this.runtime = createRenderRuntime({
      runMode: "inline",
      post: (m: FromWorker) => this.take(m),
      requestFrame: (cb) => {
        this.pending = cb;
      },
      now: () => this.clock,
      setTimer: () => undefined,
      probe: () => REPORT,
      timeMap: this.store,
    });
    this.runtime.handle({
      t: "init",
      id: 1,
      canvas: {
        width: 1280,
        height: 720,
        getContext: (id: string) => (id === "2d" ? SILENT : null),
      },
      dpr: 1,
      theme: { [BACKGROUND_TOKEN]: "#000000" },
      config: { bench: false, syncGroup: null },
    });
    const span = n - VIEW_BARS - 1;
    for (let i = 0; i < FRAMES; i += 1) {
      const left = n - VIEW_BARS - 1 - ((i * PAN_BARS) % span);
      const timeStart = T0 + left * STEP_US;
      const timeEnd = timeStart + VIEW_BARS * STEP_US;
      this.pans.push({ t: "command", id: 1, cmd: { k: "setViewport", timeStart, timeEnd } });
    }
    this.frame();
  }

  /** One pan frame: the visible range moves PAN_BARS bars and the runtime renders it. */
  step(): void {
    this.runtime.handle(this.pans[this.frameNo % FRAMES] as ToWorker);
    this.frameNo += 1;
    this.frame();
  }

  private frame(): void {
    const cb = this.pending;
    this.pending = null;
    this.clock += 16;
    if (cb !== null) cb();
  }

  private take(m: FromWorker): void {
    if (m.t === "a11y") {
      this.a11yPosts += 1;
      this.lastViewFirst = m.viewFirstBar ?? -1;
    } else if (m.t === "error") {
      this.errors += 1;
      this.lastError = m.code;
    }
  }
}

/**
 * The per-frame core alone, as `publishA11y` calls it: a ChartViewport over the same store, the
 * spread windows the runtime keeps, the follow-latest cursor (NaN until PR-3's data cursor);
 * each step scrolls, computes, compares and copies.
 */
export class A11yComputeBench {
  readonly store: BarStore;
  readonly viewport: ChartViewport;
  readonly next: MutableA11yWindow = { ...EMPTY_A11Y_WINDOW };
  readonly posted: MutableA11yWindow = { ...EMPTY_A11Y_WINDOW };
  private readonly lod = { candles: 0, footprint: 0 };
  changes = 0;

  constructor(n = A11Y_BARS) {
    this.store = a11yStore(n);
    this.viewport = new ChartViewport(this.store);
    this.viewport.setSize(1216, 720, 1);
  }

  /** Frame i: the view sits PAN_BARS * i bars into the store (wrapping). */
  step(i: number): number {
    const n = this.store.length;
    this.viewport.scrollTo((i * PAN_BARS) % (n - VIEW_BARS));
    computeA11yWindow(this.next, this.viewport.map, this.viewport, Number.NaN, this.lod);
    if (!sameCursorWindow(this.next, this.posted) || !sameView(this.next, this.posted)) {
      copyA11yWindow(this.posted, this.next);
      this.changes += 1;
    }
    return this.posted.viewFirstBar;
  }
}

/** The allocating built-ins a frame path could reach for: array and iterator helpers, `bind`. */
const ARRAY_METHODS = [
  "map",
  "filter",
  "reduce",
  "reduceRight",
  "slice",
  "concat",
  "flat",
  "flatMap",
  "forEach",
  "entries",
  "keys",
  "values",
  "toSorted",
  "toReversed",
  "toSpliced",
  "with",
] as const;
const ARRAY_STATICS = ["from", "of"] as const;
const OBJECT_STATICS = ["assign", "keys", "values", "entries", "fromEntries"] as const;

type Patch = readonly [target: object, name: string];

/**
 * Test-only allocation probe (rule 31 "no per-frame allocations"; #448's pattern): runs `run`
 * with every allocating built-in above wrapped in a call counter and returns how many calls `run`
 * made, restoring each built-in afterwards, even on a throw. A frame that copies with
 * `Object.assign`, slices or maps makes it non-zero. Literals and closures never call a built-in:
 * the scavenge count in the perf test (`v8.GCProfiler`) is the probe for those.
 */
export function probeAllocations(run: () => void): number {
  let calls = 0;
  const patches: Patch[] = [
    ...ARRAY_METHODS.map((m): Patch => [Array.prototype, m]),
    ...ARRAY_STATICS.map((m): Patch => [Array, m]),
    ...OBJECT_STATICS.map((m): Patch => [Object, m]),
    [Function.prototype, "bind"],
  ];
  const saved = patches.map(([target, name]) => Object.getOwnPropertyDescriptor(target, name));
  patches.forEach(([target, name], i) => {
    const original = saved[i]?.value as ((...a: unknown[]) => unknown) | undefined;
    if (typeof original !== "function") return;
    Object.defineProperty(target, name, {
      ...saved[i],
      value: function counted(this: unknown, ...args: unknown[]): unknown {
        calls += 1;
        return original.apply(this, args);
      },
    });
  });
  try {
    run();
  } finally {
    for (let i = 0; i < patches.length; i += 1) {
      const d = saved[i];
      const p = patches[i];
      if (d !== undefined && p !== undefined) Object.defineProperty(p[0], p[1], d);
    }
  }
  return calls;
}

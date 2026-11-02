// `dom-mirror` scene (E11-S13 PR-2, BQ-S13-14; 26 §12, 06 §4.3 DOM-mirror slice): the mirror's
// frame write at the 60-row default under a steady 30 bars/s feed at 60 fps (a new bar every second
// frame, the last bar patched every frame). Nodes are structural (no DOM in Node): this times the
// mirror's own work (pool, diff, format); the browser's layout cost is E06-T02's reference run.
// A 10-bars-per-frame fling (F14: 1.4 ms) and the opt-in 200-row cap are not this budget's: their
// shortfall goes to the 06 §4.4 ladder, never to a desynced mirror.
import { mulberry32 } from "../fixtures/rng.mjs";
import { DomMirror, type MirrorNode } from "../../src/a11y/DomMirror.js";
import { buildA11yRows, type A11yBarSource } from "../../src/a11y/rows.js";
import { computeA11yWindow, EMPTY_A11Y_WINDOW, type A11yBars } from "../../src/a11y/window.js";

const BAR_US = 60e6;

export type MirrorBars = A11yBarSource &
  A11yBars & {
    length: number;
    readonly time: Float64Array;
    readonly close: Int32Array;
  };

/** `n` seeded one-minute bars (room for `extra` appends), prices in 0.1 ticks from 60 000. */
export function makeBars(n: number, extra = 0, seed = 7): MirrorBars {
  const cap = n + extra;
  const rng = mulberry32(seed);
  const cols = {
    time: new Float64Array(cap),
    open: new Int32Array(cap),
    high: new Int32Array(cap),
    low: new Int32Array(cap),
    close: new Int32Array(cap),
    volume: new Float32Array(cap),
    delta: new Float32Array(cap),
  };
  let px = 1_000;
  for (let i = 0; i < cap; i += 1) {
    const o = px;
    px = Math.max(10, px + Math.round((rng() - 0.5) * 20));
    cols.time[i] = i * BAR_US;
    cols.open[i] = o;
    cols.close[i] = px;
    cols.high[i] = Math.max(o, px) + Math.round(rng() * 5);
    cols.low[i] = Math.min(o, px) - Math.round(rng() * 5);
    cols.volume[i] = Math.round(rng() * 1e4) / 100;
    cols.delta[i] = Math.round((rng() - 0.5) * 1e4) / 100;
  }
  const bars: MirrorBars = {
    ...cols,
    length: n,
    priceOrigin: 60_000,
    tickSize: 0.1,
    indexToTime: (i) => (i >= 0 && i < bars.length ? i * BAR_US : Number.NaN),
    timeToIndex: (t) => Math.min(bars.length - 1, Math.floor(t / BAR_US)),
  };
  return bars;
}

/** A structural element: the members the mirror writes, no layout. */
class BenchNode implements MirrorNode {
  textContent: string | null = "";
  readonly attrs = new Map<string, string>();
  readonly kids: BenchNode[] = [];
  parent: BenchNode | null = null;
  setAttribute(name: string, value: string): void {
    this.attrs.set(name, value);
  }
  removeAttribute(name: string): void {
    this.attrs.delete(name);
  }
  appendChild(child: BenchNode): void {
    child.parent = this;
    this.kids.push(child);
  }
  insertBefore(child: BenchNode, ref: BenchNode | null): void {
    child.parent = this;
    const i = ref === null ? -1 : this.kids.indexOf(ref);
    this.kids.splice(i < 0 ? this.kids.length : i, 0, child);
  }
  remove(): void {
    this.parent?.kids.splice(this.parent.kids.indexOf(this), 1);
    this.parent = null;
  }
}

export class DomMirrorBench {
  readonly times: Float64Array;
  readonly mirror: DomMirror;
  private readonly bars: MirrorBars;
  private readonly w = { ...EMPTY_A11Y_WINDOW };
  private flush: (() => void) | null = null;

  constructor(
    private readonly frames: number,
    private readonly now: () => number,
    private readonly rows = 60,
  ) {
    this.times = new Float64Array(frames);
    this.bars = makeBars(10_000, frames);
    this.mirror = new DomMirror({
      root: new BenchNode(),
      createElement: () => new BenchNode(),
      schedule: (cb) => void (this.flush = cb),
      now,
      setTimer: () => () => undefined,
      setCanvasLabel: () => undefined,
      timeZone: "UTC",
    });
  }

  /** One run: `frames` frames, each one message and one timed flush. */
  run(): void {
    const b = this.bars;
    let prev = -1;
    for (let f = 0; f < this.frames; f += 1) {
      if (f % 2 === 0) b.length = Math.min(b.time.length, b.length + 1);
      const last = b.length - 1;
      b.close[last] = (b.close[last] ?? 0) + (f % 3) - 1;
      const view = { leftIndex: b.length - 150, barSpacing: 8, plotWidth: 1200, dpr: 1 };
      computeA11yWindow(this.w, b, view, Number.NaN, { candles: 0, footprint: 0 }, this.rows);
      const rows = buildA11yRows(this.w, b, prev);
      prev = this.w.firstBar;
      this.mirror.update(this.w, rows, b.length);
      const t0 = this.now();
      this.flush?.();
      this.times[f] = this.now() - t0;
    }
  }
}

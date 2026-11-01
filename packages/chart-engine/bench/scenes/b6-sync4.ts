// `b6-sync4` scene (E11-S09 PR 2, #446 BQ-12, BQ-13; 26 §13 B6 "4 synchronised charts"): four
// charts in one sync group on one render runtime, each on its own canvas and injected GL, with
// stand-in content (the grid, the crosshair, autoscale over 5 000 seeded 1 m bars) until B5's
// candles, footprint and heatmap exist. A seeded 600-frame session moves one leader at a time
// (it changes every 60 frames): the pointer sweeps it every frame, a wheel or a key pans or zooms
// it every few frames, and the other three follow in the same tick. CI asserts the structure and
// the counters only (test/bench/scenes/b6-sync4.test.ts); the 16.7 ms aggregate and the 70 % CPU
// gate are an owner-run hardware leg on the reference machine (#446 plan §5).
import { mulberry32 } from "../fixtures/rng.mjs";
import type { GL2Like } from "../../src/gl/gl-types.js";
import { columnSource } from "../../src/viewport/index.js";
import {
  BACKGROUND_TOKEN,
  INPUT,
  KEY,
  type CapabilityReport,
  type FromWorker,
} from "../../src/worker/protocol.js";
import { createRenderRuntime, type RenderRuntime } from "../../src/worker/runtime.js";
import { sweepBars } from "./crosshair-sweep.js";

export const B6_CHARTS = 4;
export const B6_FRAMES = 600;
/** Frames each leader keeps the pointer before the next chart takes over. */
export const B6_LEAD_FRAMES = 60;
/** Half density (26 §13 B6): a 2×2 grid of 960 × 540 charts at DPR 1. */
export const B6_SIZE = { width: 960, height: 540 } as const;
const THEME = { [BACKGROUND_TOKEN]: "#0b0e11", "color.crosshair": "#848e9c" };
const BARS = 5_000;

/** One tick's per-chart outcome, the scene's counters over the run. */
export interface B6Counters {
  ticks: number;
  /** `frame` messages per chart (bench mode posts one per frame drawn). */
  readonly frames: number[];
  /** The most frames any one chart drew in one tick: 1 (no echo frame). */
  maxFramesPerChartPerTick: number;
  /** Ticks after which a member's posted range differed from the leader's. */
  rangeMismatches: number;
  /** Ticks in which the leader moved and a member did not follow in that same tick. */
  lateFollows: number;
  /** The largest `drawCalls` any chart reported. */
  maxDrawCalls: number;
  /** `uploadedBytes` summed over every frame of every chart after the first frames. */
  uploadedBytes: number;
}

export class B6Sync4Bench {
  readonly runtime: RenderRuntime;
  readonly posted: FromWorker[] = [];
  readonly counters: B6Counters = {
    ticks: 0,
    frames: new Array<number>(B6_CHARTS).fill(0),
    maxFramesPerChartPerTick: 0,
    rangeMismatches: 0,
    lateFollows: 0,
    maxDrawCalls: 0,
    uploadedBytes: 0,
  };
  private pending: (() => void)[] = [];
  private now = 1000;
  private readonly rng: () => number;
  private readonly ranges: [number, number][];
  private readonly tickFrames = new Int32Array(B6_CHARTS);

  constructor(glFor: (chart: number) => GL2Like, probe: () => CapabilityReport, seed = 0xb6) {
    this.rng = mulberry32(seed);
    const bars = sweepBars(BARS);
    const t0 = bars.time[0] as number;
    const min = 60e6;
    this.runtime = createRenderRuntime({
      runMode: "inline",
      post: (m) => void this.posted.push(m),
      requestFrame: (cb) => void this.pending.push(cb),
      now: () => this.now,
      setTimer: () => undefined,
      probe,
      timeMap: {
        length: BARS,
        barDurationUs: min,
        indexToTime: (i) => (i >= 0 && i < BARS ? t0 + i * min : Number.NaN),
        timeToIndex: (t) => (t < t0 ? -1 : Math.min(BARS - 1, Math.floor((t - t0) / min))),
      },
      priceSources: [columnSource(() => bars)],
      readoutSources: [bars],
    });
    const end = t0 + BARS * min;
    for (let c = 1; c <= B6_CHARTS; c += 1) {
      const gl = glFor(c);
      const canvas = { ...B6_SIZE, getContext: (id: string) => (id === "webgl2" ? gl : null) };
      const config = { bench: true, syncGroup: "b6" };
      this.runtime.handle({ t: "init", id: c, canvas, dpr: 1, theme: THEME, config });
      this.runtime.handle({ t: "command", id: c, cmd: { k: "setCrosshair", magnetMode: "weak" } });
    }
    const cmd = { k: "setViewport", timeStart: end - 200 * min, timeEnd: end } as const;
    this.runtime.handle({ t: "command", id: 1, cmd });
    this.ranges = Array.from({ length: B6_CHARTS }, () => [Number.NaN, Number.NaN]);
    this.tick(); // opens the backends; the first frame is not a session frame
    this.posted.length = 0;
    this.counters.frames.fill(0);
    this.counters.ticks = 0;
    this.counters.maxDrawCalls = 0;
    this.counters.uploadedBytes = 0;
  }

  /** The leader of frame `f` (1-based chart id). */
  static leaderOf(f: number): number {
    return 1 + (Math.floor(f / B6_LEAD_FRAMES) % B6_CHARTS);
  }

  /** One session frame: the leader's input, then one runtime tick. */
  step(f: number): void {
    const lead = B6Sync4Bench.leaderOf(f);
    const r = this.rng;
    const x = 40 + ((f * 13) % (B6_SIZE.width - 120));
    const y = 60 + Math.floor(r() * (B6_SIZE.height - 140));
    this.input(lead, "pointer", INPUT.move, x, y, 0);
    if (f % 5 === 0) {
      if (r() < 0.5) this.input(lead, "wheel", INPUT.wheel, x, y, r() < 0.5 ? -40 : 40);
      else this.input(lead, "key", INPUT.key, r() < 0.5 ? KEY.left : KEY.right, 0, 0);
    }
    if (f % B6_LEAD_FRAMES === B6_LEAD_FRAMES - 1) {
      this.input(lead, "pointer", INPUT.leave, x, y, 0); // the pointer moves to the next chart
    }
    this.tick();
  }

  run(): this {
    for (let f = 0; f < B6_FRAMES; f += 1) this.step(f);
    return this;
  }

  private input(chart: number, kind: "pointer" | "wheel" | "key", ...row: number[]): void {
    const events = new Float32Array(6);
    events.set(row);
    this.now += 0.25; // each input later than the last: the newest leader always wins
    this.runtime.handle({ t: "input", id: chart, kind, events });
  }

  private tick(): void {
    this.now += 16;
    const mark = this.posted.length;
    for (const cb of this.pending.splice(0)) cb();
    this.observe(mark);
  }

  private observe(mark: number): void {
    const c = this.counters;
    c.ticks += 1;
    this.tickFrames.fill(0);
    let leaderMoved = false;
    const moved = new Uint8Array(B6_CHARTS);
    for (let i = mark; i < this.posted.length; i += 1) {
      const m = this.posted[i] as FromWorker;
      if (m.t === "frame") {
        const k = m.id - 1;
        this.tickFrames[k] = (this.tickFrames[k] as number) + 1;
        c.frames[k] = (c.frames[k] as number) + 1;
        c.maxDrawCalls = Math.max(c.maxDrawCalls, m.drawCalls);
        c.uploadedBytes += m.uploadedBytes;
      } else if (m.t === "viewport" && m.pane === 0) {
        const r = this.ranges[m.id - 1] as [number, number];
        if (r[0] !== m.timeStart || r[1] !== m.timeEnd) moved[m.id - 1] = 1;
        r[0] = m.timeStart;
        r[1] = m.timeEnd;
      }
    }
    for (let k = 0; k < B6_CHARTS; k += 1) {
      c.maxFramesPerChartPerTick = Math.max(c.maxFramesPerChartPerTick, this.tickFrames[k] ?? 0);
      if (moved[k] === 1) leaderMoved = true;
    }
    const [r0] = this.ranges;
    if (r0 === undefined || Number.isNaN(r0[0])) return;
    let same = true;
    for (const r of this.ranges) if (r[0] !== r0[0] || r[1] !== r0[1]) same = false;
    if (!same) c.rangeMismatches += 1;
    if (leaderMoved && moved.some((v) => v === 0)) c.lateFollows += 1;
  }
}

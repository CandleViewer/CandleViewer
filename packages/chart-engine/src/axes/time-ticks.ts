// Time-axis tick candidates (E11-S06, README BQ-186, BQ-189, BQ-203; E11-D02 §5.2 to §5.3): the
// 23-step ladder, the smallest step whose spacing is ≥ the density gap G (sub-minute steps only
// for bars under a minute), and every candidate ranked by the coarsest calendar unit it falls on
// in the chart's zone: years > quarters > months > weeks > 2-day > days (P0, the date replaces
// the time) > hours (P2) > the step marks (P3). Below a day a rank follows the step's divisibility
// chain, so between nested steps retention is monotone as the user zooms; the ladder's 3 h, 15 m
// and 15 s marks leave when the step goes to 2 h, 10 m or 10 s (C-62). Text is cached by time.
import { barUs, screenToTime, timeToScreen } from "../viewport/transform.js";
import type { ViewportState } from "../viewport/types.js";
import type { TickSet } from "./decimate.js";
import { MARGIN_GAPS } from "./price-ticks.js";
import {
  clockText,
  createZoned,
  DAY_MS,
  dateText,
  daysFrom,
  MONTHS,
  type Zoned,
  type ZoneClock,
} from "./format.js";

const S = 1000;
const MIN = 60 * S;
const HOUR = 60 * MIN;
const steps = (unit: number, n: readonly number[]): number[] => n.map((k) => k * unit);
/** E11-D02 §5.2's 23 steps in ms; month, quarter and year are nominal (their marks are dates). */
export const TIME_LADDER: readonly number[] = [
  ...steps(S, [1, 2, 5, 10, 15, 30]),
  ...steps(MIN, [1, 2, 5, 10, 15, 30]),
  ...steps(HOUR, [1, 2, 3, 6, 12]),
  ...steps(DAY_MS, [1, 2, 7, 30, 91, 365]),
];
/** Ladder indices of the calendar ranks (a time's rank is the coarsest unit it falls on). */
export const RANK = { hour: 12, day: 17, twoDays: 18, week: 19, month: 20, quarter: 21, year: 22 };

/** The smallest step whose spacing is ≥ `gap` px; a step is never under min(bar, 1 m). */
export function timeStep(barMs: number, pxPerMs: number, gap: number): number {
  const floor = Math.min(barMs, MIN);
  for (let i = 0; i < TIME_LADDER.length; i += 1) {
    const s = TIME_LADDER[i] as number;
    if (s >= floor && s * pxPerMs >= gap) return i;
  }
  return TIME_LADDER.length - 1;
}

/**
 * Per step, the sub-day steps from it upward that each divide the next (1 h: 1 h, 2 h, 6 h, 12 h;
 * 3 h is not a multiple of 2 h). Ranking along this chain keeps zoom monotone: a candidate a finer
 * nested step adds always ranks below every candidate of the coarser step.
 */
const CHAINS: readonly (readonly number[])[] = TIME_LADDER.map((_, from) => {
  const chain = [from];
  for (let i = from + 1; i < RANK.day; i += 1) {
    if (
      (TIME_LADDER[i] as number) % (TIME_LADDER[chain[chain.length - 1] as number] as number) ===
      0
    ) {
      chain.push(i);
    }
  }
  return chain;
});

/** The rank of a local instant at ladder step `step`: -1 off the step. */
export function rankOf(z: Zoned, step = 0): number {
  if (z.ms !== 0) {
    const chain = CHAINS[step] ?? [];
    let rank = -1;
    for (const i of chain) if (i < RANK.day && z.ms % (TIME_LADDER[i] as number) === 0) rank = i;
    return rank;
  }
  if (z.day === 1) {
    if (z.month === 1) return RANK.year;
    return (z.month - 1) % 3 === 0 ? RANK.quarter : RANK.month;
  }
  if (z.weekday === 0) return RANK.week;
  return z.days % 2 === 0 ? RANK.twoDays : RANK.day;
}

/** The time axis's candidates over the plot [0, width]. */
export class TimeTicks {
  /** The ladder index picked this pass. */
  step = 0;
  private readonly z = createZoned();
  private readonly cache = new Map<number, string>();
  private seconds = false;
  // The pass's inputs, held for `add` (a method, so a pass allocates no closure).
  private vp: ViewportState | null = null;
  private width = 0;
  private gap = 0;
  private set: TickSet | null = null;
  private measure: (text: string) => number = () => 0;

  constructor(readonly clock: ZoneClock) {}

  update(
    vp: ViewportState,
    width: number,
    gap: number,
    measure: (text: string) => number,
    set: TickSet,
  ): void {
    set.clear();
    if (!(width > 0) || !(vp.barSpacing > 0)) return;
    this.vp = vp;
    this.width = width;
    this.set = set;
    this.measure = measure;
    this.gap = gap;
    const barMs = barUs(vp.map) / 1000;
    this.step = timeStep(barMs, vp.barSpacing / barMs, gap);
    const step = TIME_LADDER[this.step] as number;
    if (step < MIN !== this.seconds) this.cache.clear();
    this.seconds = step < MIN;
    // Candidates run past both ends as hidden blockers (BQ-189): a pan blinks nothing.
    const t0 = screenToTime(vp, -this.margin(gap)) / 1000;
    const t1 = screenToTime(vp, width + this.margin(gap)) / 1000;
    const clock = this.clock;
    if (step < DAY_MS) {
      const local0 = Math.ceil((t0 + clock.offset(t0)) / step) * step;
      for (let local = local0; ; local += step) {
        const t = clock.toUtc(local);
        if (t > t1 || !this.add(t)) return;
      }
    }
    const z = clock.fields(t0, this.z);
    if (this.step <= RANK.week) {
      for (let d = z.days; ; d += 1) {
        const t = clock.toUtc(d * DAY_MS);
        if (t > t1 || (t >= t0 && !this.add(t))) return;
      }
    }
    for (let y = z.year, m = z.month; ; m = m === 12 ? 1 : m + 1, y += m === 1 ? 1 : 0) {
      const t = clock.toUtc(daysFrom(y, m, 1) * DAY_MS);
      if (t > t1 || (t >= t0 && !this.add(t))) return;
    }
  }

  private margin(gap: number): number {
    return MARGIN_GAPS * gap;
  }

  /** One candidate at UTC ms `t` when its rank reaches the step; false once the set is full. */
  private add(t: number): boolean {
    const vp = this.vp as ViewportState;
    const z = this.clock.fields(t, this.z);
    const rank = rankOf(z, this.step);
    if (rank < this.step) return true;
    const x = timeToScreen(vp, t * 1000);
    const m = this.margin(this.gap);
    if (!(x >= -m && x <= this.width + m)) return true;
    let text = this.cache.get(t);
    if (text === undefined) {
      if (rank >= RANK.year) text = `${z.year}`;
      else if (rank >= RANK.month) text = MONTHS[z.month - 1] ?? "";
      else if (rank >= RANK.day) text = dateText(z);
      else text = clockText(z.ms, this.seconds);
      if (this.cache.size > 512) this.cache.clear();
      this.cache.set(t, text);
    }
    const step = TIME_LADDER[this.step] as number;
    const major = step < HOUR ? RANK.hour : step < DAY_MS ? RANK.day : RANK.month;
    const tier = step < DAY_MS && rank >= RANK.day ? 2 : rank >= major ? 1 : 0;
    return this.set?.push(x, this.measure(text), rank, t, tier, text) ?? false;
  }
}

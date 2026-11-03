// E24-S01 (#776) slice 1: one open-interest series from two sources, reconciled. REST history
// (base coin, at its native interval) is the baseline; live ticker items extend it, aligned to the
// chart's bar, last write wins per bar. One ownership rule, applied on arrival and when history
// lands: live owns a bar only when its aligned start is after the last backfilled point (the
// cadences differ; the ticket's Technical notes), and the last history span ends where live begins.
// The readout (`latest`) still shows the newest live tick inside the last history bar. Missing
// spans are gaps, never lines (US-DERIV-001 sc. 3): the store's own `coverage.gaps`, a failed
// backfill, and a live seam (a reset, or silence past the store's 10 s `ws_ticker` rule). No value
// is ever computed here.
import { alignToBar } from "./intervals";
import type { Coverage, HistoryPoint } from "./history";

/** `22`: a `ws_ticker` span with no point for over 10 s is a gap; the live side reads it alike. */
export const LIVE_GAP_MS = 10_000;
/** Live seams kept: those ending before the window go first, then the oldest past this bound. */
export const MAX_LIVE_GAPS = 256;
/** Live bars kept, the oldest first out (a 1 s bar holds ~33 min); the table shows 200 and history owns the rest. */
export const MAX_LIVE_ROWS = 2_000;

export interface LiveTick {
  /** The item's `ts_ms` (exchange time, UTC). */
  readonly tsMs: number;
  readonly base: string;
  /** `open_interest_value`, from the live ticker only (BQ 1). */
  readonly valueUsdt: string | null;
}

export interface OiRow {
  /** The span's start: a bar boundary for live rows, the stored point's `t` for history. */
  readonly tMs: number;
  readonly spanMs: number;
  readonly base: string;
  readonly valueUsdt: string | null;
  /** `rest` reads "REST history", `ws_ticker` "live" (D02 §4 Source; the provenance rule). */
  readonly source: "rest" | "ws_ticker";
  /** The newest live bar, still open. */
  readonly forming: boolean;
  /** The live item's own time; the history point's `t`. */
  readonly asOfMs: number;
  /** A2 (PROPOSED): the last history span, cut short where the first live bar begins. */
  readonly clipped?: true;
}

export type GapKind = "recorded" | "failed" | "live";

export interface OiGap {
  readonly fromMs: number;
  readonly toMs: number;
  /** `recorded`: the store reports it; `failed`: the backfill did not load; `live`: a seam. */
  readonly kind: GapKind;
}

export interface SeriesCounters {
  accepted: number;
  /** Live items at or before the last backfilled point. */
  superseded: number;
  /** Live items older than the newest live item (out of order). */
  late: number;
}

export class OiSeries {
  readonly counters: SeriesCounters = { accepted: 0, superseded: 0, late: 0 };
  /** Bumps on every change a reader would see. */
  version = 0;
  private history: readonly HistoryPoint[] = [];
  private historySpanMs: number;
  private coverage: Coverage | null = null;
  private failed = false;
  private readonly live = new Map<number, OiRow>();
  private readonly liveGaps: OiGap[] = [];
  private lastLiveTsMs: number | null = null;
  /** The newest tick after the last history point, owned bar or not: the readout's value (A1). */
  private newest: LiveTick | null = null;
  private seamPending = false;
  private rowsCache: readonly OiRow[] | null = null;

  constructor(
    readonly barMs: number,
    private readonly window: { readonly fromMs: number; readonly toMs: number },
  ) {
    this.historySpanMs = barMs;
  }

  /** The backfill landed: the live bars it now covers give way to it. */
  setHistory(points: readonly HistoryPoint[], coverage: Coverage, spanMs: number): void {
    this.history = points;
    this.coverage = coverage;
    this.historySpanMs = spanMs;
    this.failed = false;
    for (const t of [...this.live.keys()]) if (!this.liveOwns(t)) this.live.delete(t);
    // the live seams the backfill now covers go with their bars
    const kept = this.liveGaps.filter((g) => this.liveOwns(alignToBar(g.toMs, this.barMs)));
    this.liveGaps.splice(0, this.liveGaps.length, ...kept);
    this.changed();
  }

  setHistoryFailed(): void {
    if (this.failed) return;
    this.failed = true;
    this.changed();
  }

  /** A reset (`23` §7.1): the next live item starts a new segment, the span between them a gap. */
  seam(): void {
    if (this.lastLiveTsMs !== null) this.seamPending = true;
  }

  /** `true` when the item changed what a reader sees. */
  addLive(tick: LiveTick): boolean {
    const tMs = alignToBar(tick.tsMs, this.barMs);
    if (!this.liveOwns(tMs)) {
      this.counters.superseded += 1;
      return this.offerNewest(tick); // the bar stays history's; the readout still moves
    }
    const prev = this.lastLiveTsMs;
    if (prev !== null && tick.tsMs < prev) {
      this.counters.late += 1;
      return false;
    }
    const gapped = prev !== null && (this.seamPending || tick.tsMs - prev > LIVE_GAP_MS);
    if (gapped) {
      this.liveGaps.push({ fromMs: prev, toMs: tick.tsMs, kind: "live" });
      this.pruneLiveGaps();
      this.changed();
    }
    this.seamPending = false;
    this.lastLiveTsMs = tick.tsMs;
    this.counters.accepted += 1;
    this.newest = tick;
    // a repeat of the held value still moves the row's "as of" (a later `tsMs`), so it never lags
    this.live.set(tMs, {
      tMs,
      spanMs: this.barMs,
      base: tick.base,
      valueUsdt: tick.valueUsdt,
      source: "ws_ticker",
      forming: true,
      asOfMs: tick.tsMs,
    });
    // ticks arrive in order, so the first key is the oldest bar
    if (this.live.size > MAX_LIVE_ROWS) this.live.delete(this.live.keys().next().value ?? tMs);
    this.changed();
    return true;
  }

  /** History then live, ascending; only the newest live bar is `forming`. */
  rows(): readonly OiRow[] {
    if (this.rowsCache !== null) return this.rowsCache;
    const live = [...this.live.values()].sort((a, b) => a.tMs - b.tMs);
    const firstLive = live[0]?.tMs;
    const lastIndex = this.history.length - 1;
    const out: OiRow[] = this.history.map((p, i) => {
      // the last history span ends where live begins, so a finer live bar never overlaps it
      const clip =
        i === lastIndex && firstLive !== undefined && firstLive - p.tMs < this.historySpanMs;
      return {
        tMs: p.tMs,
        spanMs: clip ? firstLive - p.tMs : this.historySpanMs,
        base: p.base,
        valueUsdt: null,
        source: p.source,
        forming: false,
        asOfMs: p.tMs,
        ...(clip ? { clipped: true as const } : {}),
      };
    });
    live.forEach((row, i) => out.push(i === live.length - 1 ? row : { ...row, forming: false }));
    this.rowsCache = out;
    return out;
  }

  /** The readout's row: the last row, or the newest live tick when it is newer (A1). */
  latest(): OiRow | null {
    const rows = this.rows();
    const last = rows[rows.length - 1] ?? null;
    const tick = this.newest;
    if (tick === null || (last !== null && tick.tsMs <= last.asOfMs)) return last;
    return {
      tMs: alignToBar(tick.tsMs, this.barMs),
      spanMs: this.barMs,
      base: tick.base,
      valueUsdt: tick.valueUsdt,
      source: "ws_ticker",
      forming: true,
      asOfMs: tick.tsMs,
    };
  }

  gaps(): readonly OiGap[] {
    const out: OiGap[] = (this.coverage?.gaps ?? []).map((g) => ({ ...g, kind: "recorded" }));
    if (this.failed) {
      const firstLive = [...this.live.keys()].reduce<number | null>(
        (min, t) => (min === null || t < min ? t : min),
        null,
      );
      // rows an earlier load left are still shown: the failed span starts after them (D02 `oi-backfill-failed`)
      const last = this.lastHistoryMs();
      const fromMs = last === null ? this.window.fromMs : last + this.historySpanMs;
      const toMs = firstLive ?? this.window.toMs;
      if (fromMs < toMs) out.push({ fromMs, toMs, kind: "failed" });
    }
    out.push(...this.liveGaps);
    return out.sort((a, b) => a.fromMs - b.fromMs);
  }

  /** `coverage.from`: the first stored point, the empty state's "History starts …" (BQ 7). */
  coverageFromMs(): number | null {
    return this.coverage?.fromMs ?? null;
  }

  nativeInterval(): Coverage["nativeInterval"] | null {
    return this.coverage?.nativeInterval ?? null;
  }

  hasHistory(): boolean {
    return this.history.length > 0;
  }

  hasLive(): boolean {
    return this.live.size > 0;
  }

  /** A tick inside history's last bar: it moves the readout only when it is the newest seen. */
  private offerNewest(tick: LiveTick): boolean {
    const last = this.lastHistoryMs();
    const held = this.newest;
    if (last !== null && tick.tsMs <= last) return false;
    if (held !== null && tick.tsMs <= held.tsMs) return false;
    const same = held !== null && held.base === tick.base && held.valueUsdt === tick.valueUsdt;
    this.newest = tick;
    if (same) return false;
    this.changed();
    return true;
  }

  /** The one ownership rule: live owns a bar whose aligned start is after history's last point. */
  private liveOwns(barStartMs: number): boolean {
    const last = this.lastHistoryMs();
    return last === null || barStartMs > last;
  }

  private pruneLiveGaps(): void {
    const kept = this.liveGaps.filter((g) => g.toMs >= this.window.fromMs);
    this.liveGaps.splice(0, this.liveGaps.length, ...kept.slice(-MAX_LIVE_GAPS));
  }

  private lastHistoryMs(): number | null {
    return this.history[this.history.length - 1]?.tMs ?? null;
  }

  private changed(): void {
    this.version += 1;
    this.rowsCache = null;
  }
}

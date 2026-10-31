/**
 * The flash coalescer (E05-D03 §4 HS-1, row 3; E08-D11 D14-D19; E47-S04 BQ-2 / BQ-3): a pure decision
 * module that turns a stream of value ticks into the few flash-emphasis STARTS a surface may render.
 * No DOM, no timers, no globals: the caller injects the clock (ms) on every call and drives it from
 * its frame loop (rAF), so a fake clock tests it exactly.
 *
 *   const flash = createFlashCoalescer();
 *   flash.onTick("BTCUSDT:last", +0.5, now);       // on every value change; always update the value
 *   for (const s of flash.frame(now)) start(s);    // once per frame: s.cellId, s.direction
 *
 * Rules (HS-1; the ticket's 400 ms is superseded). MR-1 allows at most 3 starts in any half-open 1 000 ms
 * window [t, t + 1 000); an interval of 333 ms admits 4 (0, 333, 666, 999), so 334 ms is the floor:
 * - 500 ms per cell between starts (HS-1), so at most 2 starts in any half-open 1 000 ms window.
 * - Latest wins, nothing queues: one net per cell, the sum of the deltas since the last start. An idle
 *   cell flashes on its next frame (leading edge); ticks inside the window accumulate, and when the
 *   window ends one start carries their net direction. A flat net is no emphasis (flat = cancels
 *   to within float residue, see FLAT_EPSILON).
 * - At most `maxPerFrame` (20) starts per frame, higher `priority` first (the focused symbol, open
 *   positions), then the longest waiting
 *   (oldest last start first; a never-started cell first). A cell over the cap keeps its value and loses
 *   its emphasis, and its last start is unchanged, so it ranks first among its equals next frame.
 * - A cell ticking at >= 1 Hz (gaps <= 1 000 ms) for 10 s is `sustained`: no emphasis until a gap
 *   over 1 000 ms. The caller shows the sustained state, not a faster blink.
 * Values, arrows and signs always update; only the emphasis is dropped.
 */

/** A tick's direction word, or a signed price delta (summed, so the net is exact). */
export type FlashTick = "up" | "down" | "flat" | number;

export type FlashDirection = "up" | "down";

/** One emphasis to start now. */
export interface FlashStart {
  readonly cellId: string;
  readonly direction: FlashDirection;
}

export interface FlashCoalescerOptions {
  /** Minimum ms between two starts of one cell. Default 500 (HS-1). */
  readonly windowMs?: number;
  /** Most starts in one frame. Default 20 (HS-1). */
  readonly maxPerFrame?: number;
  /** Largest gap (ms) that still counts as >= 1 Hz. Default 1 000. */
  readonly busyGapMs?: number;
  /** How long (ms) of >= 1 Hz ticking makes a cell sustained. Default 10 000. */
  readonly sustainedAfterMs?: number;
}

export interface FlashCoalescer {
  /** Record a value change on a cell. `priority` (higher first) is kept as the max since the last start. */
  onTick(cellId: string, tick: FlashTick, nowMs: number, priority?: number): void;
  /** The emphasis starts to render at `nowMs`; call once per frame. */
  frame(nowMs: number): readonly FlashStart[];
  /** True while the cell is in the sustained state at `nowMs`. */
  isSustained(cellId: string, nowMs: number): boolean;
  /** Drop a cell's state (the cell unmounted). */
  forget(cellId: string): void;
}

interface Cell {
  /** Frame time of the last start; -Infinity before the first. */
  lastStart: number;
  /** Sum of the deltas since the last start (or since the cell went idle). */
  net: number;
  /** Sum of the absolute deltas since the last start: the scale the net is judged flat against. */
  mag: number;
  pending: boolean;
  priority: number;
  /** When the current unbroken >= 1 Hz run began. */
  runStart: number;
  lastTick: number;
}

/**
 * A net is flat when |net| <= FLAT_EPSILON * mag. Relative, not absolute: the API takes float price
 * deltas of any scale (BTC 0.5, a 1e-7 tick coin), so a fixed 1e-9 would swallow real moves on small
 * prices; +0.1 +0.2 -0.3 leaves 5.5e-17 against mag 0.6, far under 1e-9, and counts as flat.
 */
const FLAT_EPSILON = 1e-9;

const DEFAULTS = { windowMs: 500, maxPerFrame: 20, busyGapMs: 1000, sustainedAfterMs: 10_000 };

function deltaOf(tick: FlashTick): number {
  if (tick === "up") return 1;
  if (tick === "down") return -1;
  if (tick === "flat") return 0;
  return Number.isFinite(tick) ? tick : 0;
}

export function createFlashCoalescer(options: FlashCoalescerOptions = {}): FlashCoalescer {
  const { windowMs, maxPerFrame, busyGapMs, sustainedAfterMs } = { ...DEFAULTS, ...options };
  const cells = new Map<string, Cell>();
  // Cells with an un-rendered net; the frame walks only these, in tick order.
  const pending = new Set<string>();
  let lastPrune = Number.NEGATIVE_INFINITY;

  // Deliberate: frame time (nowMs) against the last TICK time, not the last start.
  const sustainedAt = (c: Cell, nowMs: number): boolean =>
    nowMs - c.lastTick <= busyGapMs && nowMs - c.runStart >= sustainedAfterMs;

  return {
    onTick(cellId, tick, nowMs, priority = 0) {
      let c = cells.get(cellId);
      if (c === undefined) {
        c = {
          lastStart: Number.NEGATIVE_INFINITY,
          net: 0,
          mag: 0,
          pending: false,
          priority,
          runStart: nowMs,
          lastTick: nowMs,
        };
        cells.set(cellId, c);
      } else if (nowMs - c.lastTick > busyGapMs) {
        c.runStart = nowMs; // calmed: the busy run starts over
      }
      c.lastTick = nowMs;
      c.priority = c.pending ? Math.max(c.priority, priority) : priority;
      const delta = deltaOf(tick);
      c.net += delta;
      c.mag += Math.abs(delta);
      c.pending = true;
      pending.add(cellId);
    },

    frame(nowMs) {
      const due: Array<{ id: string; cell: Cell }> = [];
      for (const id of pending) {
        const cell = cells.get(id);
        if (cell === undefined) continue;
        // Inside the window the net keeps accumulating; it is decided once the window ends.
        if (nowMs - cell.lastStart < windowMs) continue;
        due.push({ id, cell });
      }
      // Priority first, then the longest waiting (oldest lastStart; -Infinity = never started, first).
      // Explicit compares: -Infinity - -Infinity is NaN. O(d log d) over the due set only.
      due.sort((a, b) => {
        if (a.cell.priority !== b.cell.priority) return b.cell.priority - a.cell.priority;
        if (a.cell.lastStart < b.cell.lastStart) return -1;
        return a.cell.lastStart > b.cell.lastStart ? 1 : 0;
      });
      const starts: FlashStart[] = [];
      for (const { id, cell } of due) {
        pending.delete(id);
        const net = cell.net;
        const flat = Math.abs(net) <= FLAT_EPSILON * cell.mag;
        cell.net = 0;
        cell.mag = 0;
        cell.pending = false;
        if (flat || sustainedAt(cell, nowMs)) continue; // flat or sustained: the value only
        if (starts.length >= maxPerFrame) continue; // over the cap: value only, nothing queues
        cell.lastStart = nowMs;
        starts.push({ cellId: id, direction: net > 0 ? "up" : "down" });
      }
      // Quiet cells hold no state worth keeping: a gap over busyGapMs resets the run anyway.
      if (nowMs - lastPrune >= sustainedAfterMs) {
        lastPrune = nowMs;
        for (const [id, c] of cells) {
          if (!c.pending && nowMs - c.lastTick > busyGapMs && nowMs - c.lastStart >= windowMs) {
            cells.delete(id);
          }
        }
      }
      return starts;
    },

    isSustained(cellId, nowMs) {
      const c = cells.get(cellId);
      return c !== undefined && sustainedAt(c, nowMs);
    },

    forget(cellId) {
      cells.delete(cellId);
      pending.delete(cellId);
    },
  };
}

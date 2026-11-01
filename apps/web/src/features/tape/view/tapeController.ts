// E22-S01 (#714) PR-B: the tape panel's engine room, outside React. It runs once per animation
// frame after the feed's ingest (PR-A): the whale announcer reads the new prints, the reconnect
// seams become gap dividers, the pause model decides the list's top, the grid writer draws the
// window in one pass, and the coarse chrome (chips, readout, states) is published for React at
// most twice a second, or at once on a transition (D4-07, C-69). Nothing per message reaches
// React (rules/30, C-2.20); every buffer here is bounded (C-2.18).
import { locate as defaultLocate, type LocateRequest } from "../../../lib/state/chartLocate";
import type { TransportState } from "../../../lib/ws/state/types";
import type { TapeAnnouncer, Verbosity } from "../announce";
import {
  DISCONNECTED_PAUSE_REASON,
  TAPE_LIVE,
  dividerDisconnected,
  dividerGap,
  dividerNoHistory,
  dividerPaused,
  dividerPausedNotKept,
  missedLoaded,
  reconnectedGap,
  resumed,
  resumedNotKept,
  tapeStale,
} from "../copy";
import { formatSecond, formatTime, type TapeTier } from "../format";
import { DisplayList, newCursor, type Divider } from "../model/displayList";
import {
  TRADES_MAX_WINDOW_MS,
  parsePublicTrade,
  type ExtraPrint,
  type FetchTrades,
} from "../model/history";
import {
  LIVE,
  isPaused,
  step,
  type PauseCause,
  type PauseEvent,
  type PauseLayers,
  type ResumeCause,
} from "../model/pause";
import { SIDE_BUY } from "../model/ring";
import type { TapeClock, TapeFeedHandle } from "../model/tapeFeed";
import {
  COLUMN_COUNT,
  GridWriter,
  POOL_SIZE,
  ROW_HEIGHT_PX,
  serverTier,
  type TierOf,
} from "./gridWriter";

/** P1: the pointer at rest this long, then moving, is hover intent (memo F9). */
export const HOVER_REST_MS = 150;
/** P3: a soft pause parks after this long without `pointermove`. */
export const PARK_MS = 30_000;
/** E17-D01 T2: a stale feed reads strong from here. */
export const STALE_STRONG_MS = 30_000;
/** D4-07: counters publish at most twice a second; rung 1 of the ladder halves that (BQ-218). */
export const CHROME_INTERVAL_MS = 500;
export const CHROME_INTERVAL_RUNG1_MS = 1_000;
/**
 * BQ-215: rows drawn below the viewport while live. A live list moves on every 100 ms window and
 * every shown row is rewritten then, so the live window is the viewport plus this overscan, not the
 * whole pool; a pause (scroll, focus, hover, `P`) draws the full pool with D02 §2's overscan.
 */
export const LIVE_OVERSCAN_ROWS = 4;
/** BQ-215: 55 fps is a frame interval of 18.2 ms; a longer one is an overrun. */
export const FRAME_BUDGET_MS = 1_000 / 55;
/** The ladder (BQ-218): over this many overruns in the last 30 frames steps a rung down... */
const LADDER_WINDOW = 30;
const LADDER_STEP_OVERRUNS = 10;
/** ...and this many clean frames in a row steps back up one. */
const LADDER_RECOVER_FRAMES = 120;

/** Frames whose panel-side work the metrics keep (Observability). */
const WORK_SAMPLES = 256;

/** The analytics seam (BQ-212): typed, no sink; D05 §7 rules that S01 emits nothing yet. */
export type TapeEvent =
  | { readonly type: "tape.paused"; readonly cause: PauseCause }
  | {
      readonly type: "tape.resumed";
      readonly cause: ResumeCause;
      readonly inserted: number;
      readonly dropped: number;
    }
  | {
      readonly type: "tape.print_clicked";
      readonly ts_ms: number;
      readonly price: string;
      readonly side: "buy" | "sell";
      readonly tier: TapeTier;
      readonly source: "row";
    };

export type Phase = "loading" | "empty" | "streaming";
export type FeedView = "live" | "stale" | "disconnected";

/** What React renders: coarse, published at most twice a second or on a transition. */
export interface TapeChrome {
  readonly phase: Phase;
  readonly feed: FeedView;
  readonly staleSeconds: number;
  readonly staleStrong: boolean;
  readonly lastPrintTsMs: number | null;
  readonly lastPrintAgeMs: number;
  readonly ratePerSec: number;
  readonly perFrame: number;
  readonly paused: boolean;
  readonly hard: boolean;
  readonly scroll: boolean;
  readonly buffered: number;
  readonly notKept: number;
  readonly kept: number;
  readonly gapped: boolean;
  readonly loadable: boolean;
  readonly loading: boolean;
  readonly rung: 0 | 1 | 2;
  /** S12: the last print history knows, when the snapshot was empty. */
  readonly emptyLastTsMs: number | null;
}

export const INITIAL_CHROME: TapeChrome = {
  phase: "loading",
  feed: "live",
  staleSeconds: 0,
  staleStrong: false,
  lastPrintTsMs: null,
  lastPrintAgeMs: 0,
  ratePerSec: 0,
  perFrame: 0,
  paused: false,
  hard: false,
  scroll: false,
  buffered: 0,
  notKept: 0,
  kept: 0,
  gapped: false,
  loadable: false,
  loading: false,
  rung: 0,
  emptyLastTsMs: null,
};

export interface TapeDom {
  /** The `grid`: the list's one Tab stop and its scroll container. */
  readonly grid: HTMLElement;
  /** Sized to every item, so the scroll range is the list's. */
  readonly body: HTMLElement;
  /** Holds the row pool; placed at the window's first index. */
  readonly windowEl: HTMLElement;
  /** The panel's one `status` node (D29). */
  readonly status: HTMLElement;
}

export interface ControllerOptions {
  readonly feed: TapeFeedHandle;
  readonly clock: TapeClock;
  /** Epoch ms, for ages (S8-S10). */
  readonly wallNow?: (() => number) | undefined;
  readonly fetchTrades: FetchTrades;
  readonly announcer: TapeAnnouncer;
  readonly tierOf?: TierOf | undefined;
  readonly onTapeEvent?: ((event: TapeEvent) => void) | undefined;
  readonly locate?: ((request: LocateRequest) => void) | undefined;
  /** Budget #3's paint mark (E22-Q03 wires it); called at the end of a frame's write. */
  readonly onPaint?: ((atMs: number) => void) | undefined;
  readonly idBase: string;
}

interface Gap {
  readonly seq: number;
  readonly fromTsMs: number;
  readonly toTsMs: number;
  readonly divider: Divider;
  loaded: boolean;
}

export interface FrameStats {
  readonly written: number;
  readonly shown: number;
}

export class TapeController {
  private readonly feed: TapeFeedHandle;
  private readonly clock: TapeClock;
  private readonly wallNow: () => number;
  private readonly list: DisplayList;
  private readonly cursor = newCursor();
  private writer: GridWriter | null = null;
  private dom: TapeDom | null = null;
  private layers: PauseLayers = LIVE;
  private frozenTop = -1;
  private notKeptAtPause = 0;
  private scrollTop = 0;
  /** The grid's height, read once at attach and then from a ResizeObserver: no per-frame read. */
  private viewportPx = 0;
  private resizeObserver: ResizeObserver | null = null;
  private ignoreScroll = -1;
  private pinnedWindow: number | null = null;
  private pinnedActive: number | null = null;
  private activeKey: number | null = null;
  private activeCol = 0;
  private selected = false;
  private focused = false;
  /** The grid's own ring is hidden (an active cell draws the ring instead). */
  private gridRingHidden = false;
  private lastPointerMove = -Infinity;
  private transport: TransportState = "connected";
  private seenNewest = -1;
  private seamsSeen = 0;
  private lastOldest = -1;
  private readonly gaps: Gap[] = [];
  private loadingMissed = false;
  private historyBusy = false;
  private historyDone = false;
  private emptyProbe: "idle" | "busy" | "done" = "idle";
  private emptyLastTsMs: number | null = null;
  private lastPrintWall: number | null = null;
  private staleSince: number | null = null;
  private staleSaid = false;
  // the ladder (BQ-218)
  private readonly overrun = new Uint8Array(LADDER_WINDOW);
  private overrunHead = 0;
  private overrunCount = 0;
  private clean = 0;
  private rung: 0 | 1 | 2 = 0;
  private atRung = 0;
  private lastFrameAt = -1;
  private frameNo = 0;
  // chrome
  private chrome: TapeChrome = INITIAL_CHROME;
  private chromeAt = -Infinity;
  private readonly listeners = new Set<() => void>();
  private readonly unsubscribeFrame: () => void;
  /** The last frame's counts, one object written in place (no allocation per frame). */
  private readonly lastStats: { written: number; shown: number } = { written: 0, shown: 0 };
  private readonly workMs = new Float64Array(WORK_SAMPLES);
  private workHead = 0;
  private workHeld = 0;
  private disposed = false;

  constructor(private readonly options: ControllerOptions) {
    this.feed = options.feed;
    this.clock = options.clock;
    this.wallNow = options.wallNow ?? Date.now;
    this.list = new DisplayList(this.feed.ring);
    this.unsubscribeFrame = this.feed.onFrame(() => this.frame());
  }

  // ---- React's side ----

  readonly getSnapshot = (): TapeChrome => this.chrome;

  readonly subscribe = (listener: () => void): (() => void) => {
    this.listeners.add(listener);
    return () => void this.listeners.delete(listener);
  };

  /** The last frame's writer counts (the rows-per-frame metric, Observability). */
  get stats(): FrameStats {
    return this.lastStats;
  }

  /** In memory only (Observability, BQ-209): the feed's counters, the ring, the last frame. */
  metrics(): {
    readonly appended: number;
    readonly notKept: number;
    readonly ringLength: number;
    readonly rowsWritten: number;
    readonly rowsShown: number;
    readonly rung: number;
    /** The panel's own work per frame (writer, seams, chrome), p95 over the last 256 frames. */
    readonly workP95Ms: number;
    /** The feed's ingest time, worst frame. */
    readonly maxIngestMs: number;
  } {
    const m = this.feed.metrics();
    const held = Array.from(this.workMs.subarray(0, this.workHeld)).sort((a, b) => a - b);
    return {
      workP95Ms: held[Math.floor(held.length * 0.95)] ?? 0,
      maxIngestMs: m.maxIngestMs,
      appended: m.appended,
      notKept: m.notKept,
      ringLength: this.feed.ring.length,
      rowsWritten: this.lastStats.written,
      rowsShown: this.lastStats.shown,
      rung: this.rung,
    };
  }

  /** The pause layers (tests and the stories read them). */
  get pause(): PauseLayers {
    return this.layers;
  }

  get activeRow(): number | null {
    return this.activeKey;
  }

  /** The grid holds DOM focus (the row keys' `validWhen`). */
  get gridFocused(): boolean {
    return this.focused;
  }

  /** `Esc` has something to undo here (KR-2); otherwise it is not swallowed (`05` §3.3 rule 3). */
  get canEscape(): boolean {
    return this.focused && this.activeKey !== null && (!this.layers.hard || this.selected);
  }

  attach(dom: TapeDom): void {
    this.dom = dom;
    this.writer = new GridWriter(
      dom.grid,
      dom.body,
      dom.windowEl,
      this.feed.ring,
      this.feed.symbol,
      this.options.idBase,
      this.options.tierOf ?? serverTier,
    );
    this.options.announcer.attach(dom.status);
    // measured before the first write, never after one in a frame (no forced reflow)
    this.viewportPx = dom.grid.clientHeight;
    this.resizeObserver?.disconnect();
    if (typeof ResizeObserver !== "undefined") {
      this.resizeObserver = new ResizeObserver((entries) => {
        const height = entries[entries.length - 1]?.contentRect.height ?? 0;
        if (height === this.viewportPx) return;
        this.viewportPx = height;
        this.render();
      });
      this.resizeObserver.observe(dom.grid);
    }
    this.render();
  }

  dispose(): void {
    if (this.disposed) return;
    this.disposed = true;
    this.unsubscribeFrame();
    this.resizeObserver?.disconnect();
    this.resizeObserver = null;
    this.unpinAll();
    this.options.announcer.attach(null);
    this.listeners.clear();
  }

  setTransport(transport: TransportState): void {
    if (transport === this.transport) return;
    this.transport = transport;
    this.publish(true);
  }

  setVerbosity(verbosity: Verbosity): void {
    this.options.announcer.setVerbosity(verbosity);
  }

  /** S10: the pause button is T2 while disconnected, unless a hard pause was set before (P10). */
  get pauseGated(): boolean {
    return this.disconnected && !this.layers.hard;
  }

  private get disconnected(): boolean {
    return this.transport === "offline" || this.transport === "reconnecting";
  }

  // ---- pointer, scroll and focus ----

  pointerEnter(): void {
    this.lastPointerMove = this.clock.now();
    this.dispatch({ type: "rearm" });
  }

  pointerMove(): void {
    const now = this.clock.now();
    const rested = now - this.lastPointerMove >= HOVER_REST_MS;
    this.lastPointerMove = now;
    if (!this.layers.softArmed) this.dispatch({ type: "rearm" });
    else if (rested) this.dispatch({ type: "hover" });
  }

  pointerLeave(): void {
    this.dispatch({ type: "leave" });
  }

  /** The grid's `scroll` event. */
  scrolled(scrollTop: number): void {
    if (scrollTop === this.ignoreScroll) {
      this.ignoreScroll = -1;
      this.scrollTop = scrollTop;
      return;
    }
    this.scrollTop = scrollTop;
    if (scrollTop > 0) this.dispatch({ type: "scrollAway" });
    else if (this.layers.scroll) this.dispatch({ type: "jumpLive", focused: false }); // P5
    this.render();
  }

  gridFocus(): void {
    this.focused = true;
    this.render();
  }

  gridBlur(): void {
    this.focused = false;
    if (this.activeKey !== null) {
      this.setActive(null);
      this.dispatch({ type: "blur" });
    }
    this.render();
  }

  // ---- commands ----

  /** P6 / P7 from `P` or the button; `false` when the button is gated (S10, K7). */
  togglePause(cause: "key" | "button"): boolean {
    if (this.pauseGated) {
      this.options.announcer.say(DISCONNECTED_PAUSE_REASON); // E09-D09 §9.3: once per press
      return false;
    }
    this.dispatch({ type: "toggleHard", cause });
    return true;
  }

  /** K4 `Ctrl+Home`: the live edge; on a focused row the cursor goes there and the pause holds. */
  jumpLive(): void {
    if (this.activeKey !== null) {
      this.moveActiveTo(0);
      return;
    }
    if (this.layers.scroll) this.dispatch({ type: "jumpLive", focused: false });
    else this.setScroll(0);
    this.render();
  }

  /** K4 `Ctrl+End`: the oldest row. */
  jumpOldest(): void {
    if (this.activeKey !== null) {
      this.moveActiveTo(this.list.length - 1);
      return;
    }
    const max = Math.max(0, this.list.length * ROW_HEIGHT_PX - this.viewportHeight());
    if (max > 0) this.scrolled(max);
    this.setScroll(max);
    this.render();
  }

  /** The grid's own keys (KR-2, KR-3, KR-6, KR-7): `true` when the key was used. */
  gridKey(key: string): boolean {
    switch (key) {
      case "ArrowDown":
      case "ArrowUp": {
        const delta = key === "ArrowDown" ? 1 : -1;
        if (this.activeKey === null) {
          this.enterFocus(); // FP-12: the first arrow pauses on the newest row and selects it
          this.moveActiveTo(this.firstItemFrom(0, 1));
          return true;
        }
        const index = this.list.indexOfKey(this.activeKey, this.cursor);
        const next = this.firstItemFrom(index + delta, delta);
        if (next !== -1) this.moveActiveTo(next);
        return true;
      }
      case "Home":
      case "End":
      case "ArrowLeft":
      case "ArrowRight": {
        if (this.activeKey === null) return false;
        const col =
          key === "Home"
            ? 0
            : key === "End"
              ? COLUMN_COUNT - 1
              : this.activeCol + (key === "ArrowRight" ? 1 : -1);
        this.activeCol = Math.max(0, Math.min(COLUMN_COUNT - 1, col));
        this.render();
        return true;
      }
      case "Enter":
        if (this.activeKey === null) return false;
        this.locateActive();
        return true;
      case "Escape":
        return this.escape();
      default:
        return false;
    }
  }

  /** A row click (P8): pause first, then select, then locate (S6). */
  clickRow(target: Element): void {
    const row = target.closest('[role="row"]');
    const id = row?.id ?? "";
    const prefix = `${this.options.idBase}-r`;
    if (!id.startsWith(prefix)) return;
    const p = Number(id.slice(prefix.length));
    const first = this.currentFirst();
    if (!Number.isInteger(p) || p < 0 || p >= POOL_SIZE) return;
    const index = first + p;
    this.list.at(index, this.cursor);
    if (this.cursor.kind === "divider") return;
    const cell = target.closest('[role="gridcell"]');
    const col = cell === null ? 0 : Number(cell.id.slice(cell.id.lastIndexOf("c") + 1));
    this.enterFocus();
    this.activeCol = Number.isInteger(col) ? Math.max(0, Math.min(COLUMN_COUNT - 1, col)) : 0;
    this.moveActiveTo(this.list.indexOfKey(this.cursor.key, this.cursor));
    this.locateActive();
  }

  /** S15 / S16: loads the latest unloaded gap's prints from the hot tape (G-59 bounds it). */
  loadMissed(): void {
    const gap = [...this.gaps].reverse().find((g) => !g.loaded);
    if (gap === undefined || this.loadingMissed) return;
    this.loadingMissed = true;
    this.publish(true);
    void this.options
      // both ends inclusive: a sweep's prints share a millisecond, and the id dedupe drops the
      // ones the ring holds (`fromMs` is inclusive, `toMs` exclusive, hence the + 1)
      .fetchTrades({ symbol: this.feed.symbol, fromMs: gap.fromTsMs, toMs: gap.toTsMs + 1 })
      .then(
        (items) => {
          if (this.disposed) return;
          const prints = this.fresh(items);
          this.list.setBlock(gap.seq, prints);
          gap.loaded = true;
          gap.divider.text = dividerDisconnected(prints.length);
          this.list.invalidate();
          this.options.announcer.say(missedLoaded(prints.length));
        },
        () => undefined, // a refused page leaves the gap open and the button there
      )
      .finally(() => {
        this.loadingMissed = false;
        if (!this.disposed) {
          this.render();
          this.publish(true);
        }
      });
  }

  // ---- internals ----

  private fresh(items: readonly unknown[]): ExtraPrint[] {
    const out: ExtraPrint[] = [];
    const seen = new Set<string>();
    for (const item of items) {
      const p = parsePublicTrade(item);
      if (p === null || seen.has(p.id)) continue;
      if (this.feed.ring.hasId(p.id) || this.list.hasExtraId(p.id)) continue; // dedupe by id (AC4)
      seen.add(p.id);
      out.push(p);
    }
    return out.sort((a, b) => b.tsMs - a.tsMs);
  }

  private escape(): boolean {
    if (this.activeKey === null) return false; // nothing to cancel: not swallowed
    if (this.layers.hard) {
      if (!this.selected) return false;
      this.selected = false; // P13 / FP-06
      this.render();
      return true;
    }
    this.setActive(null); // FP-05: focus stays on the grid, no row active
    this.dispatch({ type: "escape" });
    return true;
  }

  private enterFocus(): void {
    this.dispatch({ type: "rowFocus" });
  }

  private setActive(key: number | null): void {
    this.activeKey = key;
    this.selected = key !== null;
    this.options.announcer.setRowFocused(key !== null);
    const ring = this.feed.ring;
    const seq = key !== null && key >= 0 && ring.has(key) ? key : null;
    if (seq !== this.pinnedActive) {
      if (this.pinnedActive !== null) ring.unpin(this.pinnedActive);
      if (seq !== null) ring.pin(seq); // FP-09: the focused print is never evicted
      this.pinnedActive = seq;
    }
  }

  /** The first non-divider index from `index` in `direction`, or -1. */
  private firstItemFrom(index: number, direction: 1 | -1): number {
    this.list.build(this.currentTop());
    for (let i = index; i >= 0 && i < this.list.length; i += direction) {
      this.list.at(i, this.cursor);
      if (this.cursor.kind !== "divider") return i;
    }
    return -1;
  }

  private moveActiveTo(index: number): void {
    if (index < 0 || index >= this.list.length) {
      this.render();
      return;
    }
    this.list.at(index, this.cursor);
    if (this.cursor.kind === "divider") return;
    this.setActive(this.cursor.key);
    // keep the row in view; no smooth scrolling (D4-06)
    const top = index * ROW_HEIGHT_PX;
    const height = this.viewportHeight();
    if (top < this.scrollTop) this.setScroll(top);
    else if (top + ROW_HEIGHT_PX > this.scrollTop + height) {
      this.setScroll(top + ROW_HEIGHT_PX - height);
    }
    this.render();
  }

  private locateActive(): void {
    if (this.activeKey === null) return;
    const index = this.list.indexOfKey(this.activeKey, this.cursor);
    if (index === -1) return;
    this.list.at(index, this.cursor);
    const ring = this.feed.ring;
    let tsMs: number;
    let price: string;
    let buy: boolean;
    let flags: number;
    if (this.cursor.kind === "row") {
      const i = ring.slot(this.cursor.seq);
      tsMs = ring.tsMs[i] ?? 0;
      price = ring.priceText(this.cursor.seq);
      buy = ring.side[i] === SIDE_BUY;
      flags = ring.flags[i] ?? 0;
    } else if (this.cursor.extra !== null) {
      tsMs = this.cursor.extra.tsMs;
      price = this.cursor.extra.price;
      buy = this.cursor.extra.side === SIDE_BUY;
      flags = this.cursor.extra.flags;
    } else return;
    this.selected = true;
    (this.options.locate ?? defaultLocate)({
      symbol: this.feed.symbol,
      tsMs,
      price: Number(price),
    });
    this.options.onTapeEvent?.({
      type: "tape.print_clicked",
      ts_ms: tsMs,
      price,
      side: buy ? "buy" : "sell",
      tier: (this.options.tierOf ?? serverTier)(flags),
      source: "row",
    });
    this.render();
  }

  private viewportHeight(): number {
    const h = this.viewportPx;
    return h > 0 ? h : 25 * ROW_HEIGHT_PX; // jsdom lays nothing out: D02's 25 compact rows
  }

  private setScroll(top: number): void {
    const value = Math.max(0, top);
    this.scrollTop = value;
    const grid = this.dom?.grid;
    if (grid !== undefined && grid.scrollTop !== value) {
      this.ignoreScroll = value;
      grid.scrollTop = value;
    }
  }

  private currentTop(): number {
    return isPaused(this.layers) ? this.frozenTop : this.feed.ring.nextSeq - 1;
  }

  private currentFirst(): number {
    return isPaused(this.layers) ? GridWriter.firstFor(this.scrollTop, this.list.length) : 0;
  }

  private dispatch(event: PauseEvent): void {
    const before = this.layers;
    const s = step(before, event);
    if (s.next === before && s.insert === "none") return; // nothing changed: no write, no publish
    this.layers = s.next;
    if (!isPaused(before) && isPaused(s.next)) {
      // pause entry freezes what is on screen now (D4-04): the list keeps its last top
      this.frozenTop = this.list.top >= 0 ? this.list.top : this.feed.ring.nextSeq - 1;
      this.notKeptAtPause = this.feed.ring.notKept;
    }
    if (s.paused !== undefined)
      this.options.onTapeEvent?.({ type: "tape.paused", cause: s.paused });
    if (s.insert !== "none") this.insert(s.insert, s.resumed ?? "key");
    this.render();
    this.publish(true);
  }

  /** D4-05 / FP-04: the buffered prints go in under one divider, in one frame, never replayed. */
  private insert(mode: "live" | "anchored", cause: ResumeCause): void {
    const ring = this.feed.ring;
    const newest = ring.nextSeq - 1;
    const inserted = Math.max(0, newest - this.frozenTop);
    const notKept = ring.notKept - this.notKeptAtPause;
    const anchorBefore = mode === "anchored" && this.activeKey !== null ? this.activeKey : null;
    const indexBefore =
      anchorBefore === null ? -1 : this.list.indexOfKey(anchorBefore, this.cursor);
    if (inserted > 0 && ring.has(this.frozenTop + 1)) {
      this.list.addDivider(
        this.frozenTop + 1,
        notKept > 0 ? dividerPausedNotKept(inserted + notKept, notKept) : dividerPaused(inserted),
      );
    }
    if (inserted > 0) {
      this.options.announcer.say(
        notKept > 0 ? resumedNotKept(inserted, notKept) : resumed(inserted),
      );
    }
    this.options.onTapeEvent?.({ type: "tape.resumed", cause, inserted, dropped: notKept });
    this.frozenTop = newest;
    this.notKeptAtPause = ring.notKept;
    if (mode === "live") {
      this.unpinWindow();
      this.setScroll(0);
      return;
    }
    // FP-04: the focused print keeps its on-screen offset
    this.list.build(newest);
    if (anchorBefore !== null && indexBefore !== -1) {
      const indexAfter = this.list.indexOfKey(anchorBefore, this.cursor);
      if (indexAfter !== -1)
        this.setScroll(this.scrollTop + (indexAfter - indexBefore) * ROW_HEIGHT_PX);
    }
  }

  private unpinWindow(): void {
    if (this.pinnedWindow !== null) this.feed.ring.unpin(this.pinnedWindow);
    this.pinnedWindow = null;
  }

  private unpinAll(): void {
    this.unpinWindow();
    if (this.pinnedActive !== null) this.feed.ring.unpin(this.pinnedActive);
    this.pinnedActive = null;
  }

  private frame(): void {
    if (this.disposed) return;
    const now = this.clock.now();
    this.ladder(now);
    const ring = this.feed.ring;
    const newest = ring.nextSeq - 1;
    if (newest > this.seenNewest) {
      this.options.announcer.observe(
        ring,
        Math.max(this.seenNewest + 1, ring.oldestSeq),
        newest,
        now,
      );
      this.seenNewest = newest;
      this.lastPrintWall = this.wallNow();
    } else this.options.announcer.tick(now);
    this.drainSeams();
    if (ring.oldestSeq !== this.lastOldest) {
      if (this.lastOldest !== -1) {
        this.list.clearTail(); // the history no longer touches the ring
        this.historyDone = false;
      }
      this.lastOldest = ring.oldestSeq;
    }
    if (this.layers.soft && now - this.lastPointerMove >= PARK_MS) this.dispatch({ type: "park" });
    this.frameNo += 1;
    // rung 2: row writes every 2nd frame while live (a paused list does not move)
    if (this.rung < 2 || isPaused(this.layers) || this.frameNo % 2 === 0) this.render();
    this.probeEmpty();
    this.publish(false);
    const end = this.clock.now();
    this.workMs[this.workHead] = end - now;
    this.workHead = (this.workHead + 1) % WORK_SAMPLES;
    if (this.workHeld < WORK_SAMPLES) this.workHeld += 1;
    this.options.onPaint?.(end);
  }

  private drainSeams(): void {
    const log = this.feed.ingest.seamLog;
    const total = this.feed.ingest.seams;
    const fresh = Math.min(log.length, total - this.seamsSeen);
    if (fresh <= 0) return;
    this.seamsSeen = total;
    for (const seam of log.slice(log.length - fresh)) {
      const from = formatTime(seam.fromTsMs);
      const to = formatTime(seam.toTsMs);
      const divider = this.list.addDivider(seam.seq, dividerGap(from, to));
      this.gaps.push({ ...seam, divider, loaded: false });
      if (this.gaps.length > 16) this.gaps.shift();
      this.options.announcer.say(reconnectedGap(from, to)); // S15, polite once
    }
  }

  private ladder(now: number): void {
    if (this.lastFrameAt >= 0) {
      const over = now - this.lastFrameAt > FRAME_BUDGET_MS + 0.5 ? 1 : 0;
      this.overrunCount += over - (this.overrun[this.overrunHead] ?? 0);
      this.overrun[this.overrunHead] = over;
      this.overrunHead = (this.overrunHead + 1) % LADDER_WINDOW;
      this.clean = over === 1 ? 0 : this.clean + 1;
      this.atRung += 1;
      if (
        this.overrunCount >= LADDER_STEP_OVERRUNS &&
        this.rung < 2 &&
        this.atRung >= LADDER_WINDOW
      ) {
        this.rung = this.rung === 0 ? 1 : 2;
        this.atRung = 0;
      } else if (this.clean >= LADDER_RECOVER_FRAMES && this.rung > 0) {
        this.rung = this.rung === 2 ? 1 : 0;
        this.atRung = 0;
        this.clean = 0;
      }
    }
    this.lastFrameAt = now;
  }

  /** S12: an empty snapshot while live asks history for the last print's time, once. */
  private probeEmpty(): void {
    if (this.emptyProbe !== "idle" || this.phase() !== "empty") return;
    this.emptyProbe = "busy";
    const to = this.wallNow();
    void this.options
      .fetchTrades({ symbol: this.feed.symbol, fromMs: to - TRADES_MAX_WINDOW_MS, toMs: to })
      .then(
        (items) => {
          const first = items.map(parsePublicTrade).find((p) => p !== null);
          this.emptyLastTsMs = first?.tsMs ?? null;
        },
        () => undefined,
      )
      .finally(() => {
        this.emptyProbe = "done";
        if (!this.disposed) this.publish(true);
      });
  }

  /** S14 (BQ-214): at the bottom of the list, history older than the oldest reachable print. */
  private fetchOlder(): void {
    if (this.historyBusy || this.historyDone) return;
    const ring = this.feed.ring;
    const tail = this.list.tailPrints;
    const last = tail[tail.length - 1];
    const oldestTs =
      last !== undefined
        ? last.print.tsMs
        : ring.length > 0
          ? (ring.tsMs[ring.slot(ring.oldestSeq)] ?? 0)
          : null;
    if (oldestTs === null) return;
    this.historyBusy = true;
    void this.options
      .fetchTrades({
        symbol: this.feed.symbol,
        fromMs: oldestTs - TRADES_MAX_WINDOW_MS,
        toMs: oldestTs,
      })
      .then(
        (items) => {
          if (this.disposed) return;
          const prints = this.fresh(items).filter((p) => p.tsMs < oldestTs);
          if (prints.length > 0) this.list.appendTail(prints);
          else {
            this.historyDone = true;
            this.list.setTailDivider(dividerNoHistory(formatSecond(oldestTs)));
          }
        },
        () => {
          this.historyDone = true; // a refused page stops the probe; no partial-history claim
        },
      )
      .finally(() => {
        this.historyBusy = false;
        if (!this.disposed) this.render();
      });
  }

  private render(): void {
    const writer = this.writer;
    if (writer === null || this.disposed) return;
    const paused = isPaused(this.layers);
    const top = this.currentTop();
    this.list.build(top);
    if (!paused && this.scrollTop !== 0) this.setScroll(0);
    const first = this.currentFirst();
    const stats = writer.render(this.list, {
      first,
      activeKey: this.activeKey,
      activeCol: this.activeCol,
      selected: this.selected,
      focused: this.focused,
      limit: paused
        ? POOL_SIZE
        : Math.ceil(this.viewportHeight() / ROW_HEIGHT_PX) + LIVE_OVERSCAN_ROWS,
    });
    this.lastStats.written = stats.written;
    this.lastStats.shown = stats.shown;
    // one focus ring at a time: the active cell's, else the grid's own (WCAG 2.4.7, FP-05)
    const hideGridRing = this.focused && this.activeKey !== null;
    if (hideGridRing !== this.gridRingHidden && this.dom !== null) {
      if (hideGridRing) this.dom.grid.style.setProperty("outline", "none");
      else this.dom.grid.style.removeProperty("outline");
      this.gridRingHidden = hideGridRing;
    }
    const ring = this.feed.ring;
    // S22 / D02-G7: a paused window and its overscan are pinned; live, nothing is
    if (paused && stats.oldestSeqShown >= 0) {
      if (stats.oldestSeqShown !== this.pinnedWindow) {
        if (this.pinnedWindow !== null) ring.unpin(this.pinnedWindow);
        ring.pin(stats.oldestSeqShown);
        this.pinnedWindow = stats.oldestSeqShown;
      }
    } else if (!paused) this.unpinWindow();
    if (paused && this.list.length > 0 && first + stats.shown >= this.list.length) {
      this.fetchOlder();
    }
  }

  private phase(): Phase {
    const snapshot = this.feed.store.getSnapshot();
    if (this.feed.ring.length > 0 || this.list.tailPrints.length > 0) return "streaming";
    if (snapshot.feed === "pending" || snapshot.feed === "idle") return "loading";
    return this.feed.ingest.counters.frames > 0 ? "empty" : "loading";
  }

  private publish(now: boolean): void {
    const at = this.clock.now();
    const snapshot = this.feed.store.getSnapshot();
    const ring = this.feed.ring;
    const paused = isPaused(this.layers);
    const wall = this.wallNow();
    const stale = snapshot.feed === "stale";
    if (stale && this.staleSince === null) this.staleSince = wall;
    if (!stale) this.staleSince = null;
    const lastData = this.lastPrintWall ?? this.staleSince ?? wall;
    const staleMs = stale ? wall - lastData : 0;
    const feedView: FeedView = this.disconnected ? "disconnected" : stale ? "stale" : "live";
    // E17-D01 §7 / D02 S8: polite once on entering T1 and on leaving it
    if (feedView === "stale" && !this.staleSaid) {
      this.options.announcer.say(tapeStale(staleMs / 1000));
      this.staleSaid = true;
    } else if (feedView === "live" && this.staleSaid) {
      this.options.announcer.say(TAPE_LIVE);
      this.staleSaid = false;
    }
    const c = this.chrome;
    const phase = this.phase();
    const notKept = paused ? ring.notKept - this.notKeptAtPause : 0;
    const gapped = this.gaps.length > 0;
    const loadable = this.gaps.some((g) => !g.loaded);
    // a transition publishes at once; counters wait out the interval (D4-07), allocating nothing
    const discrete =
      phase !== c.phase ||
      feedView !== c.feed ||
      staleMs >= STALE_STRONG_MS !== c.staleStrong ||
      paused !== c.paused ||
      this.layers.hard !== c.hard ||
      this.layers.scroll !== c.scroll ||
      gapped !== c.gapped ||
      loadable !== c.loadable ||
      this.loadingMissed !== c.loading ||
      this.rung !== c.rung ||
      notKept > 0 !== c.notKept > 0 ||
      this.emptyLastTsMs !== c.emptyLastTsMs;
    const interval = this.rung >= 1 ? CHROME_INTERVAL_RUNG1_MS : CHROME_INTERVAL_MS;
    if (!discrete && !now && at - this.chromeAt < interval) return;
    const next: TapeChrome = {
      phase,
      feed: feedView,
      staleSeconds: Math.floor(staleMs / 1000),
      staleStrong: staleMs >= STALE_STRONG_MS,
      lastPrintTsMs: snapshot.lastPrintTsMs,
      lastPrintAgeMs: this.lastPrintWall === null ? 0 : wall - this.lastPrintWall,
      ratePerSec: snapshot.ratePerSec,
      perFrame: snapshot.perFrame,
      paused,
      hard: this.layers.hard,
      scroll: this.layers.scroll,
      buffered: paused ? Math.max(0, ring.nextSeq - 1 - this.frozenTop) : 0,
      notKept,
      kept: ring.length,
      gapped,
      loadable,
      loading: this.loadingMissed,
      rung: this.rung,
      emptyLastTsMs: this.emptyLastTsMs,
    };
    if (!discrete && sameCounters(next, c)) return;
    this.chrome = next;
    this.chromeAt = at;
    for (const listener of [...this.listeners]) listener();
  }
}

const sameCounters = (a: TapeChrome, b: TapeChrome): boolean =>
  a.staleSeconds === b.staleSeconds &&
  a.lastPrintTsMs === b.lastPrintTsMs &&
  Math.floor(a.lastPrintAgeMs / 1000) === Math.floor(b.lastPrintAgeMs / 1000) &&
  a.ratePerSec === b.ratePerSec &&
  a.perFrame === b.perFrame &&
  a.buffered === b.buffered &&
  a.notKept === b.notKept &&
  a.kept === b.kept;

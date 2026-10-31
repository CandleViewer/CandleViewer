/**
 * The ticker client (E08-S08; E08-D07 D6, D27, §4.6; `23-ws-protocol.md` §6.1, §7.5, §8.5, §16.2): ONE batched `ticker`
 * subscription per connection, carrying at most 40 distinct symbols, shared by every pane that claims symbols. The 40
 * is a security control (SR-073): never exceeded, never worked around with a second subscription.
 *
 * - A change of the union (a window move, a list switch, an add that changes the window, a re-open) is an `unsub` and a
 *   `sub` (`symbols` is no `ctl` key), and the `sub` draws on the topic's rebuild share: it starts only while the
 *   client's share allows (`rebuildShare.ts`), the window wanted then; meanwhile it waits. A removal alone never
 *   re-subscribes: its symbol leaves with the next change.
 * - A `sub` the server refuses (`resync_rate_limited`) subscribes nothing: no symbol is live, the pause is reported, and
 *   the retry follows the back-off, never a loop. The public WS client API carries no refusal code (a revoked handle
 *   before any snapshot is all it says), so every refusal takes this path.
 * - Frames are read on the hub's own 4 Hz beat (`FLUSH_MS`, the 250 ms `ticker` throttle), never per arrival, and written
 *   into the per-symbol store once per beat: the coalescing. Plain code, never a statechart (`28` §1.2).
 */
import type { TopicFrame } from "../../../lib/ws/api";
import type { DataBody } from "../../../lib/ws/protocol/codec";
import type { TopicStatus } from "../../../lib/ws/state/types";
import { createBackoff, createRebuildShare } from "./rebuildShare";
import { createTickerStore, type TickerStore } from "./tickerStore";
import { tickerItemsOf, type TickerItem } from "./tickerValues";

/** `23` §16.2: distinct symbols per connection. */
export const MAX_LIVE_SYMBOLS = 40;
/** The coalescing beat: 4 Hz (`14` SCR-100 "Performance"). */
export const FLUSH_MS = 250;

/** One batched `ticker` subscription, as the transport hands it over. */
export interface TickerChannel {
  /** The frames since the last read, in order. */
  read(): readonly TopicFrame[];
  readonly status: TopicStatus;
  release(): void;
}

export interface TickerTransport {
  open(symbols: readonly [string, ...string[]]): TickerChannel;
}

/** The time source, injectable; the system one reads the globals on every call, so fake timers apply. */
export interface HubClock {
  readonly now: () => number;
  readonly setTimeout: (run: () => void, ms: number) => unknown;
  readonly clearTimeout: (id: unknown) => void;
  readonly setInterval: (run: () => void, ms: number) => unknown;
  readonly clearInterval: (id: unknown) => void;
}

export const SYSTEM_HUB_CLOCK: HubClock = {
  now: () => Date.now(),
  setTimeout: (run, ms) => setTimeout(run, ms),
  // `id` is what this clock's own timers returned; the casts only restore that type.
  clearTimeout: (id) => clearTimeout(id as ReturnType<typeof setTimeout>),
  setInterval: (run, ms) => setInterval(run, ms),
  clearInterval: (id) => clearInterval(id as ReturnType<typeof setInterval>),
};

export interface HubState {
  /** The symbols of the subscription the hub holds: pending or live. Empty while none, or after a refusal. */
  readonly live: ReadonlySet<string>;
  /** A wanted change waits for the rebuild share: when it may start. */
  readonly waitingUntil: number | null;
  /** A refused `sub`: the wait before the retry and when it is due. */
  readonly paused: { readonly delayMs: number; readonly retryAt: number } | null;
  /** Snapshots read so far: the panel's Disconnected ends with the first after a reconnect. */
  readonly snaps: number;
  /** When the held subscription was asked for (the hub's clock): its rows initialise from here. */
  readonly openedAt: number | null;
}

export interface TickerHub {
  readonly store: TickerStore;
  /** The symbols a pane wants live now (its window); the hub holds the union. */
  claim(paneId: string, symbols: readonly string[]): void;
  release(paneId: string): void;
  /** 40 less the distinct symbols the other panes hold that `list` does not. */
  budgetFor(paneId: string, list: Iterable<string>): number;
  /** The distinct symbols the other panes hold that `list` does not ("other panels use 30"). */
  othersHolding(paneId: string, list: Iterable<string>): number;
  getState(): HubState;
  subscribe(listener: () => void): () => void;
  /** When the last snapshot or delta was read (the hub's clock), read on the panel's 1 Hz tick: never a render per beat. */
  lastDataMs(): number | null;
  dispose(): void;
}

const NONE: ReadonlySet<string> = new Set();

const itemsOf = (body: DataBody): readonly TickerItem[] =>
  body.e === "j" ? tickerItemsOf(body.p) : []; // the batched `ticker` is structured (§14.8)

export function createTickerHub(
  transport: TickerTransport,
  clock: HubClock = SYSTEM_HUB_CLOCK,
): TickerHub {
  const store = createTickerStore();
  const share = createRebuildShare();
  const backoff = createBackoff();
  const claims = new Map<string, readonly string[]>();
  const listeners = new Set<() => void>();
  let channel: TickerChannel | null = null;
  let held: ReadonlySet<string> = NONE;
  let wait: unknown = null;
  let beat: unknown = null;
  let lastData: number | null = null;
  let disposed = false;
  let state: HubState = { live: NONE, waitingUntil: null, paused: null, snaps: 0, openedAt: null };

  const set = (patch: Partial<HubState>): void => {
    state = { ...state, ...patch };
    for (const listener of [...listeners]) listener();
  };

  /** Every pane's symbols in claim order, each once, at most 40: the first claimed keep their place. */
  const wanted = (): string[] => {
    const out: string[] = [];
    const seen = new Set<string>();
    for (const symbols of claims.values()) {
      for (const symbol of symbols) {
        if (seen.has(symbol)) continue;
        if (out.length >= MAX_LIVE_SYMBOLS) return out;
        seen.add(symbol);
        out.push(symbol);
      }
    }
    return out;
  };
  const covered = (want: readonly string[]): boolean =>
    channel !== null && want.every((symbol) => held.has(symbol));

  const stopWaiting = (): void => {
    if (wait !== null) clock.clearTimeout(wait);
    wait = null;
  };
  const stopBeat = (): void => {
    if (beat !== null) clock.clearInterval(beat);
    beat = null;
  };
  /** Lets the held subscription go and forgets the values of `leaving`. */
  const close = (leaving: Iterable<string>): void => {
    if (channel !== null) channel.release();
    channel = null;
    stopBeat();
    store.drop(leaving);
  };

  function flush(): void {
    const current = channel;
    if (current === null) return;
    const items: TickerItem[] = [];
    let snaps = 0;
    let data = false;
    let ended = false;
    for (const frame of current.read()) {
      if (frame.kind === "reset") {
        // A reconnect re-subscribes the held stream: that `sub` draws on the share like the client's own.
        if (frame.reason === "reconnect") share.record(clock.now());
        else if (frame.reason === "revoked" || frame.reason === "unsubscribed") ended = true;
        continue;
      }
      data = true;
      if (frame.kind === "snap") {
        snaps += 1;
        for (const body of frame.bodies) items.push(...itemsOf(body));
      } else items.push(...itemsOf(frame.body));
    }
    const now = clock.now();
    if (data) lastData = now;
    if (items.length > 0) store.apply(items, now);
    if (snaps > 0) {
      backoff.reset();
      set({ snaps: state.snaps + snaps, paused: null });
    }
    if (ended || current.status === "revoked") refused();
  }

  /** The server refused or ended the subscription: nothing is live; the retry waits out the back-off. */
  function refused(): void {
    const dropped = [...held];
    held = NONE;
    close(dropped);
    const delayMs = backoff.next();
    set({
      live: NONE,
      waitingUntil: null,
      paused: { delayMs, retryAt: clock.now() + delayMs },
      openedAt: null,
    });
    stopWaiting();
    schedule();
  }

  function start(): void {
    if (disposed) return;
    const want = wanted();
    const [first, ...rest] = want;
    if (first === undefined) return schedule();
    if (covered(want)) {
      set({ waitingUntil: null });
      return;
    }
    const leaving = [...held].filter((symbol) => !want.includes(symbol));
    close(leaving);
    channel = transport.open([first, ...rest]);
    held = new Set(want);
    const now = clock.now();
    share.record(now);
    beat = clock.setInterval(flush, FLUSH_MS);
    set({ live: held, waitingUntil: null, paused: null, openedAt: now });
  }

  /** Brings the subscription in line with the claims: now if the share allows, else when it does. */
  function schedule(): void {
    if (disposed) return;
    const want = wanted();
    if (want.length === 0) {
      stopWaiting();
      const dropped = [...held];
      held = NONE;
      close(dropped);
      if (state.live.size > 0 || state.waitingUntil !== null || state.paused !== null)
        set({ live: NONE, waitingUntil: null, paused: null, openedAt: null });
      return;
    }
    if (covered(want)) {
      // A removal alone, or nothing new: the held subscription stays.
      stopWaiting();
      if (state.waitingUntil !== null) set({ waitingUntil: null });
      return;
    }
    const now = clock.now();
    const at = Math.max(share.nextStart(now), state.paused?.retryAt ?? now);
    if (at <= now) {
      stopWaiting();
      start();
      return;
    }
    if (wait !== null && (state.paused !== null || state.waitingUntil === at)) return;
    stopWaiting();
    wait = clock.setTimeout(() => {
      wait = null;
      start();
    }, at - now);
    // While paused, the pause is the notice; otherwise the rows outside say when they go live.
    if (state.paused === null) set({ waitingUntil: at });
  }

  const othersOf = (paneId: string, list: Iterable<string>): Set<string> => {
    const mine = new Set(list);
    const others = new Set<string>();
    for (const [id, symbols] of claims) {
      if (id === paneId) continue;
      for (const symbol of symbols) if (!mine.has(symbol)) others.add(symbol);
    }
    return others;
  };

  return {
    store,
    claim(paneId, symbols) {
      if (disposed) return;
      claims.set(paneId, [...symbols]);
      schedule();
    },
    release(paneId) {
      if (!claims.delete(paneId)) return;
      schedule();
    },
    budgetFor: (paneId, list) => Math.max(0, MAX_LIVE_SYMBOLS - othersOf(paneId, list).size),
    othersHolding: (paneId, list) => othersOf(paneId, list).size,
    getState: () => state,
    subscribe(listener) {
      listeners.add(listener);
      return () => void listeners.delete(listener);
    },
    lastDataMs: () => lastData,
    dispose() {
      if (disposed) return;
      disposed = true;
      stopWaiting();
      const dropped = [...held];
      held = NONE;
      claims.clear();
      close(dropped);
      listeners.clear();
    },
  };
}

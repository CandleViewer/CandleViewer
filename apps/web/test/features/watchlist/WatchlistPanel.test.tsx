/**
 * E08-S08 (#4702): SCR-100 on R-111 (pre-ruling 1) — the four scenarios of the ticket against the derived CV
 * `ticker` golden (C-13.5), on fake timers, a fake transport under the real ticker hub, a fake instrument index and a
 * fake `/watchlists` API (no network). Plus message to pixels over the golden as the server sends it (D32), the
 * keyboard paths, focus kept off the page, axe in dark and light, and the teardown of every subscription. The app's
 * one announcer is rendered beside the panel: the panel owns no live region (E08-D07 D17). PR (c): the paths that open
 * SCR-101, each with its intent, and the lists SCR-101 stores reaching the panel (`sync`).
 */
import { createRequire } from "node:module";
import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const { apiFetch } = vi.hoisted(() => ({
  apiFetch: vi.fn<(url: string, init?: RequestInit) => Promise<Response>>(),
}));
vi.mock("../../../src/lib/http/csrfFetch", () => ({ apiFetch }));

import { ShellAnnouncer, clearAnnouncements } from "../../../src/features/app-shell/announcer";
import { KeymapHost } from "../../../src/keymap/KeymapHost";
import { getBindings, resetBindings, setBindings } from "../../../src/keymap/profile";
import type { IndexSnapshot } from "../../../src/features/symbol-search/instrumentIndex";
import { toEntry, type Instrument } from "../../../src/features/symbol-search/ranking";
import { WatchlistPanel } from "../../../src/features/watchlist/WatchlistPanel";
import type { Watchlist } from "../../../src/features/watchlist/listEdits";
import type { InstrumentSource } from "../../../src/features/watchlist/instruments";
import type { ManagerIntent } from "../../../src/features/watchlist/manager/intent";
import { createWatchlistSync, type WatchlistSync } from "../../../src/features/watchlist/sync";
import { createLocalPaneSettings, type SyncGroupPort } from "../../../src/features/watchlist/ports";
import {
  FLUSH_MS,
  FRAME_MS,
  SYSTEM_HUB_CLOCK,
  createTickerHub,
  type TickerHub,
} from "../../../src/features/watchlist/ticker/tickerHub";
import type { WatchlistApi } from "../../../src/features/watchlist/watchlistApi";
import { LAST_CADENCE_MS, type PricePrefs } from "../../../src/features/watchlist/focusedLast";
import type { TopicFrame } from "../../../src/lib/ws/api";
import { setActiveClient } from "../../../src/lib/ws/client/activeClient";
import type { WsClientHandle } from "../../../src/lib/ws/client/createWsClient";
import { INITIAL_WS_STATE } from "../../../src/lib/ws/state/reducer";
import type { WsState } from "../../../src/lib/ws/state/types";
import {
  FakeTransport,
  deltaOf,
  p95,
  restItem,
  serverPaced,
  snapOf,
  streamItem,
  BTC_STREAM,
} from "./support";

const axe = createRequire(createRequire(import.meta.url).resolve("@axe-core/playwright"))(
  "axe-core",
) as {
  run: (
    el: Element,
    o?: object,
  ) => Promise<{ violations: { id: string; impact?: string | null }[] }>;
};

// Each test draws the whole panel in jsdom, which on a loaded runner takes seconds (the 60 s window stress test keeps
// its own budget).
vi.setConfig({ testTimeout: 30_000 });

/** A whole second, so the shared 1 Hz clock ticks on whole seconds from the mount. */
const T0 = Date.UTC(2026, 9, 31, 10, 0, 0);

const inst = (
  symbol: string,
  scale: number,
  status: Instrument["status"] = "Trading",
): Instrument => ({
  symbol,
  category: "linear",
  status,
  ...(status === "Trading" ? {} : { delisted: true, status_reason: "Delisted by the exchange" }),
  price_scale: scale,
  tick_size: "0.01",
  qty_step: "0.001",
  base_coin: symbol.slice(0, -4),
  quote_coin: "USDT",
});
/** E08-D07's sample list, Majors: the three recorded symbols first, then nine more with no capture. */
const MAJORS_SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "DOGEUSDT", "ADAUSDT"].concat([
  "AVAXUSDT",
  "LINKUSDT",
  "DOTUSDT",
  "LTCUSDT",
  "BNBUSDT",
  "TONUSDT",
]);
const ALTS_SYMBOLS = Array.from({ length: 200 }, (_, i) => `A${String(i).padStart(3, "0")}USDT`);
const SCALE: Readonly<Record<string, number>> = { BTCUSDT: 2, ETHUSDT: 2, SOLUSDT: 3 };
const INSTRUMENTS = [...MAJORS_SYMBOLS, ...ALTS_SYMBOLS, "XRPUSDT"].map((s) =>
  inst(s, SCALE[s] ?? 4),
);

const list = (name: string, symbols: readonly string[], id = `id-${name}`): Watchlist => ({
  id,
  name,
  symbols: [...symbols],
  columns: [],
  version: 1,
  created_at: "2026-10-30T10:00:00Z",
  updated_at: "2026-10-30T10:00:00Z",
});
const MAJORS = list("Majors", MAJORS_SYMBOLS, "11111111-1111-4111-8111-111111111111");
const ALTS = list("Alts", ALTS_SYMBOLS.slice(0, 120), "22222222-2222-4222-8222-222222222222");
const BIG = list("Big", ALTS_SYMBOLS, "33333333-3333-4333-8333-333333333333");
const DELISTED = list("Old", ["BTCUSDT", "LUNAUSDT"], "44444444-4444-4444-8444-444444444444");

/** The index as E08-S09's answers it (`over` changes a field, `failed` for one), with `reread` to watch. */
function fakeIndex(
  over: Partial<IndexSnapshot> = {},
  reread: () => void = () => undefined,
): InstrumentSource {
  const snapshot: IndexSnapshot = {
    phase: "ready",
    entries: INSTRUMENTS.map((i) => toEntry(i)),
    known: [toEntry(inst("LUNAUSDT", 4, "Closed"))],
    unlisted: [],
    loadedAt: 0,
    cacheAgeS: 0,
    staleSince: null,
    refreshing: false,
    retryAt: null,
    failure: null,
    ...over,
  };
  return {
    subscribe: () => () => undefined,
    getSnapshot: () => snapshot,
    learn: () => undefined,
    reread,
  };
}

function fakeApi(lists: readonly Watchlist[]) {
  const replace = vi.fn<WatchlistApi["replace"]>(async (current, next) => ({
    kind: "saved",
    list: {
      ...current,
      symbols: [...next.symbols],
      columns: [...next.columns],
      version: current.version + 1,
    },
  }));
  const api: WatchlistApi = { list: vi.fn(async () => lists), replace };
  return { api, replace };
}

/** `/watchlists` as E08-T07 keeps it: each list's version, and a replace against an older one is a 412. */
function versionedApi(lists: readonly Watchlist[]) {
  const stored = new Map(lists.map((l): [string, Watchlist] => [l.id, l]));
  const replace = vi.fn<WatchlistApi["replace"]>(async (current, next) => {
    const held = stored.get(current.id);
    if (held === undefined) return { kind: "failed" };
    if (held.version !== current.version) return { kind: "conflict" };
    const saved: Watchlist = {
      ...held,
      symbols: [...next.symbols],
      columns: [...next.columns],
      version: held.version + 1,
    };
    stored.set(saved.id, saved);
    return { kind: "saved", list: saved };
  });
  const list = vi.fn<WatchlistApi["list"]>(async () => [...stored.values()]);
  const api: WatchlistApi = { list, replace };
  return { api, replace, list, stored };
}

function fakeWs() {
  let state: WsState = { ...INITIAL_WS_STATE, transport: "connected", link: { kind: "up" } };
  const listeners = new Set<() => void>();
  const handle: WsClientHandle = {
    consume: () => {
      throw new Error("SCR-100 reads the ticker through its hub");
    },
    setPane: () => undefined,
    focusPane: () => undefined,
    getState: () => state,
    subscribe: (listener) => {
      listeners.add(listener);
      return () => void listeners.delete(listener);
    },
    // The panel never asks for a handshake (CMP-077's Retry now is the shell's): nothing sent.
    retryNow: () => false,
    stop: () => undefined,
    diagnostics: () => undefined,
  };
  return {
    handle,
    set(patch: Partial<WsState>) {
      state = { ...state, ...patch };
      for (const listener of [...listeners]) listener();
    },
  };
}

let transport: FakeTransport;
let hub: TickerHub;
let ws: ReturnType<typeof fakeWs>;
let said: string[];
let observer: MutationObserver;
/** The running test's: `afterEach` aborts it, so a test still running past its timeout stops at its next step. */
let running = new AbortController();
/** The step in flight: `afterEach` waits for it, so no `act` of a test that timed out stays open into the next. */
let stepping: Promise<void> | null = null;
/** What `afterEach` restores if the test did not (a spy on a prototype). */
const undo: (() => void)[] = [];

/** Runs `tick` (a step of the fake clock) in `act`, the screen up to date after; a test that is over goes no further. */
async function advance(tick: () => Promise<void> | void): Promise<void> {
  const { signal } = running;
  signal.throwIfAborted();
  // `act` answers a bare thenable: made a promise, so that `afterEach` can wait for it however it ends.
  const inFlight = Promise.resolve(
    act(async () => {
      await tick();
    }),
  );
  stepping = inFlight;
  try {
    await inFlight;
  } finally {
    if (stepping === inFlight) stepping = null;
  }
  signal.throwIfAborted();
}

/** Advances the fake clock `ms`, the promises settled after each timer it fires. */
const flush = (ms = 0): Promise<void> =>
  advance(async () => {
    await vi.advanceTimersByTimeAsync(ms);
  });

/**
 * Runs `first` (a scroll, say), then advances the fake clock `ms` with its timers fired back to back, in one `act`: the
 * screen catches up once, when the span ends. For spans that settle no promise between timers: `flush` yields a
 * macrotask of the event loop after each timer instead (a millisecond or more), and the hub's frame loop fires one every
 * 16 ms, so minutes of it would take a minute.
 */
const run = (ms: number, first: () => void = () => undefined): Promise<void> =>
  advance(() => {
    first();
    vi.advanceTimersByTime(ms);
  });

/** vitest's fake `requestAnimationFrame` runs every 16 ms from the clock's start (T0). */
const FAKE_FRAME_MS = 16;

/**
 * Pushes each of `frames` into the ticker subscription at its time (the clock's ms), stepping the clock to every push
 * and every animation frame until `until`; `look` runs after each step, with the screen up to date.
 */
async function play(
  frames: readonly { readonly at: number; readonly frame: TopicFrame }[],
  until: number,
  look: () => void,
): Promise<void> {
  let next = 0;
  while (Date.now() < until) {
    for (let due = frames[next]; due !== undefined && due.at <= Date.now(); due = frames[next]) {
      transport.current?.push(due.frame);
      next += 1;
    }
    const frameAt = T0 + (Math.floor((Date.now() - T0) / FAKE_FRAME_MS) + 1) * FAKE_FRAME_MS;
    await flush(
      Math.min(frameAt, frames[next]?.at ?? Number.POSITIVE_INFINITY, until) - Date.now(),
    );
    look();
  }
}

/** Records each message the app's polite region says (once per change) into `said`. */
function hearPolite(): void {
  const polite = document.querySelector('[aria-live="polite"]');
  if (polite === null) throw new Error("the app's polite region is missing");
  observer = new MutationObserver(() => {
    const text = polite.textContent ?? "";
    if (text !== "" && said.at(-1) !== text) said.push(text);
  });
  observer.observe(polite, { childList: true, subtree: true, characterData: true });
}

function mount(
  lists: readonly Watchlist[],
  shown: Watchlist,
  extra: {
    syncGroup?: SyncGroupPort;
    onManage?: (intent: ManagerIntent) => void;
    sync?: WatchlistSync;
    api?: WatchlistApi;
    hub?: TickerHub | null;
    instruments?: InstrumentSource;
    /** SCR-117's price announcements; without, the app's (here no provider: the defaults). */
    pricePrefs?: PricePrefs;
  } = {},
) {
  const { api: fake, replace } = fakeApi(lists);
  const { api = fake, hub: held = hub, instruments = fakeIndex(), ...rest } = extra;
  const view = render(
    <>
      <WatchlistPanel
        listId={shown.id}
        paneId="r111"
        api={api}
        hub={held}
        instruments={instruments}
        paneSettings={createLocalPaneSettings()}
        {...rest}
      />
      <ShellAnnouncer />
    </>,
  );
  hearPolite();
  return { ...view, api, replace };
}

const grid = (): HTMLElement => screen.getByRole("grid");
const rowOf = (symbol: string): HTMLElement => {
  // A delisted row's header leads with its lock, named "Not available" (G-T2.1d).
  const header = within(grid()).getByRole("rowheader", {
    name: new RegExp(`(^|\\s)${symbol}(\\s|$)`),
  });
  const row = header.closest("tr");
  if (row === null) throw new Error(`${symbol} has no row`);
  return row;
};
const cellOf = (symbol: string, column: string): HTMLElement => {
  const cell = rowOf(symbol).querySelector<HTMLElement>(`[data-column="${column}"]`);
  if (cell === null) throw new Error(`${symbol} has no ${column} cell`);
  return cell;
};
const statusOf = (symbol: string): string => cellOf(symbol, "status").textContent ?? "";
/** The row's Status chip (CMP-239): `data-level` is "subtle" from T1, "strong" from T2. */
const chipOf = (symbol: string): Element | null =>
  cellOf(symbol, "status").querySelector('[data-cmp="CMP-239"]');
/** The Last cell's figure for a two-decimal symbol, as D9 draws it. */
const lastText = (price: number): string =>
  price.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });

/** jsdom has no layout: the grid's scroll region and rows measured as at the 784 px reference, 15 rows in view. */
function fakeLayout(rows: number) {
  const region = document.querySelector<HTMLElement>(".cv-table__region");
  if (region === null) throw new Error("no scroll region");
  let scrollTop = 0;
  Object.defineProperty(region, "scrollTop", { configurable: true, get: () => scrollTop });
  Object.defineProperty(region, "clientHeight", { configurable: true, get: () => 360 });
  const rect = (top: number, height: number) => new DOMRect(0, top, 784, height);
  const layout = vi
    .spyOn(HTMLElement.prototype, "getBoundingClientRect")
    .mockImplementation(function (this: HTMLElement) {
      if (this.tagName === "TBODY") return rect(24 - scrollTop, 24 * rows);
      if (this.tagName === "THEAD" || this.tagName === "TR") return rect(0, 24);
      return rect(0, 0);
    });
  let restored = false;
  // Once only: vi's restore puts the original back over whatever is there, the next test's spy included.
  const restore = (): void => {
    if (restored) return;
    restored = true;
    layout.mockRestore();
  };
  undo.push(restore);
  return {
    /** Scrolls the region so that `row` is the first in view. */
    scrollTo(row: number): void {
      scrollTop = row * 24;
      fireEvent.scroll(region);
    },
    restore,
  };
}

beforeEach(() => {
  running = new AbortController();
  vi.useFakeTimers({ now: T0, shouldAdvanceTime: false });
  apiFetch.mockReset();
  apiFetch.mockImplementation(async () => new Response(null, { status: 404 }));
  transport = new FakeTransport();
  hub = createTickerHub(transport);
  ws = fakeWs();
  act(() => setActiveClient(ws.handle));
  said = [];
});

afterEach(async () => {
  // A test past its timeout is still running. Its next step throws; the step in flight runs out (its clock emptied) and
  // closes its `act` here, before the next test opens one. Its spy is restored here too.
  running.abort();
  if (stepping !== null) {
    vi.clearAllTimers();
    await stepping.catch(() => undefined);
  }
  for (const restore of undo.splice(0)) restore();
  observer?.disconnect();
  hub.dispose();
  act(() => setActiveClient(null));
  clearAnnouncements();
  document.documentElement.removeAttribute("data-theme");
  vi.useRealTimers();
});

describe("Scenario 1: live columns from one batched subscription", () => {
  it("one batched ticker subscription carries Majors' 12 symbols", async () => {
    mount([MAJORS], MAJORS);
    await flush();
    expect(transport.opened).toHaveLength(1);
    expect([...(transport.opened[0]?.symbols ?? [])].sort()).toEqual([...MAJORS_SYMBOLS].sort());
  });

  it("the grid is role=grid, every header and cell readable by name; the golden replays into D9's formats", async () => {
    mount([MAJORS], MAJORS);
    await flush();
    const table = screen.getByRole("grid", { name: "Watchlist Majors, 12 symbols, manual order" });
    expect(table).toHaveAttribute("aria-rowcount", "13");
    for (const name of ["Symbol", "Last", "24h %", "Turnover USDT", "Funding %", "Funding in"])
      expect(
        within(table).getByRole("columnheader", { name: new RegExp(`^${name}`) }),
      ).toBeTruthy();
    for (const name of ["OI Δ 24h %", "Spread bps", "Rec", "Status"])
      expect(
        within(table).getByRole("columnheader", { name: new RegExp(`^${name}`) }),
      ).toBeTruthy();
    transport.current?.push(snapOf([streamItem(0), restItem("ETHUSDT"), restItem("SOLUSDT")]));
    await flush(FLUSH_MS);
    expect(cellOf("BTCUSDT", "last")).toHaveTextContent("82,751.20");
    expect(cellOf("ETHUSDT", "last")).toHaveTextContent("2,340.39");
    expect(cellOf("SOLUSDT", "last")).toHaveTextContent("101.630");
    expect(cellOf("BTCUSDT", "chg_24h_pct")).toHaveTextContent("+1.23%");
    expect(cellOf("BTCUSDT", "turnover_24h")).toHaveTextContent("3,412,632,305 USDT");
    // a row with no capture is initialising: "—", named, never an invented value
    expect(cellOf("XRPUSDT", "last")).toHaveTextContent("no value yet");
    for (const cell of within(table).getAllByRole("gridcell"))
      if (
        cell.getAttribute("data-column") !== "rec" &&
        cell.getAttribute("data-column") !== "status"
      )
        expect((cell.textContent ?? "").trim()).not.toBe("");
  });

  it(
    "coalesces Last however fast it moves, a repaint a slot (4.3 Hz at most over a run), and announces no tick",
    { timeout: 30_000 },
    async () => {
      mount([MAJORS], MAJORS);
      await flush();
      // Last moves on every frame, ten times a second for 3 s: three recorded items, each its own last price, in turn
      const cycle = [streamItem(3), streamItem(4), streamItem(19)];
      expect(new Set(cycle.map((item) => item.last_price)).size).toBe(3);
      const begin = Date.now();
      const frames = Array.from({ length: 30 }, (_, i) => {
        const item = cycle[i % cycle.length] ?? streamItem(0);
        return { at: begin + i * 100, frame: i === 0 ? snapOf([item]) : deltaOf([item]) };
      });
      const last = cellOf("BTCUSDT", "last"); // the row keeps its cells: read the figure as it changes
      const changes: number[] = [];
      let shown = last.textContent ?? "";
      await play(frames, begin + 3_000 + FLUSH_MS + FRAME_MS, () => {
        const text = last.textContent ?? "";
        if (text !== shown) changes.push(Date.now());
        shown = text;
      });
      expect(changes.length).toBeGreaterThanOrEqual(4); // the moves do reach the screen
      // after the snapshot's repaint (it takes no slot), one a slot, the slots a frame shorter than the server's 250 ms
      // with one in hand: any k of them span at least k − 1 slots (two in any slot, 4.3 Hz at most over a run)
      const moves = changes.slice(1);
      for (let i = 0; i < moves.length; i += 1)
        for (let j = i + 1; j < moves.length; j += 1)
          expect((moves[j] ?? 0) - (moves[i] ?? 0)).toBeGreaterThanOrEqual(
            (j - i - 1) * (FLUSH_MS - FRAME_MS),
          );
      expect(moves.length).toBeLessThan(frames.length - 1); // ten a second are coalesced
      expect(last).toHaveTextContent(lastText(Number(streamItem(19).last_price)));
      expect(said).toEqual([]);
    },
  );
});

describe("message to pixels (E08-D07 D32: under 100 ms p95)", () => {
  /**
   * The CV server's frames of the recording (its one 250 ms window), four times over (44 messages, 11 s) from `from`,
   * each lap a lap later in time (its items' `ts_ms` with it): the snapshot, then its deltas, the first `gap` ms after
   * it (the deltas keep the topic's own window, so a `sub`'s snapshot may come at any point of one), then one a window.
   */
  function serverMessages(from: number, gap: number) {
    const once = serverPaced(BTC_STREAM);
    const lap = (once.at(-1)?.at ?? 0) + FLUSH_MS;
    return [0, 1, 2, 3].flatMap((n) =>
      once.map(({ at, item }, i) => {
        const first = n === 0 && i === 0;
        const moved = { ...item, ts_ms: item.ts_ms + n * lap };
        return {
          at: from + (first ? 0 : at + n * lap + gap - FLUSH_MS),
          item: moved,
          frame: first ? snapOf([moved]) : deltaOf([moved]),
        };
      }),
    );
  }

  /** Plays `messages`; for each, when its value (or a later one) was on screen, less when it arrived. */
  async function toScreen(
    messages: readonly { at: number; item: { ts_ms: number }; frame: TopicFrame }[],
  ): Promise<number[]> {
    const last = cellOf("BTCUSDT", "last");
    const shownAt = messages.map((): number | undefined => undefined);
    let seen = Number.NaN;
    await play(messages, (messages.at(-1)?.at ?? Date.now()) + FLUSH_MS, () => {
      const entry = hub.store.get("BTCUSDT");
      if (entry === undefined || entry.values.tsMs === seen) return;
      seen = entry.values.tsMs;
      // the row reads its own store: what it holds is on screen in the same frame
      expect(last).toHaveTextContent(lastText(entry.values.lastPrice));
      messages.forEach(({ at, item }, i) => {
        if (shownAt[i] === undefined && at <= Date.now() && seen >= item.ts_ms)
          shownAt[i] = Date.now();
      });
    });
    return messages.map(({ at }, i) => (shownAt[i] ?? Number.POSITIVE_INFINITY) - at);
  }

  it.each([250, 20, 100, 140])(
    "the golden as the server sends it reaches the grid within a frame of each message, its first delta %i ms after the snapshot",
    { timeout: 30_000 },
    async (gap) => {
      mount([MAJORS], MAJORS);
      await flush();
      // the first message 10 ms after the subscription opened
      const latencies = await toScreen(serverMessages(Date.now() + 10, gap));
      expect(p95(latencies)).toBeLessThan(100);
      expect(Math.max(...latencies)).toBeLessThanOrEqual(FRAME_MS);
    },
  );

  it(
    "after a hidden spell (no animation frames, a read a second) each message reaches the grid within a frame again",
    { timeout: 30_000 },
    async () => {
      // A hidden document paints no animation frames: a frame asked for meanwhile waits until it shows again.
      let hidden = false;
      hub.dispose();
      hub = createTickerHub(transport, {
        ...SYSTEM_HUB_CLOCK,
        requestFrame(run) {
          const asked = { id: 0 };
          const fire = (): void => {
            if (hidden) asked.id = requestAnimationFrame(fire);
            else run();
          };
          asked.id = requestAnimationFrame(fire);
          return asked;
        },
        // `asked` is what requestFrame above returned; the cast only restores that type.
        cancelFrame: (asked) => cancelAnimationFrame((asked as { id: number }).id),
      });
      mount([MAJORS], MAJORS);
      await flush();
      const from = Date.now() + 10;
      // hidden from 2 s to 7.12 s: read at 3 s to 7 s, once a second; shown again between two of the server's frames
      const shownAgain = Date.now() + 7_120;
      setTimeout(() => {
        hidden = true;
      }, 2_000);
      setTimeout(() => {
        hidden = false;
      }, shownAgain - Date.now());
      const messages = serverMessages(from, FLUSH_MS);
      const latencies = await toScreen(messages);
      const after = latencies.filter((_, i) => (messages[i]?.at ?? 0) >= shownAgain);
      expect(after.length).toBeGreaterThan(10);
      expect(p95(after)).toBeLessThan(100);
      expect(Math.max(...after)).toBeLessThanOrEqual(FRAME_MS);
    },
  );
});

describe("Scenario 2: stale rows are never presented as live", () => {
  /** BTCUSDT and ETHUSDT keep ticking from the recording; SOLUSDT has its one snapshot item and no more. */
  async function runWithoutSol(ms: number): Promise<void> {
    for (let at = 0; at < ms; at += FLUSH_MS) {
      transport.current?.push(
        deltaOf([streamItem((at / FLUSH_MS) % BTC_STREAM.length), restItem("ETHUSDT")]),
      );
      await flush(FLUSH_MS);
    }
  }

  it("SOLUSDT with no frame for 6 s: tint, demoted text, kept values, a 'Stale 6s' chip, the state in words", async () => {
    mount([MAJORS], MAJORS);
    await flush();
    transport.current?.push(snapOf([streamItem(0), restItem("ETHUSDT"), restItem("SOLUSDT")]));
    await flush(FLUSH_MS);
    await runWithoutSol(6_750);
    const sol = rowOf("SOLUSDT");
    expect(sol).toHaveAttribute("data-freshness", "stale");
    expect(statusOf("SOLUSDT")).toContain("Stale 6s");
    expect(statusOf("SOLUSDT")).toContain("Stale, 6 seconds");
    expect(cellOf("SOLUSDT", "last")).toHaveTextContent("101.630");
    const chip = within(cellOf("SOLUSDT", "status")).getByText("Stale, 6 seconds").closest("[id]");
    expect(cellOf("SOLUSDT", "last").getAttribute("aria-describedby")).toContain(chip?.id ?? "?");
    expect(rowOf("BTCUSDT")).not.toHaveAttribute("data-freshness");
  });

  it("says one polite summary on entering the episode and one on leaving it", async () => {
    mount([MAJORS], MAJORS);
    await flush();
    transport.current?.push(snapOf([streamItem(0), restItem("ETHUSDT"), restItem("SOLUSDT")]));
    await flush(FLUSH_MS);
    await runWithoutSol(8_000);
    expect(said).toEqual(["1 watchlist symbol stale: SOLUSDT."]);
    transport.current?.push(deltaOf([restItem("SOLUSDT")]));
    await flush(FLUSH_MS);
    await runWithoutSol(2_000);
    expect(rowOf("SOLUSDT")).not.toHaveAttribute("data-freshness");
    for (let at = 0; at < 6_000; at += 1_000) {
      transport.current?.push(deltaOf([restItem("SOLUSDT")]));
      await runWithoutSol(1_000);
    }
    expect(said).toEqual(["1 watchlist symbol stale: SOLUSDT.", "Watchlist prices live again."]);
  });

  it("escalates at T2 = 15 s: 'Stale 15s' in the strong chip, the row kept in place (D1)", async () => {
    mount([MAJORS], MAJORS);
    await flush();
    transport.current?.push(snapOf([streamItem(0), restItem("ETHUSDT"), restItem("SOLUSDT")]));
    await flush(FLUSH_MS);
    await runWithoutSol(14_750);
    expect(statusOf("SOLUSDT")).toContain("Stale 14s");
    expect(chipOf("SOLUSDT")).toHaveAttribute("data-level", "subtle");
    await runWithoutSol(1_000);
    expect(statusOf("SOLUSDT")).toContain("Stale 15s");
    expect(statusOf("SOLUSDT")).toContain("Stale, 15 seconds");
    expect(chipOf("SOLUSDT")).toHaveAttribute("data-level", "strong");
    expect(within(grid()).getAllByRole("rowheader")[2]).toHaveTextContent("SOLUSDT");
  });

  it("a live row with no value yet reads '—' ('no value yet'), then 'No data yet' from T1 (D7)", async () => {
    mount([MAJORS], MAJORS);
    await flush();
    expect(transport.current?.symbols).toContain("XRPUSDT"); // live, and the recording has none of it
    await flush(4_000);
    expect(cellOf("XRPUSDT", "last")).toHaveTextContent("no value yet");
    expect(statusOf("XRPUSDT")).not.toContain("No data yet");
    await flush(1_000);
    expect(statusOf("XRPUSDT")).toContain("No data yet");
    expect(rowOf("XRPUSDT")).not.toHaveAttribute("data-freshness");
  });

  it("a server-flagged item reads 'Stale (server)' in T1's chip, then escalates at T2 like any row (D1)", async () => {
    mount([MAJORS], MAJORS);
    await flush();
    transport.current?.push(snapOf([streamItem(0), restItem("ETHUSDT")]));
    await flush(FLUSH_MS);
    transport.current?.push(deltaOf([{ ...restItem("ETHUSDT"), stale: true }]));
    await flush(1_000);
    expect(rowOf("ETHUSDT")).toHaveAttribute("data-freshness", "stale");
    expect(statusOf("ETHUSDT")).toContain("Stale (server)");
    expect(chipOf("ETHUSDT")).toHaveAttribute("data-level", "subtle");
    expect(cellOf("ETHUSDT", "last")).toHaveTextContent("2,340.39"); // the last values, kept
    await flush(15_000);
    expect(statusOf("ETHUSDT")).toContain("Stale (server)");
    expect(chipOf("ETHUSDT")).toHaveAttribute("data-level", "strong");
  });
});

describe("Scenario 3: Disconnected is a panel status, not a frozen price", () => {
  it("reads 'Disconnected — last data 00:12 ago', demotes every row, says nothing and blocks no control", async () => {
    const { replace } = mount([MAJORS], MAJORS);
    await flush();
    transport.current?.push(snapOf([streamItem(0), restItem("ETHUSDT"), restItem("SOLUSDT")]));
    await flush(FLUSH_MS);
    const lastData = Date.now();
    act(() =>
      ws.set({
        transport: "reconnecting",
        link: { kind: "reconnecting", attempt: 1, nextAttemptAtMs: lastData + 2_000 },
        outage: { sinceMs: lastData, lastDataMs: lastData },
      }),
    );
    await flush(13_000 - FLUSH_MS);
    const status = screen.getByText("Disconnected — last data 00:12 ago");
    expect(status.closest("[aria-live]")).toBeNull();
    expect(screen.getByRole("region", { name: "Watchlist Majors" })).toHaveAttribute(
      "data-cv-feed",
      "disconnected",
    );
    expect(document.body.textContent).not.toMatch(/Stale \d+s/);
    expect(cellOf("BTCUSDT", "last")).toHaveTextContent("82,751.20");
    expect(said).toEqual([]);
    for (const name of [/^Add symbol/, /^Columns/, /^Sort:/])
      expect(screen.getByRole("button", { name })).not.toHaveAttribute("aria-disabled");
    act(() => cellOf("BTCUSDT", "last").focus());
    fireEvent.keyDown(cellOf("BTCUSDT", "last"), { key: "Delete" });
    await flush();
    expect(replace).toHaveBeenCalledOnce();
    expect(screen.queryByRole("rowheader", { name: /^BTCUSDT/ })).toBeNull();
  });

  it("holds the status through the reconnect until the ticker snapshot after it arrives", async () => {
    mount([MAJORS], MAJORS);
    await flush();
    transport.current?.push(snapOf([streamItem(0)]));
    await flush(FLUSH_MS);
    act(() =>
      ws.set({
        transport: "reconnecting",
        outage: { sinceMs: Date.now(), lastDataMs: Date.now() },
      }),
    );
    await flush(3_000);
    act(() => ws.set({ transport: "connected", link: { kind: "up" }, outage: null }));
    await flush(1_000);
    expect(screen.getByText(/^Disconnected — last data/)).toBeInTheDocument();
    transport.current?.push(snapOf([streamItem(1)]));
    await flush(1_000);
    expect(screen.queryByText(/^Disconnected/)).toBeNull();
  });
});

describe("Scenario 4: the 40-symbol cap and the live window hold", () => {
  it("120 symbols with another pane holding one: 39 live, the rest '—' and 'Not live', '120 symbols · 39 live'", async () => {
    hub.claim("chart", ["XRPUSDT"]);
    mount([ALTS], ALTS);
    await flush(2_000); // the other pane's subscription drew first: changes go 2 s apart
    const held = transport.current?.symbols ?? [];
    expect(held).toHaveLength(40);
    expect(held.filter((s) => ALTS.symbols.includes(s))).toEqual(ALTS.symbols.slice(0, 39));
    expect(screen.getByText("120 symbols · 39 live")).toBeInTheDocument();
    expect(statusOf("A039USDT")).toContain("Not live");
    expect(cellOf("A039USDT", "last")).toHaveTextContent("not live");
    expect(statusOf("A038USDT")).not.toContain("Not live");
    expect(grid()).toHaveAttribute("aria-rowcount", "121");
  });

  it(
    "starts no more than 4 window moves in any 60 s, however the view scrolls",
    { timeout: 60_000 },
    async () => {
      // 60 symbols, the most drawn without windowing the rows, and the symbol column alone (the status one always
      // shows): each scroll redraws every row, the test's whole cost, and no row or cell bears on the window.
      const long = {
        ...list("Long", ALTS_SYMBOLS.slice(0, 60), "77777777-7777-4777-8777-777777777777"),
        columns: ["symbol"],
      };
      mount([long], long);
      await flush();
      const layout = fakeLayout(60);
      try {
        // A scroll every 1.5 s for 90 s, to a row near the top (0 to 12) and one near the bottom (26 to 44) in turn,
        // each showing rows the window around the last one lacks, each settling past 300 ms: each asks for a move, far
        // more than may start.
        for (let step = 0; step < 60; step += 1) {
          const row = step % 2 === 0 ? step % 13 : 45 - (step % 20);
          await run(1_500, () => layout.scrollTo(row));
        }
        await run(60_000);
      } finally {
        layout.restore();
      }
      expect(transport.opened.length).toBeGreaterThan(1);
      for (const channel of transport.opened)
        expect(transport.drawsWithin(channel.openedAt)).toBeLessThanOrEqual(4);
    },
  );

  it(
    "moves the window 300 ms after scrolling settles, never while it goes on",
    { timeout: 60_000 },
    async () => {
      mount([ALTS], ALTS);
      await flush();
      expect(transport.opened).toHaveLength(1); // rows 0 to 39
      const layout = fakeLayout(120);
      try {
        await flush(2_500); // the share would start a move now: changes go 2 s apart
        // a scroll every 100 ms for 2 s, back and forth past the window, never resting 300 ms
        for (let step = 0; step < 20; step += 1) {
          layout.scrollTo(step % 2 === 0 ? 60 : 90);
          await flush(100);
        }
        expect(transport.opened).toHaveLength(1);
        // 300 ms after the last scroll (DJ), not a millisecond before; the loop's last step waited 100 of them
        await flush(300 - 100 - 1);
        expect(transport.opened).toHaveLength(1);
        await flush(1);
        expect(transport.opened).toHaveLength(2);
        // the window around the rows in view when it settled: 90 to 103
        expect(transport.current?.symbols).toEqual(
          expect.arrayContaining(ALTS.symbols.slice(90, 104)),
        );
      } finally {
        layout.restore();
      }
    },
  );

  it("at 200 symbols the add control is T2 with the cap's words before any attempt", async () => {
    mount([BIG], BIG);
    await flush();
    // G-T2.1d: the lock, named "Not available", leads the full label
    const add = screen.getByRole("button", { name: "Not available Add symbol" });
    expect(add).toHaveAttribute("aria-disabled", "true");
    const reason = document.getElementById(add.getAttribute("aria-describedby") ?? "?");
    expect(reason).toHaveTextContent("Watching 200 symbols — remove some to add more");
    fireEvent.click(add);
    await flush();
    expect(screen.queryByRole("dialog", { name: "Add to Big" })).toBeNull();
    expect(said).toEqual(["Watching 200 symbols — remove some to add more"]);
    expect(screen.getByText("200 / 200 symbols · 40 live")).toBeInTheDocument();
  });
});

describe("keyboard paths", () => {
  it("Enter activates a row through the sync-group port; the row becomes current", async () => {
    const setSymbol = vi.fn();
    mount([MAJORS], MAJORS, { syncGroup: { name: null, setSymbol } });
    await flush();
    act(() => cellOf("ETHUSDT", "last").focus());
    fireEvent.keyDown(cellOf("ETHUSDT", "last"), { key: "Enter" });
    expect(setSymbol).toHaveBeenCalledWith("ETHUSDT");
    expect(rowOf("ETHUSDT")).toHaveAttribute("aria-current", "true");
  });

  it("Alt+↓ moves the row in manual order, says the new position once and saves the list", async () => {
    const { replace } = mount([MAJORS], MAJORS);
    await flush();
    act(() => cellOf("BTCUSDT", "last").focus());
    fireEvent.keyDown(cellOf("BTCUSDT", "last"), { key: "ArrowDown", altKey: true });
    await flush();
    expect(said).toEqual(["BTCUSDT moved to position 2 of 12."]);
    expect(replace.mock.calls[0]?.[1].symbols.slice(0, 2)).toEqual(["ETHUSDT", "BTCUSDT"]);
  });

  it("Alt+↑ on the first row is T2: nothing moves, 'Already first.' is said once", async () => {
    const { replace } = mount([MAJORS], MAJORS);
    await flush();
    act(() => cellOf("BTCUSDT", "last").focus());
    fireEvent.keyDown(cellOf("BTCUSDT", "last"), { key: "ArrowUp", altKey: true });
    await flush();
    expect(replace).not.toHaveBeenCalled();
    expect(said).toEqual(["Already first."]);
  });

  it("Del removes the row with Undo in the footer; Undo restores it in place", async () => {
    const { replace } = mount([MAJORS], MAJORS);
    await flush();
    act(() => cellOf("SOLUSDT", "last").focus());
    fireEvent.keyDown(cellOf("SOLUSDT", "last"), { key: "Delete" });
    await flush();
    expect(said).toEqual(["Removed SOLUSDT. Undo is in the footer."]);
    expect(screen.queryByRole("rowheader", { name: /^SOLUSDT/ })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Undo" }));
    await flush();
    expect(within(grid()).getAllByRole("rowheader")[2]).toHaveTextContent("SOLUSDT");
    expect(replace).toHaveBeenCalledTimes(2);
    expect(replace.mock.calls[1]?.[1].symbols).toEqual(MAJORS_SYMBOLS);
  });

  it("Ctrl+F focuses the filter; typing filters the rows; Esc clears it and returns to the grid", async () => {
    mount([MAJORS], MAJORS);
    await flush();
    act(() => cellOf("BTCUSDT", "last").focus());
    fireEvent.keyDown(cellOf("BTCUSDT", "last"), { key: "f", ctrlKey: true });
    const filter = screen.getByRole("searchbox", { name: "Filter symbols" });
    expect(document.activeElement).toBe(filter);
    fireEvent.change(filter, { target: { value: "us" } });
    fireEvent.change(filter, { target: { value: "eth" } });
    await flush(300);
    expect(
      within(grid())
        .getAllByRole("rowheader")
        .map((h) => h.textContent),
    ).toEqual(["ETHUSDT"]);
    expect(said).toEqual(["Showing 1 of 12 symbols"]);
    fireEvent.keyDown(filter, { key: "Escape" });
    fireEvent.keyDown(filter, { key: "Escape" });
    expect(within(grid()).getAllByRole("rowheader")).toHaveLength(12);
    expect(grid().contains(document.activeElement)).toBe(true);
  });

  it("a delisted row is struck with its merged cell, is not subscribed, and refuses activation with its reason", async () => {
    const setSymbol = vi.fn();
    mount([DELISTED], DELISTED, { syncGroup: { name: null, setSymbol } });
    await flush();
    expect(rowOf("LUNAUSDT")).toHaveAttribute("data-row-state", "delisted");
    expect(rowOf("LUNAUSDT")).toHaveTextContent("Delisted by the exchange");
    expect(transport.current?.symbols).toEqual(["BTCUSDT"]);
    act(() => cellOf("LUNAUSDT", "symbol").focus());
    fireEvent.keyDown(cellOf("LUNAUSDT", "symbol"), { key: "Enter" });
    await flush();
    expect(setSymbol).not.toHaveBeenCalled();
    expect(said).toEqual(["Delisted by the exchange"]);
  });
});

describe("the focused row's Last under SCR-117's price announcements (E08-D12 SR-31, BG-02)", () => {
  /** BTCUSDT's Last moving on every frame, ten a second for `ms` (three recorded prices in turn), from a snapshot. */
  const moving = (ms: number) => {
    const cycle = [streamItem(3), streamItem(4), streamItem(19)];
    const begin = Date.now();
    return {
      shown: new Set(cycle.map((item) => lastText(Number(item.last_price)))),
      frames: Array.from({ length: ms / 100 }, (_, i) => {
        const item = cycle[i % cycle.length] ?? streamItem(0);
        return { at: begin + i * 100, frame: i === 0 ? snapOf([item]) : deltaOf([item]) };
      }),
      until: begin + ms,
    };
  };
  /** What the polite region says while `frames` play, each with when it was said. */
  async function hear(run: ReturnType<typeof moving>) {
    const heard: { readonly at: number; readonly text: string }[] = [];
    await play(run.frames, run.until, () => {
      if (said.length > heard.length)
        for (const text of said.slice(heard.length)) heard.push({ at: Date.now(), text });
    });
    return heard;
  }

  it("'Always': only the focused row's Last is said, the value its cell shows, at most once per 2 s", async () => {
    mount([MAJORS], MAJORS, { pricePrefs: { announce_prices: "always", verbosity: "normal" } });
    await flush();
    act(() => cellOf("BTCUSDT", "last").focus());
    const run = moving(9_000);
    const heard = await hear(run);
    expect(heard.length).toBeGreaterThanOrEqual(3);
    for (const { text } of heard) expect(run.shown).toContain(text);
    for (let i = 1; i < heard.length; i += 1)
      expect((heard[i]?.at ?? 0) - (heard[i - 1]?.at ?? 0)).toBeGreaterThanOrEqual(
        LAST_CADENCE_MS - FAKE_FRAME_MS,
      );
    // focus off the grid: nothing more is said, however the Last moves
    act(() => screen.getByRole("searchbox", { name: "Filter symbols" }).focus());
    said.length = 0;
    expect(await hear(moving(5_000))).toEqual([]);
  });

  it("'Off', and the default 'On significant change' (no provider here), say no Last", async () => {
    for (const pricePrefs of [
      { announce_prices: "off", verbosity: "normal" } as const,
      undefined,
    ]) {
      said.length = 0;
      const view = mount([MAJORS], MAJORS, pricePrefs === undefined ? {} : { pricePrefs });
      await flush();
      act(() => cellOf("BTCUSDT", "last").focus());
      expect(await hear(moving(5_000))).toEqual([]);
      view.unmount();
      observer.disconnect();
    }
  });
});

describe("the add popover (E08-D07 D36)", () => {
  it("adds the active result, stays open for the next and says each outcome; an on-list symbol adds nothing", async () => {
    const { replace } = mount(
      [list("Short", ["BTCUSDT"], "55555555-5555-4555-8555-555555555555")],
      list("Short", ["BTCUSDT"], "55555555-5555-4555-8555-555555555555"),
    );
    await flush();
    fireEvent.click(screen.getByRole("button", { name: /^Add symbol/ }));
    await flush();
    const dialog = screen.getByRole("dialog", { name: "Add to Short" });
    const input = within(dialog).getByRole("combobox");
    fireEvent.change(input, { target: { value: "ethusdt" } });
    await flush(300);
    fireEvent.keyDown(input, { key: "ArrowDown" });
    fireEvent.keyDown(input, { key: "Enter" });
    await flush();
    expect(within(dialog).getByText("Added ETHUSDT to Short.")).toBeInTheDocument();
    expect(screen.getByRole("dialog", { name: "Add to Short" })).toBeInTheDocument();
    fireEvent.change(input, { target: { value: "btcusdt" } });
    await flush(300);
    fireEvent.keyDown(input, { key: "ArrowDown" });
    fireEvent.keyDown(input, { key: "Enter" });
    await flush();
    expect(within(dialog).getByText("BTCUSDT is already on Short.")).toBeInTheDocument();
    // the adds of one opening change the live window once, when it closes
    fireEvent.keyDown(input, { key: "Escape" });
    await flush(2_000);
    expect(replace).toHaveBeenCalledOnce();
    expect(transport.current?.symbols).toEqual(["BTCUSDT", "ETHUSDT"]);
  });
});

describe("axe and teardown", () => {
  it.each(["dark", "light"])(
    "axe finds no serious or critical issue in the %s theme",
    async (theme) => {
      document.documentElement.setAttribute("data-theme", theme);
      mount([MAJORS, ALTS], MAJORS);
      await flush();
      transport.current?.push(snapOf([streamItem(0), restItem("ETHUSDT"), restItem("SOLUSDT")]));
      await flush(7_000);
      vi.useRealTimers();
      const { violations } = await axe.run(document.body, {
        rules: { "color-contrast": { enabled: false } }, // jsdom has no layout: CI's a11y gate measures contrast
      });
      expect(violations.filter((v) => v.impact === "serious" || v.impact === "critical")).toEqual(
        [],
      );
    },
  );

  it("unmounting lets every subscription go: the pane's claim, the ticker subscription, every timer", async () => {
    const view = mount([MAJORS], MAJORS);
    await flush();
    transport.current?.push(snapOf([streamItem(0)]));
    await flush(FLUSH_MS);
    view.unmount();
    expect(transport.opened.every((c) => c.released)).toBe(true);
    expect(hub.budgetFor("other", MAJORS_SYMBOLS)).toBe(40);
    hub.dispose();
    observer.disconnect();
    expect(vi.getTimerCount()).toBe(0);
  });
});

describe("sort, held while the grid is in use (E08-D07 D5)", () => {
  const order = (): string[] =>
    within(grid())
      .getAllByRole("rowheader")
      .map((header) => header.textContent ?? "");

  it("re-ranks a live sort; held, it shows '· paused' and 'Re-sort', which re-ranks once", async () => {
    mount([MAJORS], MAJORS);
    await flush();
    transport.current?.push(snapOf([streamItem(0), restItem("ETHUSDT"), restItem("SOLUSDT")]));
    await flush(FLUSH_MS);
    const header = within(grid()).getByRole("button", { name: "24h %" });
    fireEvent.click(header);
    fireEvent.click(header);
    await flush();
    expect(order().slice(0, 3)).toEqual(["BTCUSDT", "SOLUSDT", "ETHUSDT"]);
    expect(grid()).toHaveAccessibleName(
      "Watchlist Majors, 12 symbols, sorted by 24h %, descending",
    );
    act(() => cellOf("XRPUSDT", "last").focus());
    // the recorded REST item of BTCUSDT: a smaller 24h change, so its place in the order moves
    transport.current?.push(deltaOf([restItem("BTCUSDT")]));
    await flush(2_000);
    expect(order().slice(0, 3)).toEqual(["BTCUSDT", "SOLUSDT", "ETHUSDT"]);
    expect(screen.getByRole("button", { name: /^Sort: 24h % · paused/ })).toBeInTheDocument();
    const resort = screen.getByRole("button", { name: "Re-sort" });
    act(() => resort.focus());
    fireEvent.click(resort);
    await flush();
    expect(order().slice(0, 3)).toEqual(["SOLUSDT", "BTCUSDT", "ETHUSDT"]);
    expect(screen.queryByRole("button", { name: "Re-sort" })).toBeNull();
    // Re-sort goes with the hold it answered: focus moves to Sort, never to the page (WCAG 2.4.3)
    expect(document.activeElement).toBe(screen.getByRole("button", { name: /^Sort: 24h %/ }));
  });

  it("a list past the live budget has no live sort: the headers are T2 with one footer note", async () => {
    mount([ALTS], ALTS);
    await flush();
    const last = within(grid()).getByRole("button", { name: /Last/ });
    expect(last).toHaveAttribute("aria-disabled", "true");
    const note = document.getElementById(last.getAttribute("aria-describedby") ?? "?");
    expect(note).toHaveTextContent("Live sort needs every symbol live.");
    fireEvent.click(last);
    await flush();
    expect(said).toEqual(["Live sort needs every symbol live."]);
    expect(within(grid()).getAllByRole("rowheader")[0]).toHaveTextContent("A000USDT");
  });
});

describe("the row menu (CMP-041; E08-D07 §4.2)", () => {
  it("Shift+F10 opens the row's menu; Move up is T2 at the top; Move down moves and says so", async () => {
    const { replace } = mount([MAJORS], MAJORS);
    await flush();
    act(() => cellOf("BTCUSDT", "last").focus());
    fireEvent.keyDown(cellOf("BTCUSDT", "last"), { key: "F10", shiftKey: true });
    await flush();
    const menu = screen.getByRole("menu", { name: "Actions for BTCUSDT" });
    const items = within(menu).getAllByRole("menuitem");
    expect(items.map((item) => item.textContent)).toEqual([
      "Copy symbol",
      expect.stringContaining("Move up"),
      "Move down",
      "Remove from Majors",
    ]);
    expect(within(menu).getByRole("menuitem", { name: /Move up/ })).toHaveAttribute(
      "aria-disabled",
      "true",
    );
    fireEvent.click(within(menu).getByRole("menuitem", { name: "Move down" }));
    await flush();
    expect(said).toEqual(["BTCUSDT moved to position 2 of 12."]);
    expect(replace).toHaveBeenCalledOnce();
  });
});

describe("columns (CMP-056)", () => {
  it("showing an optional column saves the list's columns", async () => {
    const events: unknown[] = [];
    const listen = (event: Event) => events.push((event as CustomEvent).detail);
    window.addEventListener("cv:analytics", listen);
    const { replace } = mount([MAJORS], MAJORS);
    await flush();
    fireEvent.click(screen.getByRole("button", { name: "Columns" }));
    await flush();
    fireEvent.click(screen.getByRole("menuitemcheckbox", { name: "Mark" }));
    await flush();
    window.removeEventListener("cv:analytics", listen);
    expect(replace.mock.calls[0]?.[1].columns.at(-1)).toBe("mark_price");
    expect(events).toContainEqual({
      name: "watchlist.column_changed",
      watchlist_id: MAJORS.id,
      column: "mark_price",
      visible: true,
    });
  });
});

describe("read-only: no workspaces:write (E08-D07 D13, §4.2)", () => {
  it("one notice; every write T2 pointing at it; a refused key says the reason and changes nothing", async () => {
    const { api, replace } = fakeApi([MAJORS]);
    render(
      <>
        <WatchlistPanel
          listId={MAJORS.id}
          paneId="r111"
          api={api}
          hub={hub}
          instruments={fakeIndex()}
          paneSettings={createLocalPaneSettings()}
          readOnly
        />
        <ShellAnnouncer />
      </>,
    );
    const polite = document.querySelector('[aria-live="polite"]');
    observer = new MutationObserver(() => {
      const text = polite?.textContent ?? "";
      if (text !== "" && said.at(-1) !== text) said.push(text);
    });
    if (polite !== null) observer.observe(polite, { childList: true, subtree: true });
    await flush();
    const notice = screen.getByText("Read-only — your role can't save workspaces.");
    const add = screen.getByRole("button", { name: "Not available Add symbol" });
    expect(add).toHaveAttribute("aria-describedby", notice.id);
    act(() => cellOf("SOLUSDT", "last").focus());
    fireEvent.keyDown(cellOf("SOLUSDT", "last"), { key: "Delete" });
    await flush();
    expect(rowOf("SOLUSDT")).toBeInTheDocument();
    expect(said).toEqual(["Your role can't save workspaces."]);
    expect(replace).not.toHaveBeenCalled();
  });
});

describe("saved edits reach the panel (C-2.12: the next save carries the server's version)", () => {
  it("edit, save, switch to another list and back: the saved list shows, and the next edit saves, no 412", async () => {
    const { api, replace } = versionedApi([MAJORS, ALTS]);
    const index = fakeIndex();
    const settings = createLocalPaneSettings();
    const page = (listId: string) => (
      <>
        <WatchlistPanel
          listId={listId}
          paneId="r111"
          api={api}
          hub={hub}
          instruments={index}
          paneSettings={settings}
        />
        <ShellAnnouncer />
      </>
    );
    const view = render(page(MAJORS.id));
    hearPolite();
    await flush();
    act(() => cellOf("SOLUSDT", "last").focus());
    fireEvent.keyDown(cellOf("SOLUSDT", "last"), { key: "Delete" });
    await flush();
    view.rerender(page(ALTS.id));
    await flush();
    // the other list's page already counts the saved list
    expect(screen.getByRole("tab", { name: "Majors, 11 symbols" })).toBeInTheDocument();
    view.rerender(page(MAJORS.id));
    await flush();
    expect(screen.queryByRole("rowheader", { name: /^SOLUSDT/ })).toBeNull();
    expect(screen.getByRole("tab", { name: "Majors, 11 symbols" })).toBeInTheDocument();
    act(() => cellOf("XRPUSDT", "last").focus());
    fireEvent.keyDown(cellOf("XRPUSDT", "last"), { key: "Delete" });
    await flush();
    expect(replace).toHaveBeenCalledTimes(2);
    expect(replace.mock.calls[1]?.[0].version).toBe(2);
    await expect(replace.mock.results[1]?.value).resolves.toMatchObject({ kind: "saved" });
    expect(said).not.toContain("Majors changed in another window.");
  });
});

describe("panel states (E08-D07 §4.2)", () => {
  it("a failed load shows the error with Retry, which reads the lists again", async () => {
    const { api } = fakeApi([MAJORS]);
    const list = vi.fn<WatchlistApi["list"]>(async () => Promise.reject(new Error("503")));
    render(
      <WatchlistPanel
        listId={MAJORS.id}
        paneId="r111"
        api={{ ...api, list }}
        hub={hub}
        instruments={fakeIndex()}
        paneSettings={createLocalPaneSettings()}
      />,
    );
    await flush();
    expect(screen.getByText("Watchlists could not be loaded.")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    await flush();
    expect(list).toHaveBeenCalledTimes(2);
  });

  it("no list: 'No watchlists yet' and 'Create watchlist', which opens the manager's path", async () => {
    const onManage = vi.fn();
    mount([], MAJORS, { onManage });
    await flush();
    expect(screen.getByRole("heading", { name: "No watchlists yet" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Create watchlist" }));
    expect(onManage).toHaveBeenCalledExactlyOnceWith({ kind: "create" });
  });

  it("an empty list: its own empty state, no subscription, and 'Add symbols to watch' opens the add", async () => {
    const empty = list("Majors", [], MAJORS.id);
    mount([empty], empty);
    await flush();
    expect(
      screen.getByRole("heading", { name: "No symbols on this watchlist" }),
    ).toBeInTheDocument();
    expect(screen.getByText("You haven't added any symbols to Majors yet.")).toBeInTheDocument();
    expect(transport.opened).toEqual([]);
    fireEvent.click(screen.getByRole("button", { name: "Add symbols to watch" }));
    await flush();
    expect(screen.getByRole("dialog", { name: "Add to Majors" })).toBeInTheDocument();
  });

  it("a failed save rolls back, says so once, and Retry sends the change again", async () => {
    const { replace } = mount([MAJORS], MAJORS);
    replace.mockResolvedValueOnce({ kind: "failed" });
    await flush();
    act(() => cellOf("SOLUSDT", "last").focus());
    fireEvent.keyDown(cellOf("SOLUSDT", "last"), { key: "Delete" });
    await flush();
    expect(rowOf("SOLUSDT")).toBeInTheDocument();
    expect(said.at(-1)).toBe("Could not save Majors. Your last change was undone.");
    const retry = screen.getByRole("button", { name: "Retry" });
    act(() => retry.focus());
    fireEvent.click(retry);
    await flush();
    expect(replace).toHaveBeenCalledTimes(2);
    expect(screen.queryByRole("rowheader", { name: /^SOLUSDT/ })).toBeNull();
    // Retry goes with the error it answered: focus moves to the grid's tab stop, never to the page
    expect(grid().contains(document.activeElement)).toBe(true);
    expect(document.activeElement).toHaveAttribute("tabindex", "0");
  });

  it("a conflict: 'Reload Majors' reads the list again in place, focus to the grid, the next save on its version", async () => {
    const { api, replace, list: reads, stored } = versionedApi([MAJORS]);
    mount([MAJORS], MAJORS, { api });
    await flush();
    // another window saved Majors first
    stored.set(MAJORS.id, {
      ...MAJORS,
      symbols: MAJORS.symbols.filter((s) => s !== "DOGEUSDT"),
      version: 2,
    });
    act(() => cellOf("SOLUSDT", "last").focus());
    fireEvent.keyDown(cellOf("SOLUSDT", "last"), { key: "Delete" });
    await flush();
    expect(said.at(-1)).toBe("Majors changed in another window.");
    const reload = screen.getByRole("button", { name: "Reload Majors" });
    act(() => reload.focus());
    fireEvent.click(reload);
    await flush();
    expect(reads).toHaveBeenCalledTimes(2);
    expect(screen.queryByRole("button", { name: "Reload Majors" })).toBeNull();
    expect(grid().contains(document.activeElement)).toBe(true);
    expect(document.activeElement).toHaveAttribute("tabindex", "0");
    // the other window's list shows, and the next save goes against its version
    expect(screen.queryByRole("rowheader", { name: /^DOGEUSDT/ })).toBeNull();
    expect(rowOf("SOLUSDT")).toBeInTheDocument();
    act(() => cellOf("SOLUSDT", "last").focus());
    fireEvent.keyDown(cellOf("SOLUSDT", "last"), { key: "Delete" });
    await flush();
    expect(replace.mock.calls.at(-1)?.[0].version).toBe(2);
    await expect(replace.mock.results.at(-1)?.value).resolves.toMatchObject({ kind: "saved" });
  });

  it("a refused sub: no symbol live, the paused notice in the header, said once", async () => {
    mount([MAJORS], MAJORS);
    await flush();
    transport.current?.revoke();
    await flush(FLUSH_MS);
    const panel = screen.getByRole("region", { name: "Watchlist Majors" });
    expect(
      within(panel).getByText("Live prices paused — retrying in 5 s", { selector: "p" }),
    ).toBeInTheDocument();
    expect(screen.getByText("12 symbols · 0 live")).toBeInTheDocument();
    // a row says why it is not live: the pause, not the 40-symbol budget
    expect(statusOf("BTCUSDT")).toContain("Not live");
    expect(statusOf("BTCUSDT")).toContain("Live prices paused");
    expect(statusOf("BTCUSDT")).not.toContain("At most 40");
    await flush(1_000);
    expect(said).toEqual(["Live prices paused — retrying in 5 s"]);
  });

  it("the paused notice counts down to the retry, and is said once", async () => {
    mount([MAJORS], MAJORS);
    await flush();
    transport.current?.revoke();
    await flush(FLUSH_MS);
    const panel = screen.getByRole("region", { name: "Watchlist Majors" });
    const notice = (s: number) =>
      within(panel).queryByText(`Live prices paused — retrying in ${s} s`, { selector: "p" });
    expect(notice(5)).toBeInTheDocument();
    await flush(2_000);
    expect(notice(3)).toBeInTheDocument();
    await flush(2_000);
    expect(notice(1)).toBeInTheDocument();
    expect(said).toEqual(["Live prices paused — retrying in 5 s"]);
  });

  it("a failed instrument index: CMP-027 with Retry, said once; the rows say why, never the 40-symbol reason", async () => {
    const reread = vi.fn();
    const failed = fakeIndex(
      { phase: "failed", entries: [], failure: { cause: "network" } },
      reread,
    );
    mount([MAJORS], MAJORS, { instruments: failed });
    await flush();
    expect(transport.opened).toEqual([]); // no symbol is known to trade: none is subscribed (23 §5.2)
    const error = document.querySelector('[data-cmp="CMP-027"]');
    if (!(error instanceof HTMLElement)) throw new Error("no CMP-027");
    expect(error).toHaveTextContent("Couldn't load the instrument list.");
    expect(document.querySelector('[aria-live="assertive"]')).toHaveTextContent(
      "Couldn't load the instrument list.",
    );
    expect(statusOf("BTCUSDT")).toContain("Not live");
    expect(statusOf("BTCUSDT")).toContain("Couldn't load the instrument list.");
    expect(document.body.textContent).not.toContain("At most 40");
    const retry = within(error).getByRole("button", { name: "Retry" });
    act(() => retry.focus());
    fireEvent.click(retry);
    expect(reread).toHaveBeenCalledOnce();
    expect(grid().contains(document.activeElement)).toBe(true);
  });

  it("no WS client: the panel reads Disconnected (D4) and no row claims the 40-symbol reason", async () => {
    mount([MAJORS], MAJORS, { hub: null });
    await flush();
    const panel = screen.getByRole("region", { name: "Watchlist Majors" });
    const status = within(panel).getByText("Disconnected", { selector: "p" });
    expect(panel).toHaveAttribute("data-cv-feed", "disconnected");
    expect(statusOf("BTCUSDT")).toContain("Not live");
    expect(cellOf("BTCUSDT", "last").getAttribute("aria-describedby")).toContain(status.id);
    expect(document.body.textContent).not.toContain("At most 40");
  });

  it("an id that is none of the lists tells the page", async () => {
    const onMissing = vi.fn();
    const { api } = fakeApi([MAJORS]);
    render(
      <WatchlistPanel
        listId="missing"
        paneId="r111"
        api={api}
        hub={hub}
        instruments={fakeIndex()}
        paneSettings={createLocalPaneSettings()}
        onMissing={onMissing}
      />,
    );
    await flush();
    expect(onMissing).toHaveBeenCalledOnce();
  });

  it("entering Disconnected reports data_confidence.state_entered once", async () => {
    const events: unknown[] = [];
    const listen = (event: Event) => events.push((event as CustomEvent).detail);
    window.addEventListener("cv:analytics", listen);
    mount([MAJORS], MAJORS);
    await flush();
    act(() => ws.set({ transport: "reconnecting", outage: { sinceMs: T0, lastDataMs: null } }));
    await flush(2_000);
    window.removeEventListener("cv:analytics", listen);
    expect(screen.getByText("Disconnected")).toBeInTheDocument();
    expect(events).toEqual([
      { name: "data_confidence.state_entered", surface: "SCR-100", state: "disconnected" },
    ]);
  });
});

describe("SCR-101's paths and lists (#4702 PR (c))", () => {
  it("the tab menu's Rename, Duplicate, Delete… and 'Manage watchlists…', and '+', open SCR-101 with their intent", async () => {
    const onManage = vi.fn<(intent: ManagerIntent) => void>();
    mount([MAJORS, ALTS], MAJORS, { onManage });
    await flush();
    const tab = screen.getByRole("tab", { name: "Majors, 12 symbols" });
    for (const [item, intent] of [
      ["Rename", { kind: "rename", listId: MAJORS.id }],
      ["Duplicate", { kind: "duplicate", listId: MAJORS.id }],
      ["Delete…", { kind: "delete", listId: MAJORS.id }],
      ["Manage watchlists…", { kind: "open", listId: MAJORS.id }],
    ] as const) {
      act(() => tab.focus());
      fireEvent.keyDown(tab, { key: "F10", shiftKey: true });
      await flush();
      fireEvent.click(screen.getByRole("menuitem", { name: item }));
      await flush();
      expect(onManage).toHaveBeenLastCalledWith(intent);
    }
    fireEvent.click(screen.getByRole("button", { name: "New watchlist" }));
    expect(onManage).toHaveBeenLastCalledWith({ kind: "create" });
  });

  it("the empty list's 'Import a list' links to SCR-101 on the list, and opens it in place asking for the import", async () => {
    const onManage = vi.fn<(intent: ManagerIntent) => void>();
    const empty = list("Majors", [], MAJORS.id);
    mount([empty], empty, { onManage });
    await flush();
    const link = screen.getByRole("link", { name: "Import a list" });
    expect(link).toHaveAttribute("href", `/watchlist/${MAJORS.id}?modal=watchlists`);
    expect(fireEvent.click(link)).toBe(false); // the page does not navigate
    expect(onManage).toHaveBeenCalledExactlyOnceWith({ kind: "import", listId: MAJORS.id });
    // a press asking for a new tab is the browser's
    fireEvent.click(link, { ctrlKey: true });
    expect(onManage).toHaveBeenCalledOnce();
  });

  it("the add popover's 'Paste several…' follows the input and opens SCR-101's paste on the list", async () => {
    const onManage = vi.fn<(intent: ManagerIntent) => void>();
    mount([MAJORS], MAJORS, { onManage });
    await flush();
    fireEvent.click(screen.getByRole("button", { name: /^Add symbol/ }));
    await flush();
    const popover = screen.getByRole("dialog", { name: "Add to Majors" });
    const paste = within(popover).getByRole("button", { name: "Paste several…" });
    expect(
      within(popover).getByRole("combobox").compareDocumentPosition(paste) &
        Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
    fireEvent.click(paste);
    await flush();
    expect(onManage).toHaveBeenCalledExactlyOnceWith({ kind: "paste", listId: MAJORS.id });
    expect(screen.queryByRole("dialog", { name: "Add to Majors" })).toBeNull();
  });

  it("a list SCR-101 saves reaches the panel: it shows, and the next edit saves against its version (no 412)", async () => {
    const { api, replace, stored } = versionedApi([MAJORS, ALTS]);
    const sync = createWatchlistSync();
    mount([MAJORS, ALTS], MAJORS, { api, sync });
    await flush();
    const saved = { ...MAJORS, symbols: [...MAJORS_SYMBOLS].reverse(), version: 2 };
    stored.set(MAJORS.id, saved);
    act(() => sync.publish({ kind: "stored", list: saved }));
    await flush();
    expect(within(grid()).getAllByRole("rowheader")[0]).toHaveTextContent("TONUSDT");
    act(() => cellOf("SOLUSDT", "last").focus());
    fireEvent.keyDown(cellOf("SOLUSDT", "last"), { key: "Delete" });
    await flush();
    expect(replace.mock.calls.at(-1)?.[0].version).toBe(2);
    await expect(replace.mock.results.at(-1)?.value).resolves.toMatchObject({ kind: "saved" });
    expect(said).not.toContain("Majors changed in another window.");
  });

  it("a list SCR-101 creates joins the tabs, an older version changes nothing, and its closing reads the lists again", async () => {
    const { api, list: reads, stored } = versionedApi([MAJORS]);
    const sync = createWatchlistSync();
    mount([MAJORS], MAJORS, { api, sync });
    await flush();
    const created = list("Breakouts", ["SOLUSDT"], "66666666-6666-4666-8666-666666666666");
    act(() => sync.publish({ kind: "stored", list: created }));
    act(() => sync.publish({ kind: "stored", list: { ...MAJORS, symbols: [], version: 1 } }));
    await flush();
    expect(screen.getByRole("tab", { name: "Breakouts, 1 symbol" })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Majors, 12 symbols" })).toBeInTheDocument();
    stored.delete(created.id);
    act(() => sync.publish({ kind: "reread" }));
    await flush();
    expect(reads).toHaveBeenCalledTimes(2);
    expect(screen.queryByRole("tab", { name: /^Breakouts/ })).toBeNull();
  });
});

describe("the Watchlist focus context (E08-D07 §6.2; #5335 A-5335-02, B-5335-03)", () => {
  afterEach(() => resetBindings());
  /** The toasts the window keymap raised (SCR-015's region, portalled): none for a key the panel handled. */
  const toasts = (): string =>
    screen.queryByRole("region", { name: "Notifications", hidden: true })?.textContent ?? "";

  it("the panel is the Watchlist context: Alt+↓ on a row moves it and says only the move, with no toast", async () => {
    render(<KeymapHost />);
    mount([MAJORS], MAJORS);
    await flush();
    expect(screen.getByRole("region", { name: "Watchlist Majors" })).toHaveAttribute(
      "data-keymap-context",
      "Watchlist",
    );
    act(() => cellOf("BTCUSDT", "last").focus());
    fireEvent.keyDown(cellOf("BTCUSDT", "last"), { key: "ArrowDown", altKey: true });
    await flush();
    expect(said).toEqual(["BTCUSDT moved to position 2 of 12."]);
    expect(toasts()).toBe("");
  });

  it("its keys are remappable: a remapped remove key removes, and the old one does nothing", async () => {
    render(<KeymapHost />);
    act(() => setBindings(new Map(getBindings()).set("watchlist.remove", "Backspace")));
    const { replace } = mount([MAJORS], MAJORS);
    await flush();
    act(() => cellOf("SOLUSDT", "last").focus());
    fireEvent.keyDown(cellOf("SOLUSDT", "last"), { key: "Delete" });
    await flush();
    expect(replace).not.toHaveBeenCalled();
    fireEvent.keyDown(cellOf("SOLUSDT", "last"), { key: "Backspace" });
    await flush();
    expect(said).toContain("Removed SOLUSDT. Undo is in the footer.");
    expect(replace).toHaveBeenCalledOnce();
    expect(toasts()).not.toContain("Watchlist view");
  });

  it("a row key pressed off a row says it needs one, naming the Watchlist view, never another view's command", async () => {
    render(<KeymapHost />);
    mount([MAJORS], MAJORS);
    await flush();
    const filter = screen.getByRole("searchbox", { name: "Filter symbols" });
    act(() => filter.focus());
    fireEvent.keyDown(filter, { key: "ArrowUp", altKey: true });
    await flush();
    expect(toasts()).toContain("Move row up is not available here (Watchlist view)");
    expect(toasts()).not.toContain("Rules");
  });
});

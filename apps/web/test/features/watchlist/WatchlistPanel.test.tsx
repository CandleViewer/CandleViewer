/**
 * E08-S08 (#4702): SCR-100 on R-111 (pre-ruling 1) — the four scenarios of the ticket against the derived CV
 * `ticker` golden (C-13.5), on fake timers, a fake transport under the real ticker hub, a fake instrument index and a
 * fake `/watchlists` API (no network). Plus the keyboard paths, axe in dark and light, and the teardown of every
 * subscription. The app's one announcer is rendered beside the panel: the panel owns no live region (E08-D07 D17).
 */
import { createRequire } from "node:module";
import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const { apiFetch } = vi.hoisted(() => ({
  apiFetch: vi.fn<(url: string, init?: RequestInit) => Promise<Response>>(),
}));
vi.mock("../../../src/lib/http/csrfFetch", () => ({ apiFetch }));

import { ShellAnnouncer, clearAnnouncements } from "../../../src/features/app-shell/announcer";
import type { IndexSnapshot } from "../../../src/features/symbol-search/instrumentIndex";
import { toEntry, type Instrument } from "../../../src/features/symbol-search/ranking";
import { WatchlistPanel } from "../../../src/features/watchlist/WatchlistPanel";
import type { Watchlist } from "../../../src/features/watchlist/listEdits";
import type { InstrumentSource } from "../../../src/features/watchlist/instruments";
import { createLocalPaneSettings, type SyncGroupPort } from "../../../src/features/watchlist/ports";
import {
  FLUSH_MS,
  createTickerHub,
  type TickerHub,
} from "../../../src/features/watchlist/ticker/tickerHub";
import type { WatchlistApi } from "../../../src/features/watchlist/watchlistApi";
import { setActiveClient } from "../../../src/lib/ws/client/activeClient";
import type { WsClientHandle } from "../../../src/lib/ws/client/createWsClient";
import { INITIAL_WS_STATE } from "../../../src/lib/ws/state/reducer";
import type { WsState } from "../../../src/lib/ws/state/types";
import { FakeTransport, deltaOf, restItem, snapOf, streamItem, BTC_STREAM } from "./support";

const axe = createRequire(createRequire(import.meta.url).resolve("@axe-core/playwright"))(
  "axe-core",
) as {
  run: (
    el: Element,
    o?: object,
  ) => Promise<{ violations: { id: string; impact?: string | null }[] }>;
};

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

function fakeIndex(): InstrumentSource {
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
  };
  return { subscribe: () => () => undefined, getSnapshot: () => snapshot, learn: () => undefined };
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

const flush = async (ms = 0): Promise<void> => {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(ms);
  });
};

function mount(
  lists: readonly Watchlist[],
  shown: Watchlist,
  extra: { syncGroup?: SyncGroupPort; onManage?: () => void } = {},
) {
  const { api, replace } = fakeApi(lists);
  const view = render(
    <>
      <WatchlistPanel
        listId={shown.id}
        paneId="r111"
        api={api}
        hub={hub}
        instruments={fakeIndex()}
        paneSettings={createLocalPaneSettings()}
        {...extra}
      />
      <ShellAnnouncer />
    </>,
  );
  const polite = document.querySelector('[aria-live="polite"]');
  if (polite === null) throw new Error("the app's polite region is missing");
  observer = new MutationObserver(() => {
    const text = polite.textContent ?? "";
    if (text !== "" && said.at(-1) !== text) said.push(text);
  });
  observer.observe(polite, { childList: true, subtree: true, characterData: true });
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

beforeEach(() => {
  vi.useFakeTimers({ now: T0, shouldAdvanceTime: false });
  apiFetch.mockReset();
  apiFetch.mockImplementation(async () => new Response(null, { status: 404 }));
  transport = new FakeTransport();
  hub = createTickerHub(transport);
  ws = fakeWs();
  act(() => setActiveClient(ws.handle));
  said = [];
});

afterEach(() => {
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

  it("repaints at no more than 4 Hz, and announces no tick", async () => {
    mount([MAJORS], MAJORS);
    await flush();
    transport.current?.push(snapOf([streamItem(0), restItem("ETHUSDT"), restItem("SOLUSDT")]));
    const changes: number[] = [];
    let last = cellOf("BTCUSDT", "last").textContent ?? ""; // "—", until the snapshot's first beat
    for (let i = 1; i < BTC_STREAM.length; i += 1) {
      for (let step = 0; step < 2; step += 1) {
        await flush(50);
        const text = cellOf("BTCUSDT", "last").textContent ?? "";
        if (text !== last) changes.push(Date.now());
        last = text;
      }
      transport.current?.push(deltaOf([streamItem(i)]));
    }
    await flush(FLUSH_MS);
    for (let i = 1; i < changes.length; i += 1)
      expect((changes[i] ?? 0) - (changes[i - 1] ?? 0)).toBeGreaterThanOrEqual(FLUSH_MS);
    expect(cellOf("BTCUSDT", "last")).toHaveTextContent(
      Number(streamItem(19).last_price).toLocaleString("en-US", { minimumFractionDigits: 2 }),
    );
    expect(said).toEqual([]);
  });
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
      mount([ALTS], ALTS);
      await flush();
      const region = document.querySelector<HTMLElement>(".cv-table__region");
      if (region === null) throw new Error("no scroll region");
      let scrollTop = 0;
      Object.defineProperty(region, "scrollTop", { configurable: true, get: () => scrollTop });
      Object.defineProperty(region, "clientHeight", { configurable: true, get: () => 360 });
      const rect = (top: number, height: number) => new DOMRect(0, top, 784, height);
      const layout = vi
        .spyOn(HTMLElement.prototype, "getBoundingClientRect")
        .mockImplementation(function (this: HTMLElement) {
          if (this.tagName === "TBODY") return rect(24 - scrollTop, 24 * 120);
          if (this.tagName === "THEAD" || this.tagName === "TR") return rect(0, 24);
          return rect(0, 0);
        });
      try {
        // A scroll every 1.5 s for 90 s, each settling past 300 ms: far more moves asked for than may start.
        for (let step = 0; step < 60; step += 1) {
          scrollTop = ((step * 37) % 100) * 24;
          fireEvent.scroll(region);
          await flush(1_500);
        }
        await flush(60_000);
      } finally {
        layout.mockRestore();
      }
      expect(transport.opened.length).toBeGreaterThan(1);
      for (const channel of transport.opened)
        expect(transport.drawsWithin(channel.openedAt)).toBeLessThanOrEqual(4);
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
    fireEvent.click(screen.getByRole("button", { name: "Re-sort" }));
    await flush();
    expect(order().slice(0, 3)).toEqual(["SOLUSDT", "BTCUSDT", "ETHUSDT"]);
    expect(screen.queryByRole("button", { name: "Re-sort" })).toBeNull();
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
    expect(onManage).toHaveBeenCalledOnce();
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
    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    await flush();
    expect(replace).toHaveBeenCalledTimes(2);
    expect(screen.queryByRole("rowheader", { name: /^SOLUSDT/ })).toBeNull();
  });

  it("a refused sub: no symbol live, the paused notice in the header, said once", async () => {
    mount([MAJORS], MAJORS);
    await flush();
    transport.current?.revoke();
    await flush(FLUSH_MS);
    const panel = screen.getByRole("region", { name: "Watchlist Majors" });
    expect(within(panel).getByText("Live prices paused — retrying in 5 s")).toBeInTheDocument();
    expect(screen.getByText("12 symbols · 0 live")).toBeInTheDocument();
    expect(statusOf("BTCUSDT")).toContain("Not live");
    await flush(1_000);
    expect(said).toEqual(["Live prices paused — retrying in 5 s"]);
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

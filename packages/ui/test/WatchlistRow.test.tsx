// @vitest-environment jsdom
import { composeStories } from "@storybook/react-vite";
import { act, type JSX } from "react";
import { expect, fireEvent, userEvent, within } from "storybook/test";
import { beforeEach, describe, it, vi } from "vitest";
import {
  GatedAnnounceProvider,
  Table,
  WATCHLIST_DEFAULT_COLUMNS,
  WATCHLIST_OPTIONAL_COLUMNS,
  WatchlistRow,
  watchlistColumns,
  type WatchlistColumnId,
  type WatchlistRowData,
  type WatchlistRowProps,
} from "../src/index.js";
import * as stories from "../src/components/WatchlistRow.stories.js";
import { seriousViolations } from "./axe.js";
import { mount } from "./theme/mount.js";

const MINUS = "−";
/** The shared 1 Hz clock's server time, and the next funding: 05:28:51 to go (E08-D07 D22). */
const NOW = Date.UTC(2026, 9, 30, 10, 31, 9);
const FUNDING = Date.UTC(2026, 9, 30, 16, 0, 0);

const BTC: WatchlistRowData = {
  symbol: "BTCUSDT",
  priceScale: 2,
  lastPrice: 64012.5,
  pctChange24h: 0.42,
  turnover24h: 1.2e9,
  fundingRate: 0.01,
  nextFundingTimeMs: FUNDING,
  openInterestChangePct24h: 2.1,
  spreadBps: 0.0234,
};
const ETH: WatchlistRowData = {
  ...BTC,
  symbol: "ETHUSDT",
  lastPrice: 3144.21,
  pctChange24h: -0.18,
  turnover24h: 8.4e8,
  fundingRate: -0.008,
  openInterestChangePct24h: -0.4,
};

type RowOptions = Omit<WatchlistRowProps, "grid" | "row" | "columns">;
interface Item {
  readonly data: WatchlistRowData;
  readonly options?: RowOptions;
}

interface HostProps {
  readonly items: readonly Item[];
  readonly columns?: readonly WatchlistColumnId[];
}

/** SCR-100's composition: CMP-049 in grid mode, one CMP-161 per symbol. */
function Host({ items, columns = WATCHLIST_DEFAULT_COLUMNS }: HostProps): JSX.Element {
  return (
    <Table<Item>
      grid
      reflow="grid"
      caption="Watchlist Majors, 2 symbols, manual order"
      columns={watchlistColumns(columns, { item: (i: Item) => i.data })}
      rows={items}
      rowKey={(i) => i.data.symbol}
      renderRow={(item, grid) => (
        <WatchlistRow grid={grid} row={item.data} columns={columns} nowMs={NOW} {...item.options} />
      )}
    />
  );
}

const page = within(document.body);
const grid = (): HTMLElement => page.getByRole("grid");
/** A row by its symbol; a delisted row's header leads with the lock, named "Not available" (E09-D09 §2.2). */
const rowOf = (symbol: string): HTMLElement =>
  page
    .getByRole("rowheader", { name: new RegExp(`^(Not available )?${symbol}`) })
    .closest("tr") as HTMLElement;
const cellIn = (symbol: string, column: string): HTMLElement =>
  rowOf(symbol).querySelector<HTMLElement>(`[data-column="${column}"]`) as HTMLElement;
const echo = (): HTMLElement | null => document.querySelector<HTMLElement>(".cv-table__echo");

beforeEach(() => {
  Element.prototype.scrollIntoView = vi.fn();
});

describe("WatchlistRow (CMP-161): the columns and D9's formats", () => {
  it("the default columns in E08-D07 §4.1's order, then the fixed Status slot", async () => {
    await mount(<Host items={[{ data: BTC }]} />);
    expect(
      within(grid())
        .getAllByRole("columnheader")
        .map((h) => h.textContent),
    ).toEqual([
      "Symbol",
      "Last",
      "24h %",
      "Turnover USDT",
      "Funding %",
      "Funding in",
      "OI Δ 24h %",
      "Spread bps",
      "Rec",
      "Status",
    ]);
  });

  it("the symbol is the row's header; each row carries CMP-161", async () => {
    await mount(<Host items={[{ data: BTC }, { data: ETH }]} />);
    expect(
      within(grid())
        .getAllByRole("rowheader")
        .map((h) => h.textContent),
    ).toEqual(["BTCUSDT", "ETHUSDT"]);
    expect(grid().querySelectorAll('tr[data-cmp="CMP-161"]')).toHaveLength(2);
  });

  it("Last at the price scale, grouped, never coloured", async () => {
    await mount(<Host items={[{ data: BTC }]} />);
    expect(cellIn("BTCUSDT", "last")).toHaveTextContent("64,012.50");
    expect(cellIn("BTCUSDT", "last").querySelector("[data-sign]")).toBeNull();
  });

  it("24h %: the sign, and ▲ as a hidden glyph coloured by the sign", async () => {
    await mount(<Host items={[{ data: BTC }]} />);
    const cell = cellIn("BTCUSDT", "chg_24h_pct");
    const glyph = cell.querySelector(".cv-wl__glyph") as HTMLElement;
    expect([glyph.textContent, glyph.dataset["sign"]]).toEqual(["▲", "positive"]);
    expect(glyph).toHaveAttribute("aria-hidden", "true");
    expect(cell).toHaveAccessibleName("+0.42%");
  });

  it("a fall: ▼ and U+2212", async () => {
    await mount(<Host items={[{ data: ETH }]} />);
    const cell = cellIn("ETHUSDT", "chg_24h_pct");
    expect(cell.querySelector(".cv-wl__glyph")).toHaveTextContent("▼");
    expect(cell).toHaveAccessibleName(`${MINUS}0.18%`);
  });

  it("Turnover to three significant figures, named in full", async () => {
    await mount(<Host items={[{ data: BTC }]} />);
    const cell = cellIn("BTCUSDT", "turnover_24h");
    expect(cell.querySelector('[aria-hidden="true"]')).toHaveTextContent("1.20B");
    expect(cell).toHaveAccessibleName("1,200,000,000 USDT");
  });

  it("Funding % at 4 dp with its sign, never coloured", async () => {
    await mount(<Host items={[{ data: ETH }]} />);
    expect(cellIn("ETHUSDT", "funding_rate")).toHaveTextContent(`${MINUS}0.0080%`);
    expect(cellIn("ETHUSDT", "funding_rate").querySelector("[data-sign]")).toBeNull();
  });

  it("Funding in counts on the shared clock, named and echoed with its UTC target", async () => {
    await mount(<Host items={[{ data: BTC }]} />);
    const cell = cellIn("BTCUSDT", "next_funding");
    expect(cell).toHaveAccessibleName("05:28:51 at 16:00:00 UTC");
    expect(cell).toHaveAttribute("data-cv-echo", "at 16:00:00 UTC");
  });

  it("Funding in at zero reads Settling…", async () => {
    await mount(<Host items={[{ data: { ...BTC, nextFundingTimeMs: NOW } }]} />);
    expect(cellIn("BTCUSDT", "next_funding")).toHaveTextContent("Settling…");
  });

  it("OI Δ with no 24 h baseline is the dash, named no 24 h baseline", async () => {
    await mount(<Host items={[{ data: { ...BTC, openInterestChangePct24h: null } }]} />);
    const cell = cellIn("BTCUSDT", "oi_chg_24h_pct");
    expect(cell).toHaveTextContent("—");
    expect(cell).toHaveAccessibleName("no 24 h baseline");
  });

  it("Spread in bps at 2 dp, never coloured", async () => {
    await mount(<Host items={[{ data: BTC }]} />);
    expect(cellIn("BTCUSDT", "spread_bps")).toHaveTextContent("0.02");
    expect(cellIn("BTCUSDT", "spread_bps").querySelector("[data-sign]")).toBeNull();
  });

  it("an optional column at the price scale: Mark", async () => {
    const columns: readonly WatchlistColumnId[] = ["symbol", "mark_price"];
    await mount(<Host columns={columns} items={[{ data: { ...BTC, markPrice: 64010.1 } }]} />);
    expect(page.getByRole("columnheader", { name: "Mark" })).toBeInTheDocument();
    expect(cellIn("BTCUSDT", "mark_price")).toHaveTextContent("64,010.10");
  });

  it("the optional prices at the price scale: Index, High 24h and Low 24h", async () => {
    const columns: readonly WatchlistColumnId[] = ["symbol", "index_price", "high_24h", "low_24h"];
    const data = { ...BTC, indexPrice: 64005.25, high24h: 65120, low24h: 62987.5 };
    await mount(<Host columns={columns} items={[{ data }]} />);
    expect(
      ["index_price", "high_24h", "low_24h"].map((c) => cellIn("BTCUSDT", c).textContent),
    ).toEqual(["64,005.25", "65,120.00", "62,987.50"]);
  });

  it("custom columns: only the given ones, in their order, then Status", async () => {
    await mount(<Host columns={["symbol", "chg_24h_pct", "last"]} items={[{ data: BTC }]} />);
    expect(
      within(grid())
        .getAllByRole("columnheader")
        .map((h) => h.textContent),
    ).toEqual(["Symbol", "24h %", "Last", "Status"]);
  });

  /** Lays `element` out cut: its text `scroll` px wide in a box `client` px wide (jsdom has no layout). */
  const cutTo = (element: Element, scroll: number, client: number): void => {
    Object.defineProperty(element, "scrollWidth", { configurable: true, value: scroll });
    Object.defineProperty(element, "clientWidth", { configurable: true, value: client });
  };
  const LONG = "1000000BABYDOGEUSDT";

  it("a cut symbol: keyboard focus shows the whole symbol in the echo (E08-D07 §4.1)", async () => {
    await mount(<Host items={[{ data: BTC }, { data: { ...BTC, symbol: LONG } }]} />);
    cutTo(cellIn(LONG, "symbol"), 151, 88);
    act(() => cellIn("BTCUSDT", "symbol").focus());
    await userEvent.keyboard("{ArrowDown}");
    expect(document.activeElement).toBe(cellIn(LONG, "symbol"));
    expect(echo()).toHaveTextContent(LONG);
    expect(echo()).not.toHaveAttribute("hidden");
  });

  it("a cut symbol: hover shows the whole symbol in the echo after CMP-016's 300 ms", async () => {
    vi.useFakeTimers();
    try {
      await mount(<Host items={[{ data: { ...BTC, symbol: LONG } }]} />);
      cutTo(cellIn(LONG, "symbol"), 151, 88);
      act(() => {
        fireEvent.pointerOver(cellIn(LONG, "symbol"));
      });
      act(() => {
        vi.advanceTimersByTime(300);
      });
      expect(echo()).toHaveTextContent(LONG);
    } finally {
      vi.useRealTimers();
    }
  });

  it("a symbol shown whole has no echo", async () => {
    await mount(<Host items={[{ data: BTC }, { data: ETH }]} />);
    act(() => cellIn("BTCUSDT", "symbol").focus());
    await userEvent.keyboard("{ArrowDown}");
    expect(document.activeElement).toBe(cellIn("ETHUSDT", "symbol"));
    expect(echo()).toHaveAttribute("hidden");
  });
});

describe("WatchlistRow (CMP-161): Rec", () => {
  it("renders nothing while the recorder store is absent", async () => {
    await mount(<Host items={[{ data: BTC }]} />);
    expect(cellIn("BTCUSDT", "rec")).toBeEmptyDOMElement();
  });

  it("the restricted lock is named Recording status restricted", async () => {
    await mount(<Host items={[{ data: { ...BTC, rec: { kind: "restricted" } } }]} />);
    expect(within(cellIn("BTCUSDT", "rec")).getByRole("img")).toHaveAccessibleName(
      "Recording status restricted",
    );
  });

  it("a chip draws its compact form and reads its full text", async () => {
    const rec = { kind: "chip", compact: "REC 24m", full: "REC · stops in 24 min" } as const;
    await mount(<Host items={[{ data: { ...BTC, rec } }]} />);
    const cell = cellIn("BTCUSDT", "rec");
    expect(cell.querySelector('[aria-hidden="true"]')).toHaveTextContent("REC 24m");
    expect(cell).toHaveAccessibleName("REC · stops in 24 min");
  });
});

describe("WatchlistRow (CMP-161): the data-confidence states", () => {
  const stale = (ageMs: number, more: object = {}): RowOptions => ({
    freshness: { ticker: { state: "stale", ageMs, ...more } },
  });

  it("live: the Status slot is empty", async () => {
    await mount(<Host items={[{ data: BTC }]} />);
    expect(cellIn("BTCUSDT", "status")).toBeEmptyDOMElement();
    expect(rowOf("BTCUSDT")).not.toHaveAttribute("data-freshness");
  });

  it("stale (T1): the row is marked and keeps its values; one chip, Stale 7s", async () => {
    await mount(<Host items={[{ data: BTC, options: stale(7000) }]} />);
    expect(rowOf("BTCUSDT")).toHaveAttribute("data-freshness", "stale");
    expect(cellIn("BTCUSDT", "last")).toHaveTextContent("64,012.50");
    const chips = rowOf("BTCUSDT").querySelectorAll('[data-cmp="CMP-239"]');
    expect(chips).toHaveLength(1);
    expect(chips[0]).toHaveAttribute("data-level", "subtle");
    expect(chips[0]?.querySelector('[aria-hidden="true"]')).toHaveTextContent("Stale 7s");
  });

  it("stale: every cell of the row is described by the chip's words", async () => {
    await mount(<Host items={[{ data: BTC, options: stale(7000) }]} />);
    expect(cellIn("BTCUSDT", "last")).toHaveAccessibleDescription("Stale, 7 seconds");
    expect(page.getByRole("rowheader", { name: /^BTCUSDT/ })).toHaveAccessibleDescription(
      "Stale, 7 seconds",
    );
  });

  it("stale past T2: the strong chip", async () => {
    await mount(<Host items={[{ data: BTC, options: stale(15_000, { escalated: true }) }]} />);
    expect(rowOf("BTCUSDT").querySelector('[data-cmp="CMP-239"]')).toHaveAttribute(
      "data-level",
      "strong",
    );
  });

  it("stale by the server's flag: Stale (server)", async () => {
    await mount(<Host items={[{ data: BTC, options: stale(1000, { server: true }) }]} />);
    expect(cellIn("BTCUSDT", "status")).toHaveTextContent("Stale (server)");
  });

  it("stale: the chip's cell echoes its detail", async () => {
    await mount(
      <Host
        items={[{ data: BTC, options: stale(7000, { detail: "Last update 10:31:02 UTC" }) }]}
      />,
    );
    expect(cellIn("BTCUSDT", "status")).toHaveAttribute("data-cv-echo", "Last update 10:31:02 UTC");
  });

  it("stale: the Status cell carries its detail for AT itself, not only in the aria-hidden echo", async () => {
    await mount(
      <Host
        items={[{ data: BTC, options: stale(7000, { detail: "Last update 10:31:02 UTC" }) }]}
      />,
    );
    expect(cellIn("BTCUSDT", "status")).toHaveAccessibleName(
      "Stale, 7 seconds Last update 10:31:02 UTC",
    );
  });

  it("stale with the exchange feed down: the Status cell reads the feed-down sentence (D28)", async () => {
    const down = "Exchange feed down — the server is restoring the connection";
    await mount(<Host items={[{ data: BTC, options: stale(7000, { detail: down }) }]} />);
    expect(cellIn("BTCUSDT", "status")).toHaveAccessibleName(`Stale, 7 seconds ${down}`);
  });

  it("initialising: every live cell is the dash, named no value yet; no chip before T1", async () => {
    await mount(
      <Host
        items={[
          { data: { symbol: "SOLUSDT", priceScale: 2 }, options: { rowState: "initialising" } },
        ]}
      />,
    );
    expect(cellIn("SOLUSDT", "last")).toHaveTextContent("—");
    expect(cellIn("SOLUSDT", "last")).toHaveAccessibleName("no value yet");
    expect(cellIn("SOLUSDT", "status")).toBeEmptyDOMElement();
    expect(rowOf("SOLUSDT")).not.toHaveAttribute("data-freshness");
  });

  it("initialising past T1: the chip reads No data yet", async () => {
    await mount(
      <Host
        items={[
          {
            data: { symbol: "SOLUSDT", priceScale: 2 },
            options: { rowState: "initialising", ...stale(6000) },
          },
        ]}
      />,
    );
    expect(cellIn("SOLUSDT", "status")).toHaveTextContent("No data yet");
    expect(rowOf("SOLUSDT").querySelector('[data-cmp="CMP-239"]')).toBeNull();
  });

  it("not live: the dash in every live cell and the chip Not live, its why in the echo", async () => {
    const why = "At most 40 symbols are live on one connection; other panels use 30.";
    await mount(
      <Host items={[{ data: BTC, options: { rowState: "not-live", notLiveDetail: why } }]} />,
    );
    expect(cellIn("BTCUSDT", "last")).toHaveTextContent("—");
    expect(cellIn("BTCUSDT", "status")).toHaveTextContent("Not live");
    expect(cellIn("BTCUSDT", "status")).toHaveAttribute("data-cv-echo", why);
  });

  it("not live: the Status cell carries its why for AT itself, not only in the aria-hidden echo", async () => {
    const why = "At most 40 symbols are live on one connection; other panels use 30.";
    await mount(
      <Host items={[{ data: BTC, options: { rowState: "not-live", notLiveDetail: why } }]} />,
    );
    expect(cellIn("BTCUSDT", "status")).toHaveAccessibleName(`Not live ${why}`);
  });

  it("delisted: the symbol struck after the lock; the live cells merged into one; Rec kept; no chip", async () => {
    await mount(
      <Host
        items={[
          { data: { ...BTC, rec: { kind: "restricted" } }, options: { rowState: "delisted" } },
        ]}
      />,
    );
    const merged = rowOf("BTCUSDT").querySelector<HTMLElement>(".cv-wl__delisted") as HTMLElement;
    expect(merged).toHaveTextContent("Delisted by the exchange");
    expect(merged).toHaveAttribute("colspan", "7");
    expect(rowOf("BTCUSDT").querySelector(".cv-wl__lock svg")).not.toBeNull();
    expect(cellIn("BTCUSDT", "rec")).not.toBeEmptyDOMElement();
    expect(cellIn("BTCUSDT", "status")).toBeEmptyDOMElement();
  });

  it("delisted: the row header is unavailable, described by the merged cell", async () => {
    await mount(<Host items={[{ data: BTC, options: { rowState: "delisted" } }]} />);
    const header = page.getByRole("rowheader", { name: "Not available BTCUSDT" });
    expect(header).toHaveAttribute("aria-disabled", "true");
    expect(header).toHaveAccessibleDescription("Delisted by the exchange");
  });

  it("delisted: the lock leads the symbol, named Not available (E09-D09 §2.2, G-T2.1d)", async () => {
    await mount(<Host items={[{ data: BTC, options: { rowState: "delisted" } }]} />);
    const header = page.getByRole("rowheader", { name: "Not available BTCUSDT" });
    const lock = within(header).getByRole("img", { name: "Not available" });
    expect(lock.compareDocumentPosition(within(header).getByText("BTCUSDT"))).toBe(
      Node.DOCUMENT_POSITION_FOLLOWING,
    );
  });

  it("delisted: a stale ticker marks nothing (its state is the merged cell)", async () => {
    await mount(
      <Host items={[{ data: BTC, options: { rowState: "delisted", ...stale(9000) } }]} />,
    );
    expect(rowOf("BTCUSDT")).not.toHaveAttribute("data-freshness");
    expect(rowOf("BTCUSDT").querySelector('[data-cmp="CMP-239"]')).toBeNull();
  });

  it("delisted: the live columns either side of Rec merge into two runs, Rec kept between them", async () => {
    await mount(
      <Host
        columns={["symbol", "last", "rec", "chg_24h_pct", "spread_bps"]}
        items={[{ data: BTC, options: { rowState: "delisted" } }]}
      />,
    );
    const runs = rowOf("BTCUSDT").querySelectorAll(".cv-wl__delisted");
    expect([...runs].map((r) => r.getAttribute("colspan"))).toEqual([null, "2"]);
    expect(rowOf("BTCUSDT").querySelector('[data-column="rec"]')).not.toBeNull();
  });

  it("a stale OI column: its cells take the stale class and the footer line's description", async () => {
    await mount(
      <>
        <Host
          items={[
            {
              data: BTC,
              options: { freshness: { oiBaseline: { state: "stale", noteId: "oi-note" } } },
            },
          ]}
        />
        <p id="oi-note">OI Δ 24h stale: baseline last read 12 min ago</p>
      </>,
    );
    const oi = cellIn("BTCUSDT", "oi_chg_24h_pct");
    expect(oi).toHaveClass("cv-freshness--stale");
    expect(oi).toHaveAccessibleDescription("OI Δ 24h stale: baseline last read 12 min ago");
    expect(cellIn("BTCUSDT", "last")).not.toHaveClass("cv-freshness--stale");
    expect(rowOf("BTCUSDT")).not.toHaveAttribute("data-freshness");
  });

  it("a stale row suppresses the OI cell's own marker (one state, never stacked)", async () => {
    await mount(
      <Host
        items={[
          {
            data: BTC,
            options: {
              freshness: {
                ticker: { state: "stale", ageMs: 7000 },
                oiBaseline: { state: "stale", noteId: "oi-note" },
              },
            },
          },
        ]}
      />,
    );
    expect(cellIn("BTCUSDT", "oi_chg_24h_pct")).not.toHaveClass("cv-freshness--stale");
  });

  it("describedBy: the host's ids join every cell's description (the panel status while disconnected)", async () => {
    await mount(
      <>
        <Host items={[{ data: BTC, options: { describedBy: "panel-status" } }]} />
        <p id="panel-status">Disconnected — last data 00:12 ago</p>
      </>,
    );
    expect(cellIn("BTCUSDT", "last")).toHaveAccessibleDescription(
      "Disconnected — last data 00:12 ago",
    );
  });
});

describe("WatchlistRow (CMP-161): keys and activation", () => {
  const focusIn = (symbol: string, column: string): void => {
    act(() => cellIn(symbol, column).focus());
  };

  it("Enter activates the row", async () => {
    const onActivate = vi.fn();
    await mount(<Host items={[{ data: BTC, options: { onActivate } }]} />);
    focusIn("BTCUSDT", "last");
    await userEvent.keyboard("{Enter}");
    expect(onActivate).toHaveBeenCalledOnce();
  });

  it("a click activates the row", async () => {
    const onActivate = vi.fn();
    await mount(<Host items={[{ data: BTC, options: { onActivate } }]} />);
    await userEvent.click(cellIn("BTCUSDT", "last"));
    expect(onActivate).toHaveBeenCalledOnce();
  });

  it("delisted: Enter refuses with the reason in the echo and never activates", async () => {
    const onActivate = vi.fn();
    await mount(<Host items={[{ data: BTC, options: { rowState: "delisted", onActivate } }]} />);
    focusIn("BTCUSDT", "symbol");
    await userEvent.keyboard("{Enter}");
    expect(onActivate).not.toHaveBeenCalled();
    expect(echo()).toHaveTextContent("Delisted by the exchange");
  });

  it("delisted: a click refuses too", async () => {
    const onActivate = vi.fn();
    await mount(<Host items={[{ data: BTC, options: { rowState: "delisted", onActivate } }]} />);
    await userEvent.click(cellIn("BTCUSDT", "symbol"));
    expect(onActivate).not.toHaveBeenCalled();
  });

  it("delisted: Enter says the reason once through the gated announcer; a held key's repeats say nothing", async () => {
    const announce = vi.fn<(text: string) => void>();
    await mount(
      <GatedAnnounceProvider announce={announce}>
        <Host items={[{ data: BTC, options: { rowState: "delisted", onActivate: vi.fn() } }]} />
      </GatedAnnounceProvider>,
    );
    focusIn("BTCUSDT", "last");
    const cell = cellIn("BTCUSDT", "last");
    fireEvent.keyDown(cell, { key: "Enter" });
    fireEvent.keyDown(cell, { key: "Enter", repeat: true });
    fireEvent.keyDown(cell, { key: "Enter", repeat: true });
    expect(announce.mock.calls).toEqual([["Delisted by the exchange"]]);
  });

  it("Alt+↑ with its reason: a held key's repeats re-show nothing", async () => {
    const announce = vi.fn<(text: string) => void>();
    const onMove = vi.fn();
    await mount(
      <GatedAnnounceProvider announce={announce}>
        <Host items={[{ data: BTC, options: { onMove, moveReason: { up: "Already first." } } }]} />
      </GatedAnnounceProvider>,
    );
    focusIn("BTCUSDT", "last");
    const cell = cellIn("BTCUSDT", "last");
    fireEvent.keyDown(cell, { key: "ArrowUp", altKey: true });
    fireEvent.keyDown(cell, { key: "ArrowUp", altKey: true, repeat: true });
    expect(announce.mock.calls).toEqual([["Already first."]]);
    expect(onMove).not.toHaveBeenCalled();
  });

  it("Alt+↓ held moves the row on every repeat (a move is not a refusal)", async () => {
    const onMove = vi.fn();
    await mount(<Host items={[{ data: BTC, options: { onMove } }]} />);
    focusIn("BTCUSDT", "last");
    const cell = cellIn("BTCUSDT", "last");
    fireEvent.keyDown(cell, { key: "ArrowDown", altKey: true });
    fireEvent.keyDown(cell, { key: "ArrowDown", altKey: true, repeat: true });
    expect(onMove.mock.calls).toEqual([["down"], ["down"]]);
  });

  it("Alt+↓ moves the row down", async () => {
    const onMove = vi.fn();
    await mount(<Host items={[{ data: BTC, options: { onMove } }]} />);
    focusIn("BTCUSDT", "last");
    await userEvent.keyboard("{Alt>}{ArrowDown}{/Alt}");
    expect(onMove).toHaveBeenCalledWith("down");
  });

  it("Alt+↑ with its reason refuses and moves nothing", async () => {
    const onMove = vi.fn();
    await mount(
      <Host items={[{ data: BTC, options: { onMove, moveReason: { up: "Already first." } } }]} />,
    );
    focusIn("BTCUSDT", "last");
    await userEvent.keyboard("{Alt>}{ArrowUp}{/Alt}");
    expect(onMove).not.toHaveBeenCalled();
    expect(echo()).toHaveTextContent("Already first.");
  });

  it("Del removes once; a held key's repeats are ignored", async () => {
    const onRemove = vi.fn();
    await mount(<Host items={[{ data: BTC, options: { onRemove } }]} />);
    focusIn("BTCUSDT", "last");
    const cell = cellIn("BTCUSDT", "last");
    fireEvent.keyDown(cell, { key: "Delete" });
    fireEvent.keyDown(cell, { key: "Delete", repeat: true });
    expect(onRemove).toHaveBeenCalledOnce();
  });

  it("Del with its reason refuses and removes nothing", async () => {
    const onRemove = vi.fn();
    const reason = "Read-only — your role can't change watchlists.";
    await mount(<Host items={[{ data: BTC, options: { onRemove, removeReason: reason } }]} />);
    focusIn("BTCUSDT", "last");
    await userEvent.keyboard("{Delete}");
    expect(onRemove).not.toHaveBeenCalled();
    expect(echo()).toHaveTextContent(reason);
  });

  it("Ctrl+C copies the row's symbol through the host, which is handed the symbol", async () => {
    const onCopy = vi.fn<(symbol: string) => void>();
    window.getSelection()?.removeAllRanges();
    await mount(<Host items={[{ data: BTC, options: { onCopy } }]} />);
    focusIn("BTCUSDT", "last");
    await userEvent.keyboard("{Control>}c{/Control}");
    expect(onCopy.mock.calls).toEqual([["BTCUSDT"]]);
  });

  it("Ctrl+C leaves a text selection in the grid alone: the browser copies it, and the host is not called", async () => {
    const onCopy = vi.fn<(symbol: string) => void>();
    await mount(<Host items={[{ data: BTC, options: { onCopy } }]} />);
    focusIn("BTCUSDT", "last");
    const selection = window.getSelection();
    selection?.selectAllChildren(cellIn("BTCUSDT", "last"));
    expect(selection?.toString()).toBe("64,012.50");
    const copy = fireEvent.keyDown(cellIn("BTCUSDT", "last"), { key: "c", ctrlKey: true });
    expect(copy).toBe(true);
    expect(onCopy).not.toHaveBeenCalled();
    selection?.removeAllRanges();
  });

  it("Ctrl+C copies the symbol past a stale selection outside the grid", async () => {
    const onCopy = vi.fn<(symbol: string) => void>();
    await mount(
      <>
        <p>Notes the reader selected earlier</p>
        <Host items={[{ data: BTC, options: { onCopy } }]} />
      </>,
    );
    // jsdom's focus() collapses the selection (a browser's keyboard focus does not): select after focusing.
    focusIn("BTCUSDT", "last");
    const selection = window.getSelection();
    selection?.selectAllChildren(page.getByText("Notes the reader selected earlier"));
    expect(selection?.toString()).toBe("Notes the reader selected earlier");
    const copy = fireEvent.keyDown(cellIn("BTCUSDT", "last"), { key: "c", ctrlKey: true });
    expect(copy).toBe(false);
    expect(onCopy.mock.calls).toEqual([["BTCUSDT"]]);
    selection?.removeAllRanges();
  });

  it("Ctrl+C leaves a selection that reaches into the grid alone, as select-all makes", async () => {
    const onCopy = vi.fn<(symbol: string) => void>();
    await mount(
      <>
        <p>Notes the reader selected earlier</p>
        <Host items={[{ data: BTC, options: { onCopy } }]} />
      </>,
    );
    focusIn("BTCUSDT", "last");
    const selection = window.getSelection();
    selection?.selectAllChildren(document.body);
    expect(selection?.toString()).toContain("64,012.50");
    const copy = fireEvent.keyDown(cellIn("BTCUSDT", "last"), { key: "c", ctrlKey: true });
    expect(copy).toBe(true);
    expect(onCopy).not.toHaveBeenCalled();
    selection?.removeAllRanges();
  });

  it("active: aria-current and the row header's description", async () => {
    await mount(
      <Host items={[{ data: BTC, options: { active: true, description: "Shows in group A" } }]} />,
    );
    expect(rowOf("BTCUSDT")).toHaveAttribute("aria-current", "true");
    expect(page.getByRole("rowheader", { name: /^BTCUSDT/ })).toHaveAccessibleDescription(
      "Shows in group A",
    );
  });
});

describe("watchlistColumns (CMP-161's column registry over CMP-049)", () => {
  it("names every optional column", () => {
    expect(watchlistColumns(WATCHLIST_OPTIONAL_COLUMNS).map((c) => c.header)).toEqual([
      "Volume 24h",
      "OI USDT",
      "Mark",
      "Index",
      "Bid",
      "Ask",
      "High 24h",
      "Low 24h",
      "Status",
    ]);
  });

  it("a stale OI baseline puts ⚠ on OI Δ's header, named stale", () => {
    const oi = watchlistColumns(WATCHLIST_DEFAULT_COLUMNS, { oiStale: true }).find(
      (c) => c.id === "oi_chg_24h_pct",
    );
    expect(oi?.headerStatus).toEqual({ icon: "warning", label: "stale", tone: "stale" });
  });

  it("sortable: every column but Status; a live-sort reason gates the live columns only (D5)", () => {
    const reason = "Live sort needs every symbol live.";
    const columns = watchlistColumns(WATCHLIST_DEFAULT_COLUMNS, {
      sortable: true,
      liveSortReason: reason,
    });
    expect(columns.filter((c) => c.sortable === true).map((c) => c.id)).toEqual([
      ...WATCHLIST_DEFAULT_COLUMNS,
    ]);
    expect(columns.filter((c) => c.sortDisabledReason === reason).map((c) => c.id)).toEqual([
      "last",
      "chg_24h_pct",
      "turnover_24h",
      "funding_rate",
      "next_funding",
      "oi_chg_24h_pct",
      "spread_bps",
    ]);
  });

  it("the Status slot is always last, and fixed", () => {
    const columns = watchlistColumns(["symbol", "status" as WatchlistColumnId, "last"]);
    expect(columns.map((c) => c.id)).toEqual(["symbol", "last", "status"]);
  });

  // Measured with the pinned faces (Inter 4.0 at type.ui.label, CMP-049's 8 px cell padding): "Turnover USDT" is
  // 87.5 px, a delisted LUNAUSDT with its 16 px lock 85.8 px. The reference is 784 px (49 em): no stacking there.
  it("the default widths hold E08-D07 §4.1's 784 px reference, with room for Turnover USDT and a delisted lock", () => {
    const columns = watchlistColumns(WATCHLIST_DEFAULT_COLUMNS);
    const width = (id: string): number => columns.find((c) => c.id === id)?.widthEm ?? 0;
    expect(width("symbol") * 16 - 16).toBeGreaterThanOrEqual(85.8);
    expect(width("turnover_24h") * 16 - 16).toBeGreaterThanOrEqual(87.5);
    expect(columns.reduce((sum, c) => sum + (c.minWidthEm ?? 0), 0)).toBeLessThanOrEqual(49);
    expect(columns.every((c) => c.minWidthEm === c.widthEm)).toBe(true);
  });
});

describe("WatchlistRow (CMP-161): axe", () => {
  it("live, stale, not live, initialising and delisted rows together", async () => {
    const host = await mount(
      <Host
        items={[
          { data: BTC, options: { active: true } },
          { data: ETH, options: { freshness: { ticker: { state: "stale", ageMs: 7000 } } } },
          { data: { ...BTC, symbol: "SOLUSDT" }, options: { rowState: "not-live" } },
          { data: { symbol: "ARBUSDT", priceScale: 4 }, options: { rowState: "initialising" } },
          { data: { ...BTC, symbol: "LUNAUSDT" }, options: { rowState: "delisted" } },
        ]}
      />,
    );
    expect(await seriousViolations(host)).toEqual([]);
  });
});

// Each story's play in jsdom (the storybook project runs them in Chromium with axe): Reflow200 and LongSymbol (its
// cut is measured) need a layout engine.
describe("WatchlistRow (CMP-161): stories", () => {
  it("runs each story's play function", { timeout: 60_000 }, async () => {
    for (const [name, Story] of Object.entries(composeStories(stories))) {
      if (name === "Reflow200" || name === "LongSymbol") continue;
      const canvasElement = document.body.appendChild(document.createElement("div"));
      await expect(Story.run({ canvasElement }), name).resolves.toBeUndefined();
      canvasElement.remove();
    }
  });
});

// The orchestrator's design read on #5146 (items 2, 4 and 6).
describe("WatchlistRow (CMP-161): the stories' set-up", () => {
  // D30 / R1: the capture comes after the play, so a play that restores the root size shows the plain table. The
  // story's set-up sets 200 % before it renders, and only its teardown (Storybook's, as the story goes) restores it.
  it("Reflow200's set-up sets the 200 % root font size, and its teardown restores it", async () => {
    const root = document.documentElement;
    const before = root.style.fontSize;
    const setUps = [stories.Reflow200.beforeEach ?? []].flat();
    expect(setUps).toHaveLength(1);
    try {
      // The set-up reads nothing of the story's context.
      const teardowns = await Promise.all(
        setUps.map((setUp) => setUp({} as Parameters<typeof setUp>[0])),
      );
      expect(root.style.fontSize).toBe("200%");
      for (const teardown of teardowns) if (typeof teardown === "function") await teardown();
      expect(root.style.fontSize).toBe(before);
    } finally {
      root.style.fontSize = before;
    }
  });

  it("host text renders in the design-system font, never the browser's serif (the panel status line)", async () => {
    const { DisconnectedRow } = composeStories(stories);
    const host = await mount(<DisconnectedRow />);
    const status = host.querySelector<HTMLElement>("#panel-status");
    expect(status?.closest<HTMLElement>('[style*="font-family"]')?.style.fontFamily).toContain(
      "var(--font-family-ui)",
    );
  });

  it("a story for each state the rule names: Hover, FocusVisible, and SCR-100's sort buttons at 784 px", () => {
    expect(Object.keys(composeStories(stories))).toEqual(
      expect.arrayContaining(["Hover", "FocusVisible", "SortableHeaders"]),
    );
  });

  it("SortableHeaders: nine sort buttons, each named with its header's whole words, Status fixed", async () => {
    const { SortableHeaders } = composeStories(stories);
    const host = await mount(<SortableHeaders />);
    const grid = within(host).getByRole("grid");
    const names = within(grid)
      .getAllByRole("button")
      .map((button) => button.textContent);
    expect(names).toEqual([
      "Symbol",
      "Last",
      "24h %",
      "Turnover USDT",
      "Funding %",
      "Funding in",
      "OI Δ 24h %",
      "Spread bps",
      "Rec",
    ]);
    expect(within(grid).getByRole("columnheader", { name: "Status" })).not.toHaveAttribute(
      "aria-sort",
    );
  });
});
